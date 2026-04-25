# Portfolio Optimizer: How to Use Guide

## 1. Export Your Data

> **🚨 CRITICAL:** You **must always** download a fresh `Portfolio_Positions_...csv` file right before running the Optimizer. The engine relies entirely on this file for your *current* share quantities. Because History exports are often limited to 90 days and may miss older sell events, the engine intentionally ignores "Sell" transactions to prevent math errors. **If you do not provide an updated Positions file, your recent trades will not be reflected in the analysis!**

The engine supports **Fidelity, Schwab, Vanguard, T. Rowe Price, and Principal** — it auto-detects the broker from the CSV format.

### Brokerage, Roth IRA, and HSA Accounts (CSV)

**Fidelity:**
1. Log in to your Fidelity account on a desktop browser.
2. Navigate to **"Positions"** → click the **"Download"** icon (downward arrow). File is typically named `Portfolio_Positions_Mar-02-2026.csv`.
3. Navigate to **"Activity & Orders"** → **"History"** → set Time Period → click **"Download"**. Repeat for each 90-day chunk going back 1–5 years.

**Schwab:**
1. Log in to Schwab → go to **"Accounts"** → **"Positions"** → click **"Export"** (CSV).
2. For history: **"History"** tab → set date range → **"Export"**.

**Vanguard:**
1. Log in → **"My Accounts"** → **"Holdings"** → **"Download"** (CSV).
2. For history: **"Transaction history"** → set date range → **"Download"**.

### 401k Account (PDF)

**Fidelity NetBenefits / Schwab / T. Rowe Price / Principal:**
1. Log in to your employer's 401k portal.
2. Navigate to **"Investments"** → your plan page.
3. Print or PDF-save the **Investment Choices** page (this contains the full plan menu and your Balance Overview).
4. Place the PDF in the `Drop_Financial_Info_Here/` folder. Ensure the filename contains the word `"options"` and does not contain `"transaction"`.

> **Note:** The 401k parser supports PDF files directly. The engine auto-detects T. Rowe Price and Principal statement formats in addition to Fidelity.

### Investor Profile

The Optimizer uses your investor profile to personalize recommendations across **all** account types. A template is auto-generated on first run. You can also create `investor_profile.txt` manually in `Drop_Financial_Info_Here/`:

```
birth_year = 1985
retirement_year = 2050
risk_tolerance = moderate
state = CA
roth_ira_contribution = 7000
taxable_contribution = 50000
hsa_contribution = 4150
401k_contribution = 23000
```

**All fields are optional.** Available settings:

| Field | Description | Default |
|-------|-------------|---------|
| `birth_year` | Your birth year | 1990 |
| `retirement_year` | Target retirement year | 2057 |
| `risk_tolerance` | `very_conservative`, `conservative`, `moderate`, `aggressive`, `very_aggressive` | Auto from age |
| `state` | 2-letter state code for tax estimates (e.g., `CA`, `TX`) | Federal only |
| `roth_ira_contribution` | Roth IRA cash to deploy ($) | $0 (auto-detect from CSV) |
| `taxable_contribution` | Taxable brokerage cash to deploy ($) | $0 (auto-detect from CSV) |
| `hsa_contribution` | HSA cash to deploy ($) | $0 (auto-detect from CSV) |
| `401k_contribution` | 401k contribution amount ($) | $0 (auto-detect from CSV) |

This enables:
- **Age-calibrated scoring** — fund evaluation weights shift based on your time horizon
- **Risk-tolerance blending** — blends performance score with stability score (lower volatility preference for conservative investors)
- **Portfolio Risk Profile** — compares your actual equity allocation to the glide-path target for your age
- **Holdings flags** — warns when holdings are mismatched to your horizon
- **TLH urgency** — near-retirement investors see elevated harvesting priority
- **401k allocation targets** — personalized equity/bond split and per-fund percentages
- **Per-account allocation plan** — Section 5f shows exactly how much to allocate to each recommended fund
- **Tax estimates** — state tax rate applied to rebalancing tax impact calculations

> **Note:** If this file is absent, the Optimizer auto-generates a template and uses default assumptions. The **interactive launchers** (Windows `.bat` / macOS `.app`) will guide you through setting up your profile on first run, and show your current profile with an option to edit on subsequent runs.

## 2. Place Your Data in the Project
For the privacy and security of your financial data, the downloaded files MUST be placed in the local `Drop_Financial_Info_Here/` folder. This folder is explicitly ignored by version control (Git) so your balances will never be uploaded to the cloud.

1. Move your single `Portfolio_Positions_...csv` file and **ALL** of your individual `Accounts_History...csv` files into the `Drop_Financial_Info_Here/` folder located inside the `Portfolio_Optimizer` project directory.

> **Engine Feature:** The Optimizer is programmed to automatically stitch all your History files together! Just drop them all into the `Drop_Financial_Info_Here/` folder—you do not need to manually combine them.

## 3. Run the Optimizer
The Optimizer generates a comprehensive Markdown report with all findings.

### Option A: The One-Click Executable (Recommended)
Launch the Optimizer in a single click without opening a terminal or configuring execution policies:

Windows:
1. Open your File Explorer and navigate to the `Portfolio_Optimizer` folder.
2. Double-click **`Portfolio_Optimizer.ps1`** (the file with the gear/window icon).
3. **Pre-Flight History Check:** The script will instantly show you the **date range** of your current transaction data and alert you to any gaps before starting the full analysis.

For a quick **Hygiene Check** (consolidate files and see date range without running the optimizer), use:
- **`Check_History_Health.ps1`** (Windows)

macOS:

1. Open Finder and navigate to the `Portfolio_Optimizer` folder.
2. Double-click **`Portfolio_Optimizer_Mac.app`**.
   - On first launch, macOS may warn about an unidentified developer. Go to **System Settings → Privacy & Security** and click **"Open Anyway"** (one-time).
