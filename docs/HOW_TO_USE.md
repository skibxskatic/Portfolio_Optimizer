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

## 2. Place Your Data in the Project
For the privacy and security of your financial data, the downloaded files MUST be placed in the local `Drop_Financial_Info_Here/` folder. This folder is explicitly ignored by version control (Git) so your balances will never be uploaded to the cloud.

1. Move your single `Portfolio_Positions_...csv` file and **ALL** of your individual `Accounts_History...csv` files into the `Drop_Financial_Info_Here/` folder located inside the `Portfolio_Optimizer` project directory.

> **Engine Feature:** The Optimizer is programmed to automatically stitch all your History files together! Just drop them all into the `Drop_Financial_Info_Here/` folder—you do not need to manually combine them.

## 3. Run the Optimizer
The Optimizer generates a comprehensive Markdown report with all findings.

### Option A: The One-Click Executable (Recommended)
Launch the Optimizer in a single click without opening a terminal or configuring execution policies:

**Windows:**
1. Open your File Explorer and navigate to the `Portfolio_Optimizer` folder.
2. Double-click **`Portfolio_Optimizer.bat`** (the file with the gear/window icon).

**macOS / Linux:**
1. Open your Finder and navigate to the `Portfolio_Optimizer` folder.
2. Double-click **`Portfolio_Optimizer.command`**. Terminal will open and run the optimizer automatically.

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

🎉 **That's it!** The engine will automatically generate a timestamped, styled `.pdf` version of your report. This report is formatted as a **single, continuous scrolling page** (with cleanly formatted tables) to eliminate page breaks entirely. It will instantly pop open on your screen so you can immediately review your insights. A permanent copy is saved in the `Drop_Financial_Info_Here/.cache/` folder.

## 4. Understanding the Output Report

The report contains:

1. **High-Level Metrics** — Weighted average expense ratio and live risk-free rate.
2. **Asset Holding Breakdown** — Every position grouped by account type (Taxable, Roth IRA, Employer 401k, HSA) with suggested actions.
3. **Tax Optimization** — Tax-loss harvesting candidates, capital gains screener, and de minimis override flags.
4. **Recommended Replacements** — Four separate tables:
   - 🚀 **Roth IRA** — Maximum growth funds (scored by Sortino Ratio + Net-of-Fees 5Y + 10Y Total Return)
   - 💼 **Employer 401k** — Income/dividend funds, plan-constrained (scored by Sharpe Ratio)
   - 🏥 **HSA** — Maximum growth, full universe (scored by Sortino Ratio + Net-of-Fees 5Y + 10Y Total Return — same tier as Roth IRA)
   - 🏦 **Taxable Brokerage** — Tax-efficient growth funds (scored by Sharpe + low yield)
   - Each table may include an **"Emerging Funds"** sub-section for funds with < 3 years of history, labeled `⚠️ < 3Y History`.
5. **401k Plan Analysis** *(If 401k PDF is provided)* — Dedicated scorecard ranking every fund in your employer's plan, highlighting Rebalance Opportunities and Underperforming Holdings.
6. **Evaluation Metrics Summary** — Explains each metric, why it's used for each account type, and how to interpret scores.

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
This also runs the **Metrics Computation QA** check (Sharpe/Sortino/MaxDD sanity on SPY).

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
