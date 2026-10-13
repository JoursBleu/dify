param(
    [string]$OutputDirectory = "$env:USERPROFILE\Downloads",
    [string]$OutputName = 'Dify-Setup-1.17.1-Windows-x64-1.0.8.exe'
)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$build = Join-Path $root 'build'
New-Item -ItemType Directory -Path $build -Force | Out-Null
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$plugin = Join-Path $root 'payload\plugins\amdgpucloud.difypkg'
$compose = Join-Path $root 'payload\tools\docker-compose-linux-x86_64'
foreach ($inputFile in @($plugin, $compose)) {
    if (-not (Test-Path -LiteralPath $inputFile -PathType Leaf)) {
        throw 'Generated payload is missing. Run prepare_payload.sh with the reviewed .difypkg before building.'
    }
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $plugin).Hash.ToLowerInvariant() -ne
    '66f7bd9c8e15136a57228088daa647953d0a373a430d85ee11abff9c5bc5e845') {
    throw 'Plugin package does not match this source release.'
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $compose).Hash.ToLowerInvariant() -ne
    '40343e21ca777173e69cff5dbafeb37c6f81f3b0d57d9e597f036e95eb63e76a') {
    throw 'Docker Compose binary does not match the pinned upstream release.'
}
$payload = Join-Path $build 'payload.zip'
if (Test-Path $payload) { Remove-Item $payload }
[IO.Compression.ZipFile]::CreateFromDirectory((Join-Path $root 'payload'), $payload,
    [IO.Compression.CompressionLevel]::Optimal, $false)
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