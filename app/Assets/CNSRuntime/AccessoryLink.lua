-- Share already-prepared materials with outfit-owned auxiliary components.
-- No asset names, outfit profiles, texture conversion, global scans or spawn hooks.
local Module = {}
local unpack = table.unpack or unpack
local PREFIX = "/Game/OutfitReversalPrepared/"

local function read(object, name)
    if object == nil then return nil end
    local ok, value = pcall(function() return object[name] end)
    if ok then return value end
    return nil
end
local function call(object, name, ...)
    local member, args = read(object, name), {...}
    if member == nil then return nil end
    local ok, value = pcall(function() return member(object, unpack(args)) end)
    if ok then return value end
    return nil
end
local function valid(object) return object ~= nil and call(object, "IsValid") == true end
local function path(object)
    if not valid(object) then return nil end
    local full = call(object, "GetFullName")
    return type(full) == "string" and full:match("^[^ ]+ (.+)$") or nil
end
local function id(object)
    if not valid(object) then return nil end
    local address = call(object, "GetAddress")
    if address and address ~= 0 then return tostring(address) end
    return path(object)
end
local function same(a, b)
    local left, right = id(a), id(b)
    return left ~= nil and left == right
end
local function list(array)
    local values = {}
    if array == nil then return values end
    if read(array, "ForEach") then
        call(array, "ForEach", function(_, value)
            if #values >= 64 then return true end
            if read(value, "get") then value = call(value, "get") end
            values[#values + 1] = value
        end)
    elseif type(array) == "table" then
        for i = 1, math.min(#array, 64) do values[#values + 1] = array[i] end
    end
    return values
end
local function isA(object, class)
    return valid(object) and call(object, "IsA", class) == true
end
local function material(component, slot)
    if not valid(component) then return nil end
    local value = call(component, "GetMaterial", slot)
    return valid(value) and value or nil
end
local function assign(component, slot, value)
    if not valid(component) or not valid(value) then return false end
    local ok = pcall(function() component:SetMaterial(slot, value) end)
    return ok and same(material(component, slot), value)
end
local function chain(materialObject)
    local values, seen = {}, {}
    for _ = 1, 12 do
        local key = id(materialObject)
        if not key or seen[key] then break end
        seen[key] = true
        values[#values + 1] = {object = materialObject, path = path(materialObject)}
        if not isA(materialObject, "/Script/Engine.MaterialInstance") then break end
        materialObject = read(materialObject, "Parent")
    end
    return values
end
local function hasPath(object, expected)
    for _, row in ipairs(chain(object)) do if row.path == expected then return true end end
    return false
end

function Module.new(options)
    options = options or {}
    local api, index, targets, classes = {}, {}, {}, {}
    local bodies, selections = {}, {}
    local timerPending, gamePending, started, tickNumber = false, false, false, 0
    local PROBE_LIMIT = 8
    local function log(message) if options.log then options.log(message) end end
    local prepared = options.prepared
    local seenFrames = {}
    local function addFrame(variant)
        if type(variant) ~= "table" or variant.supported == false or type(variant.mesh) ~= "string"
            or type(variant.accessorySources) ~= "table" then return end
        local links, keys = {}, {}
        for _, row in ipairs(variant.accessorySources) do
            if type(row) == "table" and type(row.sourceMaterial) == "string"
                and row.sourceMaterial:sub(1, 6) == "/Game/" and row.sourceMaterial:sub(1, #PREFIX) ~= PREFIX
                and type(row.preparedMaterial) == "string" and row.preparedMaterial:sub(1, #PREFIX) == PREFIX
                and type(row.bodySlot) == "number" and row.bodySlot % 1 == 0 and row.bodySlot >= 0 and row.bodySlot < 256
                and type(variant.materials) == "table" and variant.materials[row.bodySlot + 1] == row.preparedMaterial then
                links[#links + 1] = row
                keys[#keys + 1] = row.sourceMaterial .. "|" .. row.bodySlot .. "|" .. row.preparedMaterial
            end
        end
        if #links == 0 then return end
        table.sort(keys)
        local key = variant.mesh .. "|" .. table.concat(keys, ";")
        if seenFrames[key] then return end
        seenFrames[key] = true
        index[variant.mesh] = index[variant.mesh] or {}
        index[variant.mesh][#index[variant.mesh] + 1] = links
    end
    if type(prepared) == "table" and prepared.schemaVersion == 1 then
        for _, outfit in pairs(prepared.outfits or {}) do
            for _, frame in ipairs({outfit}) do for _, variant in ipairs(frame.variants or {}) do addFrame(variant) end end
            for _, frame in ipairs(outfit.previousVersions or {}) do
                for _, variant in ipairs(frame.variants or {}) do addFrame(variant) end
            end
        end
    end

    local function engineClass(name)
        if valid(classes[name]) then return classes[name] end
        if type(StaticFindObject) ~= "function" then return nil end
        local ok, value = pcall(StaticFindObject, name)
        if ok and valid(value) then classes[name] = value; return value end
    end
    -- Inspect only hard Actor/SkeletalMeshComponent object properties declared
    -- by the animation/holder Blueprint. Never read weak/soft references, arbitrary
    -- arrays, engine internals, widget properties or untyped UObject graphs.
    local propertyNames = {}
    local function references(object)
        if not valid(object) then return {} end
        local klass = call(object, "GetClass")
        local key = path(klass)
        if not key or key:sub(1, 6) ~= "/Game/" then return {} end
        local names = propertyNames[key]
        if names == nil then
            names = {}; local count, visited = 0, {}
            local actorClass = engineClass("/Script/Engine.Actor")
            local meshClass = engineClass("/Script/Engine.SkeletalMeshComponent")
            if not valid(actorClass) or not valid(meshClass) then return {} end
            for _ = 1, 8 do
                local classPath = path(klass)
                if not classPath or classPath:sub(1, 6) ~= "/Game/" or visited[classPath] then break end
                visited[classPath] = true
                call(klass, "ForEachProperty", function(property)
                    count = count + 1
                    if count > 256 then return true end
                    local full = call(property, "GetFullName")
                    if type(full) ~= "string" or not full:match("^ObjectProperty ") then return end
                    local targetClass = call(property, "GetPropertyClass")
                    if not valid(targetClass) or (call(targetClass, "IsChildOf", actorClass) ~= true
                        and call(targetClass, "IsChildOf", meshClass) ~= true) then return end
                    local name = call(call(property, "GetFName"), "ToString")
                    if type(name) == "string" and name ~= "" then names[#names + 1] = name end
                end)
                if count > 256 then break end
                klass = call(klass, "GetSuperStruct")
            end
            propertyNames[key] = names
        end
        local output = {}
        for _, name in ipairs(names) do
            local value = read(object, name)
            if valid(value) then output[#output + 1] = value end
        end
        return output
    end
    local function discover(body)
        local output, seen = {}, {}
        local function append(component)
            if not valid(component) or same(component, body) or not isA(component, "/Script/Engine.SkeletalMeshComponent") then return end
            local key = id(component)
            if key and not seen[key] and #output < 64 then seen[key] = true; output[#output + 1] = component end
        end
        local queue = {body}
        for i = 1, 64 do
            local parent = queue[i]; if not parent then break end
            for _, child in ipairs(list(read(parent, "AttachChildren"))) do
                local key = id(child)
                if key and not seen["child-" .. key] and #queue < 64 then
                    seen["child-" .. key] = true; queue[#queue + 1] = child; append(child)
                end
            end
        end
        local owner = call(body, "GetOwner")
        for _, animation in pairs({call(body, "GetPostProcessInstance"), call(body, "GetAnimInstance")}) do
            if valid(animation) and same(call(animation, "GetOwningComponent"), body) then
                for _, actor in ipairs(references(animation)) do
                    if isA(actor, "/Script/Engine.Actor") then
                        local refs, related = references(actor), same(call(actor, "GetOwner"), owner)
                        for _, component in ipairs(refs) do if same(component, body) then related = true end end
                        if related then
                            for _, component in ipairs(refs) do
                                local componentOwner = call(component, "GetOwner")
                                if same(componentOwner, actor) or same(componentOwner, owner) then append(component) end
                            end
                        end
                    end
                end
            end
        end
        return output
    end
    local function restore(record)
        if not valid(record.component) or path(read(record.component, "SkeletalMesh")) ~= record.mesh then return end
        if valid(record.original) and same(material(record.component, record.slot), record.assigned) then
            assign(record.component, record.slot, record.original)
        end
    end
    local function clear(target)
        for _, record in pairs(target.bindings) do restore(record) end
        target.bindings, target.components = {}, {}
    end
    local function frameFor(body, frames)
        local found
        for _, links in ipairs(frames or {}) do
            local matches = true
            for _, link in ipairs(links) do
                if not hasPath(material(body, link.bodySlot), link.preparedMaterial) then matches = false; break end
            end
            if matches then if found then return nil end; found = links end
        end
        return found
    end
    local function definitionFrame(data)
        if type(data) ~= "table" or data.OutfitColoursPrepared ~= true or type(data.Materials) ~= "table" then return nil end
        for _, links in ipairs(index[data.Mesh] or {}) do
            local matches = true
            for _, link in ipairs(links) do
                if data.Materials[link.bodySlot + 1] ~= link.preparedMaterial then matches = false; break end
            end
            if matches then return links end
        end
        return nil
    end
    local function update(target)
        local body = target.body
        if not valid(body) then clear(target); return false end
        local mesh = path(read(body, "SkeletalMesh"))
        local links = frameFor(body, index[mesh])
        if not links or (target.expected and links ~= target.expected) then
            clear(target); target.frame = nil
            -- An explicit prepared selection can precede the Blueprint's material
            -- application. Only that selection gets a bounded readiness window.
            -- A body capture/resume or a previously active link stops immediately.
            if target.requested and not target.matched then
                target.misses = target.misses + 1
                return target.misses < PROBE_LIMIT
            end
            return false
        end
        target.matched = true
        if target.frame ~= links or tickNumber >= target.discoverAt then
            target.components = discover(body)
            target.frame, target.discoverAt = links, tickNumber + 2
        end
        local sources = {}
        for _, link in ipairs(links) do sources[link.sourceMaterial] = material(body, link.bodySlot) end
        local visited, linked = {}, 0
        for _, component in ipairs(target.components) do
            if valid(component) then
            local componentMesh, componentID = path(read(component, "SkeletalMesh")), id(component)
            local count = call(component, "GetNumMaterials")
            if componentMesh and componentMesh ~= mesh and componentID and type(count) == "number" and count >= 0 and count <= 256 then
                for slot = 0, count - 1 do
                    local key = componentID .. ":" .. slot
                    local record, current = target.bindings[key], material(component, slot)
                    if record and record.mesh ~= componentMesh then record = nil end
                    if record and not same(current, record.assigned) and not hasPath(current, record.source) then record = nil end
                    local sourcePath, originalObject, generated
                    if record then sourcePath = record.source end
                    if not sourcePath then
                        for _, row in ipairs(chain(current)) do
                            if row.path and row.path:sub(1, #PREFIX) == PREFIX then generated = true end
                            if sources[row.path] then sourcePath, originalObject = row.path, row.object; break end
                        end
                    end
                    local source = sourcePath and sources[sourcePath]
                    if valid(source) and valid(current) then
                        visited[key] = true
                        if not record then
                            record = {component=component, mesh=componentMesh, slot=slot, source=sourcePath,
                                original=generated and originalObject or current}
                            target.bindings[key] = record
                        end
                        if same(current, source) or assign(component, slot, source) then
                            record.assigned = source
                            linked = linked + 1
                            if not target.reported then log("Linked outfit-owned auxiliary colours to the active prepared materials."); target.reported = true end
                        end
                    end
                end
            end
            end
        end
        for key, record in pairs(target.bindings) do
            if not visited[key] then restore(record); target.bindings[key] = nil end
        end
        if linked == 0 then
            target.misses = target.misses + 1
            if target.misses >= PROBE_LIMIT then clear(target); return false end
        else target.misses = 0 end
        return true
    end
    function api.Tick()
        tickNumber = tickNumber + 1
        for key, target in pairs(targets) do
            if not update(target) then targets[key] = nil end
        end
    end
    -- One-shot delayed jobs are rearmed only while there is actual work. A
    -- callback already queued when selection changes checks plain Lua state and
    -- exits without touching UObjects if the target has been removed.
    local schedule
    schedule = function()
        if not started or timerPending or gamePending or not next(targets) then return end
        timerPending = true
        local ok = pcall(ExecuteWithDelay, 1000, function()
            timerPending = false
            if not next(targets) then return end
            gamePending = true
            local queued = pcall(ExecuteInGameThread, function()
                gamePending = false
                if not next(targets) then return end
                local success = pcall(api.Tick)
                if not success then
                    for _, target in pairs(targets) do pcall(clear, target) end
                    targets = {}; log("Auxiliary colour linking stopped after an unavailable runtime operation.")
                    return
                end
                schedule()
            end)
            if not queued then gamePending = false end
        end)
        if not ok then timerPending = false end
    end
    local function arm(characterName, component, expected, requested)
        local key = id(component)
        if not key then return end
        local target = targets[key]
        if not target then
            target = {body=component, bindings={}, components={}, discoverAt=0}
            targets[key] = target
        end
        target.characterName, target.expected = characterName, expected
        target.requested, target.matched, target.misses = requested, false, 0
        schedule()
    end
    function api.CaptureMesh(characterName, _, component, character)
        if not next(index) or not valid(component) or not valid(character) then return end
        if not same(call(character, "GetSBSkeletalMeshComponent", 0), component) then return end
        characterName = tostring(characterName or "EVE"):upper()
        local previous = bodies[characterName]
        if previous and not same(previous, component) then
            for key, target in pairs(targets) do
                if target.characterName == characterName then clear(target); targets[key] = nil end
            end
        end
        bodies[characterName] = component
        local key = id(component)
        -- A capture is an event, not an idle poll. Check the result once after
        -- CNS finishes applying it; no matching prepared frame means no rearm.
        if key and not targets[key] then arm(characterName, component, selections[characterName], false) end
    end
    function api.SelectionChanged(characterName, meshType, data)
        if meshType ~= nil and meshType ~= "" and meshType ~= "Body" then return end
        characterName = tostring(characterName or "EVE"):upper()
        local expected = definitionFrame(data)
        selections[characterName] = expected
        if not expected then
            for key, target in pairs(targets) do
                if target.characterName == characterName then clear(target); targets[key] = nil end
            end
            return
        end
        local component = bodies[characterName]
        if valid(component) then arm(characterName, component, expected, true) end
    end
    function api.Start()
        if started or not next(index) then return end
        if type(ExecuteWithDelay) ~= "function" or type(ExecuteInGameThread) ~= "function" then
            log("Auxiliary colour linking unavailable; prepared body colours remain available."); return
        end
        started = true
        schedule()
    end
    return api
end
return Module
