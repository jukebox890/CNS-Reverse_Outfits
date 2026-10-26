-- Prepared metadata and a bounded auxiliary material-sharing helper.
-- No live colour conversion, UObject construction or renderer hooks.
local source = debug.getinfo(1, "S").source:gsub("^@", "")
local directory = assert(source:match("^(.*[/\\])"), "OutfitReversal needs a Scripts directory")
local function log(message) print("[OutfitReversal] " .. tostring(message) .. "\n") end
local prepared
local file, reason = io.open(directory .. "Prepared.json", "rb")
if file then
    local bytes = file:read(16 * 1024 * 1024 + 1)
    file:close()
    if bytes and #bytes <= 16 * 1024 * 1024 then
        local ok, value = pcall(function() return require("json").decode(bytes) end)
        if ok then prepared = value else log("Could not decode Prepared.json; prepared variants are unavailable.") end
    else log("Prepared.json exceeds the size limit; prepared variants are unavailable.") end
else log("Prepared.json is unavailable; only original outfit choices are available.") end
local bridge = assert(loadfile(directory .. "MetadataBridge.lua"))().new({prepared = prepared, log = log})
local ok, accessory = pcall(function()
    return assert(loadfile(directory .. "AccessoryLink.lua"))().new({prepared=prepared, log=log})
end)
if ok then
    bridge.CaptureMesh = accessory.CaptureMesh
    bridge.SelectionChanged = accessory.SelectionChanged
    accessory.Start()
else log("Auxiliary colour linking could not be loaded; prepared body colours remain available.") end
log("Outfit Colours bridge 0.4.9; loaded prepared library revision " .. tostring(prepared and prepared.libraryRevision or "unknown") .. ".")
return bridge
