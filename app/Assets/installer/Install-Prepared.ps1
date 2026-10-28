[CmdletBinding()]
param(
    [string]$GameRoot,
    [string]$ManifestPath,
    [string]$BackupRoot
)
$ErrorActionPreference='Stop'
# Resolve defaults after parameter binding: some Windows PowerShell launchers
# do not provide PSScriptRoot while evaluating parameter default expressions.
if([string]::IsNullOrWhiteSpace($ManifestPath)) {
    $preparedScriptDirectory=$PSScriptRoot
    if(-not $preparedScriptDirectory -and $PSCommandPath) { $preparedScriptDirectory=[IO.Path]::GetDirectoryName($PSCommandPath) }
    if(-not $preparedScriptDirectory -and $MyInvocation.MyCommand.Path) { $preparedScriptDirectory=[IO.Path]::GetDirectoryName($MyInvocation.MyCommand.Path) }
    if(-not $preparedScriptDirectory) { throw 'Cannot locate the installer folder. Extract Assets beside InstallPrepared.exe.' }
    $ManifestPath=Join-Path $preparedScriptDirectory 'InstallManifest.json'
}
if([string]::IsNullOrWhiteSpace($BackupRoot)) {
    $preparedLocalData=[Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)
    if(-not $preparedLocalData) { throw 'Cannot locate the local application data folder for installer backups.' }
    $BackupRoot=Join-Path $preparedLocalData 'OutfitReversalPrepared/InstallerBackups'
}

