"""Narrow, reversible CNS integration for two inspected upstream releases.

This module contains patch fragments, not upstream main.lua distributions.
It reads bytes supplied by its caller and never locates or edits a game itself.
Only exact, known baseline content (allowing BOM/CRLF) is supported. Modified
scripts are accepted only if reversing every edit recovers a known baseline.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

SUPPORTED = {
    "e4b44a7e892cfe95896f4add3730bbc9f6cf2c47035335526a9e415dc813299e": "CNS 2.2 original",
    "457cc625e03afdb059087ab45efe81665ff8fcb1fb6409a63be1055a03419e55": "CNS 2.2 Fix 1.4",
}
REVISION = "1"
MARKER = "-- OutfitColours public integration revision " + REVISION


class UnsupportedCNS(ValueError):
    """Input differs from an inspected baseline or this exact integration."""


@dataclass(frozen=True)
class Identification:
    baseline: str
    baseline_sha256: str
    integrated: bool
    revision: str | None


BOOTSTRAP = r'''-- OutfitColours public integration revision 1
-- Prepared metadata only: no renderer hooks or live UObject conversion.
local OutfitColoursBridge = {DecorateConfig = function(_, rows) return rows end}
do
    local ok, bridge = pcall(function()
        local source = debug.getinfo(1, "S").source:gsub("^@", "")
        local directory = assert(source:match("^(.*[/\\])"))
        return assert(loadfile(directory .. "OutfitReversal/Init.lua"))()
    end)
    if ok and type(bridge) == "table" and type(bridge.DecorateConfig) == "function" then
        OutfitColoursBridge = bridge
    else
        print("[OutfitColours] Prepared metadata unavailable; original CNS options remain available.\n")
    end
end
'''

POSITIONAL = '''    -- OutfitColours: preserve prepared material positions
    if jsonData.OutfitColoursPrepared == true then
        -- CNS's Blueprint deduplicates raw paths and removes empty strings.
        -- Export-text class prefixes keep slots distinct while resolving the
        -- same original object path through UE's normal soft-path parser.
        local MaterialPaths = {}
        for i, MatData in ipairs(jsonData.Materials) do
            if MatData == "" then
                MaterialPaths[i] = "OutfitColoursSlot_" .. i .. "'/Script/CoreUObject.Object'"
            else
                MaterialPaths[i] = "OutfitColoursSlot_" .. i .. "'" .. MatData .. "'"
            end
        end
        OutMatsArray:set(MaterialPaths)
    else
'''

SELECTION_OLD = '    local jsonData = jsonObject.OutfitDatas[InDataIndex:get() + 1] -- +1 because JSON arrays are 0-indexed in Lua'
SELECTION_NEW = '''    -- OutfitColours: recover a stale prepared selection
    local selectedIndex = InDataIndex:get() + 1
    local jsonData = jsonObject.OutfitDatas[selectedIndex]
    if not jsonData and #jsonObject.OutfitDatas > 0 then
        jsonData = jsonObject.OutfitDatas[1]
        Log("Unavailable outfit selection; using its first original variant. Reselect the desired outfit in CNS.")
    end'''

PARAM_OLD = '        if i > #jsonData.Parameters then return end'
PARAM_NEW = '''        if i > #jsonData.Parameters then
            local EmptyData = v:get()
            if EmptyData then
                EmptyData.MaterialIndex = 0
                EmptyData.Association = "Global"
                EmptyData.LayerIndex = -1
                EmptyData.ParamName = ""
                EmptyData.ParamType = ""
                EmptyData.FloatValue = 0
                EmptyData.FloatArray = {0, 0, 0, 0}
                EmptyData.StringValue = ""
            end
            return
        end'''

# Apply in sequence; reverse in reverse order. Each match must occur once.
EDITS = (
    ('local CNSHelpers = require("helpers")\n', 'local CNSHelpers = require("helpers")\n' + BOOTSTRAP),
    (
        '    CachedOutfitDatas[ConfigPath] = CachedOutfitDatas[ConfigPath] or CNSHelpers.loadJsonFile(ConfigPath)\n',
        '    CachedOutfitDatas[ConfigPath] = CachedOutfitDatas[ConfigPath] or CNSHelpers.loadJsonFile(ConfigPath)\n'
        '    CachedOutfitDatas[ConfigPath] = OutfitColoursBridge.DecorateConfig(ConfigPath, CachedOutfitDatas[ConfigPath])\n',
    ),
    (SELECTION_OLD, SELECTION_NEW),
    (
        '    OutMats:ForEach(function(i, v)\n        if i > #jsonData.Materials then return end',
        POSITIONAL + '    OutMats:ForEach(function(i, v)\n        if i > #jsonData.Materials then return end',
    ),
    ('        if i > #jsonData.Materials then return end', '''        -- OutfitColours: clear unused advanced output slots
        if i > #jsonData.Materials then
            v:set("")
            return
        end'''),
    ('    OutOpts:ForEach(function(i, v)\n', '    end\n    OutOpts:ForEach(function(i, v)\n'),
    (PARAM_OLD, PARAM_NEW),
)


def _text(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig").replace("\r\n", "\n")
    except UnicodeDecodeError as exc:
        raise UnsupportedCNS("CNS script is not valid UTF-8; no output was written.") from exc


def _change(source: str, reverse: bool = False) -> str:
    operations = reversed(EDITS) if reverse else EDITS
    for old, new in operations:
        before, after = (new, old) if reverse else (old, new)
        if source.count(before) != 1:
            raise UnsupportedCNS("CNS script differs from the checked integration; no output was written.")
        source = source.replace(before, after, 1)
    return source


def identify(raw: bytes) -> Identification:
    source = _text(raw)
    integrated = MARKER in source
    baseline = _change(source, reverse=True) if integrated else source
    digest = sha256(baseline.encode("utf-8")).hexdigest()
    if digest not in SUPPORTED:
        raise UnsupportedCNS("Unsupported CNS script. Use a supported original CNS 2.2 or CNS 2.2 Fix 1.4 installation.")
    if integrated and _change(baseline) != source:
        raise UnsupportedCNS("Modified integration was rejected; no output was written.")
    return Identification(SUPPORTED[digest], digest, integrated, REVISION if integrated else None)


def integrate(raw: bytes) -> bytes:
    state = identify(raw)
    if state.integrated:
        return raw
    changed = _change(_text(raw))
    if raw.count(b"\r\n") == raw.count(b"\n") and b"\r\n" in raw:
        changed = changed.replace("\n", "\r\n")
    result = changed.encode("utf-8")
    return (b"\xef\xbb\xbf" + result) if raw.startswith(b"\xef\xbb\xbf") else result


def remove_integration(raw: bytes) -> bytes:
    state = identify(raw)
    if not state.integrated:
        return raw
    changed = _change(_text(raw), reverse=True)
    if raw.count(b"\r\n") == raw.count(b"\n") and b"\r\n" in raw:
        changed = changed.replace("\n", "\r\n")
    result = changed.encode("utf-8")
    return (b"\xef\xbb\xbf" + result) if raw.startswith(b"\xef\xbb\xbf") else result


def main() -> int:
    parser = argparse.ArgumentParser(description="Check or stage a supported CNS integration; never edits the input.")
    parser.add_argument("source", type=Path, help="Installed CNS Scripts/main.lua")
    parser.add_argument("--output", type=Path, help="New output file; existing files are refused")
    args = parser.parse_args()
    raw = args.source.read_bytes()
    state = identify(raw)
    print(state.baseline + ("; integration already present" if state.integrated else "; ready to integrate"))
    if args.output:
        if args.output.resolve() == args.source.resolve():
            parser.error("Choose a separate staging output; this command does not replace installed scripts.")
        with args.output.open("xb") as stream:
            stream.write(integrate(raw))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
