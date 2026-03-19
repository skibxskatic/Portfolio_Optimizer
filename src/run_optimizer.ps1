# run_optimizer.ps1
$ErrorActionPreference = "Stop"

Write-Host "Initializing Portfolio Optimizer..." -ForegroundColor Cyan

# 1. Activate the virtual environment
$VenvRoot = Join-Path $PSScriptRoot "..\venv"
$VenvActivate = Join-Path $VenvRoot "Scripts\Activate.ps1"

if ($env:VIRTUAL_ENV) {
    Write-Host "Virtual environment already active ($env:VIRTUAL_ENV)." -ForegroundColor Green
}
elseif (Test-Path $VenvActivate) {
    . $VenvActivate
    Write-Host "Virtual environment activated." -ForegroundColor Green
}
else {
    Write-Host "Virtual environment not found. Creating one..." -ForegroundColor Yellow
    py -m venv "$VenvRoot"
    . $VenvActivate
    Write-Host "Installing dependencies..." -ForegroundColor Yellow
    pip install -r (Join-Path $PSScriptRoot "..\requirements.txt")
    pip install pandas numpy yfinance requests lxml openpyxl
    Write-Host "Virtual environment created and dependencies installed." -ForegroundColor Green
}

# 2. Setup Cache
$cacheDir = Join-Path $PSScriptRoot "..\Drop_Financial_Info_Here\.cache"
if (-Not (Test-Path $cacheDir)) {
    New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null
}

# 3. Run the application
try {
    Write-Host "`n[!] CRITICAL REMINDER: Ensure you have JUST downloaded a fresh Portfolio_Positions.csv from your brokerage." -ForegroundColor Yellow
    Write-Host "    The engine ignores 'Sells' in History files and relies entirely on your Positions file for true current quantities." -ForegroundColor Yellow
    
    Write-Host "`nPress Enter to confirm your data is fresh and begin analysis, or Ctrl+C to cancel..." -ForegroundColor White -NoNewline
    Read-Host
    
    Write-Host "`nGenerating full portfolio analysis report..." -ForegroundColor Cyan
    py src\portfolio_analyzer.py
}
catch {
    Write-Host "An error occurred while running the optimizer:" -ForegroundColor Red
    Write-Host $_.Exception.Message
    Pause
}
