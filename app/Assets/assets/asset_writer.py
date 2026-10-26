"""UE4.26 prepared Texture2D/MIC authoring without Unreal Editor.

Uses neutral, previously cooked templates and the MIT UE4-DDS-Tools serializer.
Only generated /Game/OutfitReversalPrepared paths are accepted for outputs.
Original parent materials remain external dependencies; no shaders are authored.
"""
from __future__ import annotations
import contextlib
import hashlib
import io
import math
from pathlib import Path
import re
import struct
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / 'vendor' / 'UE4-DDS-Tools' / 'src'
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))
from unreal.uasset import Uasset
from unreal.import_export import UassetName, UassetImport
from directx.dds import DDS

PREFIX = '/Game/OutfitReversalPrepared/'
# Existing cooked asset names can contain hyphens, including the object name.
# Keep generated destinations on their previous narrower allowlist.
PATH = re.compile(r'^/Game/(?:[\w-]+/)*[\w-]+(?:\.[\w-]+)?$')
GENERATED_PATH = re.compile(r'^/Game/(?:[\w-]+/)*[\w]+(?:\.[\w]+)?$')


def object_path(value, generated=False):
    pattern = GENERATED_PATH if generated else PATH
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError('Invalid game asset reference')
    package, _, name = value.partition('.')
    short = package.rsplit('/', 1)[1]
    if name and name != short:
        raise ValueError('Object name must match the package basename')
    if generated and not package.startswith(PREFIX):
        raise ValueError('Output asset must have an isolated prepared path')
    return package, short


def destination(root, value):
    package, _ = object_path(value, generated=True)
    root = Path(root).resolve()
    result = (root / 'SB' / 'Content' / package[len('/Game/'):]).with_suffix('.uasset')
    if not result.resolve().is_relative_to(root):
        raise ValueError('Output escapes its staging directory')
    return result


def load(path):
    with contextlib.redirect_stdout(io.StringIO()):
        result = Uasset(str(path), '4.26')
    if len(result.exports) != 1:
        raise ValueError('Only one-export neutral templates are supported')
    return result


def save(asset, output):
    asset.header.guid = uuid.uuid4().bytes
    asset.header.generation_data = [1, len(asset.name_list)]
    asset.header.package_source = 0
    with contextlib.redirect_stdout(io.StringIO()):
        asset.save(str(output))


def _name(asset, text):
    for i, name in enumerate(asset.name_list):
        if str(name) == text:
            return i
    item = UassetName()
    item.update(text, update_hash=True)
    asset.name_list.append(item)
    encoded = text.encode('ascii') if text.isascii() else text.encode('utf-16-le')
    asset.header.inc_file_size(4 + len(encoded) + (1 if text.isascii() else 2) + 4)
    return len(asset.name_list) - 1


def _fname(asset, text):
    return struct.pack('<ii', _name(asset, text), 0)


def _tag(asset, name, kind, data, extra=b''):
    return (_fname(asset, name) + _fname(asset, kind) + struct.pack('<ii', len(data), 0)
            + extra + b'\0' + data)


def _struct(asset, name, kind, data):
    return _tag(asset, name, 'StructProperty', data, _fname(asset, kind) + bytes(16))


def _array(asset, name, kind, values):
    if not values:
        return b''
    items = b''.join(values)
    inner = _struct(asset, name, kind, items)
    return _tag(asset, name, 'ArrayProperty', struct.pack('<i', len(values)) + inner,
                _fname(asset, 'StructProperty'))


def _parameter_info(asset, name):
    return _struct(asset, 'ParameterInfo', 'MaterialParameterInfo',
        _tag(asset, 'Name', 'NameProperty', _fname(asset, name))
        + _tag(asset, 'Association', 'ByteProperty', _fname(asset, 'GlobalParameter'),
               _fname(asset, 'EMaterialParameterAssociation'))
        + _tag(asset, 'Index', 'IntProperty', struct.pack('<i', -1))
        + _fname(asset, 'None'))


