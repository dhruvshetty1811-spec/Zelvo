$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskUv = Join-Path $taskRoot '.tools\uv\uv.exe'
if (-not (Test-Path -LiteralPath $taskUv)) {
    & node --use-system-ca (Join-Path $PSScriptRoot 'download-uv.mjs')
    if ($LASTEXITCODE -ne 0) { throw 'Could not download the project-local package manager.' }
    Expand-Archive -LiteralPath (Join-Path $taskRoot '.tools\uv.zip') -DestinationPath (Join-Path $taskRoot '.tools\uv') -Force
}
& (Join-Path $PSScriptRoot 'uv.ps1') python install 3.12.12 --no-bin --no-registry
if ($LASTEXITCODE -ne 0) { throw 'Could not install project-local Python.' }
& (Join-Path $PSScriptRoot 'uv.ps1') sync --python 3.12.12
if ($LASTEXITCODE -ne 0) { throw 'Could not synchronise the project environment.' }
