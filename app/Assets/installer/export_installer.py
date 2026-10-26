"""Export a narrowly scoped prepared install bundle as EXE plus Assets only."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil

ROOT = Path(__file__).resolve().parent
SCRIPTS = 'SB/Binaries/Win64/ue4ss/Mods/DekCNS/Scripts/'
REQUIRED = {SCRIPTS + name for name in ('main.lua', 'OutfitReversal/Init.lua', 'OutfitReversal/MetadataBridge.lua', 'OutfitReversal/Prepared.json')}
OPTIONAL = {SCRIPTS+'OutfitReversal/AccessoryLink.lua'}
PACKAGE = re.compile(r'^SB/Content/Paks/~mods/OutfitReversalPrepared/(OutfitReversalPrepared_[0-9]{1,10}_P)\.(pak|ucas|utoc)$')


def plain(path):
    path = Path(path)
    for item in (path, *path.parents):
        if item.is_symlink() or (item.exists() and getattr(item.stat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('Links and junctions are not supported')
    return path


def export_installer(preparedInstallDirectory, destination):
    source = plain(Path(preparedInstallDirectory).absolute()).resolve()
    destination = plain(Path(destination).absolute()).resolve()
    if destination.exists():
        raise FileExistsError('Destination already exists; choose a fresh export folder')
    if destination == source or destination.is_relative_to(source):
        raise ValueError('Export destination must be outside prepared inputs')
    data = json.loads(plain(source / 'InstallManifest.json').read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict) or type(data.get('schemaVersion')) is not int or data.get('schemaVersion') != 1 or not isinstance(data.get('files'), list):
        raise ValueError('Unsupported install manifest')
    if data.get('containerProfile')!='stellarblade-initial-single-export-v1':
        raise ValueError('Obsolete prepared container format. Prepare again before exporting.')
    rows, seen, groups = [], set(), {}
    for row in data['files']:
        if not isinstance(row, dict):
            raise ValueError('Manifest file entries must be objects')
        relative, digest = row.get('relativePath'), row.get('sha256')
        if not isinstance(relative, str) or '\\' in relative or ':' in relative or relative.startswith('/') or any(part in ('', '.', '..') for part in relative.split('/')):
            raise ValueError('Manifest paths must be plain relative SB paths')
        if relative.casefold() in seen:
            raise ValueError('Duplicate install destination')
        seen.add(relative.casefold())
        match = PACKAGE.fullmatch(relative)
        if relative not in REQUIRED | OPTIONAL and not match:
            raise ValueError('Install manifest contains an unsupported file')
        if not isinstance(digest, str) or not re.fullmatch('[0-9a-fA-F]{64}', digest):
            raise ValueError('Manifest SHA256 is invalid')
        path = plain(source / Path(*PurePosixPath(relative).parts)).resolve()
        if not path.is_relative_to(source) or not path.is_file():
            raise ValueError('Manifest source is missing or escapes prepared inputs')
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest.lower():
            raise ValueError('Prepared source SHA256 does not match the manifest')
        if match:
            groups.setdefault(match.group(1), set()).add(match.group(2))
        rows.append({'relativePath': relative, 'sha256': digest.lower()})
    remove_all = data.get('removeAllPrepared') is True
    metadata = json.loads(plain(source/(SCRIPTS+'OutfitReversal/Prepared.json')).read_text(encoding='utf-8-sig'))
    empty_removal = remove_all and metadata.get('schemaVersion') == 1 and metadata.get('outfits') == {} and not groups
    if (remove_all and not empty_removal) or not REQUIRED.issubset({row['relativePath'] for row in rows}) or (not groups and not empty_removal) or any(exts != {'pak', 'ucas', 'utoc'} for exts in groups.values()):
        raise ValueError('Prepared install requires four CNS files and complete package triplets')
    template = ROOT / 'InstallPrepared.exe'
    script = ROOT / 'Install-Prepared.ps1'
    if not template.is_file() or not script.is_file():
        raise FileNotFoundError('Installer template or script is missing')
    destination.mkdir(parents=True)
    try:
        assets = destination / 'Assets'; assets.mkdir()
        shutil.copyfile(template, destination / 'InstallPrepared.exe')
        shutil.copyfile(script, assets / script.name)
        # Never distribute the preparer's absolute game directory or extra fields.
        manifest = {'schemaVersion': 1, 'files': rows}
        manifest['containerProfile']=data['containerProfile']
        if empty_removal:manifest['removeAllPrepared']=True
        original_cns = data.get('sourceCnsMainSha256')
        if not isinstance(original_cns, str) or not re.fullmatch('[0-9a-fA-F]{64}', original_cns):
            raise ValueError('Missing source CNS checksum; prepare again before exporting')
        manifest['sourceCnsMainSha256'] = original_cns.lower()
        (assets / 'InstallManifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        for row in rows:
            relative = Path(*PurePosixPath(row['relativePath']).parts)
            target = assets / relative; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / relative, target)
            if hashlib.sha256(target.read_bytes()).hexdigest() != row['sha256']:
                raise ValueError('Exported payload failed SHA256 verification')
    except BaseException:
        # Only the fresh directory created above is removed; source is untouched.
        shutil.rmtree(destination)
        raise
    return {'schemaVersion': 1, 'files': len(rows), 'layout': ['InstallPrepared.exe', 'Assets'], 'sourceFilesChanged': False}

