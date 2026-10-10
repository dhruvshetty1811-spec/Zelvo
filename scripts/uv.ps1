$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$env:UV_CACHE_DIR = Join-Path $taskRoot '.cache\uv'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $taskRoot '.runtime\python'
$env:UV_PYTHON_BIN_DIR = Join-Path $taskRoot '.tools\python-bin'
$env:UV_HTTP_TIMEOUT = '300'
$taskCertBundle = Join-Path $taskRoot '.tools\ca-bundle.pem'
if (Test-Path -LiteralPath $taskCertBundle) { $env:SSL_CERT_FILE = $taskCertBundle }
Push-Location $taskRoot
try {
    & (Join-Path $taskRoot '.tools\uv\uv.exe') @args
    $taskExit = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $taskExit
