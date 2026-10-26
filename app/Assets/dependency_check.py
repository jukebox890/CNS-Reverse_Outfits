"""Bounded, offline dependency advice. Never downloads, loads DLLs or edits a game."""
from hashlib import sha256
from pathlib import Path
import re
from time import perf_counter

CNS_URL = 'https://www.nexusmods.com/stellarblade/mods/1496'
UE4SS_URL = 'https://www.nexusmods.com/stellarblade/mods/2952'
# Official SB UE4SS 1.3 release, independently checked against archive SHA256
# 1001bfb90dc16a76f585616a1105657c7fdbc48bb749d26c3262a30c61de83eb.
# Its own runtime log says 3.0.1 Beta: that label is NOT its distribution version.
UE4SS_13 = {
    'ue4ss/UE4SS.dll': 'e0cc51ce5b47d5be82194510b0b4b4054dd15ce0322a983655a022f92d27dabe',
    'dwmapi.dll': 'a30732477f2d7134b712aa1d295ebdf2f1b5a9dd46a10b6ce494819cba1774fa',
    'ue4ss/Mods/BPModLoaderMod/Scripts/main.lua': '943d3ea59345ab804ac46c38573ce20b1bb1e53f851800db2a0fead3edb03ee3',
    'ue4ss/UE4SS_Signatures/FText_Constructor.lua': '141a03057e16408a520356a58052dfccca7f5a0ba371925b12208e75235f92f7',
}


def _read(path, limit):
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('File exceeds quick-check limit')
    return raw


def _row(name, state, version, message, url):
    return dict(name=name, state=state, version=version, message=message, url=url)


def _ue4ss(binary):
    dll = binary/'ue4ss/UE4SS.dll'
    if not dll.is_file():
        return _row('UE4SS', 'missing', None, 'Install Stellar Blade UE4SS 1.3 or a newer stable SB release before playing.', UE4SS_URL)
    for relative, expected in UE4SS_13.items():
        path = binary/relative
        if not path.is_file():
            return _row('UE4SS', 'incomplete', None, 'UE4SS installation is incomplete. Install the complete Stellar Blade UE4SS 1.3 release.', UE4SS_URL)
        if sha256(_read(path, 64*1024*1024)).hexdigest() != expected:
            return _row('UE4SS', 'unverified', None, 'UE4SS found; SB release version could not be verified. Check or update to stable SB UE4SS 1.3 or newer; a generic 3.x/beta label is not evidence of a newer SB release.', UE4SS_URL)
    return _row('UE4SS', 'ok', 'SB 1.3', 'Stellar Blade UE4SS 1.3 verified.', UE4SS_URL)


def _cns(binary, paks, containers):
    main = binary/'ue4ss/Mods/DekCNS/Scripts/main.lua'
    if not main.is_file():
        return _row('CNS', 'missing', None, 'Install Custom Nanosuit System 2.2 or newer before preparing outfits.', CNS_URL)
    text = _read(main, 2*1024*1024).decode('utf-8-sig')
    # Only the source's assignment counts, not a URL, comment or runtime log.
    match = re.search(r'^\s*(?:local\s+)?CNS_Version\s*=\s*[\'"]([0-9]+(?:\.[0-9]+){1,3})([^\'"\r\n]*)[\'"]', text, re.M)
    version = match.group(1) if match else None
    candidates = [paks/'LogicMods/DekCNS_P.utoc']
    candidates.extend(Path(row['path']) for row in containers if Path(row.get('path', '')).stem.lower() == 'dekcns_p')
    package = any(all(path.with_suffix(ext).is_file() for ext in ('.pak', '.utoc', '.ucas')) for path in candidates)
    if not package:
        return _row('CNS', 'incomplete', version, 'CNS helper found, but its complete DekCNS_P package was not found. Install the complete Custom Nanosuit System download.', CNS_URL)
    if not match:
        return _row('CNS', 'unverified', None, 'CNS found; version could not be read. Verify Custom Nanosuit System 2.2 or newer is installed.', CNS_URL)
    if match.group(2).strip() or tuple(map(int, version.split('.'))) < (2, 2):
        return _row('CNS', 'update', version, 'Update Custom Nanosuit System to stable 2.2 or newer before preparing outfits.', CNS_URL)
    return _row('CNS', 'ok', version, 'Custom Nanosuit System '+version+' found. Script compatibility is checked separately when preparing.', CNS_URL)


def check(pak_root, containers=()):
    started = perf_counter()
    paks = Path(pak_root)
    binary = paks.parents[1]/'Binaries/Win64'
    rows = []
    for name, inspect, url in (('CNS', lambda: _cns(binary, paks, containers), CNS_URL), ('UE4SS', lambda: _ue4ss(binary), UE4SS_URL)):
        try:
            rows.append(inspect())
        except (OSError, ValueError, UnicodeError):
            rows.append(_row(name, 'unverified', None, name+' could not be checked quickly. Verify its installation using the linked mod page.', url))
    return dict(items=rows, elapsedMs=round((perf_counter()-started)*1000, 2), offline=True)
