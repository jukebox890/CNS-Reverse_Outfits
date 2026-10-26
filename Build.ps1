[CmdletBinding()]
param(
    [string]$DistributionArchive,
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_-]{0,40}$')][string]$OutputName = 'build'
)
$ErrorActionPreference = 'Stop'
if ($OutputName -in @('app','Branding','review')) { throw 'Choose a fresh build folder name.' }
$output = Join-Path $PSScriptRoot $OutputName
if (Test-Path -LiteralPath $output) { throw 'Output folder already exists. Choose a fresh -OutputName; no previous build is deleted.' }
$compiler = @(
    (Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'),
    (Join-Path $env:WINDIR 'Microsoft.NET/Framework/v4.0.30319/csc.exe')
) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not $compiler) { throw 'The .NET Framework 4.x C# compiler is unavailable.' }
if ($DistributionArchive) { & (Join-Path $PSScriptRoot 'Verify-Source.ps1') -DistributionArchive $DistributionArchive }
else { & (Join-Path $PSScriptRoot 'Verify-Source.ps1') }

if ($DistributionArchive) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = (Resolve-Path -LiteralPath $DistributionArchive).Path
    $zip = [IO.Compression.ZipFile]::OpenRead($archive)
    try {
        $prefix = [IO.Path]::GetFullPath($output) + [IO.Path]::DirectorySeparatorChar
        $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
        foreach ($entry in $zip.Entries) {
            $name = $entry.FullName
            if ($name.Contains('\') -or $name.Contains(':') -or $name.StartsWith('/') -or $name -match '(^|/)\.\.?(/|$)') { throw 'Archive contains an unsafe path.' }
            $target = [IO.Path]::GetFullPath((Join-Path $output $name))
            if (-not $target.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)) { throw 'Archive path escapes the output folder.' }
            if (-not $seen.Add($name)) { throw 'Archive contains duplicate paths.' }
            if ((($entry.ExternalAttributes -shr 16) -band 0xF000) -eq 0xA000) { throw 'Archive links are not supported.' }
        }
        [IO.Directory]::CreateDirectory($output) | Out-Null
        foreach ($entry in $zip.Entries) {
            $target = Join-Path $output $entry.FullName
            if ($entry.FullName.EndsWith('/')) { [IO.Directory]::CreateDirectory($target) | Out-Null; continue }
            [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target)) | Out-Null
            [IO.Compression.ZipFileExtensions]::ExtractToFile($entry,$target,$false)
        }
    } finally { $zip.Dispose() }
} else { [IO.Directory]::CreateDirectory($output) | Out-Null }

# Copy only versioned source assets; the optional archive supplies runtimes/data.
$sourceAssets = Join-Path $PSScriptRoot 'app/Assets'
foreach ($file in Get-ChildItem -LiteralPath $sourceAssets -File -Recurse) {
    $relative = $file.FullName.Substring($sourceAssets.Length).TrimStart('\','/')
    $target = Join-Path (Join-Path $output 'Assets') $relative
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target)) | Out-Null
    [IO.File]::Copy($file.FullName,$target,$true)
}
$installerFolder = Join-Path $output 'Assets/installer'
[IO.Directory]::CreateDirectory($installerFolder) | Out-Null
$icon = Join-Path $PSScriptRoot 'Branding/OutfitColours.ico'
$common = @('/nologo','/target:winexe','/platform:anycpu','/optimize+','/debug-','/utf8output',
    '/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll','/reference:System.Web.Extensions.dll',
    "/win32icon:$icon","/resource:$icon,OutfitColours.ico")
$shared = @((Join-Path $PSScriptRoot 'SettingsPanel.cs'),(Join-Path $PSScriptRoot 'AppIcon.cs'))
& $compiler @common "/out:$(Join-Path $output 'OutfitColoursPreparer.exe')" (Join-Path $PSScriptRoot 'Preparer.cs') @shared
if ($LASTEXITCODE -ne 0) { throw 'Preparer compilation failed.' }
& $compiler @common "/out:$(Join-Path $installerFolder 'InstallPrepared.exe')" (Join-Path $PSScriptRoot 'PreparedInstaller.cs') @shared
if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }

$manifestPath = Join-Path $output 'Assets/DistributionManifest.json'
$files = @(Get-ChildItem -LiteralPath $output -File -Recurse | Where-Object { $_.FullName -ne $manifestPath } | Sort-Object FullName | ForEach-Object {
    [ordered]@{path=$_.FullName.Substring($output.Length+1).Replace('\','/');sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant();bytes=$_.Length}
})
$json = [ordered]@{schemaVersion=1;files=$files} | ConvertTo-Json -Depth 6
[IO.File]::WriteAllText($manifestPath,$json,[Text.UTF8Encoding]::new($false))
if ($DistributionArchive) { Write-Output "Built runnable 0.4.10 review copy in $OutputName. No game files were changed." }
else { Write-Output "Compiled both 0.4.10 EXEs in $OutputName. This source-only build still needs the runtime/data bundle; see BUILDING.md." }
