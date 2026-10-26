"""Checked CNS decoder repairs. Does not access UObjects or game files.

Prepared material arrays are positional. CNS's Blueprint RemoveEmptyStrings
also deduplicates paths, so blank and repeated entries must be encoded before
passing through that helper. The per-slot export-text prefix is stripped by
UE4.26's FSoftObjectPath parser; the underlying material path stays unchanged.
"""
MARKER='-- OutfitColours: clear unused advanced output slots'
POSITIONAL_MARKER='-- OutfitColours: preserve prepared material positions'

def patch_stale_outputs(source):
    source=source.replace('\r\n','\n')
    if MARKER not in source:
        source = _patch_stale_outputs(source)
    source = _patch_positional_materials(source)
    return _patch_selection_fallback(source)


def _patch_selection_fallback(source):
    marker='-- OutfitColours: recover a stale prepared selection'
    if marker in source:return source
    old='local jsonData = jsonObject.OutfitDatas[InDataIndex:get() + 1] -- +1 because JSON arrays are 0-indexed in Lua'
    if source.count(old)!=1:
        raise ValueError('CNS selection decoder differs from the inspected version; no helper was overwritten.')
    new='''-- OutfitColours: recover a stale prepared selection
    local selectedIndex = InDataIndex:get() + 1
    local jsonData = jsonObject.OutfitDatas[selectedIndex]
    if not jsonData and #jsonObject.OutfitDatas > 0 then
        -- Original index zero is always retained. Old removed alternates must
        -- never dereference a nil mesh/material record after an upgrade.
        jsonData = jsonObject.OutfitDatas[1]
        Log("Unavailable outfit selection; using its first original variant. Reselect the desired outfit in CNS.")
    end'''
    return source.replace(old,new,1)

def _patch_stale_outputs(source):
    old_material='if i > #jsonData.Materials then return end'
    old_parameter='if i > #jsonData.Parameters then return end'
    if source.count(old_material)!=1 or source.count(old_parameter)!=1:
        raise ValueError('CNS advanced decoder differs from the inspected version; no helper was overwritten.')
    source=source.replace(old_material,'''-- OutfitColours: clear unused advanced output slots
        if i > #jsonData.Materials then
            v:set("")
            return
        end''',1)
    source=source.replace(old_parameter,'''if i > #jsonData.Parameters then
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
        end''',1)
    return source

def _patch_positional_materials(source):
    if POSITIONAL_MARKER in source:
        return source
    start='    OutMats:ForEach(function(i, v)\n        '+MARKER
    end='    OutOpts:ForEach(function(i, v)'
    if source.count(start)!=1 or source.count(end)!=1:
        raise ValueError('CNS advanced material decoder differs from the inspected version; no helper was overwritten.')
    first=source.index(start)
    last=source.index(end,first)
    original=source[first:last]
    if not original.rstrip().endswith('end)'):
        raise ValueError('CNS advanced material decoder has an unexpected boundary.')
    replacement='''    -- OutfitColours: preserve prepared material positions
    if jsonData.OutfitColoursPrepared == true then
        -- BP RemoveEmptyStrings uses AddUnique: raw blanks or duplicate paths
        -- would move a later clothing material onto an earlier skin slot.
        -- Use the normal FString-array setter, as CNS does for OutfitPaths.
        -- Struct parameter arrays remain bounded and are never resized here.
        local MaterialPaths = {}
        for i, MatData in ipairs(jsonData.Materials) do
            if MatData == "" then
                -- This resident UObject class is never a MaterialInstance.
                -- The Blueprint's checked material cast therefore skips it,
                -- preserving the existing slot without invalid-path errors.
                MaterialPaths[i] = "OutfitColoursSlot_" .. i .. "'/Script/CoreUObject.Object'"
            else
                MaterialPaths[i] = "OutfitColoursSlot_" .. i .. "'" .. MatData .. "'"
            end
        end
        OutMatsArray:set(MaterialPaths)
    else
'''+original+'''    end
'''
    return source[:first]+replacement+source[last:]
