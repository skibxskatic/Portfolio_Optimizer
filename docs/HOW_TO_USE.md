# Fidelity Optimizer: How to Use Guide

## 1. Export Your Data from Fidelity

> **🚨 CRITICAL:** You **must always** download a fresh `Portfolio_Positions_...csv` file right before running the Optimizer. The engine relies entirely on this file for your *current* share quantities. Because Fidelity History exports are limited to 90 days and often miss older sell events, the engine intentionally ignores "Sell" transactions to prevent math errors. **If you do not provide an updated Positions file, your recent trades will not be reflected in the analysis!**

### Brokerage, Roth IRA, and HSA Accounts (CSV)
1. Log in to your Fidelity account on a desktop browser.
2. Navigate to the **"Positions"** tab.
3. In the top right corner of the positions table, click the small **"Download"** icon (it looks like a downward arrow).
   - This will download a file typically named `Portfolio_Positions_Mar-02-2026.csv`.
4. Next, navigate to the **"Activity & Orders"** tab.
5. Under the "History" sub-tab, open the "Time Period" filter.
6. **Important Note:** Fidelity only allows exporting 90 days of history at a time. To get the full picture for capital gains, you should export multiple 90-day chunks going back 1 to 5 years (e.g., `Accounts_History_Q1.csv`, `Accounts_History_Q2.csv`, etc.).
7. Click the **"Download"** icon in the top right for each time period you select.

### 401k Account (PDF)
1. Log in to **Fidelity NetBenefits** (your employer 401k portal).
2. Navigate to **"Investments"** → your plan page.
3. Print or PDF-save the **Investment Choices** page (this contains the full menu of funds available in your plan along with your **Balance Overview**).
4. Place the PDF in the `Drop_Financial_Info_Here/` folder.

> **Note:** The 401k parser requires a one-time text extraction step. Before running the main Optimizer, double-click **`Fidelity_401k_PDF_Extractor.bat`** to automatically read your PDF.

## 2. Place Your Data in the Project
For the privacy and security of your financial data, the downloaded files MUST be placed in the local `Drop_Financial_Info_Here/` folder. This folder is explicitly ignored by version control (Git) so your balances will never be uploaded to the cloud.

1. Move your single `Portfolio_Positions_...csv` file and **ALL** of your individual `Accounts_History...csv` files into the `Drop_Financial_Info_Here/` folder located inside the `Fidelity_Optimizer` project directory you just downloaded.

> **Engine Feature:** The Optimizer is programmed to automatically stitch all your History files together! Just drop them all into the `Drop_Financial_Info_Here/` folder—you do not need to manually combine them.

## 3. Run the Optimizer
The Optimizer generates a comprehensive Markdown report with all findings.

### Option A: The One-Click Executable (Recommended)
Launch the Optimizer in a single click without opening a terminal or configuring execution policies:

1. Open your File Explorer and navigate to the `Fidelity_Optimizer` folder you downloaded.
2. Double-click **`Fidelity_Optimizer.bat`** (the file with the gear/window icon).

Alternatively, if you are already in the IDE terminal, you can run the PowerShell script directly:
```bash
PowerShell -File src\run_optimizer.ps1
```

### Option B: Direct Python Execution
```bash
cd path\to\your\downloaded\Fidelity_Optimizer\
.\venv\Scripts\Activate.ps1
py src\portfolio_analyzer.py
```

🎉 **That's it!** The engine will automatically generate a timestamped, styled `.pdf` version of your report. This report is formatted as a **single, continuous scrolling page** (with cleanly formatted tables) to eliminate page breaks entirely. It will instantly pop open on your screen so you can immediately review your insights. A permanent copy is saved in the `Drop_Financial_Info_Here/.cache/` folder.

## 4. Understanding the Output Report

The report contains:

1. **High-Level Metrics** — Weighted average expense ratio and live risk-free rate.
2. **Asset Holding Breakdown** — Every position grouped by account type (Taxable, Roth IRA, 401k/HSA) with suggested actions.
3. **Tax Optimization** — Tax-loss harvesting candidates, capital gains screener, and de minimis override flags.
4. **Recommended Replacements** — Three separate tables:
   - 🚀 **Roth IRA** — Maximum growth funds (scored by Sortino Ratio)
   - 💰 **401k / HSA** — Income/dividend funds (scored by Sharpe Ratio)
   - 🏦 **Taxable Brokerage** — Tax-efficient growth funds (scored by Sharpe + low yield)
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
Running Asset Routing QA on known benchmarks (SCHD, QQQ, VTI)...
✅ Asset Routing QA PASSED: 3-Bucket routing logic is correct.
--- ALL QA PASSED, BEGINNING ENGINE RUN ---
```

The checks that run automatically:
1. **API Sanity Check:** Verifies SPY and SCHD yield/ER are within known-good bounds.
2. **Dynamic Screener QA:** Confirms live-scraped candidates are ETFs/Mutual Funds, not stocks.
3. **Asset Routing Validation:** Tests 3-Bucket routing (SCHD→401k/HSA, QQQ→Roth IRA, VTI→Taxable).
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
