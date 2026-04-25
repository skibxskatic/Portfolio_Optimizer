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
    
    # --- Investor Profile Setup ---
    $profilePath = Join-Path $PSScriptRoot "..\Drop_Financial_Info_Here\investor_profile.txt"

    # Risk tolerance menu labels
    $riskLevels = @(
        @{ key="1"; value="very_conservative"; label="Very Conservative - Capital preservation priority" },
        @{ key="2"; value="conservative";      label="Conservative - Stability-focused" },
        @{ key="3"; value="moderate";          label="Moderate - Balanced growth and stability" },
        @{ key="4"; value="aggressive";        label="Aggressive - Growth-focused" },
        @{ key="5"; value="very_aggressive";   label="Very Aggressive - Maximum growth" }
    )

    function Read-ProfileField($prompt, $default) {
        $input = Read-Host "$prompt [$default]"
        if ([string]::IsNullOrWhiteSpace($input)) { return $default } else { return $input.Trim() }
    }

    function Show-Profile($path) {
        Write-Host "`n--- Investor Profile ---" -ForegroundColor Cyan
        $content = Get-Content $path -ErrorAction SilentlyContinue
        $fields = @{}
        foreach ($line in $content) {
            if ($line -match '^\s*([^#]\w+)\s*=\s*(.+)') {
                $fields[$Matches[1].Trim()] = $Matches[2].Trim()
            }
        }
        $birth = if ($fields.ContainsKey("birth_year")) { $fields["birth_year"] } else { "not set" }
        $retire = if ($fields.ContainsKey("retirement_year")) { $fields["retirement_year"] } else { "not set" }
        $risk = if ($fields.ContainsKey("risk_tolerance")) { $fields["risk_tolerance"] } else { "auto (from age)" }
        $state = if ($fields.ContainsKey("state")) { $fields["state"] } else { "not set (federal rates only)" }
        $rothC = if ($fields.ContainsKey("roth_ira_contribution")) { "$" + $fields["roth_ira_contribution"] } else { "auto-detect" }
        $taxC = if ($fields.ContainsKey("taxable_contribution")) { "$" + $fields["taxable_contribution"] } else { "auto-detect" }
        $hsaC = if ($fields.ContainsKey("hsa_contribution")) { "$" + $fields["hsa_contribution"] } else { "auto-detect" }
        $k401C = if ($fields.ContainsKey("401k_contribution")) { "$" + $fields["401k_contribution"] } else { "auto-detect" }
        Write-Host "  Birth Year:        $birth"
        Write-Host "  Retirement Year:   $retire"
        Write-Host "  Risk Tolerance:    $risk"
        Write-Host "  State:             $state"
        Write-Host "  Roth IRA Contrib:  $rothC"
        Write-Host "  Taxable Contrib:   $taxC"
        Write-Host "  HSA Contrib:       $hsaC"
        Write-Host "  401k Contrib:      $k401C"
        Write-Host "------------------------" -ForegroundColor Cyan
    }

    function Build-Profile() {
        Write-Host "`n--- Investor Profile Setup ---" -ForegroundColor Cyan
        $birth = Read-ProfileField "Birth year" "1990"
        $retire = Read-ProfileField "Retirement year" "2057"

        # Auto-recommend risk tolerance based on years to retirement
        $yearsOut = [int]$retire - (Get-Date).Year
        if ($yearsOut -ge 30) { $autoRisk = "very_aggressive"; $autoNum = "5" }
        elseif ($yearsOut -ge 20) { $autoRisk = "aggressive"; $autoNum = "4" }
        elseif ($yearsOut -ge 10) { $autoRisk = "moderate"; $autoNum = "3" }
        elseif ($yearsOut -ge 3)  { $autoRisk = "conservative"; $autoNum = "2" }
        else { $autoRisk = "very_conservative"; $autoNum = "1" }

        Write-Host "`nRisk Tolerance (auto-recommendation: $autoRisk based on $yearsOut yrs to retirement):"
        foreach ($r in $riskLevels) { Write-Host "  $($r.key). $($r.label)" }
        $riskInput = Read-ProfileField "Choose 1-5 or press Enter for auto" $autoNum
        $riskChoice = ($riskLevels | Where-Object { $_.key -eq $riskInput }).value
        if (-not $riskChoice) { $riskChoice = $autoRisk }

        Write-Host "`nState (2-letter code for tax estimates, or press Enter to skip):"
        Write-Host "  If skipped, tax estimates will use federal rates only (no state tax applied)."
        $stateInput = Read-Host "State code [skip]"
        $stateLine = ""
        if ($stateInput -and $stateInput.Length -eq 2) { $stateLine = "state = $($stateInput.ToUpper())" }

        Write-Host "`nContribution amounts - how much cash to deploy per account."
        Write-Host "Press Enter to auto-detect from core/money-market positions in your CSV (recommended)."
        $rothC = Read-Host "Roth IRA $ [auto-detect from CSV]"
        $taxC = Read-Host "Taxable $ [auto-detect from CSV]"
        $hsaC = Read-Host "HSA $ [auto-detect from CSV]"
        $k401C = Read-Host "401k $ [auto-detect from CSV]"

        # Write profile
        $lines = @(
            "# Investor Profile for Portfolio Optimizer",
            "birth_year = $birth",
            "retirement_year = $retire",
            "risk_tolerance = $riskChoice"
        )
        if ($stateLine) { $lines += $stateLine }
        if ($rothC) { $lines += "roth_ira_contribution = $rothC" }
        if ($taxC) { $lines += "taxable_contribution = $taxC" }
        if ($hsaC) { $lines += "hsa_contribution = $hsaC" }
        if ($k401C) { $lines += "401k_contribution = $k401C" }

        $lines | Set-Content -Path $profilePath -Encoding UTF8
        Write-Host "`nProfile saved." -ForegroundColor Green
    }

    if (Test-Path $profilePath) {
        Show-Profile $profilePath
        $editChoice = Read-Host "Press Enter to continue, or type 'edit' to modify"
        if ($editChoice -eq "edit") { Build-Profile }
    } else {
        Write-Host "`nNo investor profile found. Let's set one up." -ForegroundColor Yellow
        Build-Profile
    }

    # 4. History Coverage Pre-Check
    Write-Host "`nChecking transaction history coverage..." -ForegroundColor Cyan
    python -u src\portfolio_analyzer.py --check-history

    Write-Host "Press Enter to begin full analysis, or Ctrl+C to stop and collect more history..." -ForegroundColor White -NoNewline
    Read-Host
    
    Write-Host "`nGenerating full portfolio analysis report..." -ForegroundColor Cyan
    $env:PYTHONIOENCODING='utf-8'
    python -u src\portfolio_analyzer.py
    
    Write-Host "`nAnalysis Complete." -ForegroundColor Green
    Pause
}
catch {
    Write-Host "An error occurred while running the optimizer:" -ForegroundColor Red
    Write-Host $_.Exception.Message
    Pause
}
