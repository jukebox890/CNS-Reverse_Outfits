# Outfit Colours 0.4.11

Prepare alternate colours for your installed custom CNS outfits, then select them
alongside the originals in the game's nanosuit menu.

## Requirements

- Windows x64 and Stellar Blade PC.
- [Custom Nanosuit System 2.2](https://www.nexusmods.com/stellarblade/mods/1496).
- [Stellar Blade UE4SS — SB UE4SS 1.3](https://www.nexusmods.com/stellarblade/mods/2952).
- Installed custom CNS outfits, with their `.dekcns.json` definitions and packages.

The inspected CNS 2.2 Fix 1.4 script is also supported. Script compatibility is
checked before preparing an installer; unrecognized CNS edits are not overwritten.
Use the Stellar Blade-specific UE4SS release linked above. A generic UE4SS 3.x/beta
version label does not identify a newer Stellar Blade loader release.

Python, image libraries, PowerShell and the tested game mapping are included.
You do not need to install Python separately. The first preparation needs internet
access to download the pinned asset reader and compression codecs to a local cache.
The bundled mapping is selected automatically; other game builds may need their
own matching mapping in Settings.

## Start here

1. Extract the entire download to a folder of your choice. Keep
   `OutfitColoursPreparer.exe` beside its `Assets` folder. Run the EXE from there.
2. Open Settings and confirm the Stellar Blade installation folder containing
   `SB`. A single detected Steam installation is selected automatically.
3. Click **1. Scan outfits**. Search and select the custom outfits you want to edit.
   The standard BS outfit catalogue is excluded. Dependency advice appears only
   when an installation needs attention.
4. Choose your colours, then click **3. Prepare selected**. Wait for the green
   **PREPARATION COMPLETE** message. This step does not modify the installed game.
5. Close the game, then click **4. Install prepared**. The installer uses the saved
   game folder, verifies its payload and backs up affected installed files.
6. Start Stellar Blade. Use CNS's outfit-selection arrows to choose the added
   colour version. The original outfit choice remains available.

**Open output** opens the installer assets folder. A separate
`InstallPrepared.exe` is also available one folder above it; keep that EXE beside
its own `Assets` folder if you move the installer.

## Colour options

- **Reverse colours:** changes colours to their opposites, including lightness by
  default. Check **Disable lightness inversion** to keep the original lightness.
- **Convert all to white:** creates pale shades while retaining texture detail.
- **Preserve skin-like texture colours:** protects likely skin within mixed
  clothing/skin textures. Recognized dedicated skin assets are excluded separately.
  If clothing barely changes, try lowering the advanced strength or preparing
  again with this filter unchecked.
- **Retain red / Retain gold:** keeps those colours instead of converting them.

Open Advanced settings and check **Enable advanced settings** to apply its values.
Skin, red and gold strengths use 50 as standard. Higher values protect a wider
range. At skin strength 100, strong skin evidence can preserve an entire material,
including clothing that shares it. Zero disables the extra skin-like colour
filter; recognized dedicated skin assets remain excluded.

**Reverse red and blue** makes red become blue and blue become red in Reverse
colours mode. Retained colours take priority, so leave Retain red off when you
want red to become blue.

## Keep several colour versions

Enable **Keep previous colour versions of selected outfits** under Advanced
settings. Prepare the outfit, change settings, then prepare it again. You can
prepare several versions before installing; only the final combined output needs
to be installed. One preparation run uses one settings combination.

With Keep previous off, a new preparation replaces the selected outfit's earlier
saved colour versions. Previously prepared, unchecked outfits retain their saved
versions and settings. Unprepared outfits do not receive generated choices.

The list shows a compact version count. Select an outfit to see its saved settings
and whether they match the installed version.

## Animated accessories

Related auxiliary mesh components can follow the prepared outfit when they share
verified source materials. The helper discovers relationships from attachments
and the outfit's animation/controller references; no outfit profiles are hardcoded.

Selection changes wake a short discovery window. Repeated checks continue only
while matching auxiliary components are present. Ordinary outfits and preparations
with no matching components return to idle. Allow a short delay for accessories
to inherit the selected colours. Their meshes, physics and visibility are preserved.

## Update or remove

After upgrading the tool, prepare once and install the updated output to update
the installed helper. Existing successful unchecked preparations stay included.
Enable Keep previous if you want to retain every earlier version of a selected
outfit while preparing it again. You do not need to delete your preparation library.

To remove colour choices, select the outfits and click **Uninstall selected**.
The confirmation removes **all generated colour versions of the selected outfits**.
Original outfits and unselected generated choices remain. Close the game first.

Settings, the preparation library, output and backups are stored in Windows local
application data. The default output folder is `%LOCALAPPDATA%\OutfitReversalPrepared`.
Do not delete that library if you want to keep earlier preparations for later runs.

## Results and support

Skin filtering is heuristic on mixed textures. Custom shaders, independent assets
and ambiguous material settings can limit conversion. A **Partial** result means
some inputs could not be safely converted. Try one outfit first when testing a
new mod or game build. The tool checks generated packages, but those checks do not
replace an in-game visual check.

For troubleshooting, include the tool version, outfit name, selected settings and
the relevant error text or log. Review logs for personal file paths before sharing.
Original outfit archives and CNS definitions are kept intact; installation adds
generated packages and updates the checked CNS helper integration.

## Third-party notices

Original third-party licenses and notices are retained inside Assets:

- CPython: `Runtime/Python/LICENSE.txt`.
- Pillow: `Runtime/Python/Lib/site-packages/pillow-12.3.0.dist-info/licenses/`.
- NumPy: `Runtime/Python/Lib/site-packages/numpy-2.5.4.dist-info/licenses/`.
- PowerShell/.NET: `Runtime/PowerShell/LICENSE.txt` and `ThirdPartyNotices.txt`.
- Texture/package tooling: `assets/vendor/` and `packaging/` notices.

Runtime provenance and pinned upstream downloads are recorded in
`runtime-provenance.json`; distributed file checksums are in
`DistributionManifest.json`.
Asset reading uses [FModel](https://github.com/4sval/FModel) and
[CUE4Parse](https://github.com/FabianFG/CUE4Parse).
