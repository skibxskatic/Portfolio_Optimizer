# Fidelity Optimizer: How to Use Guide

## 1. Export Your Data from Fidelity
To run the Optimizer, you first need to export your current portfolio and trading history directly from your Fidelity account:

1. Log in to your Fidelity account on a desktop browser.
2. Navigate to the **"Positions"** tab.
3. In the top right corner of the positions table, click the small **"Download"** icon (it looks like a downward arrow).
   - This will download a file typically named `Portfolio_Positions_Mar-02-2026.csv`.
4. Next, navigate to the **"Activity & Orders"** tab.
5. Under the "History" sub-tab, open the "Time Period" filter.
6. **Important Note:** Fidelity only allows exporting 90 days of history at a time. To get the full picture for capital gains, you should export multiple 90-day chunks going back 1 to 5 years (e.g., `Accounts_History_Q1.csv`, `Accounts_History_Q2.csv`, etc.).
7. Click the **"Download"** icon in the top right for each time period you select.

## 2. Place Your Data in the Project
For the privacy and security of your financial data, the downloaded CSV files MUST be placed in the local `data/` folder. This folder is explicitly ignored by version control (Git) so your balances will never be uploaded to the cloud.

1. Move your single `Portfolio_Positions_...csv` file and **ALL** of your individual `Accounts_History...csv` files into the following directory:
   `e:\GenAI_Antigravity_Projects\02_Active_Projects\Fidelity_Optimizer\data\`

> **✨ Engine Feature:** The Optimizer is programmed to automatically stitch all your History files together! Just drop them all into the `data/` folder—you do not need to manually combine them.

## 3. Run the Optimizer
Open your terminal (Command Prompt, PowerShell, or the IDE Terminal) and navigate to the project directory:

```bash
cd e:\GenAI_Antigravity_Projects\02_Active_Projects\Fidelity_Optimizer\
```

Activate the virtual environment if it isn't already active:
```bash
.\venv\Scripts\Activate.ps1
```

You have two choices for running the analysis:

### Option A: The Terminal UI (Quick Snapshot)
Run the script to see a quick, color-coded summary directly in your terminal:
```bash
py terminal_ui.py
```
*Note: This view is secured by our Privacy Guard—it will show you which funds to replace and how many lots are underwater, but it will never print your actual dollar balances to the screen.*

### Option B: The Markdown Report (Deep Dive)
Run the analyzer to generate a comprehensive, structured document:
```bash
py portfolio_analyzer.py
```
This will generate a new file at `data/Portfolio_Analysis_Report.md`. Open this file in your IDE or a Markdown reader to see the full, detailed breakdown of your asset health, specific tax-loss harvesting targets, and dynamic replacement ETF recommendations.

## 4. Understanding the Pre-Flight QA Checks
Every time you run either `terminal_ui.py` or `portfolio_analyzer.py`, the engine **automatically runs a series of Quality Assurance checks** before processing any of your data. These checks protect you from running analysis on corrupted API data or bad CSV exports.

You will see output like this at the start of every run:
```
--- PRE-FLIGHT QA CHECKS ---
Running API Reality Checks against known benchmarks (SPY, SCHD)...
✅ API Reality Check PASSED: yfinance extraction logic is structurally sound.
Running Dynamic Screener QA on live targets...
🛡️ QA Filter Working: Successfully intercepted and dropped individual stock 'NVDA'...
✅ Dynamic Screener QA PASSED: Engine successfully filtered raw targets down to N pure ETFs/Funds.
--- ALL QA PASSED, BEGINNING ENGINE RUN ---
```

The three checks that run automatically are:
1. **API Sanity Check:** Fetches SPY and SCHD and verifies their yield and ER are within known-good bounds. If `yfinance` ever breaks its data format, this check will catch it.
2. **Dynamic Screener QA:** Verifies that the live-scraped fund candidates are ETFs or Mutual Funds — not individual stocks. The 🛡️ messages confirm that stocks are being intercepted.
3. **Ingestion Checksum:** (Runs as part of the full report) Confirms that no rows were dropped when your Positions CSV was parsed.

> **⚠️ If a check fails:** The engine will print a clear `❌ PRE-FLIGHT FAILED` message and abort safely. No partial or corrupted report will be generated.

### Running the Validator Standalone (for Debugging)
If you want to test data integrity without running a full analysis, you can run the validator directly:
```bash
py validator.py
```
This is useful after updating the codebase, changing dependencies, or troubleshooting data issues.

## 5. Diagnostic Tools
The project also includes a standalone diagnostic tool for advanced analysis:

*   **`er_performance_analyzer.py`** — Analyzes the trade-off between Expense Ratio and fund performance (1-year and 3-year net returns). Run this to validate the current 0.40% ER threshold:
    ```bash
    py er_performance_analyzer.py
    ```
