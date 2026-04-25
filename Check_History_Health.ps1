# Check_History_Health.ps1
# Automates history consolidation and range checking for repo hygiene.
$ErrorActionPreference = "Stop"

$Host.UI.RawUI.WindowTitle = "History Health Check"
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host "   Portfolio History Health & Hygiene Check" -ForegroundColor Cyan
Write-Host "====================================================" -ForegroundColor Cyan

# 1. Setup paths
$PSScriptRoot = Get-Location
$VenvRoot = Join-Path $PSScriptRoot "venv"
$VenvActivate = Join-Path $VenvRoot "Scripts\Activate.ps1"

# 2. Activate environment
if ($env:VIRTUAL_ENV) {
    # Already active
}
elseif (Test-Path $VenvActivate) {
    . $VenvActivate
}
else {
    Write-Host "[!] Virtual environment not found. Please run Portfolio_Optimizer.ps1 first to initialize." -ForegroundColor Red
    Pause
    exit
}

# 3. Perform Consolidation (Automated Hygiene)
Write-Host "`n[1/2] Consolidating history files..." -ForegroundColor Cyan
python src\portfolio_analyzer.py --consolidate

# 4. Check Coverage Range
Write-Host "[2/2] Assessing history coverage range..." -ForegroundColor Cyan
python src\portfolio_analyzer.py --check-history

Write-Host "----------------------------------------------------"
Write-Host "Hygiene check complete." -ForegroundColor Green
Write-Host "You can now run Portfolio_Optimizer.ps1 with clean data."
Write-Host "----------------------------------------------------"
Pause