function Assert-PreparedPlainPath([string]$Path) {
    $current=[IO.Path]::GetFullPath($Path)
    while($current) {
        if(Test-Path -LiteralPath $current) {
            $item=Get-Item -LiteralPath $current -Force
            if(($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "Links and junctions are not supported: $current" }
        }
        $parent=[IO.Path]::GetDirectoryName($current)
        if($parent -eq $current) { break }
        $current=$parent
    }
}

function Test-PreparedContained([string]$Root,[string]$Path) {
    $rootFull=[IO.Path]::GetFullPath($Root).TrimEnd('\','/')
    $pathFull=[IO.Path]::GetFullPath($Path)
    return $pathFull.Equals($rootFull,[StringComparison]::OrdinalIgnoreCase) -or $pathFull.StartsWith($rootFull+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)
}

function Join-PreparedTarget([string]$Root,[string]$Relative) {
    if([string]::IsNullOrWhiteSpace($Relative) -or [IO.Path]::IsPathRooted($Relative) -or $Relative.Contains(':')) { throw 'Manifest paths must be relative SB paths.' }
    $parts=$Relative.Replace('\','/').Split('/')
    if(@($parts | Where-Object { $_ -in @('','.','..') }).Count) { throw "Invalid manifest path: $Relative" }
    $result=[IO.Path]::GetFullPath((Join-Path $Root ($parts -join [IO.Path]::DirectorySeparatorChar)))
    if(-not (Test-PreparedContained $Root $result)) { throw "Path escapes its expected folder: $Relative" }
    Assert-PreparedPlainPath $result
    return $result
}

function Get-PreparedProcesses { return @(Get-Process -ErrorAction SilentlyContinue) }

function Assert-PreparedGameClosed([string]$Root) {
    foreach($process in @(Get-PreparedProcesses)) {
        $processPath=$null
        try { $processPath=$process.Path } catch {}
        $knownName=$process.ProcessName -in @('SB','SB-Win64-Shipping','StellarBlade','StellarBlade-Win64-Shipping')
        $insideGame=$false
        if($processPath) { $insideGame=Test-PreparedContained $Root $processPath }
        if($knownName -or $insideGame) { throw "Close Stellar Blade before installing. Running process: $($process.ProcessName)" }
    }
}

function Copy-PreparedFile([string]$Source,[string]$Destination) {
    Copy-Item -LiteralPath $Source -Destination $Destination -Force -ErrorAction Stop
}

function Get-PreparedHash([string]$Path) {
    $algorithm=[Security.Cryptography.SHA256]::Create()
    $stream=[IO.File]::OpenRead($Path)
    try { return ([BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace('-','').ToLowerInvariant() }
    finally { $stream.Dispose(); $algorithm.Dispose() }
}

function Get-PreparedContainerId([string]$Path) {
    Assert-PreparedPlainPath $Path
    $stream=[IO.File]::OpenRead($Path)
    try {
        $header=New-Object byte[] 64
        $count=$stream.Read($header,0,64)
        if($count -ne 64 -or [Text.Encoding]::ASCII.GetString($header,0,16) -cne '-==--==--==--==-') {
            throw "Cannot validate the IoStore header: $Path"
        }
        $headerSize=[BitConverter]::ToUInt32($header,20)
        if($header[16] -eq 0 -or $headerSize -lt 64 -or $headerSize -gt $stream.Length) {throw "Invalid IoStore header size/version: $Path"}
        return ([BitConverter]::ToUInt64($header,56)).ToString('x16')
    } finally { $stream.Dispose() }
}

function Assert-PreparedNoContainerConflict([string]$Paks,[object]$Plan,[string[]]$ReplacedFiles) {
    $replaced=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach($path in $ReplacedFiles) {[void]$replaced.Add([IO.Path]::GetFullPath($path))}
    $incoming=@{};$numbers=@{}
    foreach($entry in $Plan) {
        if($entry.kind -ne 'package' -or [IO.Path]::GetExtension($entry.source) -ine '.utoc') {continue}
        $id=Get-PreparedContainerId $entry.source
        if($id -in @('0000000000000000','ffffffffffffffff')) {throw "Prepared package has an invalid container ID: $($entry.source)"}
        if($incoming.ContainsKey($id)) {throw 'Prepared output contains overlapping IoStore container IDs.'}
        $incoming[$id]=$entry.source
        if([IO.Path]::GetFileName($entry.source) -match '(?i)OutfitReversalPrepared_([0-9]+)_P') {$numbers[[int]$Matches[1]]=$entry.source}
    }
    if(-not $incoming.Count) {return}
    $scanErrors=@()
    $installedTocs=@(Get-ChildItem -LiteralPath $Paks -Filter '*.utoc' -File -Recurse -ErrorAction SilentlyContinue -ErrorVariable scanErrors)
    foreach($scanError in $scanErrors) {Write-Warning 'An installed package directory could not be inspected. Its internal container IDs could not be checked.'}
    foreach($toc in $installedTocs) {
        if($replaced.Contains([IO.Path]::GetFullPath($toc.FullName))) {continue}
        # Check visible number reservations even when an unrelated header is bad.
        foreach($label in [regex]::Matches($toc.Name,'(?i)(?:pakchunk|OutfitReversalPrepared_)([0-9]+)(?:\D|$)')) {
            $number=0
            if([int]::TryParse($label.Groups[1].Value,[ref]$number) -and $numbers.ContainsKey($number)) {
                throw "Chunk number conflict with an installed package: $($toc.FullName). Prepare again before installing."
            }
        }
        Assert-PreparedPlainPath $toc.FullName
        try {$id=Get-PreparedContainerId $toc.FullName}
        catch {Write-Warning "Cannot read installed IoStore header: $($toc.FullName). Filename reservations were checked; its internal ID could not be checked.";continue}
        if($incoming.ContainsKey($id)) {throw "Container ID conflict with an installed package: $($toc.FullName). Prepare again with the current mod list before installing."}
    }
}

function Invoke-PreparedInstall([string]$Manifest,[string]$TargetGame,[string]$Backups) {
    $manifestFull=[IO.Path]::GetFullPath($Manifest)
    Assert-PreparedPlainPath $manifestFull
    $bundleRoot=Split-Path $manifestFull -Parent
    $data=Get-Content -LiteralPath $manifestFull -Raw | ConvertFrom-Json
    if([string]$data.containerProfile -cne 'stellarblade-initial-single-export-v1'){throw 'Prepare outfits again with version 0.4.2 or newer before installing this output.'}
    if(($data.schemaVersion -isnot [int] -and $data.schemaVersion -isnot [long]) -or $data.schemaVersion -ne 1 -or $data.files -isnot [array]) { throw 'Unsupported install manifest version or files array.' }
    if(-not $TargetGame) { $TargetGame=[string]$data.gameRoot }
    if(-not $TargetGame -or -not [IO.Path]::IsPathRooted($TargetGame)) { throw 'Set GameRoot to the Stellar Blade folder containing SB.' }
    $targetRoot=[IO.Path]::GetFullPath($TargetGame)
    Assert-PreparedPlainPath $targetRoot
    $pakRoot=Join-PreparedTarget $targetRoot 'SB/Content/Paks'
    if(-not (Test-Path -LiteralPath $pakRoot -PathType Container)) { throw 'The selected game folder must contain SB/Content/Paks.' }
    Assert-PreparedGameClosed $targetRoot
    $scriptsPrefix='SB/Binaries/Win64/ue4ss/Mods/DekCNS/Scripts/'
    $requiredScripts=@(($scriptsPrefix+'main.lua'), ($scriptsPrefix+'OutfitReversal/Init.lua'), ($scriptsPrefix+'OutfitReversal/MetadataBridge.lua'), ($scriptsPrefix+'OutfitReversal/Prepared.json'))
    $allowedScripts=$requiredScripts+@($scriptsPrefix+'OutfitReversal/AccessoryLink.lua')
    $packagePrefix='SB/Content/Paks/~mods/OutfitReversalPrepared/'
    $packagePattern='^SB/Content/Paks/~mods/OutfitReversalPrepared/(OutfitReversalPrepared_[0-9]{1,10}_P)\.(pak|ucas|utoc)$'
    $seen=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $groups=@{}
    $plan=[Collections.Generic.List[object]]::new()
    foreach($file in @($data.files)) {
        if($file.relativePath -isnot [string] -or $file.sha256 -isnot [string]) { throw 'Manifest paths and SHA256 values must be strings.' }
        $relative=$file.relativePath
        if($relative.Contains('\')) { throw 'Use forward slashes in manifest relativePath values.' }
        if(-not $seen.Add($relative)) { throw "Duplicate manifest target: $relative" }
        $kind='script'
        if($relative -cmatch $packagePattern) {
            $kind='package'
            if(-not $groups.ContainsKey($Matches[1])) { $groups[$Matches[1]]=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase) }
            [void]$groups[$Matches[1]].Add($Matches[2])
        } elseif($relative -cnotin $allowedScripts) { throw "Manifest target is outside this installer's scope: $relative" }
        $expected=([string]$file.sha256).ToLowerInvariant()
        if($expected -notmatch '^[a-f0-9]{64}$') { throw "Invalid SHA256 for $relative" }
        $source=Join-PreparedTarget $bundleRoot $relative
        $target=Join-PreparedTarget $targetRoot $relative
        if(-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Missing prepared file: $relative" }
        if((Get-PreparedHash $source) -cne $expected) { throw "Prepared file failed its checksum: $relative" }
        if((Test-Path -LiteralPath $target) -and -not (Test-Path -LiteralPath $target -PathType Leaf)) { throw "A target file is occupied by a folder: $target" }
        $plan.Add([pscustomobject]@{relative=$relative;source=$source;target=$target;kind=$kind;sha256=$expected;existed=(Test-Path -LiteralPath $target -PathType Leaf)})
    }
    foreach($required in $requiredScripts) { if(-not $seen.Contains($required)) { throw "Install manifest is missing a required script: $required" } }
    $originalCns=[string]$data.sourceCnsMainSha256
    if($originalCns -notmatch '^[a-fA-F0-9]{64}$') { throw 'Source CNS checksum is missing. Prepare outfits again with the current preparer.' }
    $mainEntry=@($plan | Where-Object { $_.relative -ceq ($scriptsPrefix+'main.lua') })[0]
    if(-not $mainEntry.existed) { throw 'Install CNS before installing prepared outfits.' }
    $currentCns=Get-PreparedHash $mainEntry.target
    if($currentCns -ine $originalCns -and $currentCns -ine $mainEntry.sha256) { throw 'CNS changed since preparation. Prepare again before installing to preserve your current CNS setup.' }
    $removeAll=$data.removeAllPrepared -is [bool] -and $data.removeAllPrepared
    $metadata=Get-Content -LiteralPath (Join-PreparedTarget $bundleRoot ($scriptsPrefix+'OutfitReversal/Prepared.json')) -Raw | ConvertFrom-Json
    $emptyRemoval=$removeAll -and $metadata.schemaVersion -eq 1 -and $metadata.outfits -is [pscustomobject] -and @($metadata.outfits.PSObject.Properties).Count -eq 0 -and $groups.Count -eq 0
    if(($removeAll -and -not $emptyRemoval) -or (-not $groups.Count -and -not $emptyRemoval)) { throw 'Install manifest requires complete generated package triplets, or a validated empty uninstall.' }
    foreach($group in $groups.Keys) { if($groups[$group].Count -ne 3) { throw "Generated package is missing part of its pak/ucas/utoc triplet: $group" } }
    $packageDirectory=Join-PreparedTarget $targetRoot $packagePrefix.TrimEnd('/')
    $oldPackages=@()
    if(Test-Path -LiteralPath $packageDirectory) {
        foreach($item in @(Get-ChildItem -LiteralPath $packageDirectory -Force)) {
            Assert-PreparedPlainPath $item.FullName
            if(-not $item.PSIsContainer -and $item.Name -match '^OutfitReversalPrepared_[0-9]{1,10}_P\.(pak|ucas|utoc)$') { $oldPackages+=$item.FullName }
        }
    }
    Assert-PreparedNoContainerConflict $pakRoot $plan $oldPackages
    $backupBase=[IO.Path]::GetFullPath($Backups)
    if(Test-PreparedContained $pakRoot $backupBase) { throw 'Backups must be stored outside the game Paks folder.' }
    Assert-PreparedPlainPath $backupBase
    $backup=Join-Path $backupBase ((Get-Date -Format 'yyyyMMdd-HHmmss')+'-'+[guid]::NewGuid().ToString('N').Substring(0,10))
    Assert-PreparedPlainPath $backup
    [void][IO.Directory]::CreateDirectory($backup)
    $changedScripts=[Collections.Generic.List[object]]::new()
    $movedPackages=[Collections.Generic.List[object]]::new()
    $newPackages=[Collections.Generic.List[object]]::new()
    $journal=[ordered]@{schemaVersion=1;gameRoot=$targetRoot;state='staging';files=@($plan | ForEach-Object { @{relativePath=$_.relative;sha256=$_.sha256;existed=$_.existed} });oldPackages=@($oldPackages)}
    $journalPath=Join-Path $backup 'InstallJournal.json'
    $journal | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $journalPath -Encoding UTF8
    try {
        foreach($entry in $plan) {
            $stage=Join-PreparedTarget (Join-Path $backup 'Staging') $entry.relative
            [void][IO.Directory]::CreateDirectory((Split-Path $stage -Parent))
            Copy-PreparedFile $entry.source $stage
            if((Get-PreparedHash $stage) -cne $entry.sha256) { throw "Staged checksum mismatch: $($entry.relative)" }
            $entry | Add-Member -NotePropertyName staged -NotePropertyValue $stage
            if($entry.kind -eq 'script' -and $entry.existed) {
                $saved=Join-PreparedTarget (Join-Path $backup 'OriginalScripts') $entry.relative
                [void][IO.Directory]::CreateDirectory((Split-Path $saved -Parent))
                Copy-PreparedFile $entry.target $saved
                if((Get-PreparedHash $saved) -cne (Get-PreparedHash $entry.target)) { throw "Script backup checksum mismatch: $($entry.relative)" }
                $entry | Add-Member -NotePropertyName saved -NotePropertyValue $saved
            }
        }
        Assert-PreparedGameClosed $targetRoot
        Assert-PreparedNoContainerConflict $pakRoot $plan $oldPackages
        $journal.state='installing'
        $journal | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $journalPath -Encoding UTF8
        foreach($old in $oldPackages) {
            $saved=Join-Path (Join-Path $backup 'OriginalPackages') ([IO.Path]::GetFileName($old))
            [void][IO.Directory]::CreateDirectory((Split-Path $saved -Parent))
            Assert-PreparedPlainPath $old
            Assert-PreparedPlainPath $saved
            if(-not (Test-PreparedContained $packageDirectory $old) -or -not (Test-PreparedContained $backup $saved)) { throw 'Package backup path escaped the expected scope.' }
            $movedPackages.Add([pscustomobject]@{target=$old;saved=$saved})
            Move-Item -LiteralPath $old -Destination $saved -ErrorAction Stop
        }
        foreach($entry in $plan) {
            Assert-PreparedPlainPath $entry.target
            [void][IO.Directory]::CreateDirectory((Split-Path $entry.target -Parent))
            if($entry.kind -eq 'script') { $changedScripts.Add($entry); Copy-PreparedFile $entry.staged $entry.target }
            else { $newPackages.Add($entry); Move-Item -LiteralPath $entry.staged -Destination $entry.target -ErrorAction Stop }
            if((Get-PreparedHash $entry.target) -cne $entry.sha256) { throw "Installed checksum mismatch: $($entry.relative)" }
        }
        $journal.state='installed'
        $journal | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $journalPath -Encoding UTF8
        return [pscustomobject]@{gameRoot=$targetRoot;backup=$backup;scripts=$requiredScripts.Count;packages=$groups.Count;oldFilesBackedUp=$oldPackages.Count}
    } catch {
        $originalError=$_
        $rollbackErrors=[Collections.Generic.List[string]]::new()
        foreach($entry in $newPackages) {
            try { Assert-PreparedPlainPath $entry.target; if(Test-Path -LiteralPath $entry.target -PathType Leaf) { Remove-Item -LiteralPath $entry.target -Force -ErrorAction Stop } }
            catch { $rollbackErrors.Add($_.Exception.Message) }
        }
        foreach($entry in $changedScripts) {
            try {
                Assert-PreparedPlainPath $entry.target
                if($entry.existed) { Copy-PreparedFile $entry.saved $entry.target }
                elseif(Test-Path -LiteralPath $entry.target -PathType Leaf) { Remove-Item -LiteralPath $entry.target -Force -ErrorAction Stop }
            } catch { $rollbackErrors.Add($_.Exception.Message) }
        }
        foreach($entry in $movedPackages) {
            try {
                Assert-PreparedPlainPath $entry.target
                Assert-PreparedPlainPath $entry.saved
                if(Test-Path -LiteralPath $entry.saved -PathType Leaf) { Move-Item -LiteralPath $entry.saved -Destination $entry.target -ErrorAction Stop }
            } catch { $rollbackErrors.Add($_.Exception.Message) }
        }
        $journal.state='rolled_back'
        $journal.error=$originalError.Exception.Message
        $journal.rollbackErrors=@($rollbackErrors)
        if($rollbackErrors.Count) { $journal.state='rollback_needs_attention' }
        $journal | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $journalPath -Encoding UTF8
        if($rollbackErrors.Count) { throw "Install failed; recovery needs attention. Backups: $backup. Original error: $($originalError.Exception.Message). Recovery errors: $($rollbackErrors -join '; ')" }
        throw "Install failed; previous files were restored. Backups: $backup. Reason: $($originalError.Exception.Message)"
    }
}

if($MyInvocation.InvocationName -ne '.') {
    try {
        $result=Invoke-PreparedInstall $ManifestPath $GameRoot $BackupRoot
        Write-Host "Prepared outfits installed. Active generated packages: $($result.packages)."
        Write-Host "Previous generated files and scripts backed up to: $($result.backup)"
        exit 0
    } catch {
        Write-Host $_.Exception.Message -ForegroundColor Red
        Write-Host 'If Windows reports access denied, close the game and run InstallPrepared.exe as administrator.'
        exit 1
    }
}
