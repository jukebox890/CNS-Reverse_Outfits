# Verification of 0.4.11

Checked on Windows on 28 October 2026:

- Both 0.4.11 EXEs compile from the four supplied C# files, with the existing icon embedded. Version and icon resource checks passed.
- The only functional change from 0.4.10 is the extractor child-process launch policy. Colour transforms, CNS helpers, templates, mapping and runtimes are byte-for-byte unchanged. Version labels, release notes and distribution hashes were updated.
- The unsigned-script regression test passed on the development app and the extracted final ZIP under RemoteSigned, AllSigned and Restricted process policies, with the internet download flag present. Old launches were blocked; the fixed launcher succeeded in all three cases. The actual extractor reached its own job validation rather than a signing error. Saved policy snapshots were identical before and after. No game files were modified.
- Source/compiler-input hashes and original-release hashes are recorded in SourceManifest.json. Verify-Source.ps1 checks them.
- The final distribution privacy audit includes nested archives, runtime provenance/notices, binary strings and Python bytecode. The publication source is separately scanned for private paths and local identifiers. No findings were detected.

These are source/build/provenance checks, not a malware certification, a Nexus approval decision or exhaustive in-game testing. Build.ps1 compiles both custom EXEs; runnable assembly reuses the pinned release bundle for third-party binaries and compiled data. Different PE timestamps/module identifiers can change rebuilt EXE hashes. The repository is associated with its public GitHub account.

The previous 0.4.10 archive is preserved unchanged. No game installation was modified for this release.
