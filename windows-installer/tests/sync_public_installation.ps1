param(
    [Parameter(Mandatory=$true)][string]$ExecutablePath
)
$ErrorActionPreference = 'Stop'
$source = Split-Path -Parent $PSScriptRoot
$installed = Join-Path $env:LOCALAPPDATA 'Programs\DifyLocal'
$targetExe = Join-Path $installed 'Dify.exe'
$settings = Join-Path $installed 'settings.xml'
$checksumFile = "$ExecutablePath.sha256"
if (-not (Test-Path -LiteralPath $checksumFile -PathType Leaf)) {
    throw 'A reviewed EXE checksum sidecar is required for an explicit public-file update.'
}
$expectedExe = (Get-Content -LiteralPath $checksumFile -Raw).Split(' ')[0].Trim()
if ($expectedExe -notmatch '^[a-f0-9]{64}$') { throw 'Invalid EXE checksum sidecar.' }
$expectedPlugin = '66f7bd9c8e15136a57228088daa647953d0a373a430d85ee11abff9c5bc5e845'
if (-not (Test-Path -LiteralPath $targetExe -PathType Leaf) -or
    -not (Test-Path -LiteralPath $settings -PathType Leaf)) {
    throw 'Existing installer-owned manager and settings are required; no application installation performed.'
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $ExecutablePath).Hash.ToLowerInvariant() -ne $expectedExe) {
    throw 'The replacement EXE does not match the reviewed delivery.'
}
$plugin = Join-Path $source 'payload\plugins\amdgpucloud.difypkg'
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $plugin).Hash.ToLowerInvariant() -ne $expectedPlugin) {
    throw 'The replacement plugin does not match the reviewed delivery.'
}
$running = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $targetExe })
if ($running.Count -gt 0) {
    throw 'The installed desktop manager is running; close that window before updating public files.'
}
$settingsBefore = (Get-FileHash -Algorithm SHA256 -LiteralPath $settings).Hash
$guideName = [string][char]0x5B89 + [char]0x88C5 + [char]0x8BF4 + [char]0x660E + '.txt'
$publicFiles = @(
    'plugins\amdgpucloud.difypkg', 'plugins\INSTALL_windows_zh_Hans.txt',
    'plugins\README_zh_Hans.md', 'plugins\PRIVACY.md',
    'windows\runtime.sh', 'windows\installer.manifest',
    $guideName, 'THIRD_PARTY_NOTICES.txt'
)
foreach ($relative in $publicFiles) {
    $from = Join-Path (Join-Path $source 'payload') $relative
    if (-not (Test-Path -LiteralPath $from -PathType Leaf)) { throw "Public source file missing: $relative" }
}
$backup = Join-Path $env:LOCALAPPDATA ('Programs\DifyLocal-backups\publisher-0.0.8-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $backup | Out-Null
Copy-Item -LiteralPath $targetExe -Destination (Join-Path $backup 'Dify-before-1.0.8.exe')
$previousBranded = Join-Path $installed 'payload\plugins\amdgpucloud.difypkg'
if (Test-Path -LiteralPath $previousBranded -PathType Leaf) {
    Copy-Item -LiteralPath $previousBranded -Destination (Join-Path $backup 'previous-amdgpucloud.difypkg')
}
$oldPackage = Join-Path $installed 'payload\plugins\radeon_cloud.difypkg'
if (Test-Path -LiteralPath $oldPackage -PathType Leaf) {
    Move-Item -LiteralPath $oldPackage -Destination (Join-Path $backup 'previous-plugin-0.0.6.difypkg')
}
foreach ($relative in $publicFiles) {
    $from = Join-Path (Join-Path $source 'payload') $relative
    $to = Join-Path (Join-Path $installed 'payload') $relative
    if (-not (Test-Path -LiteralPath $from -PathType Leaf)) { throw "Public source file missing: $relative" }
    Copy-Item -LiteralPath $from -Destination $to -Force
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $from).Hash -ne
        (Get-FileHash -Algorithm SHA256 -LiteralPath $to).Hash) { throw "Public file verification failed: $relative" }
}
Copy-Item -LiteralPath $ExecutablePath -Destination $targetExe -Force
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $settings).Hash -ne $settingsBefore) {
    throw 'Unexpected settings change during public-file update.'
}
if ((Get-Item -LiteralPath $targetExe).VersionInfo.FileVersion -ne '1.0.8.0') {
    throw 'Installed manager version verification failed.'
}
Write-Output 'PASS: idle desktop manager 1.0.8 and public payload synchronized; old package archived outside active payload.'
Write-Output 'Settings unchanged. No Linux services, credentials, signature policy or databases modified.'
Write-Output "Previous public artifacts: $backup"