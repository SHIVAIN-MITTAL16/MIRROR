$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonPath = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Repository virtual environment was not found. Create .venv and install requirements.txt first.'
}

$backendLog = Join-Path $env:TEMP 'mirror-backend.log'
$backendErrorLog = Join-Path $env:TEMP 'mirror-backend-error.log'
$frontendLog = Join-Path $env:TEMP 'mirror-frontend.log'
$frontendErrorLog = Join-Path $env:TEMP 'mirror-frontend-error.log'
$backend = Start-Process -FilePath $pythonPath `
    -ArgumentList @('-m', 'uvicorn', 'backend.ai_app:app', '--host', '127.0.0.1', '--port', '8002') `
    -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $backendLog -RedirectStandardError $backendErrorLog
$frontend = Start-Process -FilePath $pythonPath `
    -ArgumentList @('-m', 'http.server', '5501', '--directory', 'frontened') `
    -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $frontendLog -RedirectStandardError $frontendErrorLog

Write-Output "Backend PID: $($backend.Id)"
Write-Output "Frontend PID: $($frontend.Id)"
Write-Output 'Open http://127.0.0.1:5501'
Write-Output "Logs: $backendLog, $backendErrorLog, $frontendLog, $frontendErrorLog"
