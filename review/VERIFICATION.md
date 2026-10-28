# Verification of 0.4.12

Checked on Windows on 28 October 2026:

- Both EXEs compile from the supplied C# source; their only source change from 0.4.11 is the version label.
- Five scan/packaging/installer regression tests passed on the working app and the extracted final ZIP. Tests cover invalid/truncated headers, an unreadable file, numeric reservations, malformed CNS rows followed by valid outfits, the complete scan command, package construction, and Windows PowerShell 5.1 installer checks.
- Readable installed container-ID collisions, unreadable filename chunk conflicts and malformed incoming packages remain rejected. Unrelated unreadable headers are warnings. Test fixture files are used throughout; no actual game is modified.
- The pinned asset reader handled an unrelated malformed header fixture without aborting. The supplied UpDownDance Short 1.1 archive has a readable version-2 header and was accepted by the inventory. The originally reported E_P file is a different file and was not available for byte-level testing. No third-party mod assets are included in this source repository.
- The final ZIP differs from 0.4.11 only in the two EXEs, prep.py, chunk_inventory.py, packaging/pack_legacy.py, installer/Install-Prepared.ps1, README, release notes and distribution manifest. Colour transformations, mapping, templates, dependencies and in-game helpers are unchanged.
- Source hashes and matching release hashes are recorded in SourceManifest.json. Verify-Source.ps1 validates them. Build.ps1 compiles both custom EXEs; runnable assembly reuses the pinned release bundle for third-party binaries and data.
- Final archive privacy checks cover 1,815 files, runtime provenance/notices, nested archives and Python bytecode. The public source is separately scanned for private paths and identifiers. Both passed without findings.

These are bounded source/build/provenance checks, not a malware certification, a Nexus approval decision or exhaustive game compatibility testing. Unreadable installed container IDs cannot be checked. The repository remains associated with its public GitHub account. Earlier published archives remain unchanged.
