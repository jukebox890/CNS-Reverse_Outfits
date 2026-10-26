-- CNS metadata only. Prepared assets are selected through CNS's normal loader.
-- No UE4SS hooks, UObject access, renderer operations, or outfit profiles.
local Module = {}

local function clone(value, seen)
    if type(value) ~= "table" then return value end
    seen = seen or {}
    if seen[value] then return seen[value] end
    local output = {}; seen[value] = output
    for key, item in pairs(value) do output[clone(key, seen)] = clone(item, seen) end
    return output
end
local function array(value)
    local output = {}
    for i, item in ipairs(type(value) == "table" and value or {}) do output[i] = item end
    return output
end
local function dense(value)
    if type(value) ~= "table" then return false end
    local count = 0
    for key in pairs(value) do
        if type(key) ~= "number" or key % 1 ~= 0 or key < 1 then return false end
        count = count + 1
    end
    return count == #value
end
local function integer(value, minimum)
    return type(value) == "number" and value == value and value % 1 == 0 and value >= minimum
end
local function finite(value)
    return type(value) == "number" and value == value and value ~= math.huge and value ~= -math.huge
end
local function body(meshType) return meshType == nil or meshType == "" or meshType == "Body" end
local function parameterKey(spec)
    if type(spec) ~= "table" or not integer(spec.MaterialIndex or 0, 0)
        or type(spec.ParamName) ~= "string" or spec.ParamName == "" then return nil end
    local association, layer = spec.Association or "Global", spec.LayerIndex or -1
    if association ~= "Global" and association ~= "Layer" and association ~= "Blend" then return nil end
    if not integer(layer, -1) then return nil end
    local kind = spec.ParamType
    if kind ~= "Texture" and kind ~= "Vector" and kind ~= "Scalar" then return nil end
    return table.concat({spec.MaterialIndex or 0, association, layer, spec.ParamName, kind}, "\0")
