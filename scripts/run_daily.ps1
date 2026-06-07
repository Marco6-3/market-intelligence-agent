$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$LogDir = Join-Path $ProjectRoot "logs"
$WatchlistPath = Join-Path $ProjectRoot "watchlist.yaml"
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
}

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$LogPath = Join-Path $LogDir "daily-run-$Timestamp.log"

if (-not (Test-Path $WatchlistPath)) {
    "Missing watchlist.yaml. Copy watchlist.example.yaml to watchlist.yaml and edit it first." |
        Tee-Object -FilePath $LogPath
    exit 1
}

if (Test-Path $VenvPython) {
    $Python = $VenvPython
} else {
    $Python = "python"
}

Push-Location $ProjectRoot
try {
    "Started market intelligence run at $(Get-Date -Format o)" | Tee-Object -FilePath $LogPath
    & $Python -m market_agent run --watchlist $WatchlistPath 2>&1 |
        Tee-Object -FilePath $LogPath -Append
    $ExitCode = $LASTEXITCODE
    "Finished at $(Get-Date -Format o) with exit code $ExitCode" |
        Tee-Object -FilePath $LogPath -Append
    exit $ExitCode
} finally {
    Pop-Location
}
