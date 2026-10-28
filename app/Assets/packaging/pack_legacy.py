"""Standalone UE4.26 IoStore packaging through the pinned MIT retoc utility.

Only generated texture/MIC legacy assets under the isolated prepared namespace
are accepted. No engine commandlet or UnrealPak is invoked. This is a prototype:
successful binary verification is not an in-game compatibility claim.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from sb_container import normalize_container
from chunk_inventory import scan_containers
import re
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent
DEFAULT_RETOC = ROOT / 'retoc-v0.1.5/retoc.exe'
MAGIC = b'-==--==--==--==-'
CHUNKS = re.compile(r'(?:pakchunk|OutfitReversalPrepared_)(\d+)(?:\D|$)', re.I)
PREFIX = 'SB/Content/OutfitReversalPrepared/'


def header(path):
    path = Path(path)
    with path.open('rb') as handle:
        data = handle.read(64)
    if len(data) != 64 or data[:16] != MAGIC:
        raise ValueError('Invalid IoStore header')
    size = struct.unpack_from('<I', data, 20)[0]
    if data[16] == 0 or not 64 <= size <= path.stat().st_size:
        raise ValueError('Invalid IoStore version/header size')
    return dict(containerId=f'{struct.unpack_from("<Q", data, 56)[0]:016x}',
                version=data[16], filenameChunks=[int(m.group(1)) for m in CHUNKS.finditer(path.name)])


def _installed(root):
    if root is None:
        return []
    root = Path(root)
    if not root.is_dir():
        raise ValueError('pak_root must be an existing directory')
    # Installed packages are advisory inputs, not our generated output. Keep
    # unreadable entries' filename reservations without aborting on other mods.
    return scan_containers(root)


def _conflicts(rows, chunk, container_id=None):
    if any(chunk in row['filenameChunks'] for row in rows):
        raise ValueError('Chunk filename number is already installed; select an unused number')
    if container_id and any(row['containerId'] == container_id for row in rows):
        raise ValueError('Generated internal container ID is already installed')


def _run(executable, args, cwd):
    result = subprocess.run([str(executable), '--override-container-header-version', 'Initial',
                             '--override-toc-version', 'DirectoryIndex', *args], cwd=cwd,
                            capture_output=True, text=True, encoding='utf-8', errors='replace',
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError('retoc failed: ' + result.stdout + result.stderr)
    return result.stdout + result.stderr


def package_legacy(input_root, output_root, *, chunk_id=61947, pak_root=None, retoc=None):
    """Package a generated legacy tree and return the cook backend manifest fields.

    Fresh installed headers are checked before packaging and again before output
    publication. retoc derives identity from its output basename, so the *actual*
    resulting header is compared, never UE's unrelated pakchunk-name prediction.
    """
    if isinstance(chunk_id, bool) or not isinstance(chunk_id, int) or not 1 <= chunk_id < 2**31:
        raise ValueError('chunk_id must be a positive signed 32-bit integer')
    source, output = Path(input_root).resolve(), Path(output_root).resolve()
    paks = Path(pak_root).resolve() if pak_root else None
    executable = Path(retoc).resolve() if retoc else DEFAULT_RETOC
    if not executable.is_file():
        raise FileNotFoundError('Standalone retoc executable is missing')
    if not source.is_dir():
        raise ValueError('Legacy input directory is missing')
    if output == source or output.is_relative_to(source):
        raise ValueError('Output must not be inside the legacy input tree')
    if paks and (output == paks or output.is_relative_to(paks)):
        raise ValueError('Output must be outside installed Paks')
    version = subprocess.run([str(executable), '--version'], capture_output=True, text=True,
                             encoding='utf-8', errors='replace',
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if version.returncode or version.stdout.strip() != 'retoc_cli 0.1.5':
        raise ValueError('This prototype requires the verified retoc 0.1.5 utility')
    expected = set()
    for path in source.rglob('*'):
        if not path.is_file():
            continue
        relative = path.relative_to(source).as_posix()
        if (path.is_symlink() or not path.resolve().is_relative_to(source)
                or not relative.startswith(PREFIX) or path.suffix not in ('.uasset', '.uexp', '.ubulk', '.uptnl')):
            raise ValueError('Only generated prepared legacy assets are accepted')
        if '/EditorOnly/' in relative or path.stem.startswith('PAL_'):
            raise ValueError('Editor stubs and labels must not be packaged')
        if path.suffix == '.uasset':
            if not path.with_suffix('.uexp').is_file():
                raise ValueError('Every cooked legacy asset requires a matching .uexp')
            expected.add(relative)
    if not expected:
        raise ValueError('No cooked legacy assets found')
    _conflicts(_installed(paks), chunk_id)
    output.mkdir(parents=True, exist_ok=True)
    basename = f'OutfitReversalPrepared_{chunk_id}_P'
    # Publish only after retoc verification and exact directory manifest checks.
    with tempfile.TemporaryDirectory(prefix='pack-', dir=output) as temporary:
        stage = Path(temporary)
        toc = stage / (basename + '.utoc')
        _run(executable, ['to-zen', str(source), str(toc), '--version', 'UE4_26'], stage)
        profile = normalize_container(executable, toc, stage, _run)
        files = [toc.with_suffix(extension) for extension in ('.pak', '.ucas', '.utoc')]
        if not all(path.is_file() and path.stat().st_size for path in files):
            raise RuntimeError('retoc did not produce a complete triplet')
        identity = header(toc)
        if identity['version'] != 2:
            raise RuntimeError('Expected UE4.26 DirectoryIndex TOC version')
        if identity['containerId'] in ('0000000000000000', 'ffffffffffffffff'):
            raise RuntimeError('Invalid generated container identity')
        verified = _run(executable, ['verify', str(toc)], stage)
        if 'verified' not in verified.casefold():
            raise RuntimeError('retoc did not confirm binary verification')
        _run(executable, ['manifest', str(toc)], stage)
        manifest = json.loads((stage / 'pakstore.json').read_text(encoding='utf-8'))
        actual = {data['filename'].removeprefix('../../../')
                  for entry in manifest['oplog']['entries'] for data in entry['packagedata']}
        if actual != expected:
            raise RuntimeError('Packaged asset paths differ from the exact prepared input set')
        _conflicts(_installed(paks), chunk_id, identity['containerId'])
        published = []
        hashes = {}
        backups = {}
        try:
            for path in files:
                destination = output / path.name
                if destination.is_symlink() or (destination.exists() and not destination.is_file()):
                    raise ValueError('Package destination must be an ordinary file')
                hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
                if destination.exists():
                    backup = stage / ('previous-' + path.name)
                    destination.replace(backup)
                    backups[destination] = backup
                path.replace(destination)
                published.append(str(destination))
        except BaseException:
            for destination in map(Path, published):
                destination.unlink(missing_ok=True)
            for destination, backup in backups.items():
                backup.replace(destination)
            raise
    return dict(packageFiles=published, chunkId=chunk_id, containerId=identity['containerId'],
                packageSha256=hashes, packagedAssets=sorted('/Game/'+path[len('SB/Content/'):-7] for path in expected),
                validation=dict(retocVersion='0.1.5', binaryVerified=True, exactAssetSet=True,
                    installedConflictsChecked=paks is not None, actualContainerIdChecked=True,
                    engineInvoked=False, inGameVisualTested=False, **profile))
