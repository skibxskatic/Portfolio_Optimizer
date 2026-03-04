# Fidelity Portfolio Optimizer – Product Requirements Document (PRD)

## 1. Overview
**Project Name:** Fidelity Optimizer (Antigravity IDE Automation)
**Objective:** Build a local data processing engine to analyze exported Fidelity brokerage account data and optimize the portfolio for a **1-3 year time horizon**. The core focus is maximizing medium-term gains while strictly minimizing expense ratios (ERs) and mitigating short-term capital gains taxes during rebalancing or profit-taking.

## 2. Target User & Use Case
*   **User:** A retail investor with an active Fidelity brokerage account holding various assets (ETFs, Mutual Funds, Stocks).
*   **Use Case:** The user periodically downloads their `Positions.csv` and `History.csv` from Fidelity. They feed these files into the local Python engine to receive a comprehensive analysis of their current asset allocation, tax liabilities by lot, fee bloat, and actionable rebalancing recommendations geared toward a 1-3 year holding period.

## 3. Core Constraints & Philosophies
1.  **Time Horizon (1-3 Years):** Unlike a pure Boglehead 40-year strategy, a 1-3 year horizon demands lower volatility and slightly higher liquidity/income generation (e.g., shorter duration bonds, lower beta equities, or dividend growth) depending on the user's specific risk tolerance.
2.  **Tax Efficiency First:** Avoid realizing gains held for `< 365 days` to sidestep punitive Short-Term Capital Gains (STCG) tax brackets.
3.  **Expense Reduction:** Flag and propose replacements for any funds charging high advisory fees or expense ratios (ER > 0.40%).
4.  **Local & Secure:** No API calls uploading the user's raw financial data to external servers. Only anonymized ticker queries (via `yfinance` or similar) are permitted. The CSVs stay local.

## 4. Key Features & Workflows

### Phase 1: Ingestion & Parsing (Data Layer)
*   **Fidelity CSV Parser:** A robust Pandas module designed specifically to ingest Fidelity's standard CSV structures (skipping header metadata, mapping column names). Supports automatic aggregation of multiple `Accounts_History*.csv` files.
*   **Tax Lot Unrolling:** Break down aggregate ticker holdings into individual tax lots (Purchase Date, Cost Basis, Current Value) to calculate holding periods using FIFO (First-In-First-Out) accounting.

### Phase 2: Market Intelligence Engine
*   **Dynamic Candidate Scraper (`get_dynamic_etf_universe`):** Before scoring replacement funds, the engine fetches a live universe of 60-80 candidate ETFs and Mutual Funds directly from Yahoo Finance's screener pages (`finance.yahoo.com/etfs`, `/screener/predefined/top_mutual_funds`) using a lightweight `requests` + regex parser. If scraping fails, it falls back to a hardcoded baseline of 6 high-quality dividend funds.
*   **Ticker Hook (`yfinance`):** Fetch live pricing, trailing 12-month dividend yields, beta, expense ratios, and historical average returns (1-Year, 3-Year, 5-Year) for all holdings and replacement candidates.
*   **Portfolio Snapshot:** Generate a breakdown of allocations (Equities vs. Fixed Income vs. Cash) and a calculated weighted-average expense ratio.

### Phase 3: The Optimization Engine (Ruleset)
*   **The "One-Year Wait" Screener:** Group all unprofitable lots and profitable lots into STCG (< 1 year) and LTCG (> 1 year) buckets.
*   **Tax-Loss Harvesting (TLH) Detector:** Identify lots currently held at a loss that can be sold to offset other gains, alongside generating a list of highly correlated substitute ETFs (to avoid wash sales).
*   **Expense Bloat Scanner:** Identify mutual funds or ETFs with ERs $>0.40\%$ and suggest Fidelity/Vanguard low-cost index equivalents.

### Phase 4: Output & Reporting
*   **Rebalancing Terminal UI:** A clean CLI interface providing a plain-English briefing:
    * *Example: "You are holding 50 shares of SPY purchased 11 months ago at a 15% gain. Hold for 32 more days before selling to trigger Long-Term Capital Gains rates."*
    * *Example: "Your mutual fund XYZ charges 0.65%. Switching to FSKAX could save you $X over 3 years."*
