$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonPath = Join-Path $repoRoot '.venv\Scripts\python.exe'
$playwrightCmd = Join-Path $repoRoot 'node_modules\.bin\playwright.cmd'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Repository .venv is required. Install requirements.txt first.' }
if (-not (Test-Path -LiteralPath $playwrightCmd)) { throw 'Playwright is not installed. Run npm install first.' }

$browserCache = if ($env:PLAYWRIGHT_BROWSERS_PATH) { $env:PLAYWRIGHT_BROWSERS_PATH } else { Join-Path $env:LOCALAPPDATA 'ms-playwright' }
$chromium = Get-ChildItem -LiteralPath $browserCache -Directory -Filter 'chromium-*' -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $chromium) { throw 'Playwright Chromium is missing. Run npx playwright install chromium.' }

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("mirror-browser-qa-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tempRoot | Out-Null
$databasePath = Join-Path $tempRoot 'browser-qa.sqlite3'
$backendOut = Join-Path $tempRoot 'backend.log'
$backendErr = Join-Path $tempRoot 'backend-error.log'
$frontendOut = Join-Path $tempRoot 'frontend.log'
$frontendErr = Join-Path $tempRoot 'frontend-error.log'
$backend = $null
$frontend = $null
$backendPort = $null
$frontendPort = $null
$runFailure = $null
$cleanupWarnings = [System.Collections.Generic.List[string]]::new()
$previousDb = $env:MIRROR_DATABASE_PATH
$previousCors = $env:MIRROR_CORS_ORIGINS
$previousFront = $env:MIRROR_E2E_FRONTEND_URL
$previousBack = $env:MIRROR_E2E_BACKEND_URL

function Get-ListeningProcessIds([int]$Port) {
    $netstat = Join-Path $env:SystemRoot 'System32\netstat.exe'
    foreach ($line in (& $netstat -ano -p tcp 2>$null)) {
        if ($line -match ("^\s*TCP\s+\S+:" + $Port + "\s+\S+\s+LISTENING\s+(\d+)\s*$")) {
            [int]$Matches[1]
        }
    }
}

function Stop-ServiceTree([System.Diagnostics.Process]$Process, [int]$Port, [string]$Name) {
    if (-not $Process) {
        $unexpectedListeners = @(Get-ListeningProcessIds $Port | Sort-Object -Unique)
        if ($unexpectedListeners.Count -gt 0) {
            $cleanupWarnings.Add("Port $Port has a listener, but this run has no process handle to identify it; it was left running.")
            return $false
        }
        return $true
    }
    if ($Process) {
        $Process.Refresh()
        if (-not $Process.HasExited) {
            $taskkill = Join-Path $env:SystemRoot 'System32\taskkill.exe'
            & $taskkill /PID $Process.Id /T /F *> $null
            try { $Process.WaitForExit(10000) } catch { }
            $Process.Refresh()
            if (-not $Process.HasExited) {
                $cleanupWarnings.Add("$Name process $($Process.Id) did not exit after its process tree was stopped.")
            }
        }
        $Process.Dispose()
    }

    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    do {
        $listenerIds = @(Get-ListeningProcessIds $Port | Sort-Object -Unique)
        if ($listenerIds.Count -eq 0) { return $true }
        foreach ($listenerId in $listenerIds) {
            $listener = Get-Process -Id $listenerId -ErrorAction SilentlyContinue
            if (-not $listener) { continue }
            $listenerPath = $null
            try { $listenerPath = $listener.Path } catch { }
            if (-not $listenerPath -or
                [System.IO.Path]::GetFullPath($listenerPath) -ine [System.IO.Path]::GetFullPath($pythonPath)) {
                $cleanupWarnings.Add("Port $Port is still owned by an unrelated or unidentified process; it was left running.")
                return $false
            }
            Stop-Process -Id $listenerId -Force -ErrorAction SilentlyContinue
            try { Wait-Process -Id $listenerId -Timeout 5 -ErrorAction SilentlyContinue } catch { }
        }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $deadline)

    $cleanupWarnings.Add("$Name listener on port $Port did not stop; its temporary files will be retained.")
    return $false
}

function Wait-LogFilesReleased([string[]]$Paths) {
    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    do {
        $allReleased = $true
        foreach ($path in $Paths) {
            if (-not (Test-Path -LiteralPath $path)) { continue }
            $stream = $null
            try {
                $stream = [System.IO.File]::Open($path, [System.IO.FileMode]::Open,
                    [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
            } catch [System.IO.IOException] {
                $allReleased = $false
            } finally {
                if ($stream) { $stream.Dispose() }
            }
        }
        if ($allReleased) { return $true }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $deadline)
    return $false
}

try {
    $findFreePort = {
        $tcpListener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
        try { $tcpListener.Start(); return ([System.Net.IPEndPoint]$tcpListener.LocalEndpoint).Port }
        finally { $tcpListener.Stop() }
    }
    $backendPort = & $findFreePort
    $frontendPort = & $findFreePort
    while ($frontendPort -eq $backendPort) { $frontendPort = & $findFreePort }
    $backendUrl = "http://127.0.0.1:$backendPort"
    $frontendUrl = "http://127.0.0.1:$frontendPort"
    $env:MIRROR_DATABASE_PATH = $databasePath
    $env:MIRROR_CORS_ORIGINS = $frontendUrl
    $env:MIRROR_E2E_FRONTEND_URL = $frontendUrl
    $env:MIRROR_E2E_BACKEND_URL = $backendUrl
    $backend = Start-Process -FilePath $pythonPath -ArgumentList @('-m','uvicorn','backend.ai_app:app','--host','127.0.0.1','--port',[string]$backendPort) -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $backendOut -RedirectStandardError $backendErr
    $frontend = Start-Process -FilePath $pythonPath -ArgumentList @('-m','http.server',[string]$frontendPort,'--directory','frontened') -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $frontendOut -RedirectStandardError $frontendErr

    $ready = $false
    $lastReadinessError = $null
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        try {
            $healthResponse = Invoke-WebRequest -UseBasicParsing -Uri "$backendUrl/health" -TimeoutSec 2
            $front = Invoke-WebRequest -UseBasicParsing -Uri "$frontendUrl/" -TimeoutSec 2
            if ([int]$healthResponse.StatusCode -eq 200 -and [int]$front.StatusCode -eq 200) { $ready = $true; break }
            $lastReadinessError = "Health HTTP $($healthResponse.StatusCode); frontend HTTP $($front.StatusCode)."
        } catch { $lastReadinessError = $_.Exception.Message; Start-Sleep -Milliseconds 500 }
        if (($backend -and $backend.HasExited) -or ($frontend -and $frontend.HasExited)) { break }
    }
    if (-not $ready) {
        Get-Content $backendErr,$frontendErr -ErrorAction SilentlyContinue
        Get-Content $backendOut,$frontendOut -ErrorAction SilentlyContinue
        throw "MIRROR frontend/backend did not become ready ($lastReadinessError)."
    }

    Write-Output "Browser QA services ready on temporary ports (frontend $frontendPort, backend $backendPort)."
    & $playwrightCmd test
    if ($LASTEXITCODE -ne 0) { throw "Playwright exited with code $LASTEXITCODE. Failure screenshots and traces are in test-results/browser." }
} catch {
    $runFailure = $_
} finally {
    $frontStopped = $true
    $backendStopped = $true
    try { if ($frontendPort) { $frontStopped = Stop-ServiceTree $frontend $frontendPort 'Frontend' } }
    catch { $frontStopped = $false; $cleanupWarnings.Add("Frontend cleanup failed: $($_.Exception.Message)") }
    try { if ($backendPort) { $backendStopped = Stop-ServiceTree $backend $backendPort 'Backend' } }
    catch { $backendStopped = $false; $cleanupWarnings.Add("Backend cleanup failed: $($_.Exception.Message)") }

    if ($null -eq $previousDb) { Remove-Item Env:MIRROR_DATABASE_PATH -ErrorAction SilentlyContinue } else { $env:MIRROR_DATABASE_PATH = $previousDb }
    if ($null -eq $previousCors) { Remove-Item Env:MIRROR_CORS_ORIGINS -ErrorAction SilentlyContinue } else { $env:MIRROR_CORS_ORIGINS = $previousCors }
    if ($null -eq $previousFront) { Remove-Item Env:MIRROR_E2E_FRONTEND_URL -ErrorAction SilentlyContinue } else { $env:MIRROR_E2E_FRONTEND_URL = $previousFront }
    if ($null -eq $previousBack) { Remove-Item Env:MIRROR_E2E_BACKEND_URL -ErrorAction SilentlyContinue } else { $env:MIRROR_E2E_BACKEND_URL = $previousBack }

    # Start-Process owns the redirected handles; dispose its process handles only
    # after exit, then verify the log files can be opened exclusively.
    $logsReleased = $false
    try { $logsReleased = Wait-LogFilesReleased @($backendOut,$backendErr,$frontendOut,$frontendErr) }
    catch { $cleanupWarnings.Add("Could not verify service log handles: $($_.Exception.Message)") }
    if (-not $logsReleased) {
        $cleanupWarnings.Add("One or more service logs remain locked; temporary files were retained at $tempRoot.")
    }
    if ($frontStopped -and $backendStopped -and $logsReleased) {
        $resolvedTemp = (Resolve-Path -LiteralPath $tempRoot -ErrorAction SilentlyContinue).Path
        $tempPrefix = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd('\') + '\'
        $leaf = if ($resolvedTemp) { Split-Path -Leaf $resolvedTemp } else { '' }
        if (($resolvedTemp) -and ($resolvedTemp.StartsWith($tempPrefix,[System.StringComparison]::OrdinalIgnoreCase)) -and
            ($leaf -match '^mirror-browser-qa-[0-9a-f]{32}$')) {
            Remove-Item -LiteralPath $resolvedTemp -Recurse -Force
        } else {
            $cleanupWarnings.Add("Temporary directory path failed the safety check and was retained: $tempRoot")
        }
    }
}

foreach ($warning in $cleanupWarnings) { Write-Warning $warning }
if ($runFailure) { throw $runFailure }
if ($cleanupWarnings.Count -gt 0) { throw 'Browser test cleanup was incomplete; review the warnings and retained temporary files.' }
