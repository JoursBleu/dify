param(
    [Parameter(Mandatory=$true)][string]$ExecutablePath,
    [int]$RunningDifyPort = 0
)
$ErrorActionPreference = 'Stop'
$directory = Join-Path $env:TEMP ('dify-bridge-report-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $directory | Out-Null
foreach ($mode in @('--self-test', '--wsl-self-test')) {
    $report = Join-Path $directory ($mode.TrimStart('-') + '.txt')
    $process = Start-Process -FilePath $ExecutablePath -ArgumentList $mode,$report -Wait -PassThru
    if (-not (Test-Path $report)) { throw "Test report missing: $mode" }
    $text = Get-Content -Raw -Encoding UTF8 $report
    Write-Output $text
    if ($process.ExitCode -ne 0 -or -not $text.StartsWith('PASS:')) {
        throw "Native Windows executable test failed: $mode"
    }
}
if ($RunningDifyPort -gt 0) {
    $report = Join-Path $directory 'http-self-test.txt'
    $process = Start-Process -FilePath $ExecutablePath -ArgumentList `
        '--http-self-test',$report,$RunningDifyPort -Wait -PassThru
    if (-not (Test-Path $report)) { throw 'Windows HTTP regression report is missing.' }
    $text = Get-Content -Raw -Encoding UTF8 $report
    Write-Output $text
    if ($process.ExitCode -ne 0 -or -not $text.StartsWith('PASS:')) {
        throw 'Exact Windows .NET Dify HTTP regression failed.'
    }
}
Write-Output "Reports: $directory"