3. Terminal will open and run the optimizer automatically.

> **Note:** The `.app` wrapper automatically handles file permissions — no terminal commands required. If you prefer the command line, you can also run `./Portfolio_Optimizer.command` directly.

Both launchers will automatically create a virtual environment and install all dependencies if one doesn't already exist. If a venv is already active, they skip activation entirely.

Alternatively, if you are already in the IDE terminal, you can run the PowerShell script directly:
```bash
PowerShell -File src\run_optimizer.ps1
```

### Option B: Direct Python Execution
```bash
cd path\to\your\Portfolio_Optimizer\
.\venv\Scripts\Activate.ps1
py src\portfolio_analyzer.py
```

🎉 **That's it!** The engine will automatically generate both an **interactive HTML report** and a **PDF version**. The HTML report opens in your browser with clickable navigation and collapsible sections. Both are saved in the `Drop_Financial_Info_Here/.cache/` folder.

## 4. Understanding the Output Report

The report contains:

1. **Executive Summary** — Features a ⚡ **Immediate Execution Steps** table highlighting highest-priority actions, priority level, and estimated tax impact, followed by auto-generated summary bullets.
2. **High-Level Metrics** — Weighted average expense ratio, live risk-free rate, and a Portfolio Risk Profile comparing your equity allocation to the target for your age.
2. **Asset Holding Breakdown** — Positions grouped under sub-headers by account type (Taxable Brokerage, Roth IRA, HSA) with suggested actions and age-appropriate horizon flags. 401k holdings are shown as a summary with a pointer to Section 5.
3. **Tax Optimization** — Tax-loss harvesting candidates, capital gains screener, and de minimis override flags.
4. **Recommended Replacements** — Four separate tables:
   - 🚀 **Roth IRA** — Maximum growth funds (scored by Sortino Ratio + Net-of-Fees 5Y + 10Y Total Return)
   - 💼 **Employer 401k** — Income/dividend funds, plan-constrained (scored by Sharpe Ratio)
   - 🏥 **HSA** — Maximum growth, full universe (scored by Sortino Ratio + Net-of-Fees 5Y + 10Y Total Return — same tier as Roth IRA)
   - 🏦 **Taxable Brokerage** — Tax-efficient growth funds (scored by Sharpe + low yield)
   - Each table may include an **"Emerging Funds"** sub-section for funds with < 3 years of history, labeled `⚠️ < 3Y History`.
5. **401k Plan Analysis** *(If 401k PDF is provided)* — Dedicated scorecard ranking every fund in your employer's plan, highlighting Rebalance Opportunities, Underperforming Holdings, and an age-aware **Recommended Allocation** table (Section 5e) with target percentages based on your glide-path profile. **Portfolio Rebalancing Plan** (Section 5f) — per-account allocation tables for Roth IRA, Taxable Brokerage, and HSA showing Score, Stability, Allocation %, pertinent metric comparison, and existing holdings evaluation.
6. **Next Steps** — Contextual action items grouped by category: high-ER replacements with tax context, TLH actions with wash-sale warnings, 401k rebalancing, and age-inappropriate holdings.
7. **Why These Recommendations** — A plain-English verdict table (Keep/Replace/Evaluate per holding with human-readable "Why"), plus a collapsible methodology section explaining each metric, per-account scoring, and age-aware adjustments.

## 5. Understanding the Pre-Flight QA Checks
Every time you run `portfolio_analyzer.py`, the engine **automatically runs Quality Assurance checks** before processing your data:

```
--- PRE-FLIGHT QA CHECKS ---
Running API Reality Checks against known benchmarks (SPY, SCHD)...
✅ API Reality Check PASSED: yfinance extraction logic is structurally sound.
Running Dynamic Screener QA on live targets...
✅ Dynamic Screener QA PASSED: Engine successfully filtered raw targets.
Running Asset Routing QA on known benchmarks (SCHD, QQQ, VTI, VGT)...
✅ Asset Routing QA PASSED: 4-Bucket routing (Taxable, Roth IRA, 401k/Tax-Deferred, HSA growth-tier) validated.
--- ALL QA PASSED, BEGINNING ENGINE RUN ---
```

The checks that run automatically:
1. **API Sanity Check:** Verifies SPY and SCHD yield/ER are within known-good bounds.
2. **Dynamic Screener QA:** Confirms live-scraped candidates are ETFs/Mutual Funds, not stocks.
3. **Asset Routing Validation:** Tests 4-Bucket routing against SCHD (→401k), QQQ (→Roth IRA), VTI (→Taxable), VGT (→Roth IRA, confirming HSA growth-tier sourcing).
4. **Ingestion Checksum:** Confirms no rows were dropped during CSV parsing.

> **⚠️ If a check fails:** The engine prints `❌ PRE-FLIGHT FAILED` and aborts safely.

### Running the Validator Standalone
```bash
py src\validator.py
```
This also runs additional checks: **Metrics Computation QA** (Sharpe/Sortino/MaxDD sanity on SPY), **Wash Sale Detection**, **Asset Classification**, **Risk Tolerance Mapping** (all 5 levels valid), and **Allocation Normalization** (sums to 100%).

## 6. Diagnostic Tools

*   **`er_performance_analyzer.py`** — Analyzes Expense Ratio vs. performance trade-offs:
    ```bash
    py src\er_performance_analyzer.py
    ```
*   **`metrics.py`** — Standalone smoke test for the risk-adjusted metrics engine:
    ```bash
    py src\metrics.py
    ```
*   **`401k_parser.py`** — Parse and display 401k holdings from extracted PDF text:
    ```bash
    py src\401k_parser.py
    ```
