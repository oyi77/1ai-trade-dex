# PolyEdge Engine Restart - Windows PowerShell

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$projectDir = Split-Path -Parent $scriptDir

Set-Location $projectDir

Write-Host "=== PolyEdge Engine Restart (Windows) ===" -ForegroundColor Cyan
& "$scriptDir\stop.ps1"
Start-Sleep -Seconds 3
& "$scriptDir\start.ps1"