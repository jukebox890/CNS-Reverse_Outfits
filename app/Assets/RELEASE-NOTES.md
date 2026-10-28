# Outfit Colours 0.4.11

- Fix preparation stopping with "Extractor.ps1 is not digitally signed" on
  Windows systems that require signed downloaded scripts.
- The extractor now starts with an execution policy applied only to its own
  PowerShell subprocess. Saved Windows policies are not changed; policies
  enforced by an administrator remain respected.

Colour conversion, skin preservation, saved colour versions and installed helper
behaviour are unchanged. Existing preparations remain usable. Extract the full
new download and run OutfitColoursPreparer.exe; no outfit reinstall is needed
solely for this launcher fix.
