# Verification of this source snapshot

Checked on Windows on 27 October 2026:

- The original release ZIP matches SHA256 `97b7618d30569024a835e2feec2b5e052b1be929e6db54b7da4eb7a62c302883` and size 142,332,471 bytes.
- All 49 copied shipped source/notice/metadata/sample files match the release ZIP byte-for-byte. The four C# sources and icon are recorded separately in SourceManifest.json (54 inputs in total).
- Build.ps1 compiled both application EXEs using the Windows .NET Framework C# compiler. Runnable assembly against the pinned archive also completed.
- Inspection in separate reflection-only processes found matching assembly identity, method signatures, method IL, local-variable descriptions, exception-handler descriptions and embedded resource names between each rebuilt EXE and its original release counterpart. Inspection did not launch either EXE. The icon compiler input is recorded in SourceManifest.json. `Inspect-Assembly.ps1` provides the inspection code.
- The documented offline synthetic-image smoke test completed and generated one texture and a package triplet without reading a game or installing files.
- Publication files were scanned for local profile/workspace paths and local private identifiers, including ASCII and UTF-16 representations. No findings were detected. Build products, runtimes, private test inputs/logs and previous repository history are excluded from publication.

These are source/build/provenance checks, not a malware certification, a Nexus approval decision or an exhaustive in-game test. Reflection comparison does not establish byte-identical PE files or check the behaviour of every upstream dependency. A source/privacy audit cannot guarantee universal anonymity; the public repository remains associated with its GitHub account.

The existing 0.4.10 download was not rebuilt or changed by this source publication.
