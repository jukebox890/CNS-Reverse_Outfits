<#
.SYNOPSIS
Read-only CUE4Parse extraction for CNS colour preparation. Requires PowerShell 7.
.DESCRIPTION
Input JSON fields: pakRoot, mappings, libraries, nativeRoot (optional), outputRoot,
meshes [{id, mesh, parameters: CNS Parameters[], materialOverrides: [{index,material}],
         userConfigs: CNS UserConfigs (optional)}].
Optional extraContainers[], includeSkin (default false), maxTextures (default 0 = unlimited).
All output is written below outputRoot. Game containers are opened read-only.
This script extracts evidence and PNG sources; it does not alter CNS or game assets.
#>
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Job)
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'PowerShell 7 or newer is required.' }
$revJob = Get-Content -LiteralPath $Job -Raw | ConvertFrom-Json -AsHashtable -Depth 100
foreach ($revRequired in @('pakRoot','mappings','libraries','outputRoot','meshes')) {
    if (-not $revJob.ContainsKey($revRequired)) { throw "Job is missing $revRequired" }
}
$revOutput = [IO.Path]::GetFullPath([string]$revJob.outputRoot)
$revPaks = [IO.Path]::GetFullPath([string]$revJob.pakRoot)
# Never write into the source installation, even if a job accidentally requests it.
$revPaksPrefix = $revPaks.TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
if ($revOutput.Equals($revPaks,[StringComparison]::OrdinalIgnoreCase) -or $revOutput.StartsWith($revPaksPrefix,[StringComparison]::OrdinalIgnoreCase)) {
    throw 'outputRoot must not be the source Paks directory or one of its descendants.'
}
[IO.Directory]::CreateDirectory($revOutput) | Out-Null
$revLib = [IO.Path]::GetFullPath([string]$revJob.libraries)
foreach ($revDll in @('CUE4Parse.dll','CUE4Parse-Conversion.dll')) {
    [Reflection.Assembly]::LoadFrom((Join-Path $revLib $revDll)) | Out-Null
}
[Runtime.InteropServices.NativeLibrary]::Load((Join-Path $revLib 'libSkiaSharp.dll')) | Out-Null
if ($revJob.nativeRoot) {
    $revNative = [string]$revJob.nativeRoot
    [IO.Directory]::CreateDirectory($revNative) | Out-Null
    Write-Host 'Initializing compression readers (first preparation may download upstream codec files).'
    [CUE4Parse.Compression.OodleHelper]::Initialize((Join-Path $revNative 'oodle-data-shared.dll'))
    [CUE4Parse.Compression.ZlibHelper]::Initialize((Join-Path $revNative 'zlib-ng2.dll'))
}
$revVersions = [CUE4Parse.UE4.Versions.VersionContainer]::new([CUE4Parse.UE4.Versions.EGame]::GAME_UE4_26)
$revProvider = [CUE4Parse.FileProvider.DefaultFileProvider]::new($revPaks,[IO.SearchOption]::AllDirectories,$revVersions,[StringComparer]::OrdinalIgnoreCase)
$revProvider.Initialize()
foreach ($revContainer in @($revJob.extraContainers)) { if ($revContainer) { $revProvider.RegisterVfs([string]$revContainer) } }
$revProvider.MappingsContainer = [CUE4Parse.MappingsProvider.Usmap.FileUsmapTypeMappingsProvider]::new([string]$revJob.mappings)
$revMounted = $revProvider.Mount()
$revProvider.PostMount()
$revReport = [ordered]@{
    schemaVersion=1; tool='CNS Offline Reversal Extractor'; complete=$false;
    provider=[ordered]@{mounted=$revMounted; indexedFiles=$revProvider.Files.Count; unloadedContainers=$revProvider.UnloadedVfs.Count; game='UE4.26'; mappings=[string]$revJob.mappings};
    meshes=@(); textures=@(); issues=@();
    limitations=@('Colour semantics are inferred from parameter and asset names; ambiguous inputs are reported, not changed.', 'Runtime-spawned accessory actors are not enumerated by a skeletal-mesh-only job.', 'Shader arithmetic and static material branches are not reconstructed; effective parameters include potentially inactive inputs.')
}
$revObjects = [Collections.Generic.Dictionary[string,object]]::new([StringComparer]::Ordinal)
$revStates = [Collections.Generic.Dictionary[string,object]]::new([StringComparer]::Ordinal)
$revImages = [Collections.Generic.Dictionary[string,object]]::new([StringComparer]::Ordinal)
$revIssueKeys = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
$revIndexedPackages=$null
function Add-RevIssue([string]$Code,[string]$Target,[string]$Detail) {
    $revDetail = ($Detail -split "`r?`n")[0]
    if ($revDetail.Length -gt 500) { $revDetail=$revDetail.Substring(0,500) }
    if ($revIssueKeys.Add("$Code|$Target|$revDetail")) {
        $revReport.issues += [ordered]@{code=$Code;target=$Target;detail=$revDetail}
    }
}
function Get-RevPackage([object]$Reference) {
    if ($null -eq $Reference) { return $null }
    if ($Reference -is [string]) { $revPath=[string]$Reference }
    elseif ($Reference.ObjectPath) { $revPath=[string]$Reference.ObjectPath }
    else { return $null }
    $revPath=$revPath.Replace('\','/')
    if ($revPath -match "^[^']+'([^']+)'$") { $revPath=$Matches[1] }
    $revPath=$revPath -replace '\.uasset$','' -replace '\.[^/]+$',''
    # Cooked mods may retain their author's project name in the container
    # directory index. Unreal mounts that project's Content at /Game too.
    if ($revPath -match '^/?([^/]+)/Content/(.+)$') {
        if($Matches[1] -ieq 'Engine') { $revPath='/Engine/'+$Matches[2] }
        else { $revPath='/Game/'+$Matches[2] }
    }
    if (-not $revPath.StartsWith('/')) { $revPath='/'+$revPath }
    return $revPath
}
function Get-RevObjectPath([object]$Reference) {
    $revPackage=Get-RevPackage $Reference
    if (-not $revPackage) { return $null }
    return $revPackage+'.'+($revPackage -split '/')[-1]
}
function Find-RevIndexedPackage([string]$Package) {
    # Called only after the provider's normal /Game lookup failed. Match the
    # complete Content-relative path, never a filename or a fuzzy suffix.
    if(-not $Package.StartsWith('/Game/',[StringComparison]::OrdinalIgnoreCase)) { return $null }
    if($null -eq $script:revIndexedPackages) {
        $script:revIndexedPackages=[Collections.Generic.Dictionary[string,object]]::new([StringComparer]::OrdinalIgnoreCase)
        foreach($revIndexedPath in $revProvider.Files.Keys) {
            if($revIndexedPath -notmatch '^([^/]+)/Content/(.+)\.uasset$' -or $Matches[1] -ieq 'Engine') { continue }
            $revLogical='/Game/'+$Matches[2]
            if(-not $script:revIndexedPackages.ContainsKey($revLogical)) { $script:revIndexedPackages[$revLogical]=[Collections.Generic.List[string]]::new() }
            $script:revIndexedPackages[$revLogical].Add([string]$revIndexedPath)
        }
    }
    if(-not $script:revIndexedPackages.ContainsKey($Package)) { return $null }
    $revCandidates=$script:revIndexedPackages[$Package]
    if($revCandidates.Count -ne 1) {
        Add-RevIssue 'ambiguous_source_project_path' $Package ('Multiple cooked Content roots: '+($revCandidates -join ', '))
        return $null
    }
    return [string]$revCandidates[0]
}
function Get-RevAsset([string]$Reference,[string]$Kind='Material') {
    $revPackage=Get-RevPackage $Reference
    if (-not $revPackage) { return $null }
    $revCacheKey="$Kind|$revPackage"
    if ($revObjects.ContainsKey($revCacheKey)) { return $revObjects[$revCacheKey] }
    try {
        try { $revExports=@($revProvider.LoadPackageObjects($revPackage)) }
        catch {
            $revIndexedPath=Find-RevIndexedPackage $revPackage
            if(-not $revIndexedPath) { throw }
            $revExports=@($revProvider.LoadPackageObjects($revIndexedPath))
            Add-RevIssue 'source_project_root_resolved' $revPackage $revIndexedPath
        }
        if($revJob.exportProperties) {
            $revEvidence=Join-Path $revOutput 'properties'
            [IO.Directory]::CreateDirectory($revEvidence)|Out-Null
            [IO.File]::WriteAllText((Join-Path $revEvidence (($revPackage -split '/')[-1]+'.json')),([Newtonsoft.Json.JsonConvert]::SerializeObject($revExports)),[Text.UTF8Encoding]::new($false))
        }
        $revAsset=$null
        foreach($revExport in $revExports) {
            $revType=$revExport.GetType().Name
            if (($Kind -eq 'Material' -and $revType -in @('UMaterialInstanceConstant','UMaterial','UMaterialInstance')) -or
                ($Kind -eq 'Mesh' -and $revType -in @('USkeletalMesh','UStaticMesh')) -or
                ($Kind -eq 'Texture' -and $revType -eq 'UTexture2D')) { $revAsset=$revExport;break }
        }
        if (-not $revAsset) { throw "No $Kind export in package" }
        $revObjects[$revCacheKey]=$revAsset
        return $revAsset
    } catch {
        Add-RevIssue 'asset_load_failed' $revPackage $_.Exception.Message
        $revObjects[$revCacheKey]=$null
        return $null
    }
}
function Convert-RevJson([object]$Asset) {
    return [Newtonsoft.Json.JsonConvert]::SerializeObject($Asset) | ConvertFrom-Json -AsHashtable -Depth 100
}
function Get-RevAssociation([object]$Association) {
    switch -Regex ([string]$Association) {
        '(^|::)(Global|GlobalParameter)$|^2$' { return 2 }
        '(^|::)(Layer|LayerParameter)$|^0$' { return 0 }
        '(^|::)(Blend|BlendParameter)$|^1$' { return 1 }
        default { return -1 }
    }
}
function Get-RevInfo([object]$Info) {
    if (-not $Info -or -not $Info.Name) { return $null }
    $revAssoc=Get-RevAssociation $Info.Association
    if ($revAssoc -lt 0) { Add-RevIssue 'parameter_association_unknown' ([string]$Info.Name) ([string]$Info.Association); return $null }
    $revIndex=-1
    if ($Info.Contains('Index')) { $revIndex=[int]$Info.Index }
    return [ordered]@{name=[string]$Info.Name;association=$revAssoc;index=$revIndex;key=(([string]$Info.Name).ToLowerInvariant()+"|$revAssoc|$revIndex")}
}
function New-RevState {
    return @{chain=@();materialClass=$null;texture=[Collections.Generic.Dictionary[string,object]]::new([StringComparer]::Ordinal);vector=[Collections.Generic.Dictionary[string,object]]::new([StringComparer]::Ordinal);scalar=[Collections.Generic.Dictionary[string,object]]::new([StringComparer]::Ordinal);masterDefaultsEnumerated=$false}
}
function Copy-RevState([object]$State) {
    $revCopy=New-RevState
    $revCopy.chain=@($State.chain);$revCopy.materialClass=$State.materialClass;$revCopy.masterDefaultsEnumerated=$State.masterDefaultsEnumerated
    foreach($revKind in @('texture','vector','scalar')) { foreach($revKey in $State[$revKind].Keys) { $revCopy[$revKind][$revKey]=$State[$revKind][$revKey] } }
    return $revCopy
}
function Get-RevMaterialState([string]$Reference,[string[]]$Ancestors=@()) {
    $revPackage=Get-RevPackage $Reference
    if ($revStates.ContainsKey($revPackage)) { return Copy-RevState $revStates[$revPackage] }
    $revState=New-RevState
    if ($Ancestors.Count -ge 32 -or $revPackage -cin $Ancestors) { Add-RevIssue 'material_parent_cycle_or_limit' $revPackage 'Parent chain exceeded 32 or repeated';return $revState }
    $revMaterial=Get-RevAsset $revPackage
    if (-not $revMaterial) { return $revState }
    try { $revData=Convert-RevJson $revMaterial } catch { Add-RevIssue 'material_properties_unreadable' $revPackage $_.Exception.Message; return $revState }
    $revProps=$revData.Properties
    $revParent=Get-RevPackage $revProps.Parent
    if ($revParent) { $revState=Get-RevMaterialState $revParent (@($Ancestors)+$revPackage) }
    $revState.chain=@($revPackage)+@($revState.chain)
    # Report the resolved instance itself, not the inherited parent's class.
    $revState.materialClass=$revMaterial.GetType().Name
    $revCached=$revProps.CachedExpressionData.Parameters
    if ($revCached) {
        foreach($revTable in @(@('scalar','RuntimeEntries','ScalarValues'),@('vector','RuntimeEntries[1]','VectorValues'),@('texture','RuntimeEntries[2]','TextureValues'))) {
            $revInfos=@($revCached[$revTable[1]].ParameterInfos)
            $revValues=@($revCached[$revTable[2]])
            if($revInfos.Count -ne $revValues.Count) { Add-RevIssue 'master_parameter_count_mismatch' $revPackage ([string]$revTable[0]); continue }
            for($revI=0;$revI -lt $revInfos.Count;$revI++) {
                $revInfo=Get-RevInfo $revInfos[$revI]
                if($revInfo) { $revState[$revTable[0]][$revInfo.key]=@{info=$revInfo;value=$revValues[$revI];source=$revPackage;origin='master_default'} }
            }
        }
        $revState.masterDefaultsEnumerated=$true
    }
    foreach($revTable in @(@('texture','TextureParameterValues'),@('vector','VectorParameterValues'),@('scalar','ScalarParameterValues'))) {
        foreach($revEntry in @($revProps[$revTable[1]])) {
            if(-not $revEntry) { continue }
            $revInfo=Get-RevInfo $revEntry.ParameterInfo
            if($revInfo) { $revState[$revTable[0]][$revInfo.key]=@{info=$revInfo;value=$revEntry.ParameterValue;source=$revPackage;origin='material_override'} }
        }
    }
    if(-not $revState.masterDefaultsEnumerated) { Add-RevIssue 'master_defaults_unavailable' $revPackage 'No readable CachedExpressionData in resolved parent chain.' }
    $revStates[$revPackage]=Copy-RevState $revState
    return $revState
}
function Test-RevProtected([object]$Hints,[switch]$AllowHairTexture) {
    if ($revJob.includeSkin -eq $true) { return $false }
    $revProtectedWords='(?i)(?:^|[_/\s.\-])(skin|base[_\s]*body|custom[_\s]*body|body_skin|face|hair|head|eyebrow|eyelash|iris|eyeball|stocking)(?:$|[_/\s.\-])'
    # Imported outfits sometimes reuse a hair-named diffuse map for lace.
    # The already-inspected clothing slot and explicit colour input provide
    # stronger role evidence than that source filename alone.
    if($AllowHairTexture) { $revProtectedWords=$revProtectedWords.Replace('|hair|','|') }
    foreach($revHint in @($Hints)) {
        if($null -eq $revHint) { continue }
        $revRaw=([string]$revHint).Replace('\','/')
        # Explicit /Skin/ and Body_Skin tokens remain useful role evidence.
        # Camel-case only the asset/slot name: an author's namespace such as
        # MySkinSuit must not classify every clothing material as skin.
        if($revRaw -match $revProtectedWords) { return $true }
        $revName=($revRaw -split '/')[-1]
        $revName=$revName -creplace '([a-z])([A-Z])','$1 $2'
        if($revName -match $revProtectedWords) { return $true }
    }
    return $false
}
function Get-RevDeclaredSkinSlots([object]$Configs) {
    # A CNS author can identify a skin slot more reliably than a cooked name
    # such as MI_Test. Do not infer skin from a generic "Body" clothing label.
    # These hints only protect slots; they never substitute a different UV map.
    $revResult=[Collections.Generic.Dictionary[int,string]]::new()
    if($revJob.includeSkin -eq $true -or $Configs -isnot [Collections.IDictionary]) { return ,$revResult }
    foreach($revKind in @('TextureOptions','VectorControls','ScalarControls')) {
        foreach($revControl in @($Configs[$revKind])) {
            if($revControl -isnot [Collections.IDictionary] -or -not $revControl.Contains('MaterialIndex')) { continue }
            $revIndex=-1
            if(-not [int]::TryParse([string]$revControl.MaterialIndex,[ref]$revIndex) -or $revIndex -lt 0) { continue }
            $revLabel=([string]$revControl.DisplayName)+' '+([string]$revControl.ParamName)
            $revLabel=$revLabel -creplace '([a-z])([A-Z])','$1 $2'
            $revSkinLabel=$revLabel -match '(?i)(?:^|[_\s.\-/])(skin|tattoo|tattoos)(?:$|[_\s.\-/])'
            $revSkinTextures=$false
            if($revKind -eq 'TextureOptions') {
                $revPaths=@($revControl.Textures | Where-Object { $_ })
                if($revPaths.Count -gt 0) {
                    $revProtectedCount=0
                    foreach($revPath in $revPaths) { if(Test-RevProtected ([string]$revPath)) { $revProtectedCount++ } }
                    $revSkinTextures=$revProtectedCount -eq $revPaths.Count
                }
            }
            if($revSkinLabel -or $revSkinTextures) {
                $revResult[$revIndex]='CNS '+$revKind+': '+[string]$revControl.DisplayName
            }
        }
    }
    return ,$revResult
}
function Get-RevTextureKind([string]$Name,[string]$Texture) {
    $revCompact=$Name.ToLowerInvariant() -replace '[^a-z0-9]',''
    if($revCompact -match 'normal|rough|metal|mask|opacity|occlusion|height|displace|detailnormal|(^|[^a-z])(ao|orm|rma)|packed|channel') { return 'technical' }
    $revTexName=($Texture -split '/')[-1]
    if($revTexName -match '(?i)(?:^|[_\s.\-])(n|normal|mask|orm|rma|ao|m)(?:$|[_\s.\-])') { return 'technical' }
    if($revCompact -match 'basecolou?r|albedo|diffuse|diff|colou?r') { return 'colour' }
    if($revTexName -match '(?i)(?:^|[_\s.\-])(d|diffuse|albedo|basecolor|basecolour|bc)(?:$|[_\s.\-])') { return 'colour' }
    return 'unknown'
}
function Get-RevSkinReferenceRole([string]$SlotName,[string]$Material,[object]$Chain,[string]$DeclaredReason,[string]$Parameter,[string]$Texture) {
    # Reference extraction is stricter than the general protection rule. Hair,
    # stockings and cosmetics are protected too, but are not skin-colour samples.
    # Test actual asset names, not the author's namespace or outfit directory.
    $revRoleNames=@($SlotName)
    foreach($revHint in @($Material)+@($Chain)) {
        if($revHint) { $revRoleNames+=(([string]$revHint).Replace('\','/') -split '/')[-1] }
    }
    $revRoleText=($revRoleNames -join ' ') -creplace '([a-z])([A-Z])','$1 $2'
    $revExcluded='(?i)(?:^|[_\s.\-/])(hair|face|head|eye|eyes|eyebrow|eyelash|iris|eyeball|stocking|stockings|makeup|cosmetic)(?:$|[_\s.\-/])'
    if($revRoleText -match $revExcluded) { return $null }
    $revSkinWords='(?i)(?:^|[_\s.\-/])(skin|base[_\s]*body|custom[_\s]*body|body[_\s]*skin)(?:$|[_\s.\-/])'
    $revSkinRole=$revRoleText -match $revSkinWords
    $revExplicitSkin=$DeclaredReason -match '(?i)(?:^|[_\s.\-/])(skin|tattoo|tattoos)(?:$|[_\s.\-/])'
    if(-not $revSkinRole -and -not $revExplicitSkin) { return $null }
    $revBindingConfidence=if($revSkinRole) {'high'} else {'medium'}
    $revCompact=$Parameter.ToLowerInvariant() -replace '[^a-z0-9]',''
    if($revCompact -notmatch '^(?:skin)?(?:basecolou?r|albedo|diffuse|diff)(?:texture|map)?[0-9]*$') { return $null }
    if((Get-RevTextureKind $Parameter $Texture) -ne 'colour') { return $null }
    $revTextureName=(($Texture.Replace('\','/') -split '/')[-1]) -creplace '([a-z])([A-Z])','$1 $2'
    if($revTextureName -match $revExcluded) { return $null }
    if($revTextureName -match '(?i)(?:^|[_\s.\-/])(tattoo|tattoos)(?:$|[_\s.\-/])') {
        return @{role='tattoo_skin';confidence='unknown';bindingConfidence=$revBindingConfidence;usable=$false;reason='Effective skin colour input is named as a tattoo texture; retained as evidence only.'}
    }
    if($revTextureName -match '(?i)(?:^|[_\s.\-/])(cloth|clothes|clothing|dress|outfit|mixed)(?:$|[_\s.\-/])') {
        return @{role='mixed_or_unknown';confidence='unknown';bindingConfidence=$revBindingConfidence;usable=$false;reason='Skin slot colour input also names clothing or mixed content; retained as evidence only.'}
    }
    $revConfidence=if($revSkinRole) {'high'} else {'medium'}
    $revReason=if($revSkinRole) {'Dedicated skin material/slot and effective base-colour input.'} else {'CNS author identifies skin; effective base-colour input requires pixel purity validation.'}
    return @{role='dedicated_skin';confidence=$revConfidence;bindingConfidence=$revBindingConfidence;usable=$true;reason=$revReason}
}
function Get-RevSkinReferences([object]$SlotReport,[object]$State,[string]$DeclaredReason) {
    $revReferences=@()
    foreach($revEntry in $State.texture.Values) {
        $revTexturePath=Get-RevPackage $revEntry.value
        if(-not $revTexturePath) { continue }
        $revRole=Get-RevSkinReferenceRole $SlotReport.name $SlotReport.material $State.chain $DeclaredReason $revEntry.info.name $revTexturePath
        if(-not $revRole) { continue }
        $revImage=Export-RevTexture $revTexturePath
        if(-not $revImage) { continue }
        $revReferences+=([ordered]@{slot=$SlotReport.index;material=$SlotReport.material;parameter=$revEntry.info.name;association=$revEntry.info.association;layer=$revEntry.info.index;source=(Get-RevObjectPath $revTexturePath);png=$revImage.png;origin=$revEntry.origin;inheritedFrom=$revEntry.source;reason=$revRole.reason;confidence=$revRole.confidence;bindingConfidence=$revRole.bindingConfidence;role=$revRole.role;usable=$revRole.usable;referenceOnly=$true})
    }
    return $revReferences
}
function Get-RevHash([string]$Text) { return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($Text))).ToLowerInvariant() }
function Export-RevTexture([string]$Reference) {
    $revPackage=Get-RevPackage $Reference
    if($revImages.ContainsKey($revPackage)) { return $revImages[$revPackage] }
    if([int]$revJob.maxTextures -gt 0 -and $revImages.Count -ge [int]$revJob.maxTextures) { Add-RevIssue 'texture_limit' $revPackage 'Job maxTextures reached';return $null }
    $revTexture=Get-RevAsset $revPackage 'Texture'
    if(-not $revTexture) { return $null }
    $revBitmap=$null
    try {
        $revTextureData=Convert-RevJson $revTexture
        $revBitmap=[CUE4Parse_Conversion.Textures.TextureDecoder]::Decode($revTexture,[CUE4Parse.UE4.Assets.Exports.Texture.ETexturePlatform]::DesktopMobile)
        if($null -eq $revBitmap) { throw 'Texture decoder returned no bitmap' }
        $revExtension=''
        $revPng=[CUE4Parse_Conversion.Textures.TextureEncoder]::Encode($revBitmap,[CUE4Parse_Conversion.Options.ETextureFormat]::Png,$false,[ref]$revExtension,100)
        $revRel='sources/'+(Get-RevHash $revPackage).Substring(0,20)+'.png'
        $revDestination=Join-Path $revOutput $revRel
        [IO.Directory]::CreateDirectory((Split-Path $revDestination -Parent))|Out-Null
        [IO.File]::WriteAllBytes($revDestination,$revPng)
        $revSrgb=$true
        if($revTextureData.Properties.Contains('SRGB')) { $revSrgb=[bool]$revTextureData.Properties.SRGB }
        $revImage=[ordered]@{source=(Get-RevObjectPath $revPackage);package=$revPackage;png=$revRel;width=$revBitmap.Width;height=$revBitmap.Height;pixelFormat=[string]$revTextureData.PixelFormat;srgb=$revSrgb;mipCount=@($revTextureData.Mips).Count;sourceProperties=$revTextureData.Properties;sha256=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($revPng)).ToLowerInvariant()}
        $revImages[$revPackage]=$revImage
        $revReport.textures+=$revImage
        Write-Host "Exported $revPackage [$($revBitmap.Width)x$($revBitmap.Height)]"
        return $revImage
    } catch { Add-RevIssue 'texture_decode_failed' $revPackage $_.Exception.Message; return $null }
    finally { if($null -ne $revBitmap -and $revBitmap -is [IDisposable]) { $revBitmap.Dispose() } }
}
try {
    Write-Host "Mounted $revMounted readers; indexed $($revProvider.Files.Count) files."
    foreach($revMeshJob in @($revJob.meshes)) {
        if($revMeshJob.outfitIndex -and $revMeshJob.outfitTotal) {
            $revProgress=[ordered]@{phase='extract';step=1;total=5;message='Inspecting outfit assets with PowerShell';outfitIndex=[int]$revMeshJob.outfitIndex;outfitTotal=[int]$revMeshJob.outfitTotal;outfitName=[string]$revMeshJob.outfitName;variantIndex=[int]$revMeshJob.variantIndex;variantTotal=[int]$revMeshJob.variantTotal}
            if($revJob.bindingsOnly){$revProgress.phase='cook';$revProgress.step=3;$revProgress.message='Checking retained material bindings'}
            [Console]::Out.WriteLine('[PROGRESS] '+($revProgress|ConvertTo-Json -Compress))
        }
        $revMeshPath=Get-RevPackage $revMeshJob.mesh
        $revMeshReport=[ordered]@{id=[string]$revMeshJob.id;mesh=(Get-RevObjectPath $revMeshPath);slots=@();skinReferences=@();complete=$false}
        $revReport.meshes+=$revMeshReport
        $revMesh=Get-RevAsset $revMeshPath 'Mesh'
        if(-not $revMesh) { continue }
        $revDeclaredSkin=Get-RevDeclaredSkinSlots $revMeshJob.userConfigs
        $revSlots=@($revMesh.SkeletalMaterials)
        if(-not $revSlots -or ($revSlots.Count -eq 1 -and $null -eq $revSlots[0])) { Add-RevIssue 'unsupported_mesh_type' $revMeshPath 'Expected SkeletalMaterials';continue }
        for($revSlotIndex=0;$revSlotIndex -lt $revSlots.Count;$revSlotIndex++) {
            $revSlot=$revSlots[$revSlotIndex]
            $revSlotName=[string]$revSlot.MaterialSlotName
            $revSlotReport=[ordered]@{index=$revSlotIndex;name=$revSlotName;material=$null;chain=@();textures=@();vectors=@();scalars=@();status='unresolved'}
            $revMeshReport.slots+=$revSlotReport
            $revDeclaredReason=if($revDeclaredSkin.ContainsKey($revSlotIndex)) {$revDeclaredSkin[$revSlotIndex]} else {''}
            $revProtectedSlot=$revDeclaredSkin.ContainsKey($revSlotIndex) -or (Test-RevProtected $revSlotName)
            if($revDeclaredReason) { $revSlotReport.protectionReason=$revDeclaredReason }
            $revMaterialPath=$null
            foreach($revOverride in @($revMeshJob.materialOverrides)) {
                if($revOverride -and [int]$revOverride.index -eq $revSlotIndex) { $revMaterialPath=Get-RevPackage $revOverride.material }
            }
            if(-not $revMaterialPath -and $null -ne $revSlot.Material) {
                try { $revMaterialPath=Get-RevPackage ((Convert-RevJson $revSlot.Material).ObjectPath) } catch {}
                if(-not $revMaterialPath) {
                    try { $revMaterialPath=Get-RevPackage ($revSlot.Material.GetPathName()) } catch {}
                }
            }
            if(-not $revMaterialPath) {
                # Null entries are legitimate placeholders in custom meshes,
                # not failed reads and not permission to borrow another slot.
                if($null -eq $revSlot.Material -or $revSlot.Material.IsNull -or ($revSlot.Material.PSObject.Properties.Name -contains 'Index' -and [int]$revSlot.Material.Index -eq 0)) { $revSlotReport.status='empty_material_slot' }
                else { Add-RevIssue 'material_reference_unresolved' "$revMeshPath`:$revSlotIndex" $revSlotName }
                continue
            }
            $revSlotReport.material=Get-RevObjectPath $revMaterialPath
            if($revJob.bindingsOnly){
                $revBindingAsset=Get-RevAsset $revMaterialPath 'Material'
                if($revBindingAsset){$revSlotReport.materialClass=$revBindingAsset.GetType().Name;$revSlotReport.status='binding_only'}
                else {
                    # A shared mod path may be ambiguous for the offline reader.
                    # The mesh import itself still supplies an exact typed binding;
                    # restore that reference only, without reading/recolouring it.
                    try {
                        $revImport=Convert-RevJson $revSlot.Material
                        if((Get-RevPackage $revImport.ObjectPath) -ceq $revMaterialPath -and [string]$revImport.ObjectName -match "^(MaterialInstanceConstant|MaterialInstance|Material)'") {
                            $revSlotReport.materialClass='U'+$Matches[1];$revSlotReport.status='binding_only';$revSlotReport.classEvidence='exact_mesh_import'
                        }
                    } catch {}
                }
                continue
            }
            if(Test-RevProtected $revMaterialPath) { $revProtectedSlot=$true }
            $revState=Get-RevMaterialState $revMaterialPath
            $revSlotReport.chain=@($revState.chain)
            $revSlotReport.materialClass=$revState.materialClass
            if(Test-RevProtected $revState.chain) { $revProtectedSlot=$true }
            # CNS per-variant parameters override the cooked instance defaults.
            foreach($revParameter in @($revMeshJob.parameters)) {
                if(-not $revParameter -or [int]$revParameter.MaterialIndex -ne $revSlotIndex) { continue }
                $revInfo=Get-RevInfo @{Name=[string]$revParameter.ParamName;Association=$revParameter.Association;Index=$revParameter.LayerIndex}
                if(-not $revInfo) { continue }
                $revKind=([string]$revParameter.ParamType).ToLowerInvariant()
                if($revKind -in @('texture','vector','scalar')) { $revState[$revKind][$revInfo.key]=@{info=$revInfo;value=$revParameter.Value;source='cns_variant';origin='cns_variant'} }
            }
            if($revProtectedSlot) {
                $revSlotReport.status='protected_skin_or_cosmetic'
                $revMeshReport.skinReferences+=@(Get-RevSkinReferences $revSlotReport $revState $revDeclaredReason)
                # Evidence-only source defaults for maximum-safety resets. Never
                # recolour these, or infer another body's texture/UV layout.
                $revSlotReport.restoreVectors=@()
                foreach($revEntry in $revState.vector.Values) {
                    $revSlotReport.restoreVectors+=([ordered]@{parameter=$revEntry.info.name;association=$revEntry.info.association;layer=$revEntry.info.index;value=$revEntry.value;origin=$revEntry.origin})
                }
                # Skin references are evidence only. Do not place their texture
                # or vector inputs in the replacement planner's slot tables.
                continue
            }
            foreach($revEntry in $revState.texture.Values) {
                $revTexturePath=Get-RevPackage $revEntry.value
                $revKind=Get-RevTextureKind $revEntry.info.name $revTexturePath
                $revAllowHairSource=$revKind -eq 'colour'
                if((Test-RevProtected $revTexturePath -AllowHairTexture:$revAllowHairSource) -or (Test-RevProtected $revEntry.info.name)) { $revKind='protected' }
                $revTexReport=[ordered]@{parameter=$revEntry.info.name;association=$revEntry.info.association;layer=$revEntry.info.index;source=(Get-RevObjectPath $revTexturePath);origin=$revEntry.origin;inheritedFrom=$revEntry.source;kind=$revKind;png=$null}
                if($revKind -eq 'colour' -and $revTexturePath) {
                    $revImage=Export-RevTexture $revTexturePath
                    if($revImage) { $revTexReport.png=$revImage.png }
                } elseif($revKind -eq 'unknown') { Add-RevIssue 'texture_semantics_unknown' "$revMaterialPath|$($revEntry.info.key)" ([string]$revTexturePath) }
                $revSlotReport.textures+=$revTexReport
            }
            foreach($revEntry in $revState.vector.Values) {
                $revName=$revEntry.info.name
                $revKind='other'
                if($revName -match '(?i)tint|colou?r' -and $revName -notmatch '(?i)normal|rough|metal|mask|(?:^|_)CH(?:$|_)|channel|sss|subsurface|scatter|occlusion|(?:^|[ _])AO(?:$|[ _])') { $revKind='colour' }
                $revSlotReport.vectors+=([ordered]@{parameter=$revName;association=$revEntry.info.association;layer=$revEntry.info.index;value=$revEntry.value;origin=$revEntry.origin;inheritedFrom=$revEntry.source;kind=$revKind})
            }
            foreach($revEntry in $revState.scalar.Values) { $revSlotReport.scalars+=([ordered]@{parameter=$revEntry.info.name;association=$revEntry.info.association;layer=$revEntry.info.index;value=$revEntry.value}) }
            $revSlotReport.status='inspected'
            $revSlotReport.masterDefaultsEnumerated=$revState.masterDefaultsEnumerated
        }
    }
} finally {
    $revManifest=Join-Path $revOutput 'extraction-manifest.json'
    [IO.File]::WriteAllText($revManifest,($revReport|ConvertTo-Json -Depth 100),[Text.UTF8Encoding]::new($false))
    $revProvider.Dispose()
    Write-Host "Manifest: $revManifest"
}
