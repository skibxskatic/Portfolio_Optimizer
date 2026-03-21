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
    pip install -r (Join-Path $PSScriptRoot "..\requirements.txt") --quiet 2>$null
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
    
    # --- Investor Profile Validation ---
    $profilePath = Join-Path $PSScriptRoot "..\Drop_Financial_Info_Here\investor_profile.txt"
    $profileValid = $false
    $profileBirth = 1990
    $profileRetire = 2057

    if (Test-Path $profilePath) {
        $profileContent = Get-Content $profilePath -ErrorAction SilentlyContinue
        foreach ($line in $profileContent) {
            $line = $line.Trim()
            if ($line -match '^\s*birth_year\s*=\s*(\d{4})') { $profileBirth = [int]$Matches[1] }
            if ($line -match '^\s*retirement_year\s*=\s*(\d{4})') { $profileRetire = [int]$Matches[1] }
        }
        if ($profileBirth -eq 1990 -and $profileRetire -eq 2057) {
            Write-Host "`n[!] Investor Profile: Values match defaults (born 1990, retiring 2057)." -ForegroundColor Yellow
            Write-Host "    If these aren't your actual values, edit 'Drop_Financial_Info_Here\investor_profile.txt'." -ForegroundColor Yellow
        } else {
            $yearsOut = $profileRetire - (Get-Date).Year
            Write-Host "`n[OK] Investor Profile: Born $profileBirth, Retiring $profileRetire ($yearsOut years out)" -ForegroundColor Green
            $profileValid = $true
        }
    } else {
        Write-Host "`n[!] No investor_profile.txt found - age-aware features will use defaults (born 1990, retiring 2057)." -ForegroundColor Yellow
        Write-Host "    For personalized scoring, create 'Drop_Financial_Info_Here\investor_profile.txt' with:" -ForegroundColor Yellow
        Write-Host "       birth_year = 1985" -ForegroundColor Yellow
        Write-Host "       retirement_year = 2050" -ForegroundColor Yellow
    }

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
