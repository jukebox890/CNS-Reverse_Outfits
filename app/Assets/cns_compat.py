"""Supported fresh CNS bases and exact earlier prepared-colour helper revisions."""
from hashlib import sha256
from public_integration import integrate, UnsupportedCNS
from cns_integration import patch_stale_outputs

# Earlier released helper revisions; content identity only, no machine paths or
# outfit-specific assumptions. Preserve their existing performance/extension edits.
EARLIER_REVISIONS = {
    'eed0b52a7154f1d8b39d75b16798f0eeb32c1e3458c0d3903fab0ed0b92346b7',
    'bc788baa28f0fb46c117fb29c8b0dd9c001df00dccfd84d82c5ce40bd407cc1b',
    'e4f280ac0127c799633ad3fe38fc1744b5da1cd1765aa94db2af8e589644bfa5',
    '4044446cb6453193b7684720e2bee42f7246db8b09157fc9ea7a6c37194ed55f',
}

CAPTURE_OLD='    OutCharacterMesh:set(CharacterMesh)'
CAPTURE_NEW='''    -- OutfitColours: capture the selected body for auxiliary colour links
    if OutfitColoursBridge.CaptureMesh then
        OutfitColoursBridge.CaptureMesh(CharacterName, MeshType, CharacterMesh, Character)
    end
    OutCharacterMesh:set(CharacterMesh)'''

NOTIFY_END='    end)\nend\n\n-- Function to clear the cached outfits'


def _notify_end(bridge):
    return '''    end)
    -- OutfitColours: wake auxiliary links only for the selected colour variant
    if BRIDGE.SelectionChanged then
        BRIDGE.SelectionChanged(jsonObject.CharacterID or "EVE", jsonObject.FitMeshType or "", jsonData)
    end
end

-- Function to clear the cached outfits'''.replace('BRIDGE',bridge)


def _with_selection_notify(text,bridge):
    if text.count(NOTIFY_END)!=1:raise UnsupportedCNS('CNS advanced-selection handoff differs from the checked version.')
    return text.replace(NOTIFY_END,_notify_end(bridge),1)


def integrate_installed(raw):
    # Remove only our exact add-on before checking the upstream integration.
    # A modified block still fails the existing baseline/hash checks.
    try:text=raw.decode('utf-8-sig').replace('\r\n','\n')
    except UnicodeDecodeError as error:raise UnsupportedCNS('CNS script is not valid UTF-8.') from error
    removed=False
    for bridge in ('OutfitColoursBridge','ReversalBridge'):
        block=_notify_end(bridge)
        if block in text:
            if text.count(block)!=1:raise UnsupportedCNS('Duplicate auxiliary selection block.')
            text=text.replace(block,NOTIFY_END,1);removed=True
    if CAPTURE_NEW in text:
        if text.count(CAPTURE_NEW)!=1:raise UnsupportedCNS('Duplicate auxiliary capture block.')
        text=text.replace(CAPTURE_NEW,CAPTURE_OLD,1)
        removed=True
    if removed:
        raw=text.encode('utf-8')
    try:
        result=integrate(raw)
        text=result.decode('utf-8-sig').replace('\r\n','\n')
        if text.count(CAPTURE_OLD)!=1:raise UnsupportedCNS('CNS character-mesh handoff differs from the checked version.')
        return _with_selection_notify(text.replace(CAPTURE_OLD,CAPTURE_NEW,1),'OutfitColoursBridge').encode('utf-8')
    except UnsupportedCNS:
        if sha256(raw).hexdigest() not in EARLIER_REVISIONS or b'OutfitReversal integration' not in raw:
            raise UnsupportedCNS('Installed CNS is not a supported original, Fix 1.4, or checked earlier colour-helper revision. No installed files were changed.')
        return _with_selection_notify(patch_stale_outputs(raw.decode('utf-8-sig')),'ReversalBridge').encode('utf-8')
