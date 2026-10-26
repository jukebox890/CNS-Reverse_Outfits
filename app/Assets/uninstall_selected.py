"""Remove selected generated choices, preserving shared assets and other policies."""
from contextlib import contextmanager
import copy
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

SCRIPTS = 'SB/Binaries/Win64/ue4ss/Mods/DekCNS/Scripts/'
PREPARED = SCRIPTS+'OutfitReversal/Prepared.json'
PROFILE = 'stellarblade-initial-single-export-v1'
HERE = Path(__file__).resolve().parent


@contextmanager
def operation_lock(output):
    """OS lock is automatically released if this process exits unexpectedly."""
    path = Path(output)/'Operation.lock'
    with path.open('a+b') as handle:
        handle.seek(0)
        if not handle.read(1):
            handle.write(b'0');handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ValueError('Another scan, preparation or uninstall is running. Wait for it to finish.') from error
        try:
            yield
        finally:
            if os.name == 'nt':
                handle.seek(0);msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    path = Path(path);path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')
    os.replace(temporary, path)


def filter_bundle(source, destination, ids, source_cns=None):
    """Validate input and export filtered metadata with unchanged shared payloads."""
    sys.path.insert(0, str(HERE/'installer'))
    from export_installer import export_installer, plain
    source = plain(Path(source).resolve())
    manifest = read(source/'InstallManifest.json')
    if manifest.get('containerProfile') != PROFILE:
        raise ValueError('Prepare outfits again before uninstalling this older output.')
    metadata = read(plain(source/PREPARED))
    if metadata.get('schemaVersion') != 1 or not isinstance(metadata.get('outfits'), dict):
        raise ValueError('Prepared outfit metadata is invalid; nothing was removed.')
    metadata['outfits'] = {key: value for key, value in metadata['outfits'].items() if key not in ids}
    staging = destination.parent/(destination.name+'-payload')
    staging.mkdir(parents=True)
    rows = []
    for row in manifest['files']:
        relative = row['relativePath']
        # Validate the source manifest through the exporter before mutating it.
        # Copy only its narrow allowlist; no arbitrary game files are collected.
        from export_installer import REQUIRED, OPTIONAL, PACKAGE
        if relative not in REQUIRED | OPTIONAL and not PACKAGE.fullmatch(relative):
            raise ValueError('Unsupported uninstall payload path.')
        original = plain(source/relative)
        if sha256(original.read_bytes()).hexdigest() != row['sha256']:
            raise ValueError('Prepared payload changed. Prepare again before uninstalling.')
        if PACKAGE.fullmatch(relative) and not metadata['outfits']:
            continue
        target = staging/relative;target.parent.mkdir(parents=True, exist_ok=True)
        if relative == PREPARED:
            write(target, metadata)
        else:
            shutil.copyfile(original, target)
        rows.append(dict(relativePath=relative, sha256=sha256(target.read_bytes()).hexdigest()))
    manifest['files'] = rows
    manifest['removeAllPrepared'] = not bool(metadata['outfits'])
    if source_cns is not None:
        manifest['sourceCnsMainSha256'] = source_cns
    write(staging/'InstallManifest.json', manifest)
    export_installer(staging, destination)
    return metadata


def installed_bundle(game, destination):
    """Snapshot only this mod's helper files and owned package triplets."""
    from cns_compat import integrate_installed
    sys.path.insert(0, str(HERE/'installer'))
    from export_installer import plain, PACKAGE
    game = plain(Path(game).resolve())
    live = game/(SCRIPTS+'main.lua')
    raw = plain(live).read_bytes();integrate_installed(raw)
    rows = []
    paths = [game/(SCRIPTS+name) for name in ('main.lua', 'OutfitReversal/Init.lua', 'OutfitReversal/MetadataBridge.lua', 'OutfitReversal/Prepared.json')]
    accessory=game/(SCRIPTS+'OutfitReversal/AccessoryLink.lua')
    if accessory.is_file():paths.append(accessory)
    packages = game/'SB/Content/Paks/~mods/OutfitReversalPrepared'
    if packages.is_dir():
        paths += [path for path in packages.iterdir() if PACKAGE.fullmatch(path.relative_to(game).as_posix())]
    for path in paths:
        relative = path.relative_to(game).as_posix()
        target = destination/relative;target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(plain(path), target)
        rows.append(dict(relativePath=relative, sha256=sha256(target.read_bytes()).hexdigest()))
    write(destination/'InstallManifest.json', dict(schemaVersion=1, containerProfile=PROFILE,
        sourceCnsMainSha256=sha256(raw).hexdigest(), files=rows))
    return read(destination/PREPARED)


