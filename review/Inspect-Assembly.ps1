param([string]$Path)
$ErrorActionPreference='Stop'
$assembly=[Reflection.Assembly]::ReflectionOnlyLoadFrom((Resolve-Path -LiteralPath $Path).Path)
foreach($reference in $assembly.GetReferencedAssemblies()) { [Reflection.Assembly]::ReflectionOnlyLoad($reference.FullName) | Out-Null }
$flags=[Reflection.BindingFlags]'Public,NonPublic,Static,Instance,DeclaredOnly'
$rows=@(foreach($type in $assembly.GetTypes() | Sort-Object FullName){
    foreach($method in @($type.GetMethods($flags)) + @($type.GetConstructors($flags)) | Sort-Object MetadataToken){
        $body=$method.GetMethodBody()
        [ordered]@{type=$type.FullName;token=$method.MetadataToken;signature=$method.ToString();
            il=if($body){[Convert]::ToBase64String($body.GetILAsByteArray())}else{''};
            locals=if($body){@($body.LocalVariables | ForEach-Object {$_.ToString()})}else{@()};
            handlers=if($body){@($body.ExceptionHandlingClauses | ForEach-Object {$_.ToString()})}else{@()}}
    }
})
[ordered]@{identity=$assembly.FullName;methods=$rows;resources=@($assembly.GetManifestResourceNames())} | ConvertTo-Json -Depth 7 -Compress
