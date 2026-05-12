# PolyEdge Engine Stop - Windows PowerShell

$ErrorActionPreference = "Continue"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$projectDir = Split-Path -Parent $scriptDir

Set-Location $projectDir

Write-Host "=== PolyEdge Engine Stop (Windows) ===" -ForegroundColor Cyan

if (Get-Command pm2 -ErrorAction SilentlyContinue) {
    Write-Host "[PM2] Stopping all services..." -ForegroundColor Green
    pm2 stop ecosystem.config.js
    Write-Host "[PM2] All services stopped." -ForegroundColor Green
    pm2 list
}
else {
    Write-Host "[INFO] Stopping Python processes..." -ForegroundColor Yellow
    Get-Process python | Where-Object { $_.Path -like "*venv*" } | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Host "[DONE] All processes stopped." -ForegroundColor Green
}