"""Synthetic scan/packaging/installer regressions. No real game is modified."""
import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--app',type=Path,required=True)
args=parser.parse_args()
ASSETS=args.app.resolve()/'Assets'
sys.path[:0]=[str(ASSETS),str(ASSETS/'packaging')]
import chunk_inventory as ci
import prep
import pack_legacy
import engine_free_backend as backend


def toc(path,identity=123):
    raw=bytearray(64);raw[:16]=ci.MAGIC;raw[16]=2
    struct.pack_into('<I',raw,20,64);struct.pack_into('<Q',raw,56,identity)
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    return path


class ScanRobustness(unittest.TestCase):
    def setUp(self):
        self.parent=Path.cwd().resolve()
        self.temp=tempfile.TemporaryDirectory(dir=self.parent,prefix='outfit scan check ')
        self.root=Path(self.temp.name).resolve()
        assert self.root.is_relative_to(self.parent) and self.root!=self.parent
        self.paks=self.root/'Game/SB/Content/Paks';self.paks.mkdir(parents=True)

    def tearDown(self):self.temp.cleanup()

    def test_mixed_headers_and_filename_reservations(self):
        toc(self.paks/'valid.UTOC',42)
        (self.paks/'dance.utoc').write_bytes(b'unsupported')
        (self.paks/'pakchunk61947_P.utoc').write_bytes(b'')
        broken=toc(self.paks/'invalid-size.utoc');raw=bytearray(broken.read_bytes());struct.pack_into('<I',raw,20,999);broken.write_bytes(raw)
        rows=ci.scan_containers(self.paks)
        self.assertEqual(len(rows),4)
        self.assertEqual(sum(r['containerId'] is None for r in rows),3)
        self.assertEqual(ci.duplicate_container_groups(rows),[])
        self.assertEqual(ci.choose_chunk(rows=rows),61948)
        self.assertFalse(ci.chunk_is_available(61947,rows))
        toc(self.paks/'pakchunk61947_other.utoc',12)
        labels=ci.duplicate_chunk_label_groups(ci.scan_containers(self.paks))
        self.assertEqual(labels[0]['containerIds'],['000000000000000c'])
        self.assertEqual(len(labels[0]['unreadableHeaders']),1)
        with self.assertRaises(ValueError):ci.read_utoc_header(broken)
        with self.assertRaises(ValueError):pack_legacy.header(broken)
        with self.assertRaises(ValueError):pack_legacy._conflicts(rows,61947)
        with self.assertRaises(ValueError):pack_legacy._conflicts(rows,61948,'000000000000002a')

    def test_unreadable_file_does_not_abort(self):
        blocked=toc(self.paks/'pakchunk61947_locked.utoc')
        toc(self.paks/'readable.utoc',8)
        original=Path.open
        def deny(path,*a,**kw):
            if path==blocked:raise PermissionError('Synthetic denied read')
            return original(path,*a,**kw)
        with mock.patch.object(Path,'open',deny):
            rows=ci.scan_containers(self.paks)
        self.assertEqual(len(rows),2)
        self.assertEqual(next(r for r in rows if r['path']==str(blocked))['headerError'],'unreadable_header')
        self.assertEqual(ci.choose_chunk(rows=rows),61948)

    def definitions(self):
        rows=[{'CharacterID':None}, {'UniqueFitID':'bad-shape','OutfitDatas':{'Mesh':'invalid'}},
              {'UniqueFitID':'bad-paths','OutfitPaths':'/Game/NotAnArray'},
              {'UniqueFitID':'bad-mesh','OutfitDatas':[{'Mesh':123}]},
              {'UniqueFitID':'fixture','DisplayName':'Example outfit','OutfitPaths':['/Game/Example.Example']}]
        (self.paks/'outfits.dekcns.json').write_text(json.dumps(rows))
        (self.paks/'broken.dekcns.json').write_text('{broken')

    def test_bad_cns_rows_preserve_later_outfits(self):
        self.definitions()
        records,issues=prep.scan({'pakRoot':str(self.paks)})
        self.assertEqual([r['id'] for r in records],['fixture'])
        self.assertEqual(len(issues),5)
        self.assertFalse(records[0]['duplicate'])

    def test_complete_scan_and_packaging_with_unrelated_bad_toc(self):
        self.definitions()
        unrelated=self.paks/'unrelated-animation.utoc';unrelated.write_bytes(b'unsupported-header')
        settings=self.root/'settings.json';settings.write_text(json.dumps({'pakRoot':str(self.paks)}))
        output=self.root/'scan'
        result=subprocess.run([sys.executable,'-B',str(ASSETS/'prep.py'),'--settings',str(settings),'--output',str(output),'--scan'],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('WARNING:',result.stdout)
        inventory=json.loads((output/'inventory.json').read_text())
        self.assertEqual(len(inventory['outfits']),1)
        self.assertTrue(any(r.get('code')=='installed_container_unreadable' for r in inventory['issues']))
        job=json.loads((ASSETS/'sample/job.json').read_text())
        job.update(outputRoot=str(self.root/'cooked'),pakRoot=str(self.paks),chunkId=ci.choose_chunk(self.paks))
        job['textures'][0]['sourcePng']=str(ASSETS/'sample/colour.png')
        with contextlib.redirect_stdout(io.StringIO()):built=backend.build(job,progress=lambda *_:None)
        self.assertTrue(built['validation']['binaryVerified'])
        self.assertEqual(len(built['packageFiles']),3)
        self.assertEqual(unrelated.read_bytes(),b'unsupported-header')

    def test_installer_keeps_strict_incoming_and_collision_checks(self):
        bad=self.paks/'unrelated.utoc';bad.write_bytes(b'unsupported')
        huge=self.paks/'pakchunk99999999999999999999_P.utoc';huge.write_bytes(b'unsupported')
        incoming=toc(self.root/'OutfitReversalPrepared_61948_P.utoc',555)
        fixture=self.root/'fixture.json'
        fixture.write_text(json.dumps({'script':str(ASSETS/'installer/Install-Prepared.ps1'),'paks':str(self.paks),'incoming':str(incoming),'scratch':str(self.root)}))
        harness=self.root/'test.ps1'
        harness.write_text('''param([string]$Fixture)
$ErrorActionPreference='Stop'
$f=Get-Content -LiteralPath $Fixture -Raw | ConvertFrom-Json
. $f.script -ManifestPath (Join-Path $f.scratch 'unused.json') -BackupRoot (Join-Path $f.scratch 'backups')
$plan=@([pscustomobject]@{kind='package';source=$f.incoming})
Assert-PreparedNoContainerConflict $f.paks $plan @()
$identityCollision=Join-Path $f.paks 'different-name.utoc'
[IO.File]::WriteAllBytes($identityCollision,[IO.File]::ReadAllBytes($f.incoming))
$rejected=$false
try {Assert-PreparedNoContainerConflict $f.paks $plan @()} catch {if($_.Exception.Message -notmatch 'Container ID conflict'){throw};$rejected=$true}
if(-not $rejected){throw 'Installed internal ID collision ignored'}
[IO.File]::WriteAllText($identityCollision,'unsupported')
$bad=Join-Path $f.paks 'pakchunk61948_P.utoc'
[IO.File]::WriteAllText($bad,'unsupported')
$rejected=$false
try {Assert-PreparedNoContainerConflict $f.paks $plan @()} catch {if($_.Exception.Message -notmatch 'Chunk number conflict'){throw};$rejected=$true}
if(-not $rejected){throw 'Unreadable filename reservation ignored'}
# This file was created inside the verified temporary fixture root above.
[IO.File]::WriteAllBytes($bad,[IO.File]::ReadAllBytes($f.incoming))
$rejected=$false
try {Assert-PreparedNoContainerConflict $f.paks $plan @()} catch {$rejected=$true}
if(-not $rejected){throw 'Installed collision ignored'}
[IO.File]::WriteAllText($f.incoming,'unsupported')
$rejected=$false
try {Assert-PreparedNoContainerConflict $f.paks $plan @()} catch {if($_.Exception.Message -notmatch 'IoStore header'){throw};$rejected=$true}
if(-not $rejected){throw 'Malformed incoming package accepted'}
'PASS: unrelated headers tolerated; incoming package and conflicts remain strict.'
''',encoding='utf-8')
        shell=Path(__import__('os').environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
        result=subprocess.run([str(shell),'-NoProfile','-ExecutionPolicy','Bypass','-File',str(harness),'-Fixture',str(fixture)],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('PASS:',result.stdout)
        self.assertEqual(bad.read_bytes(),b'unsupported')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ScanRobustness))
    raise SystemExit(0 if result.wasSuccessful() else 1)