def write_material(row, output_root, template=None):
    """Write one child MIC, arbitrary global texture/vector overrides, no static data."""
    package, name = object_path(row['assetPath'], generated=True)
    parent_package, parent_name = object_path(row['parent'])
    if parent_package.startswith(PREFIX):
        raise ValueError('Parent must be the original material outside generated assets')
    parent_class = row.get('parentClass', 'MaterialInstanceConstant')
    if parent_class not in ('MaterialInstanceConstant', 'Material'):
        raise ValueError('Unsupported original parent class')
    a = load(template or ROOT / 'templates' / 'MI_Template.uasset')
    if a.exports[0].class_name != 'MaterialInstanceConstant':
        raise ValueError('Invalid material template')
    # Rebuild names/imports; no source outfit names or unused references survive.
    a.name_list = []
    a.imports = []
    core = _name(a, '/Script/CoreUObject')
    engine = _name(a, '/Script/Engine')
    _name(a, package)

    def add_import(class_name, text, outer=0, class_package=None):
        imp = UassetImport()
        imp.class_package_name_id = core if class_package is None else class_package
        imp.class_package_name_number = imp.class_name_number = imp.name_number = 0
        imp.class_name_id = _name(a, class_name)
        imp.class_package_import_id = outer
        imp.name_id = _name(a, text)
        a.imports.append(imp)
        return -len(a.imports)

    engine_package = add_import('Package', '/Script/Engine')
    mic_class = add_import('Class', 'MaterialInstanceConstant', engine_package)
    cdo = add_import('MaterialInstanceConstant', 'Default__MaterialInstanceConstant', engine_package, engine)
    pp = add_import('Package', parent_package)
    parent = add_import(parent_class, parent_name, pp, engine)
    texture_refs = {}
    texture_values = []
    vector_values = []
    used = set()
    for kind, rows in (('texture', row.get('textureParameters', [])), ('vector', row.get('vectorParameters', []))):
        for param in rows:
            if (param.get('association', 2) not in (2, 'Global') or param.get('index', -1) != -1):
                raise ValueError('Only Global parameter association is supported')
            pn = param.get('name')
            if not isinstance(pn, str) or not pn or len(pn) > 256 or '\0' in pn:
                raise ValueError('Invalid parameter name')
            identity = (kind, pn.casefold())
            if identity in used:
                raise ValueError('Duplicate parameter override')
            used.add(identity)
            item = _parameter_info(a, pn)
            if kind == 'texture':
                original=param.get('sourceReference') is True
                tp, tn = object_path(param['value'], generated=not original)
                if original and tp.startswith(PREFIX):
                    raise ValueError('An original texture reference cannot point to generated assets')
                if tp not in texture_refs:
                    texture_refs[tp] = add_import('Texture2D', tn, add_import('Package', tp), engine)
                item += _tag(a, 'ParameterValue', 'ObjectProperty', struct.pack('<i', texture_refs[tp]))
                values = texture_values
            else:
                value = param['value']
                if len(value) != 4 or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in value):
                    raise ValueError('Vector needs four finite channels')
                item += _struct(a, 'ParameterValue', 'LinearColor', struct.pack('<4f', *value))
                values = vector_values
            item += _struct(a, 'ExpressionGUID', 'Guid', bytes(16)) + _fname(a, 'None')
            values.append(item)
    data = _tag(a, 'Parent', 'ObjectProperty', struct.pack('<i', parent))
    data += _array(a, 'VectorParameterValues', 'VectorParameterValue', vector_values)
    data += _array(a, 'TextureParameterValues', 'TextureParameterValue', texture_values)
    data += _fname(a, 'None') + bytes(4)  # UObject GUID flag; MIC has no static permutation.
    exp = a.exports[0]
    exp.name_id = _name(a, name)
    exp.name_number = 0
    exp.class_index = mic_class
    exp.template_index = cdo
    exp.outer_index = exp.super_index = 0
    # Import creation precedes child serialization; class/CDO serialization
    # precedes child creation. Matches UE4.26's cooked MIC dependencies.
    deps = [parent] + list(texture_refs.values())
    a.preload_dependency_ids = deps + [mic_class, cdo]
    a.header.preload_dependency_count = len(a.preload_dependency_ids)
    exp.remainings = exp.remainings[:-20] + struct.pack('<5i', 0, 0, len(deps), 2, 0)
    exp.object.bin = data
    exp.object.uexp_size = len(data)
    a.depends_map = [0]
    output = destination(output_root, row['assetPath'])
    save(a, output)
    reread = load(output)
    if len(reread.imports) != len(a.imports) or reread.exports[0].object.bin != data:
        raise RuntimeError('Material serialization roundtrip failed')
    return dict(row, cookedObjectPath=package + '.' + name, parentClass=parent_class,
                staticOverridesAuthored=False)