end
local function validParameter(spec)
    if not parameterKey(spec) then return false end
    if spec.ParamType == "Texture" then return type(spec.Value) == "string" end
    if spec.ParamType == "Scalar" then return finite(spec.Value) end
    if not dense(spec.Value) or (#spec.Value ~= 3 and #spec.Value ~= 4) then return false end
    for _, value in ipairs(spec.Value) do if not finite(value) then return false end end
    return true
end

function Module.new(options)
    options = options or {}
    local api, reported, registrations = {}, {}, {}
    local enabled = options.enabled ~= false
    local decorated = setmetatable({}, {__mode = "k"})
    local prepared = options.prepared
    local function warn(code, message)
        if reported[code] then return end
        reported[code] = true
        if options.log then options.log(message) else print("[OutfitReversal] " .. message .. "\n") end
    end
    if type(prepared) ~= "table" or prepared.schemaVersion ~= 1 or type(prepared.outfits) ~= "table" then
        if prepared ~= nil then warn("schema", "Prepared.json has an unsupported schema; originals remain available.") end
        prepared = {schemaVersion = 1, outfits = {}}
    end

    local function prepareVariants(original, variants, advanced, count, supplied)
        local item = supplied
        if item == nil then item = prepared.outfits[original.UniqueFitID] end
        if item == nil then return nil end
        local function reject(reason) return nil, "Prepared outfit rejected: " .. original.UniqueFitID .. " (" .. reason .. ")" end
        if type(item) ~= "table" or item.originalCount ~= count or not dense(item.variants) or #item.variants ~= count then
            return reject("source variant count changed")
        end
        local result, states = {}, {}
        for i = 1, count do
            local source = advanced and variants[i] or {
                Mesh = variants[i], Materials = {}, Parameters = {},
                PonyPhysics = original.PonyPhysics or "", HiddenMats = clone(original.HiddenMats or {}),
            }
            local spec = item.variants[i]
            if type(spec) ~= "table" or spec.mesh ~= source.Mesh then return reject("source mesh changed") end
            if spec.supported == false then
                result[i], states[i] = clone(source), {supported = false, mode = spec.mode or "reverse"}
            else
            if not dense(spec.materials) or #spec.materials > 256 then return reject("invalid material array or more than 256 materials") end
            for _, path in ipairs(spec.materials) do
                if type(path) ~= "string" then return reject("materials must be positional path strings") end
            end
            local additions, replaced = spec.parameters or {}, spec.replacedParameters or {}
            if not dense(additions) or not dense(replaced) then return reject("invalid parameter arrays") end
            local remove, updates = {}, {}
            for _, keySpec in ipairs(replaced) do
                local key = parameterKey(keySpec)
                if not key then return reject("invalid replaced parameter key") end
                remove[key] = true
            end
            for _, parameter in ipairs(additions) do
                local key = parameterKey(parameter)
                if not validParameter(parameter) or updates[key] then return reject("invalid or duplicate prepared parameters") end
                updates[key], remove[key] = parameter, true
            end
            local merged = {}
            for _, parameter in ipairs(source.Parameters or {}) do
                if not remove[parameterKey(parameter) or false] then merged[#merged + 1] = clone(parameter) end
            end
            for _, parameter in ipairs(additions) do merged[#merged + 1] = clone(parameter) end
            if #merged > 10 then return reject("merged parameters exceed CNS's 10-entry array") end
            local copy = clone(source)
            -- Complete positional arrays are supplied by the offline preparer.
            -- An empty entry preserves the mesh's material at that position.
            copy.Materials, copy.Parameters = clone(spec.materials), merged
            -- Only generated alternatives use the positional FString decoder;
            -- the original variant and its legacy CNS behavior stay intact.
            copy.OutfitColoursPrepared = true
            if type(spec.maximumSkinResetParameters) == "table" and #spec.maximumSkinResetParameters > 0 then
                warn("skin-reset-" .. original.UniqueFitID .. "-" .. i,
                    "Maximum skin source reset available: " .. original.UniqueFitID .. " variant " .. i ..
                    "; source defaults " .. #spec.maximumSkinResetParameters .. "; CNS parameters " .. #merged .. ".")
            end
            result[i] = copy
            states[i] = {supported = true, mode = spec.mode or "reverse", partial = spec.partial == true}
            end
        end
        local anySupported = false
        for _, state in ipairs(states) do if state.supported then anySupported = true end end
        if not anySupported then return nil end
        return result, nil, states
    end

    function api.DecorateConfig(configPath, rows)
        if not enabled or type(rows) ~= "table" or decorated[rows] then return rows end
        local output, records = array(rows), {}
        for rowIndex, original in ipairs(rows) do
            if type(original) == "table" and body(original.FitMeshType)
                and type(original.UniqueFitID) == "string" and original.UniqueFitID ~= "" then
                local advanced = type(original.OutfitDatas) == "table" and #original.OutfitDatas > 0
                local variants = advanced and original.OutfitDatas or original.OutfitPaths
                local count = type(variants) == "table" and #variants or 0
                local good = count > 0
                for i = 1, count do
                    local variant = variants[i]
                    local mesh = advanced and type(variant) == "table" and variant.Mesh or variant
                    if type(mesh) ~= "string" or mesh == "" or
                        (advanced and (type(variant.Materials) ~= "table" or type(variant.Parameters) ~= "table")) then good = false end
                end
                if good then
                    local preparedVariants, reason, preparedStates = prepareVariants(original, variants, advanced, count)
                    if reason then warn(tostring(configPath) .. "-" .. rowIndex, reason) end
                    -- Leave all upstream fields exactly as authored when there
                    -- is no usable preparation for this particular outfit.
                    if preparedVariants then
                    local copy = {}; for key, value in pairs(original) do copy[key] = value end
                    copy.OutfitPaths, copy.OutfitNames = array(original.OutfitPaths), array(original.OutfitNames)
                    if advanced then copy.OutfitDatas = array(original.OutfitDatas)
                    elseif preparedVariants then
                        copy.OutfitDatas = {}
                        for i = 1, count do
                            copy.OutfitDatas[i] = {Mesh = variants[i], Materials = {}, Parameters = {},
                                PonyPhysics = original.PonyPhysics or "", HiddenMats = clone(original.HiddenMats or {})}
                        end
                    end
                    local selectionMap, selectionStates = {}, {}
                    for i = 1, count do selectionMap[i] = i end
                    local appended = count
                    local groups = {}
                    local item = prepared.outfits[original.UniqueFitID]
                    if type(item.previousVersions) == "table" and dense(item.previousVersions) then
                        for version, earlier in ipairs(item.previousVersions) do
                            local values, problem, states = prepareVariants(original, variants, advanced, count, earlier)
                            if values then groups[#groups + 1] = {values = values, states = states}
                            elseif problem then warn(tostring(configPath) .. "-" .. rowIndex .. "-version-" .. version, problem) end
                        end
                    end
                    groups[#groups + 1] = {values = preparedVariants, states = preparedStates}
                    for version, group in ipairs(groups) do
                        for i = 1, count do
                            local label = copy.OutfitNames[i]
                            if type(label) ~= "string" or label == "" then
                                label = count == 1 and "Original" or "Variant " .. i
                                copy.OutfitNames[i] = label
                            end
                            local state = group.states and group.states[i]
                            if state and state.supported then
                                local suffix = state.mode == "white" and "White" or "Reversed"
                                if #groups > 1 then suffix = suffix .. " " .. version end
                                if state.partial then suffix = suffix .. " / Partial" end
                                appended = appended + 1
                                selectionMap[appended] = i
                                selectionStates[appended] = state
                                copy.OutfitNames[appended] = count == 1 and suffix or label .. " / " .. suffix
                                copy.OutfitDatas[appended] = group.values[i]
                            end
                        end
                    end
                    output[rowIndex] = copy
                    records[original.UniqueFitID] = {source = original, count = count, advanced = advanced,
                        path = configPath, prepared = preparedVariants ~= nil, states = preparedStates,
                        selectionMap = selectionMap, selectionStates = selectionStates, total = appended}
                    end
                elseif count > 0 then
                    warn("invalid-" .. tostring(configPath) .. "-" .. rowIndex,
                        "Skipped an outfit with incomplete variant definitions in " .. tostring(configPath))
                end
            end
        end
        registrations[configPath] = records
        decorated[output] = true
        return output
    end

    function api.ResolveSelection(id, index)
        local record
        for _, group in pairs(registrations) do
            if group[id] then if record then return nil end; record = group[id] end
        end
        if not record or not integer(index, 0) or index >= record.total then return nil end
        local originalIndex = record.selectionMap[index + 1] - 1
        local source = record.advanced and record.source.OutfitDatas[originalIndex + 1]
        return {id = id, configPath = record.path, index = index, originalIndex = originalIndex,
            originalCount = record.count, reversed = index >= record.count,
            prepared = (record.selectionStates[index + 1] and record.selectionStates[index + 1].supported) or (index < record.count and record.states and record.states[originalIndex + 1].supported) or false,
            sourceMesh = source and source.Mesh or record.source.OutfitPaths[originalIndex + 1]}
    end
    function api.Setup() end
    function api.CaptureMesh() end
    function api.SetEnabled(value) enabled = value == true end
    return api
end

return Module
