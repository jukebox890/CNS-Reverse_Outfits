"""Read-only asset-reader setup from a pinned official FModel download.

Reader assemblies are obtained into the downloader's local cache, not harvested
from a developer machine or distributed with user-specific configuration.
"""
import hashlib
import io
import json
from pathlib import Path
import struct
import urllib.request
import zipfile
import zlib

URL = 'https://github.com/4sval/FModel/releases/download/aug-2026/FModel.zip'
SHA256 = 'ce1995fbc876cd0d0f54d3f7af5babc0e949d87fe4c4f2fada55c6e1e062eacc'
MARKER = bytes.fromhex('8b1202b96a612038727b930214d7a03213f5b9e6efae3318ee3b2dce24b36aae')
FILES = {
    'AssetRipper.TextureDecoder.dll', 'blake3_dotnet.dll', 'Blake3.dll',
    'BouncyCastle.Cryptography.dll', 'CommunityToolkit.HighPerformance.dll',
    'CUE4Parse-Conversion.dll', 'CUE4Parse-Natives.dll', 'CUE4Parse.dll',
    'FixedMathSharp.dll', 'Fmod5Sharp.dll', 'GenericReader.dll',
    'K4os.Compression.LZ4.dll', 'libSkiaSharp.dll', 'MemoryPack.Core.dll',
    'NAudio.Core.dll', 'Newtonsoft.Json.dll', 'OffiUtils.dll',
    'OggVorbisEncoder.dll', 'Oodle.NET.dll', 'OodleSharp.dll', 'Serilog.dll',
    'SevenZip.dll', 'SharpGLTF.Core.dll', 'SharpGLTF.Toolkit.dll',
    'SixLabors.ImageSharp.dll', 'SkiaSharp.dll', 'SubstreamSharp.dll',
    'System.IO.Hashing.dll', 'UE4Config.dll', 'VGAudio.dll',
    'Zlib-ng.NET.dll', 'ZstdSharp.dll', 'zlib-ng2.dll', 'oodle-data-shared.dll',
}


def read_string(stream):
    size, shift = 0, 0
    for _ in range(5):
        byte = stream.read(1)
        if not byte:
            raise ValueError('Incomplete .NET bundle string')
        byte = byte[0]
        size |= (byte & 127) << shift
        if byte < 128:
            if size > 1024 * 1024:
                raise ValueError('Bundle string exceeds supported size')
            return stream.read(size).decode('utf-8')
        shift += 7
    raise ValueError('Invalid bundle string length')


def bundle_entries(data):
    marker = data.find(MARKER)
    if marker < 8:
        raise ValueError('Official FModel is not a supported .NET bundle')
    offset = struct.unpack_from('<Q', data, marker - 8)[0]
    if offset >= len(data):
        raise ValueError('Invalid .NET bundle header')
    stream = io.BytesIO(data);stream.seek(offset)
    major, minor, count = struct.unpack('<IIi', stream.read(12))
    if major not in (2, 6) or not 1 <= count <= 2000:
        raise ValueError('Unsupported .NET bundle version')
    read_string(stream)
    stream.read(40)  # deps/runtimeconfig offsets + flags
    entries = []
    for _ in range(count):
        offset, size = struct.unpack('<QQ', stream.read(16))
        compressed = struct.unpack('<Q', stream.read(8))[0] if major >= 6 else 0
        kind = stream.read(1)[0]
        name = read_string(stream)
        if offset + (compressed or size) > len(data) or size > 256 * 1024 * 1024:
            raise ValueError('Bundle member is outside its file')
        entries.append(dict(name=name,offset=offset,size=size,compressed=compressed,kind=kind))
    return entries


def extract_reader(archive, destination):
    archive, destination = Path(archive), Path(destination)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise ValueError('Asset-reader download differs from the pinned official release')
    with zipfile.ZipFile(archive) as zipped:
        names = [n for n in zipped.namelist() if n.lower().endswith('fmodel.exe')]
        if len(names) != 1:
            raise ValueError('Official archive does not contain one FModel executable')
        data = zipped.read(names[0])
    entries = bundle_entries(data)
    destination.mkdir(parents=True, exist_ok=True)
    written = []
    for row in entries:
        if row['name'] not in FILES:
            continue
        content = data[row['offset']:row['offset'] + (row['compressed'] or row['size'])]
        if row['compressed']:
            content = zlib.decompress(content, -15)
        if len(content) != row['size']:
            raise ValueError('Reader member has an invalid decompressed size')
        (destination / row['name']).write_bytes(content)
        written.append(dict(name=row['name'],sha256=hashlib.sha256(content).hexdigest()))
    required = {'CUE4Parse.dll','CUE4Parse-Conversion.dll','libSkiaSharp.dll'}
    if not required.issubset({r['name'] for r in written}):
        raise ValueError('Official release is missing required asset-reader libraries')
    (destination/'reader-provenance.json').write_text(json.dumps(dict(source=URL,sha256=SHA256,files=written),indent=2))
    return destination


def ensure_reader(settings, output):
    folder = Path(settings.get('libraries') or Path(output)/'Reader')
    valid = False
    try:
        provenance = json.loads((folder/'reader-provenance.json').read_text())
        rows = provenance['files']
        valid = (provenance['sha256'] == SHA256 and len(rows) >= 3
                 and {'CUE4Parse.dll','CUE4Parse-Conversion.dll','libSkiaSharp.dll'}.issubset({r['name'] for r in rows})
                 and all(r['name'] in FILES and hashlib.sha256((folder/r['name']).read_bytes()).hexdigest() == r['sha256'] for r in rows))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    if not valid:
        archive = Path(settings.get('readerArchive') or Path(output)/'ReaderCache'/'FModel.zip')
        if not archive.is_file():
            archive.parent.mkdir(parents=True,exist_ok=True)
            print('Setting up the asset reader from the official FModel release (first preparation only).',flush=True)
            request = urllib.request.Request(URL,headers={'User-Agent':'OutfitColours-Preparer'})
            with urllib.request.urlopen(request,timeout=120) as response, archive.open('wb') as target:
                while block := response.read(1024*1024):
                    target.write(block)
        extract_reader(archive,folder)
    settings['libraries'] = str(folder.resolve())
    settings['nativeRoot'] = str(folder.resolve())
    return folder
