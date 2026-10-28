# Review guide — 0.4.12

## Review scope

This repository accompanies the unchanged `Outfit-Colours-Preparer-0.4.12.zip` Nexus upload. Its original SHA256 and size are in SourceManifest.json. Source manifest entries marked `shipped-file` are copied byte-for-byte from that archive; `compiler-input` entries identify the C# source and embedded icon used for the custom EXEs.

The release manifest covers the full portable bundle, including third-party files not duplicated in Git. There is no private development history, machine-specific configuration or prepared outfit library in this snapshot. Repository history contains the earlier public 0.4.10 review snapshot. Publishing source does not itself guarantee scanner approval or establish that every game/outfit combination is compatible.

## Entry points

| File | Purpose |
| --- | --- |
| Preparer.cs | Windows Forms UI; selects outfits/settings and starts local preparation processes |
| PreparedInstaller.cs | Windows Forms installer; validates the staged install bundle before invoking its installer script |
| SettingsPanel.cs / AppIcon.cs | Shared game-folder detection/settings and embedded icon loading |
| app/Assets/prep.py | Scan, prepare, retained-version library, staging and uninstall orchestration |
| app/Assets/Extractor.ps1 | Read-only asset inspection and image export through the downloaded reader |
| app/Assets/colour_bake.py / skin_safety.py / skin_reset.py | Colour transforms and skin protection/reset evidence |
| app/Assets/engine_free_backend.py / assets/asset_writer.py / packaging/ | Texture/material serialization and package construction |
| app/Assets/installer/Install-Prepared.ps1 / export_installer.py | Validated installation, backups and portable installer export |
| app/Assets/public_integration.py / CNSRuntime/ | Checked CNS script integration and in-game metadata/accessory helpers |
| app/Assets/reader_setup.py | Pinned first-run asset-reader download and extraction |

## File/system access

- The application can discover Steam library locations from Steam's registry value and library manifests. The user can choose a game folder manually.
- Settings are stored under the current user's local application data. Default preparation output/library is `%LOCALAPPDATA%/OutfitReversalPrepared`. Paths are resolved at runtime.
- Scanning reads CNS JSON definitions and package/container headers. Preparation reads game/mod assets and writes to the selected output/library, rather than modifying original outfit packages.
- Installation is a separate explicit action. It verifies allowed relative destination paths, complete package triplets and SHA256 hashes, and checks the source CNS script. It backs up affected files and writes the prepared packages plus CNS helper integration into the chosen game.
- Uninstall acts on all generated colour versions of the selected outfits and preserves unrelated choices. Review prep.py, uninstall_selected.py and the installer for the exact scope/guards.
- The optional Start Stellar Blade button opens the detected Steam launch URI. The program does not require a startup service or scheduled task.
- Prepared installer exports omit the preparer's absolute game path. Logs generated during use can contain the user's paths and should be reviewed before sharing.

## Network activity

Compilation and runnable assembly in Build.ps1 do not download dependencies.

At the first preparation, reader_setup.py downloads this pinned official archive when a valid reader cache is unavailable:

```text
https://github.com/4sval/FModel/releases/download/aug-2026/FModel.zip
SHA256: ce1995fbc876cd0d0f54d3f7af5babc0e949d87fe4c4f2fada55c6e1e062eacc
```

The archive SHA256 is checked before extraction. Only explicitly allowlisted reader assemblies are extracted from the bundled FModel executable; FModel.exe itself is not launched. Reader-cache files are checked against recorded hashes on reuse. Extractor.ps1 also initializes the reader's Oodle/Zlib helpers; the upstream helper libraries may fetch codec files if absent. Those codec operations belong to the reader dependencies and are not claimed to have the same archive pinning as reader_setup.py.

The project code contains no account login, telemetry uploader or automatic mod-version updater. UI links open the relevant CNS/UE4SS mod pages in the user's browser. See the exact sources for all process arguments and URLs; dependency behaviour should be reviewed at the upstream source as well.

## In-game helper

Generated textures/materials are prepared before launch. The Lua helper integrates the prepared choices with CNS. It also handles auxiliary components when a selected prepared outfit has matching verified source materials. It uses short discovery windows and returns to idle when no matching component exists. It does not convert image pixels during gameplay, and it contains no hardcoded per-outfit asset profile.

## Build and provenance limits

BUILDING.md provides an offline compile step for both custom EXEs and an optional runnable assembly step against the hash-checked published bundle. The latter deliberately reuses third-party binaries and compiled data; it is not a complete source rebuild of every upstream dependency. Different compiler metadata can change the resulting EXE hashes.

The original download includes CPython's `python313.zip` standard library inside its runtime folder. That is an upstream runtime component, not another hidden mod installer. The specific cause of Nexus quarantine has not been established; this repository is evidence for manual review, not a bypass of that review.

## 0.4.12 installed-header handling

Outfit entries still originate only from CNS definitions. The separate installed-container inventory reads headers to avoid conflicts across all mods. An unreadable/unsupported installed header now produces a warning and a null identity; its filename chunk reservations are retained. Unknown IDs are excluded from duplicate-ID grouping. Packaging uses the same inventory, and the installer tolerates unreadable unrelated headers after checking visible filename reservations. Incoming/generated header validation, hash checks and known collision rejection stay strict. Unknown internal IDs cannot be verified, so warnings are not a claim that every installed mod is valid or conflict-free. No existing mod is repaired, renamed, removed or changed.
