[CmdletBinding()]
param([string]$DistributionArchive)
$ErrorActionPreference = 'Stop'
$manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'review/SourceManifest.json') -Raw | ConvertFrom-Json
foreach ($row in $manifest.files) {
    $path = Join-Path $PSScriptRoot $row.path
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing source file: $($row.path)" }
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $row.sha256) { throw "Source checksum differs: $($row.path)" }
}
if ($DistributionArchive) {
    $archive = (Resolve-Path -LiteralPath $DistributionArchive).Path
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $manifest.releaseArchive.sha256) { throw 'This is not the reviewed 0.4.10 distribution archive.' }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead($archive)
    try {
        foreach ($row in @($manifest.files | Where-Object { $_.kind -eq 'shipped-file' })) {
            $entry = $zip.GetEntry($row.releasePath)
            if ($null -eq $entry) { throw "Release entry missing: $($row.releasePath)" }
            $stream = $entry.Open(); $hasher = [Security.Cryptography.SHA256]::Create()
            try { $hash = [BitConverter]::ToString($hasher.ComputeHash($stream)).Replace('-','').ToLowerInvariant() }
            finally { $stream.Dispose(); $hasher.Dispose() }
            if ($hash -ne $row.sha256) { throw "Release/source mismatch: $($row.path)" }
        }
        Write-Output 'Original release hash and all copied source files verified.'
    } finally { $zip.Dispose() }
}
Write-Output "Verified $($manifest.files.Count) source/compiler-input checksums for 0.4.10."
