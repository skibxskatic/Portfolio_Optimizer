# GEMINI.md - Portfolio Optimizer Instructions

This document provides foundational mandates and technical context for the Portfolio Optimizer project. All future interactions should prioritize these guidelines.

## Project Overview
The **Portfolio Optimizer** is a local, privacy-first Python engine designed to analyze investment portfolios, identify tax-loss harvesting (TLH) opportunities, and recommend tax-efficient fund placements. It follows a "time in market over timing the market" philosophy, focusing on long-term wealth accumulation through expense reduction and smart asset routing.

### Core Technologies
- **Language:** Python 3.x
- **Data:** `pandas`, `numpy`, `yfinance` (market data)
- **PDF Extraction:** `pypdf` (for 401k statements/investment menus)
- **Reporting:** Markdown to PDF (continuous single-page format)
- **Automation:** PowerShell and Batch scripts for user-friendly execution.

## Architecture & Key Files
- **`src/portfolio_analyzer.py`:** The main engine orchestrating ingestion, analysis, and report generation.
- **`src/file_ingestor.py`:** Auto-detects and routes files (CSV, PDF) to specialized parsers.
- **`src/validator.py`:** Pre-flight sanity checks (Checksums, API health, logic validation). **Must pass before analysis runs.**
- **`src/metrics.py`:** Mathematical module for risk-adjusted returns (Sharpe, Sortino, Max Drawdown, Tracking Error).
- **`src/401k_parser.py`:** Parses 401k statement PDFs and investment option menus.
- **`src/parser.py`:** Standard brokerage CSV parser (Positions and History).
- **`src/market_data.py`:** Fetches live pricing, yields, and expense ratios.
- **`src/er_performance_analyzer.py`:** Diagnostic tool to quantitatively validate the 0.40% ER screening threshold against net performance tradeoffs.
- **`Portfolio_Optimizer.bat`:** Primary user entry point (Windows).
- **`Portfolio_Optimizer_Mac.app`:** macOS launcher (native `.app` bundle — no `chmod` needed).
- **`Portfolio_Optimizer.command`:** macOS shell script (used internally by the `.app`).
- **`src/run_optimizer.ps1`:** The PowerShell execution wrapper that handles virtual environment activation, cache setup, and launches the engine.

## Building and Running
### Prerequisites
- Python 3.x installed.
- A virtual environment named `venv` in the root.

### Setup
Both launchers auto-create the venv and install dependencies if missing. For manual setup:
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install pandas numpy yfinance requests lxml openpyxl
```

### Execution
- **Windows:** Double-click `Portfolio_Optimizer.bat`.
- **macOS:** Double-click `Portfolio_Optimizer_Mac.app` (or run `./Portfolio_Optimizer.command` from terminal).
- **Developer Run:** `python src/portfolio_analyzer.py` (ensure `venv` is active).
- **Validation Check:** `python src/validator.py`.

## Development Conventions & Mandates
1. **Privacy-First:** Never log, print, or transmit raw financial data (dollar amounts, account numbers). All processing stays local.
2. **Buy-and-Hold:** Recommendations focus on long-term efficiency, not short-term trading.
3. **Tax Efficiency:**
    - Prefer LTCG (> 365 days) over STCG.
    - **De Minimis Override:** STCG gains < 1% of lot value are flagged as "safe to reallocate."
4. **Smart Asset Routing (4-Bucket Model):**
    - **Roth IRA:** Maximum Growth (High Beta, Low Yield).
    - **401k/HSA:** Income/Dividends (Tax-deferred). 401k is constrained to the plan's menu.
    - **Taxable Brokerage:** Tax-Efficient Growth (Low distribution yield).
5. **Expense Reduction:** Only recommend a lower-ER fund if it also provides superior **net-of-fees returns**.
6. **Continuous PDF Output:** Reports must be rendered in a single-page continuous format to avoid breaking tables.
7. **Validation First:** Any logic changes must be verified via `src/validator.py` and the test cases in `src/test_data/`.

## Testing Strategy
- **Synthetic Data:** Use `src/test_data/Test_Positions.csv` for logic verification (STCG vs LTCG boundaries, de minimis cases).
- **Pre-Flight Pipeline:** The `validator.py` script automatically runs before every analysis. New features MUST add corresponding checks to this file.
- **TDD Scripts:** `src/test_tlh_screener.py` and `src/test_pdf_format.py` provide isolated verification for Phase 1 Tax Lot Unrolling and continuous PDF generation respectively.
