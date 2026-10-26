# Dependencies and source locations

Exact versions, archive URLs and SHA256 values from the submitted 0.4.10 release are retained in [runtime-provenance.json](app/Assets/runtime-provenance.json) and [reviewed-dependencies.json](app/Assets/release/reviewed-dependencies.json). The full [release manifest](app/Assets/DistributionManifest.json) identifies distributed files. These are provenance records, not a promise that an upstream URL will remain available.

| Component | Version in 0.4.10 | Source / notices |
| --- | --- | --- |
| CPython Windows embeddable x64 | 3.13.17 | [CPython](https://github.com/python/cpython), [official download](https://www.python.org/ftp/python/3.13.17/); PSF and bundled notices |
| Pillow | 12.3.0 | [Pillow](https://github.com/python-pillow/Pillow); MIT-CMU and bundled codec/font notices |
| NumPy | 2.5.4 | [NumPy](https://github.com/numpy/numpy); BSD-3-Clause and bundled numerical-library notices |
| PowerShell x64 / bundled .NET | 7.6.8 | [official release](https://github.com/PowerShell/PowerShell/releases/tag/v7.6.8); MIT and ThirdPartyNotices.txt |
| Texture serializer | exact source file hashes recorded | [UE4-DDS-Tools](https://github.com/matyalatte/UE4-DDS-Tools); the shipped subset is included under app/Assets/assets/vendor/, with its MIT licence |
| texconv | custom DLL project 0.6.0 | [source and release](https://github.com/matyalatte/Texconv-Custom-DLL/releases/tag/v0.6.0); MIT and bundled notices included here |
| retoc | 0.1.5 | [source and release](https://github.com/trumank/retoc/releases/tag/v0.1.5); MIT notice included here |
| Asset reader (first-use download) | pinned FModel aug-2026 archive | [FModel](https://github.com/4sval/FModel), [CUE4Parse](https://github.com/FabianFG/CUE4Parse); their upstream licences apply |

Our custom compiled executables are built from the four root .cs files. The Python, PowerShell and Lua project files are shipped as readable source. No private compiled project helper is omitted from this snapshot.

The source-only repository omits third-party EXE/DLL/PYD runtime files, Python's standard-library ZIP, the .usmap mapping and the four small binary texture/material templates. Optional runnable assembly reads those from the exact original release archive; it retains the original licence files. A reviewer can inspect our code and compile both EXEs without extracting that archive.

Asset-reader downloads and compression-codec initialization are explained in [the review guide](review/NEXUS-REVIEW.md). They are runtime dependencies, not silent updates to the mod.