*   **Portfolio Analysis Report:** A markdown document summarizing the findings. Asset Holding Breakdowns must group assets by Account Name first, and Suggested Action second.
    *   **Replacement Optimizer:** Dynamically recommends lower-fee ETF/Mutual Fund alternatives (no individual stocks). The scoring algorithm is:
        ```
        Score = (Yield × 2) + (3-Year Avg Return × 1.5) + (1-Year Return × 1)
        ```
        This formula heavily weights the 3-Year trailing average to suit the 1-3 year investment horizon. The output table MUST include 1-Year, 3-Year, and 5-Year historical returns for transparency.

### Phase 5: Quality Assurance (Pre-Flight Pipeline)
*   **Pre-Flight Gate:** The `validator.py` script MUST run automatically before every analysis in both `portfolio_analyzer.py` and `terminal_ui.py`. If any check fails, the engine must abort immediately and print a clear diagnostic message rather than generating a corrupted report.
*   **QA Checks (`validator.py`):**
    *   **Reality Check 1 – Ingestion Validation:** Assert that the total "Current Value" parsed by Pandas matches the raw CSV sum to within $1.00 tolerance.
    *   **Reality Check 2 – API Sanity:** Fetch SPY and SCHD and assert their yield and ER are within known-good bounds. This detects if a `yfinance` API update breaks field extraction.
    *   **Reality Check 3 – Dynamic Screener QA:** Verify that the live-scraped candidate universe passes the ETF/Mutual Fund type filter, and that no candidate reports perfectly `0.0%` across all return metrics (corrupted data guard).

### Phase 6: Documentation & Onboarding
*   **Living "How to Use" Guide:** A centralized guide (`docs/HOW_TO_USE.md`) defining exactly how to export CSVs from Fidelity, place them in the secure `data/` folder, trigger the interfaces, and run standalone validation.
*   **Continuous Maintenance Clause:** Whenever workflows, paths, or execution steps change in scripts, this documentation file **MUST be updated concurrently** to ensure it remains the single source of truth for operating the Optimizer.

## 5. Verification & Testing Strategy (Self-Improving Protocol)
To ensure the scripts are robust and data is accurate before finalization, all logic must pass the following reality checks:

### 1. Ingestion Validation (Data Layer)
*   **Checksums:** Assert that the total parsed portfolio value in Pandas matches the raw CSV to prevent dropped rows.
*   **Privacy Guard:** Automated check to ensure zero financial data (dollar amounts, account numbers) is printed to standard output during testing or execution.

### 2. API Reality Checks (Market Data)
*   **Known-Good Baselines:** Before running dynamic rules, the script must fetch data for benchmark ETFs (e.g., `SPY`, `SCHD`) and compare the results against a hardcoded "sane" range.
    * *Example:* If `yfinance` returns a yield of 400% for SCHD instead of ~3.5%, the script must halt and flag an API parsing error rather than generating a corrupted report.
*   **Dynamic Screener QA:** The live web scraper must mathematically verify that all extracted candidate tickers are strictly labeled as Exchange Traded Funds or Mutual Funds by Yahoo Finance. Any individual stocks (Equities) dynamically scraped must be intercepted and explicitly dropped.
*   **Data Integrity Check:** Any candidate fund returning perfectly `0.0%` for its 1-Year, 3-Year, and 5-Year historical returns must be rejected as corrupted API data, preventing empty tickers from polluting the final recommendations.

### 3. Logic Verification (Ruleset)
*   Create a mock `Test_Positions.csv` in `test_data/` containing artificial edge cases:
    * Lots held exactly 364 days vs 366 days (STCG vs LTCG boundary).
    * Funds with known expense ratios of 0.65% (must trigger replacement).
*   The Optimization Engine must successfully pass 100% of these synthetic test cases before being deemed complete.
*   **Pre-Flight Pipeline:** The `validator.py` script must be actively integrated to automatically execute and assert these reality checks *before* the terminal UI or markdown analyzer runs.

## 6. Technical Stack
*   **Language:** Python 3.x
*   **Data Processing:** `pandas`, `numpy`
*   **Market Data:** `yfinance`
*   **Web Scraping (Dynamic Screener):** `requests`, `re`, `lxml`
*   **Output Presentation:** `rich` (for terminal UI styling) and Markdown report generation.

## 7. Future Extensions
*   Backtesting engine (using `scipy.optimize` to plot the Efficient Frontier and optimize the portfolio's Sharpe ratio specifically mapped to a 3-year trailing window).
*   Wash-sale safety period tracker (30-day countdown timers for harvested lots).
*   ER vs. Performance diagnostic tool (`er_performance_analyzer.py`) — quantitatively validates the 0.40% ER threshold by measuring net return trade-offs over 1-3 year horizons.
