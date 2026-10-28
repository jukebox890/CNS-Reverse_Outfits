# Build 0.4.11

## Requirements

- Windows x64.
- Windows PowerShell 5.1 and the .NET Framework 4.x C# compiler (`csc.exe`). Build.ps1 checks the standard Framework64/Framework locations. A game installation, Python installation and administrator rights are not needed to compile the two launchers.
- Download this repository using **Code â†’ Download ZIP** and extract it, or clone it. Open PowerShell in the extracted repository folder.

## 1. Compile both application executables

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Build.ps1
```

This uses the supplied C# sources and embeds `Branding/OutfitColours.ico`. It produces:

```text
build/
  OutfitColoursPreparer.exe
  Assets/
    installer/InstallPrepared.exe
    ...shipped script sources...
```

This **compile-only output is not a complete runnable distribution**: large third-party dependencies, mapping and texture/material templates are omitted from the source repository. The compiler step is offline. `ExecutionPolicy Bypass` applies to this invocation only; it does not change the machine's saved policy.

## 2. Assemble a runnable review copy (optional)

Obtain the original **0.4.11** download submitted on Nexus Mods. Use that file, not an archive of this GitHub repository. Build.ps1 verifies its exact SHA256 before extracting anything.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Build.ps1 -DistributionArchive "D:\Downloads\Outfit-Colours-Preparer-0.4.11.zip" -OutputName runnable
```

Replace the example archive location with your own. This extracts the known dependency/data bundle into `runnable/`, overlays the matching repository scripts, compiles both EXEs from the repository source, and regenerates the distribution checksums. It does not execute the supplied EXEs or contact the network during assembly. It does not install into a game.

The archive supplies unmodified third-party runtimes and tools, the game mapping and four small compiled templates. Their original checksums are listed in `app/Assets/DistributionManifest.json`; upstream locations and licensing are documented in THIRD-PARTY.md. This is an application rebuild against a pinned release bundle, **not a claim to rebuild every third-party binary from source**.

Build.ps1 refuses an existing output folder. Use a fresh `-OutputName` for another build. It never deletes an earlier build.

## 3. Verify the source and archive

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Verify-Source.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Verify-Source.ps1 -DistributionArchive "D:\Downloads\Outfit-Colours-Preparer-0.4.11.zip"
```

The second command also compares every copied shipped source file byte-for-byte with the reviewed ZIP. `review/SourceManifest.json` records the compiler inputs separately, since the .cs files were not part of the end-user ZIP.

No PDB/debug files are generated. The .NET Framework compiler may vary PE timestamps, module identifiers or metadata between builds; a whole-EXE hash difference alone does not show a code difference. The archive SHA256 identifies the original download, not newly compiled EXEs.

## Optional offline package smoke test

After assembling `runnable/`, run its bundled Python against the supplied synthetic image. This tests writing a package triplet without reading a game or installing anything:

```powershell
Push-Location .\runnable\Assets\sample
try {
  & ..\Runtime\Python\python.exe -B ..\..\Assets\engine_free_backend.py .\job.json
  if ($LASTEXITCODE -ne 0) { throw 'Sample package build failed.' }
} finally { Pop-Location }
```

The output is in `runnable/Assets/sample/output/`. It is a synthetic test package, not an outfit mod to install.

## Functional testing

Run `runnable/OutfitColoursPreparer.exe`, choose your own game folder, scan and prepare a custom CNS outfit. Initial asset-reader/codec setup needs internet access. Preparation writes to the selected output folder; installation is a separate explicit action. See the shipped README for game requirements and backup/uninstall behaviour. Visual and compatibility testing still requires the actual game and outfits.

## Unsigned-script regression test

After assembling runnable/, run:

```powershell
& .\runnable\Assets\Runtime\Python\python.exe -B .\review\Test-ExecutionPolicy.py --app .\runnable
```

This uses temporary synthetic jobs and internet-marked unsigned scripts under RemoteSigned, AllSigned and Restricted process policies. It verifies the old command is blocked, the fixed extraction launcher succeeds, the actual extractor reaches job validation, and saved policies stay unchanged. It does not read a game or install files. Administrator-enforced policies are respected; the controlled test stops if one is active.
