# run_optimizer.ps1
$ErrorActionPreference = "Stop"

Write-Host "Initializing Fidelity Optimizer..." -ForegroundColor Cyan

# 1. Activate the virtual environment
$VenvActivate = Join-Path $PSScriptRoot "venv\Scripts\Activate.ps1"
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

# 2. Run the application
try {
    Write-Host "Generating full portfolio analysis report..." -ForegroundColor Cyan
    python portfolio_analyzer.py
}
catch {
    Write-Host "An error occurred while running the optimizer:" -ForegroundColor Red
    Write-Host $_.Exception.Message
    Pause
}