def uninstall(settings, output, candidate, ids, records, issues, inventory_writer):
    """Stage first, then commit local changes with rollback if installation fails.

    Shared triplets remain byte-identical while any outfit still references them.
    The final removal installs empty metadata and backs up/removes owned triplets.
    """
    output = Path(output).resolve()
    ids = set(ids)
    if not ids:
        raise ValueError('Select at least one prepared outfit to uninstall.')
    known = set(candidate.state['outfits'])
    if not ids.issubset(known):
        raise ValueError('Some selected outfits have no saved preparation. Scan again before uninstalling.')
    run = output/'Runs'/('uninstall-'+uuid.uuid4().hex[:12]);run.mkdir(parents=True)
    delivery = output/'Install'
    source = delivery/'Assets'
    if not source.is_dir():
        raise ValueError('The previous installer output is missing. Prepare outfits again before uninstalling.')
    print('UNINSTALL: checking selected choices and staging backups.', flush=True)
    candidate.remove(ids)
    filter_bundle(source, run/'Install', ids)
    game = Path(settings['pakRoot']).parents[2]
    installed_path = game/PREPARED
    installed = read(installed_path) if installed_path.is_file() else {'outfits': {}}
    game_changes = bool(ids.intersection(installed.get('outfits', {})))
    if game_changes:
        installed_bundle(game, run/'InstalledBefore')
        filter_bundle(run/'InstalledBefore', run/'GameInstall', ids)
    before = run/'LocalBefore';before.mkdir()
    # Exact local bytes for rollback; never collect unrelated files or assets.
    paths = [output/'Library/index.json', output/'Prepared.json', output/'inventory.json']
    saved = {}
    for path in paths:
        if path.is_file():
            backup = before/path.relative_to(output);backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, backup);saved[path] = backup
        else:
            saved[path] = None
    previous_state = copy.deepcopy(candidate.library.state)
    previous_digest = candidate.library._base_digest
    promoted = False;committed = False;result = None
    try:
        candidate.commit();committed = True
        delivery.rename(before/'Install')
        (run/'Install').rename(delivery);promoted = True
        write(output/'Prepared.json', candidate.prepared_manifest())
        if game_changes:
            print('UNINSTALL: removing selected colour choices from the game; keeping other installed choices unchanged.', flush=True)
            shell = settings.get('powershell') or str(HERE/'Runtime/PowerShell/pwsh.exe')
            result = subprocess.run([shell, '-NoProfile', '-File', str(run/'GameInstall/Assets/Install-Prepared.ps1'),
                '-GameRoot', str(game), '-BackupRoot', str(output/'InstallerBackups')],
                capture_output=True, text=True, encoding='utf-8', errors='replace',
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if result.returncode:
                print(result.stdout+result.stderr, flush=True)
                raise ValueError('Uninstall did not complete. Previous preparations were restored; see the process log.')
    except BaseException:
        if promoted:
            delivery.rename(run/'FailedInstall')
        if (before/'Install').exists():
            (before/'Install').rename(delivery)
        if committed:
            for path, backup in saved.items():
                if backup is not None:
                    temporary = path.with_name(path.name+'.rollback.tmp');shutil.copyfile(backup, temporary);os.replace(temporary, path)
                elif path.is_file():
                    path.unlink()
            candidate.library.state = previous_state;candidate.library._base_digest = previous_digest
        raise
    if result is not None:
        print(result.stdout+result.stderr, flush=True)
        try:
            (run/'install.log').write_text(result.stdout+result.stderr, encoding='utf-8')
        except OSError:
            print('Uninstall completed; its diagnostic log could not be saved.', flush=True)
    # A failed UI refresh must not report a completed game transaction as failed.
    try:
        inventory_writer(settings, candidate, records, issues, output)
    except (OSError, ValueError) as error:
        print('Uninstall completed; scan again to refresh the outfit list: '+str(error), flush=True)
    return dict(success=True, uninstalledOutfits=sorted(ids), gameFilesModified=game_changes,
        preparedOutfits=len(candidate.prepared_manifest()['outfits']), installFolder=str(delivery))
