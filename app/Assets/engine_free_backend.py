"""Experimental replacement for editor-based prepared texture/material cooking.

Input is the preparer's cook-job JSON. No UE commandlets, UnrealPak or engine
installation are used. PNG recolouring itself remains in the preparer's colour
policy stage; this backend builds game assets from those already recoloured PNGs.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'assets'))
sys.path.insert(0, str(ROOT / 'packaging'))
from asset_writer import object_path, write_material, write_texture


def publish_complete(stage, output, filenames):
    """Publish package triplet and its manifest together, restoring on failure."""
    stage, output = Path(stage), Path(output)
    for name in filenames:
        if Path(name).name != name:
            raise ValueError('Publication requires plain filenames')
        target = output / name
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ValueError('Completed output destination must be an ordinary file')
    backups, published = {}, []
    try:
        for name in filenames:
            source, target = stage / name, output / name
            if target.exists():
                backup = stage / ('previous-' + name)
                target.replace(backup)
                backups[target] = backup
            source.replace(target)
            published.append(target)
    except BaseException:
        for target in published:
            target.unlink(missing_ok=True)
        for target, backup in backups.items():
            backup.replace(target)
        raise


def validate_job(raw):
    output = Path(raw['outputRoot']).expanduser().resolve()
    paks = Path(raw['pakRoot']).expanduser().resolve() if raw.get('pakRoot') else None
    if paks and (output == paks or output.is_relative_to(paks)):
        raise ValueError('Output must be outside the installed Paks folder')
    occupied = set()
    known_textures = set()
    for key in ('textures', 'materials'):
        rows = raw.get(key, [])
        if not isinstance(rows, list):
            raise ValueError('Asset lists are required')
        for row in rows:
            package, name = object_path(row['assetPath'], generated=True)
            if package.casefold() in occupied:
                raise ValueError('Duplicate output asset path')
            occupied.add(package.casefold())
            if key == 'textures':
                source = Path(row['sourcePng']).resolve()
                if not source.is_file() or source.suffix.lower() != '.png':
                    raise ValueError('Texture input must be an existing PNG')
                known_textures.add(package + '.' + name)
    if not occupied:
        raise ValueError('No assets selected for building')
    for row in raw.get('materials', []):
        object_path(row['parent'])
        for param in row.get('textureParameters', []):
            original=param.get('sourceReference') is True
            package, name = object_path(param['value'], generated=not original)
            if original and package.startswith('/Game/OutfitReversalPrepared/'):
                raise ValueError('An original texture reference must not point to generated assets')
            if not original and package + '.' + name not in known_textures:
                raise ValueError('Child material references a texture missing from the job')
    return output, paks


def build(raw, *, progress=print):
    from pack_legacy import package_legacy
    output, paks = validate_job(raw)
    output.mkdir(parents=True, exist_ok=True)
    chunk = raw.get('chunkId', 61947)
    if isinstance(chunk, bool) or not isinstance(chunk, int) or not 1 <= chunk < 2**31:
        raise ValueError('Chunk number must be a positive signed 32-bit integer')
    started = time.monotonic()
    # All intermediates stay in a private fresh directory; existing completed
    # outputs are untouched if compression or serialization fails.
    scratch = output / 'builds'
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch, prefix='engine-free-') as temp:
        legacy = Path(temp) / 'legacy'
        textures = []
        materials = []
        for i, row in enumerate(raw.get('textures', []), 1):
            progress(f'Texture {i}/{len(raw["textures"])}: {object_path(row["assetPath"])[1]}')
            textures.append(write_texture(row, legacy, texconv=raw.get('texconv')))
        for i, row in enumerate(raw.get('materials', []), 1):
            progress(f'Material {i}/{len(raw["materials"])}: {object_path(row["assetPath"])[1]}')
            materials.append(write_material(row, legacy))
        progress('Packaging generated assets...')
        complete = Path(temp) / 'complete'
        result = package_legacy(legacy, complete, chunk_id=chunk, pak_root=paks,
                                retoc=raw.get('retoc'))
        names = [Path(p).name for p in result['packageFiles']]
        result['packageFiles'] = [str(output / name) for name in names]
        manifest = dict(result, textures=textures, materials=materials, backend='engine-free-prototype',
                        elapsedSeconds=round(time.monotonic() - started, 3),
                        validation=dict(result.get('validation', {}), engineInvoked=False,
                            inGameVisualTested=False, colourPolicyAppliedUpstream=True))
        manifest_name = 'prepared-cook-manifest.json'
        (complete / manifest_name).write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        publish_complete(complete, output, names + [manifest_name])
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job', type=Path, help='Preparation job JSON; source PNGs are already recoloured')
    args = parser.parse_args()
    raw = json.loads(args.job.read_text(encoding='utf-8-sig'))
    # Paths in a portable job belong to its own folder, never the caller's cwd.
    for key in ('outputRoot', 'pakRoot', 'retoc', 'texconv'):
        if raw.get(key) and not Path(raw[key]).is_absolute():
            raw[key] = str((args.job.resolve().parent / raw[key]).resolve())
    for row in raw.get('textures', []):
        if not Path(row['sourcePng']).is_absolute():
            row['sourcePng'] = str((args.job.resolve().parent / row['sourcePng']).resolve())
    result = build(raw)
    print(json.dumps({'success': True, 'backend': result['backend'],
                      'textures': len(result['textures']), 'materials': len(result['materials']),
                      'engineInvoked': False, 'inGameVisualTested': False}))


if __name__ == '__main__':
    main()
