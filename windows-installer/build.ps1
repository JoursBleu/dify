param(
    [string]$OutputDirectory = "$env:USERPROFILE\Downloads",
    [string]$OutputName = 'Dify-Setup-1.17.1-Windows-x64-1.0.10.exe'
)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$payloadRoot = Join-Path $root 'payload'
function Assert-PayloadFile([string]$relative) {
    $path = Join-Path $payloadRoot $relative.Replace('/', '\')
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw 'Generated payload is incomplete. Run prepare_payload.sh before building.'
    }
    $item = Get-Item -LiteralPath $path -Force
    while ($null -ne $item) {
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw 'Payload links are not permitted.'
        }
        if ($item.FullName -eq $payloadRoot) { break }
        $item = Get-Item -LiteralPath (Split-Path -Parent $item.FullName) -Force
    }
    return $path
}
$build = Join-Path $root 'build'
New-Item -ItemType Directory -Path $build -Force | Out-Null
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$pin = Assert-PayloadFile '.upstream-commit'
if ([IO.File]::ReadAllText($pin).TrimEnd([char[]]"`r`n") -ne
    '8387590ace4a094de812b7847fc6a4c3a27cd52b') {
    throw 'Prepare the exact Dify 1.17.1 release, not the feature branch or main checkout.'
}
$manifest = Assert-PayloadFile '.prepared.sha256'
$files = @{}
foreach ($line in Get-Content -LiteralPath $manifest -Encoding UTF8) {
    if ($line -notmatch '\A([a-f0-9]{64})  (.+)\z') { throw 'Invalid prepared payload receipt.' }
    $digest = $Matches[1]
    $relative = $Matches[2]
    if ($relative -match '[\\:\x00-\x1f*?"<>|]' -or
        @($relative.Split('/') | Where-Object { $_ -in @('', '.', '..', '.env') }).Count -gt 0 -or
        $relative -notmatch '\A(LICENSE|docker/.+|api-compat/(prepare_overlay|model_catalog|amdtokenfactory_remote)\.py|plugins/(AMDTokenFactory-0\.0\.10\.difypkg|INSTALL_windows_zh_Hans\.txt|README_zh_Hans\.md|PRIVACY\.md)|tools/docker-compose-linux-x86_64)\z' -or
        $files.ContainsKey($relative)) { throw 'Unsafe or duplicated prepared payload path.' }
    $inputFile = Assert-PayloadFile $relative
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $inputFile).Hash.ToLowerInvariant() -ne $digest) {
        throw 'Prepared source has changed; rerun prepare_payload.sh instead of editing generated files.'
    }
    $files[$relative] = $digest
}
foreach ($relative in @('LICENSE', 'docker/docker-compose.yaml', 'docker/.env.example',
    'api-compat/prepare_overlay.py', 'api-compat/model_catalog.py', 'api-compat/amdtokenfactory_remote.py',
    'plugins/AMDTokenFactory-0.0.10.difypkg', 'plugins/INSTALL_windows_zh_Hans.txt',
    'plugins/README_zh_Hans.md', 'plugins/PRIVACY.md', 'tools/docker-compose-linux-x86_64')) {
    if (-not $files.ContainsKey($relative)) { throw 'Prepared payload receipt is incomplete.' }
}
$plugin = Assert-PayloadFile 'plugins/AMDTokenFactory-0.0.10.difypkg'
$compose = Assert-PayloadFile 'tools/docker-compose-linux-x86_64'
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $plugin).Hash.ToLowerInvariant() -ne
    'a52e0e67f0c152d2d458ac77e4ac4fc189bd69e2d29d81f07b3f2d3555ebb528') {
    throw 'Plugin package does not match this source release.'
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $compose).Hash.ToLowerInvariant() -ne
    '40343e21ca777173e69cff5dbafeb37c6f81f3b0d57d9e597f036e95eb63e76a') {
    throw 'Docker Compose binary does not match the pinned upstream release.'
}
# Embed only reviewed/generated inputs and the explicit bootstrap assets. Stray
# .env files, images, caches or obsolete packages in the worktree are never read.
$guideName = [string][char]0x5B89 + [char]0x88C5 + [char]0x8BF4 + [char]0x660E + '.txt'
foreach ($relative in @('.upstream-commit', '.prepared.sha256', 'THIRD_PARTY_NOTICES.txt', $guideName,
    'tools/COMPOSE-LICENSE.txt', 'windows/runtime.sh', 'windows/local.override.yaml',
    'windows/prepare-remote-models.sh', 'windows/remote-models.override.yaml',
    'windows/shortcuts.ps1', 'windows/installer.manifest')) {
    $inputFile = Assert-PayloadFile $relative
    $files[$relative] = (Get-FileHash -Algorithm SHA256 -LiteralPath $inputFile).Hash.ToLowerInvariant()
}
$payload = Join-Path $build 'payload.zip'
if (Test-Path $payload) { Remove-Item $payload }
$archive = [IO.Compression.ZipFile]::Open($payload, [IO.Compression.ZipArchiveMode]::Create)
try {
    foreach ($relative in @($files.Keys | Sort-Object)) {
        [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive,
            (Assert-PayloadFile $relative), $relative, [IO.Compression.CompressionLevel]::Optimal) | Out-Null
    }
} finally { $archive.Dispose() }
# Verify the packed bytes against the frozen input digests, not files reopened
# after a concurrent payload preparation. Never compile a mixed-generation ZIP.
$archive = [IO.Compression.ZipFile]::OpenRead($payload)
try {
    if ($archive.Entries.Count -ne $files.Count) { throw 'Packed payload inventory changed.' }
    foreach ($entry in $archive.Entries) {
        $stream = $entry.Open()
        $sha = [Security.Cryptography.SHA256]::Create()
        try { $digest = [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
        finally { $sha.Dispose(); $stream.Dispose() }
        if ($files[$entry.FullName] -ne $digest) { throw 'Payload changed while packing; prepare and build again.' }
    }
} finally { $archive.Dispose() }
$compiler = "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path $compiler)) { throw '.NET Framework 4.8 compiler is unavailable.' }
$output = Join-Path $OutputDirectory $OutputName
if (Test-Path $output) { throw 'Versioned output already exists; refusing to overwrite a delivered EXE.' }
& $compiler /nologo /target:winexe /platform:x64 /optimize+ /utf8output `
    /r:System.Windows.Forms.dll /r:System.Drawing.dll /r:System.Xml.Linq.dll `
    /r:System.IO.Compression.dll /r:System.IO.Compression.FileSystem.dll `
    "/win32manifest:$(Join-Path $root 'payload\windows\installer.manifest')" `
    "/resource:$payload,dify.payload.zip" "/out:$output" (Join-Path $root 'DifySetup.cs')
if ($LASTEXITCODE -ne 0) { throw 'Windows EXE compilation failed.' }
$hash = (Get-FileHash -Algorithm SHA256 $output).Hash.ToLowerInvariant()
[IO.File]::WriteAllText("$output.sha256", "$hash  $([IO.Path]::GetFileName($output))`r`n", [Text.Encoding]::ASCII)
Write-Output "Created: $output"
Write-Output "Size: $((Get-Item $output).Length) bytes"
Write-Output "SHA-256: $hash"