# run_optimizer.ps1
$ErrorActionPreference = "Stop"

Write-Host "Initializing Fidelity Optimizer..." -ForegroundColor Cyan

# 1. Activate the virtual environment
$VenvActivate = Join-Path $PSScriptRoot "..\venv\Scripts\Activate.ps1"
if (Test-Path $VenvActivate) {
    . $VenvActivate
    Write-Host "Virtual environment activated." -ForegroundColor Green
}
else {
    Write-Host "Error: Virtual environment not found at $VenvActivate" -ForegroundColor Red
    Write-Host "Please run 'python -m venv venv' and install requirements first." -ForegroundColor Yellow
    Pause
    exit
}

# 2. Setup Cache
$cacheDir = Join-Path $PSScriptRoot "..\Drop_Financial_Info_Here\.cache"
if (-Not (Test-Path $cacheDir)) {
    New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null
}

# 3. Run the application
try {
    Write-Host "`n[!] CRITICAL REMINDER: Ensure you have JUST downloaded a fresh Portfolio_Positions.csv from Fidelity." -ForegroundColor Yellow
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
