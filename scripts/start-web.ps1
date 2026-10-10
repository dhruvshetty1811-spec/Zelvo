param([switch]$NoBuild)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskPython = Join-Path $taskRoot '.venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $taskPython)) { throw 'Run scripts/bootstrap.ps1 and scripts/uv.ps1 sync first.' }
Push-Location $taskRoot
try {
    if (!$NoBuild) {
        Push-Location (Join-Path $taskRoot 'frontend')
        try {
            if (!(Test-Path -LiteralPath 'node_modules')) {
                & npm.cmd ci --no-audit --no-fund
                if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
            }
            & npm.cmd run build
            if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
        } finally { Pop-Location }
    }
    if (!(Test-Path -LiteralPath 'frontend/dist/index.html')) { throw 'Build the frontend before using -NoBuild.' }
    Write-Host 'ZELVO: http://127.0.0.1:8000  (Ctrl+C to stop)'
    & $taskPython -m zelvo.api
} finally { Pop-Location }
