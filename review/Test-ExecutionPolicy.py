"""Regression check for unsigned downloaded extractor subprocesses.

Uses temporary synthetic jobs; never opens game files or changes saved policies.
Run with the application's bundled Python. --app selects an extracted app folder.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True)
    args = parser.parse_args()
    assets = args.app.resolve() / 'Assets'
    shell = assets / 'Runtime/PowerShell/pwsh.exe'
    sys.path.insert(0, str(assets))
    import prep

    def launch(arguments, env=None):
        return subprocess.run([str(shell), '-NoProfile', *map(str, arguments)], env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8',
            errors='replace', timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    def policies():
        result = launch(['-Command', "Get-ExecutionPolicy -List | Select-Object @{n='Scope';e={$_.Scope.ToString()}},@{n='ExecutionPolicy';e={$_.ExecutionPolicy.ToString()}} | ConvertTo-Json -Compress"])
        assert result.returncode == 0, 'Cannot inspect policy precedence'
        return json.loads(result.stdout)

    before = policies()
    # Do not attempt to override policies enforced by an administrator.
    assert all(row['ExecutionPolicy'] == 'Undefined' for row in before if row['Scope'] in ('MachinePolicy', 'UserPolicy')), 'Managed policy prevents this controlled test'
    rows = []
    scratch_parent = Path.cwd().resolve()
    with tempfile.TemporaryDirectory(dir=scratch_parent, prefix='outfit policy check ') as temporary:
        root = Path(temporary).resolve()
        assert root.is_relative_to(scratch_parent) and root != scratch_parent
        probe = root / 'Extractor.ps1'
        probe.write_text('''param([string]$Job)
$task = Get-Content -LiteralPath $Job -Raw | ConvertFrom-Json
[IO.Directory]::CreateDirectory($task.outputRoot) | Out-Null
'{"schemaVersion":1,"probe":true}' | Set-Content -LiteralPath (Join-Path $task.outputRoot 'extraction-manifest.json') -Encoding utf8
''', encoding='utf-8')
        Path(str(probe) + ':Zone.Identifier').write_text('[ZoneTransfer]\nZoneId=3\n', encoding='ascii')
        fake_settings = dict(pakRoot=str(root/'unused paks'), mappings=str(root/'unused.usmap'),
            libraries=str(root/'unused reader'), powershell=str(shell))
        old_here, old_policy = prep.HERE, os.environ.get('PSExecutionPolicyPreference')
        try:
            prep.HERE = root
            for policy in ('RemoteSigned', 'AllSigned', 'Restricted'):
                os.environ['PSExecutionPolicyPreference'] = policy
                job = root / 'old-job.json'
                job.write_text(json.dumps(dict(outputRoot=str(root/'old-output'))))
                old = launch(['-File', probe, '-Job', job], env=os.environ.copy())
                assert old.returncode != 0, 'Old launch unexpectedly succeeded under ' + policy
                assert not (root/'old-output').exists(), 'Blocked old script executed'
                output = root / policy
                fixed = prep.prepare_extraction(fake_settings, [], output)
                assert fixed == {'schemaVersion': 1, 'probe': True}, 'Fixed launch failed under ' + policy
                assert os.environ['PSExecutionPolicyPreference'] == policy, 'Parent process policy changed'
                rows.append(dict(policy=policy, oldLaunchBlocked=True, fixedLaunchPassed=True, internetMarkedScript=True))
        finally:
            prep.HERE = old_here
            if old_policy is None: os.environ.pop('PSExecutionPolicyPreference', None)
            else: os.environ['PSExecutionPolicyPreference'] = old_policy

        # The actual extractor must reach its own job validation, rather than a
        # signing error. An empty job fails before asset reading or output writes.
        actual = root/'actual Extractor.ps1'
        shutil.copyfile(assets/'Extractor.ps1', actual)
        Path(str(actual)+':Zone.Identifier').write_text('[ZoneTransfer]\nZoneId=3\n', encoding='ascii')
        invalid = root/'invalid-job.json'; invalid.write_text('{}')
        child_env = {**os.environ, 'PSExecutionPolicyPreference': 'AllSigned'}
        result = launch(['-ExecutionPolicy','Bypass','-File',actual,'-Job',invalid], env=child_env)
        assert result.returncode != 0 and 'Job is missing pakRoot' in result.stdout, 'Actual extractor did not reach job validation'
        assert 'not digitally signed' not in result.stdout, 'Actual extractor was still blocked'

    assert before == policies(), 'Persistent/default policy snapshot changed'
    print(json.dumps(dict(success=True, scenarios=rows, actualExtractorReachedValidation=True,
        savedPoliciesUnchanged=True, gameFilesModified=False)))


if __name__ == '__main__':
    main()
