# PolyEdge Engine Startup - Windows PowerShell

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$projectDir = Split-Path -Parent $scriptDir

Set-Location $projectDir

Write-Host "=== PolyEdge Engine Start (Windows) ===" -ForegroundColor Cyan

if (Get-Command pm2 -ErrorAction SilentlyContinue) {
    Write-Host "[PM2] Starting all services..." -ForegroundColor Green
    pm2 start ecosystem.config.js
    pm2 save
    pm2 list
}
else {
    Write-Host "[WARN] PM2 not found. Install: npm install -g pm2" -ForegroundColor Yellow
    Write-Host "[INFO] Starting services manually..." -ForegroundColor Yellow

    if (-not (Test-Path "venv")) {
        Write-Host "[INFO] Creating Python venv..." -ForegroundColor Green
        python -m venv venv
    }

    .\venv\Scripts\Activate.ps1

    if (-not (Test-Path ".omc\logs")) {
        New-Item -ItemType Directory -Path ".omc\logs" -Force | Out-Null
    }

    Write-Host "[INFO] Starting polyedge-api..." -ForegroundColor Green
    $env:DISABLE_TRADING_SCHEDULER = "true"
    $env:PYTHONPATH = $projectDir
    Start-Process -FilePath "python" -ArgumentList "run.py" -NoNewWindow -RedirectStandardOutput ".omc\logs\polyedge-api-out.log" -RedirectStandardError ".omc\logs\polyedge-api-error.log"

    Write-Host "[INFO] Starting polyedge-bot..." -ForegroundColor Green
    $env:PYTHONPATH = $projectDir
    Start-Process -FilePath "python" -ArgumentList "-m", "backend.core.orchestrator" -NoNewWindow -RedirectStandardOutput ".omc\logs\polyedge-bot-out.log" -RedirectStandardError ".omc\logs\polyedge-bot-error.log"

    if (Test-Path "frontend") {
        if (-not (Test-Path "frontend\node_modules")) {
            Write-Host "[INFO] Installing frontend dependencies..." -ForegroundColor Green
            & npm --prefix "frontend" install
        }

        if (-not (Test-Path "frontend\dist")) {
            Write-Host "[INFO] Building frontend..." -ForegroundColor Green
            & npm --prefix "frontend" run build
        }

        Write-Host "[INFO] Starting polyedge-frontend..." -ForegroundColor Green
        $frontendProc = Start-Process -FilePath "npm" -ArgumentList "run", "preview", "--", "--port", "5174" -NoNewWindow -WorkingDirectory "frontend" -RedirectStandardOutput ".omc\logs\polyedge-frontend-out.log" -RedirectStandardError ".omc\logs\polyedge-frontend-error.log"
    }

    Write-Host "[DONE] All services started." -ForegroundColor Green
}