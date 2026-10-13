param([Parameter(Mandatory=$true)][string]$ExecutablePath)
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath('DesktopDirectory')
$programs = Join-Path ([Environment]::GetFolderPath('Programs')) 'Dify Local'
New-Item -ItemType Directory -Path $programs -Force | Out-Null
function Add-Shortcut([string]$path, [string]$arguments) {
    $shortcut = $shell.CreateShortcut($path)
    $shortcut.TargetPath = $ExecutablePath
    $shortcut.Arguments = $arguments
    $shortcut.WorkingDirectory = Split-Path -Parent $ExecutablePath
    $shortcut.Description = 'Dify 1.17.1 local application (WSL2 / Docker)'
    $shortcut.Save()
}
Add-Shortcut (Join-Path $desktop 'Dify.lnk') '--start'
Add-Shortcut (Join-Path $programs 'Dify Start.lnk') '--start'
Add-Shortcut (Join-Path $programs 'Dify Stop.lnk') '--stop'
Add-Shortcut (Join-Path $programs 'Dify Console.lnk') '--open'
Add-Shortcut (Join-Path $programs 'Dify Manager.lnk') ''
Write-Output 'Desktop and Start Menu Dify shortcuts created.'