def write_texture(row, output_root, template=None, texconv=None):
    """PNG -> compressed mipchain, or exact-size NPOT BGRA -> cooked Texture2D."""
    from PIL import Image
    package, name = object_path(row['assetPath'], generated=True)
    source = Path(row['sourcePng']).resolve()
    if row.get('sourceSha256') and hashlib.sha256(source.read_bytes()).hexdigest() != row['sourceSha256']:
        raise ValueError('Prepared texture input changed after the job was created')
    with Image.open(source) as image:
        if image.width < 1 or image.height < 1 or max(image.size) > 8192:
            raise ValueError('Texture dimensions must be 1..8192')
        dimensions = image.size
        alpha = image.convert('RGBA').getchannel('A').getextrema()[0] != 255
    a = load(template or ROOT / 'templates' / 'T_Template.uasset')
    if a.exports[0].class_name != 'Texture2D':
        raise ValueError('Invalid texture template')
    old_name = str(a.name_list[a.exports[0].name_id])
    for i, item in enumerate(list(a.name_list)):
        text = str(item)
        if text == old_name:
            a.update_name_list(i, name)
        elif text.startswith('/Game/'):
            a.update_name_list(i, package)
    texture = a.get_texture_list()[0]
    # Author ordinary properties, with no source-file metadata.
    texture.props = (
        _struct(a, 'ImportedSize', 'IntPoint', struct.pack('<2i', *dimensions))
        + _struct(a, 'LightingGuid', 'Guid', uuid.uuid4().bytes)
        + _tag(a, 'LODGroup', 'ByteProperty', _fname(a, 'TEXTUREGROUP_Character'), _fname(a, 'TextureGroup'))
        + _fname(a, 'None') + bytes(4) + b'\1\0\1\0\1\0\0\0')
    output = destination(output_root, row['assetPath'])
    work = Path(output_root).resolve() / '_dds' / name
    work.mkdir(parents=True, exist_ok=True)
    converter = Path(texconv or ROOT / 'vendor' / 'texconv-v0.6.0' / 'texconv.exe').resolve()
    if not converter.is_file():
        raise FileNotFoundError('Standalone texture converter not found')
    power_of_two = all((n & (n - 1)) == 0 for n in dimensions)
    compressed = min(dimensions) >= 4 and power_of_two
    # Block rounding must never pad an outfit's original UV atlas. Like UE4's
    # no-mip NPOT policy, retain exact source dimensions rather than resize.
    fmt = ('BC3_UNORM' if alpha else 'BC1_UNORM') if compressed else 'B8G8R8A8_UNORM'
    pixel_format = ('PF_DXT5' if alpha else 'PF_DXT1') if compressed else 'PF_B8G8R8A8'
    result = subprocess.run([str(converter), '-nologo', '-y', '-m', '0' if power_of_two else '1', '-srgb', '-sepalpha',
        '-f', fmt, '-o', str(work), str(source)], capture_output=True, text=True,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError('Texture compression failed: ' + result.stdout[-1200:] + result.stderr[-1200:])
    dds_path = work / (source.stem + '.dds')
    with contextlib.redirect_stdout(io.StringIO()):
        dds = DDS.load(str(dds_path))
        texture.change_format(pixel_format)
        texture.inject_dds(dds)
    # DDS is an intermediate, not an asset to include in the legacy package tree.
    dds_path.unlink()
    # Keep larger mip levels streamable. The tiny neutral template has none.
    for mip in texture.mipmaps:
        inline = not compressed or max(mip.width, mip.height) <= 256
        mip.update(mip.data, (mip.width, mip.height), 1, inline)
    texture.has_ubulk = any(mip.has_ubulk_bulk() for mip in texture.mipmaps)
    texture.has_uptnl = False
    save(a, output)
    reread = load(output).get_texture_list()[0]
    if (reread.get_max_size() != dimensions or len(reread.mipmaps) != len(texture.mipmaps)
        or [m.data for m in reread.mipmaps] != [m.data for m in texture.mipmaps]):
        raise RuntimeError('Texture and mip serialization roundtrip failed')
    return dict(row, cookedObjectPath=package + '.' + name, pixelFormat=texture.pixel_format,
                width=dimensions[0], height=dimensions[1], mipCount=len(texture.mipmaps),
                srgb=True, sourceHasAlpha=alpha, streamableBulk=texture.has_ubulk)
