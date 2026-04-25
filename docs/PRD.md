# Portfolio Optimizer – Product Requirements Document (PRD)

> [!INFO] Technical Docs
> **Logic:** [[HOW_IT_WORKS]]
> **Constraints:** [[CONSTRAINTS]]
> **User Guide:** [[HOW_TO_USE]]
> **Finance Context:** [[2026_Tax_Checklist]] | [[2026_LLC_Tax_Guide]]

## 1. Overview
**Project Name:** Portfolio Optimizer
**Objective:** Build a local data processing engine to analyze exported brokerage account data and optimize the portfolio for **long-term wealth accumulation**. The core focus is maximizing after-tax compounding through tax-efficient asset placement, low expenses, and evidence-based fund evaluation — following a "time in market over timing the market" philosophy.

## 2. Target User & Use Case
*   **User:** A retail investor with an active brokerage and retirement account(s) holding various assets (ETFs, Mutual Funds, Index Funds).
*   **Scope Exclusion:** Individual equities (stocks) are **strictly excluded** from all analysis and recommendations. The engine operates exclusively on index funds, mutual funds, and exchange-traded funds (ETFs).
*   **Use Case:** The user periodically downloads their `Positions.csv` and `History.csv` from their brokerage. They feed these files into the local Python engine to receive a comprehensive analysis of their current asset allocation, tax liabilities by lot, fee bloat, and actionable rebalancing recommendations tailored to each account type.

## 3. Core Constraints & Philosophies
1.  **Buy-and-Hold, Long-Term Focus:** The investor follows a "time in market over timing the market" strategy. The engine does not attempt to time entries or exits. Instead, it focuses on periodic portfolio hygiene — ensuring holdings are in the right accounts, expenses are low, and tax liabilities are minimized through intelligent lot management.
2.  **Tax Efficiency First:** Avoid realizing gains held for `< 365 days` to sidestep punitive Short-Term Capital Gains (STCG) tax brackets — with a **De Minimis Override** (see Section 4.3).
3.  **Expense Reduction:** Flag and propose replacements for any funds where a lower-cost alternative delivers superior **net-of-fees returns** over comparable time horizons. The raw 0.40% ER threshold serves as an initial screen, but the engine must compare *net returns* before recommending a switch.
4.  **Local & Secure:** No API calls uploading the user's raw financial data to external servers. Only anonymized ticker queries (via `yfinance` or similar) are permitted. The CSVs stay local.
5.  **4-Bucket Tax-Optimized Asset Placement:** Maximize after-tax returns by intelligently placing assets across four distinct account types based on each account's tax treatment (see Section 4.3, Smart Asset Routing).
6.  **Fund-Only Scope:** The engine will never recommend, score, or analyze individual company equities. All candidate sourcing, scoring, and replacement logic is restricted to index funds, mutual funds, and ETFs.

## 4. Key Features & Workflows

### Phase 1: Ingestion & Parsing (Data Layer)
*   **Multi-Broker Adapter Layer (`src/parsers/`):** A broker-agnostic ingestion layer built on an abstract `BrokerAdapter` base class. An `ADAPTER_REGISTRY` ordered list `[Fidelity, Schwab, Vanguard, TRowePrice, Principal, Generic]` is iterated per file; the first adapter whose `detect()` method returns `True` claims the file. All adapters output the same **canonical schema** regardless of source broker. `GenericAdapter` is always last — it uses fuzzy column-name matching as a fallback for unknown brokers.
    *   **Canonical Positions columns:** `Symbol`, `Description`, `Account Name`, `Account Type`, `Quantity`, `Current Value`, `Cost Basis Total`, `Average Cost Basis`, `Expense Ratio`
    *   **Canonical History columns:** `Date`, `Action` (`Buy` | `Sell` | `Reinvestment` | `Dividend` | `Transfer`), `Symbol`, `Description`, `Quantity`, `Price`, `Amount`, `Account Name`
*   **Automatic History Consolidation:** The engine automatically detects multiple history CSV files, merges them, deduplicates transactions, and sorts by date. It generates a single master file named with the transaction date range and archives individual files to a local `archived/` folder.
*   **Pre-Flight History Assessment:** Immediate terminal reporting of the date range (Oldest to Newest) of current history. Calculates the percentage of the portfolio missing history to provide actionable guidance on exactly how far back the user needs to download reports.
*   **CSV Parser (`parser.py` shim → `parsers.fidelity.FidelityAdapter`):** `portfolio_analyzer.py` calls `load_fidelity_positions()` / `load_fidelity_history()` unchanged.
 These are backward-compat shims that delegate to `FidelityAdapter`. Fidelity history action strings are normalized at the adapter layer (`YOU BOUGHT`→`Buy`, `REINVESTMENT`→`Reinvestment`, etc.) and column names are renamed to canonical form (`Run Date`→`Date`, `Account`→`Account Name`).
    *   **Data Freshness Requirement:** The parser relies on `Portfolio_Positions.csv` as the absolute source of truth for the *current* quantity of shares held today. A fresh export is required per run.
*   **Tax Lot Unrolling:** Break down aggregate ticker holdings into individual tax lots (Purchase Date, Cost Basis, Current Value) to calculate holding periods using FIFO (First-In-First-Out) accounting. The unroller intentionally **ignores sell transactions** in the history CSVs, as applying sells manually would double-count share depletion already reflected in the current positions file. Uses canonical `Date` column and `Action.isin({'Buy', 'Reinvestment'})` filter.
*   **401k Parser (`401k_parser.py` shim → `parsers.fidelity.FidelityAdapter`):** A backward-compat shim re-exporting 401k parsing functions from `parsers.fidelity`. Extracts current holdings from the "Balance Overview" section and dynamically discovers the available plan fund menu from the "Investment Choices" section. No hardcoding required. Tax lot analysis is **not applicable** to 401k accounts (tax-deferred). T. Rowe Price and Principal 401k formats are handled by their respective adapters.
*   **File Format Auto-Dispatcher (`file_ingestor.py`):** A 3-layer detection pipeline that auto-detects file formats (CSV, Excel, PDF, extracted text) and routes to the correct adapter. For 401k files, iterates `ADAPTER_REGISTRY` calling each adapter's `detect_401k()`. For CSV/Excel positions and history files, calls `detect_broker()` to find the matching adapter. PDFs are extracted inline via `pypdf` — no separate batch file step needed.

### Phase 2: Market Intelligence Engine
*   **Dynamic Candidate Scraper (`get_dynamic_etf_universe`):** Before scoring replacement funds, the engine fetches a live universe of 60-80 candidate ETFs and Mutual Funds directly from Yahoo Finance's screener pages (`finance.yahoo.com/etfs`, `/screener/predefined/top_mutual_funds`) using a lightweight `requests` + regex parser. If scraping fails, it falls back to a hardcoded baseline of 24 funds covering all 4 routing buckets (Tax-Deferred, Roth IRA, Taxable Brokerage, Bond). Individual equities returned by the scraper must be intercepted and dropped.
*   **Ticker Hook (`yfinance`):** Fetch live pricing, trailing 12-month dividend yields, beta, expense ratios, and historical average returns (1-Year, 3-Year, 5-Year, 10-Year where available) for all holdings and replacement candidates.
*   **Portfolio Snapshot:** Generate a breakdown of allocations (Equities vs. Fixed Income vs. Cash) and a calculated weighted-average expense ratio.

### Phase 3: The Optimization Engine (Ruleset)

#### 3a. Tax Lot Screening
*   **The "One-Year Wait" Screener:** Group all unprofitable lots and profitable lots into STCG (< 1 year) and LTCG (> 1 year) buckets. The output must indicate the originating **Account Name** for each lot grouping alongside the symbol to clarify where the gains reside.
*   **De Minimis Gain Override:** Lots with unrealized STCG gains below **1% of the lot's current value** are flagged as *"Safe to reallocate — gain is immaterial"* regardless of holding period. This prevents being locked into an underperforming fund over negligible tax savings. The threshold is **configurable** via a `DE_MINIMIS_GAIN_PCT` constant (default: `0.01`).
*   **Tax-Loss Harvesting (TLH) Detector:** Identify lots currently held at a loss that can be sold to offset other gains, alongside generating a list of highly correlated substitute ETFs (to avoid wash sales).

#### 3b. Expense & Fee Evaluation
*   **Expense Bloat Scanner:** Identify funds or ETFs with ERs above 0.40% as an initial screen. However, the engine must then compare **net-of-fees returns** (return after ER deduction) over 3-5 year windows before recommending a replacement. A fund charging 0.55% ER that outperforms net-of-fees is not flagged for replacement. Only funds that are both *more expensive* AND *underperforming* net-of-fees vs. available alternatives are recommended for replacement.
*   **Net-of-Fees Comparison Methodology:** Each flagged fund is compared against the **single best available alternative within the same asset routing bucket**. This ensures apples-to-apples comparison (e.g., a small-cap value fund is compared against the best small-cap alternative, not against SPY).

#### 3c. Smart Asset Routing (4-Bucket Tax Location Strategy)
The engine uses a **5-tier stable routing hierarchy** to categorize assets and route them to the most tax-efficient account type:

1. **Golden Whitelist:** Core funds (VTI, VOO, SCHX -> Taxable; QQQ, VGT, SMH -> Roth IRA) are anchored permanently to eliminate "beta-flip" noise.
2. **High-Yield Anchors:** REITS, BDCs, and Preferred Stock categories are forced to Tax-Deferred (401k) to avoid high tax drag.
3. **Category Anchoring:** Uses long-term fund classification (e.g., "Technology" -> Roth; "Municipal Bond" -> Taxable) for stability.
4. **3-Year Beta Fallback:** Volatility routing uses a 3-year lookback (increased from 1y) to ignore temporary market spikes.
5. **Default Taxable:** Final fallback for unknown asset classes.

| Bucket | Logic | Target Account | Rationale |
|---|---|---|---|
| **Maximum Growth** | Whitelist / High Beta (>1.0) | **Roth IRA** | All growth is permanently tax-free. Put your biggest compounders here. |
| **Income / Dividend** | Yield Anchors / High Yield (≥2.0%) | **Employer 401k** | Tax-deferred; dividends don't create annual drag. |
| **Income / Dividend** | High Yield (≥2.0%) | **HSA** | Triple tax advantage. Same scoring model as 401k but with full universe access. |
| **Tax-Efficient Growth** | Whitelist / Low Beta (≤1.0) | **Taxable Brokerage** | Capital appreciation without taxable events. Minimal distributions. |

**Account Name Mapping:** The engine maps CSV `Account Name` values to routing buckets:

| CSV Account Name | Routing Bucket |
|---|---|
| `INDIVIDUAL` | Taxable Brokerage |
| `Melissa Investments` | Taxable Brokerage |
| `ROTH IRA` | Roth IRA |
| `Health Savings Account` | HSA |
| `401k` (from plan parser) | Employer 401k |

**401k Replacement Constraint:** For 401k accounts, replacement recommendations are **dynamically constrained to the employer's plan menu** by extracting available fund tickers from the user's Investment Options PDF text. HSA accounts have **no such constraint** and receive the full dynamic universe. The engine does not hardcode any employer-specific data — it works for any 401k plan. See [[Pia_and_Wes_Investment_Analysis_Apr_2026]] for joint investment context.

#### 3d. Per-Account Scoring & Evaluation Metrics
Rather than a single global scoring formula, the engine uses **account-specific scoring** that weights metrics aligned to each account's investment objective:

**Individual Brokerage Account — Objective: Growth via capital appreciation, minimal distributions, tax-efficient**
*   **Primary Metrics:**
    *   **Net-of-Fees Return (5Y):** What you actually earned after expenses — the single most important number.
    *   **Sharpe Ratio:** Risk-adjusted return (return per unit of total volatility). Two funds with 12% return but different volatility are not equal — the smoother one compounds better and reduces the temptation to panic-sell during drawdowns.
*   **Tiebreaker Metrics:**
    *   **Max Drawdown:** Worst peak-to-trough decline. In a taxable account, a severe drawdown might trigger emotionally-driven selling that realizes losses at the wrong time.
    *   **Tracking Error:** For index funds, confirms the fund faithfully replicates its benchmark — a low-cost S&P 500 fund with high tracking error is a red flag.

**Roth IRA — Objective: Maximum total return, all growth permanently tax-free**
*   **Primary Metrics:**
    *   **Net-of-Fees Return (5Y):** What you actually earned — critical for your most valuable tax shelter.
    *   **Sortino Ratio:** Like Sharpe but only penalizes *downside* volatility. Perfect for aggressive growth where upside swings are welcome — you don't want to penalize a fund for going UP more than expected.
*   **Tiebreaker Metrics:**
    *   **Total Return (10Y):** The Roth has the longest horizon (untouched until retirement). The longest available track record is the best predictor of durable compounding. **If a fund has less than 10 years of price history, this metric is omitted and marked as "Insufficient History" in the report.**

**Employer 401k — Objective: Income/dividends + steady compounding, tax-deferred until retirement**
*   **Primary Metrics:**
    *   **Net-of-Fees Return (5Y):** Consistent returns matter for accounts generating income.
    *   **Sharpe Ratio:** Steady compounding requires consistency — high-volatility income funds erode predictability.
*   **Tiebreaker Metrics:**
    *   **Tracking Error:** Confirms index funds are doing their job. Especially important for bond index funds commonly held in these accounts.

**HSA — Objective: Same as 401k, with full investment universe and triple tax advantage**
*   Uses the same scoring model as Employer 401k (Sharpe + Net-of-Fees + Tracking Error).
*   HSA candidates are NOT constrained to any plan menu — they access the full dynamic universe.
*   **Triple Tax Advantage:** Contributions are pre-tax, growth is tax-free, and qualified medical withdrawals are tax-free.

**Metric Computation Details:**
*   **Risk-Free Rate:** Sharpe and Sortino ratios require a risk-free rate benchmark. This is **fetched live** from the 13-week Treasury Bill yield (ticker `^IRX`) via `yfinance` at the start of each analysis run.
*   **Tracking Error Benchmark Detection:** Tracking Error is computed against each fund's actual benchmark index, not a universal proxy. The engine uses `yfinance` fund info fields (`benchmarkTickerSymbol`, `category`) to detect the appropriate benchmark. If no benchmark can be detected, the Tracking Error metric is omitted for that fund.
*   **Metrics Module:** All risk-adjusted metrics (Sharpe, Sortino, Max Drawdown, Tracking Error, Total Return) are computed from daily price history via `yfinance` in a dedicated `metrics.py` module. If the Yahoo Finance API omits trailing summary returns (like 3Y or 5Y returns, common for mutual funds), the module automatically falls back to downloading price history and mathematically computing the exact annualized return. This module caches historical data internally to avoid redundant API calls.

#### 3e. Age-Aware Scoring & Personalization
When an `investor_profile.txt` is present (or using defaults), the engine computes an `age_factor` (0.0 = at retirement, 1.0 = 40+ years out) and applies it across all account types:
*   **Risk-Calibrated Weights:** Per-account scoring weights shift smoothly — young investors get higher growth emphasis, near-retirement investors get higher risk/drawdown emphasis.
*   **Portfolio Risk Profile:** Section 1 reports aggregate equity % vs. glide-path target for the investor's age.
*   **Holdings Flags:** Section 2 appends age-appropriate warnings (e.g., bonds in young Roth, high-beta near retirement).
*   **Replacement Penalties:** Roth IRA replacement candidates receive a 0.85x score modifier if age-inappropriate (high-beta near retirement, or bond/stable value for young investors).
*   **TLH Urgency:** Tax-loss harvesting priority labels (High/Normal/Low) based on age_factor, with a near-retirement alert callout.

**Metric Summary:**

| Metric | Individual Brokerage | Roth IRA | Employer 401k | HSA | What It Measures |
|---|---|---|---|---|---|
| Net-of-Fees Return (5Y) | ✅ Primary | ✅ Primary | ✅ Primary | ✅ Primary | Actual return after expenses |
| Sharpe Ratio | ✅ Primary | | ✅ Primary | ✅ Primary | Return per unit of total volatility |
| Sortino Ratio | | ✅ Primary | | | Return per unit of downside volatility |
| Max Drawdown | ✅ Tiebreaker | | | | Worst peak-to-trough decline |
| Tracking Error | ✅ Tiebreaker | | ✅ Tiebreaker | ✅ Tiebreaker | How closely fund tracks its benchmark |
| Total Return (10Y) | | ✅ Tiebreaker | | | Longest-term compounding track record |

### Phase 4: Output & Reporting
*   **Portfolio Analysis Report (`Portfolio_Analysis_Report.md` & PDF):** The engine outputs a comprehensive markdown document which is automatically converted to a styled PDF. Asset Holding Breakdowns must group assets under sub-headers by Account Type (Taxable Brokerage, Roth IRA, HSA, Employer 401k), sorted by Account Name then Suggested Action within each group. 401k holdings are suppressed from the per-row table and shown as a summary pointing to the dedicated Section 5 analysis. The resulting PDF output must feature clean, styled tables (black borders, padded cells, gray header rows) and MUST be rendered in a **continuous single-page custom format** (e.g. `297x2000mm`) instead of standard discrete pages to completely eliminate page breaks that cut off tables.
    *   *Example output: "Your mutual fund XYZ charges 0.65% but only returns 7.2% net-of-fees over 5 years. FSKAX returns 9.8% net-of-fees at 0.015% ER. Switching could improve your net returns."*
    *   *Example (De Minimis): "You hold 20 shares of ABC at a $1.50 STCG gain (0.3% of lot value). This is below the 1% de minimis threshold — safe to reallocate without material tax impact."*
    *   **Replacement Optimizer:** Dynamically recommends lower-fee ETF/Mutual Fund alternatives (no individual stocks). The engine generates a **Consolidated Target Portfolio** for every account, visually grouping primary scoring metrics (e.g., `Net 5Y Ret`, `Sortino (5Y)`) and ensuring target allocations sum to exactly 100.0%.
    *   **Account-First Hierarchy:** The report is organized primarily by individual accounts (Joint, Roth, HSA, 401k). Each section is self-contained with current holdings, target blueprints, and account-specific cash deployment.
    *   **HSA & Roth Aggressive Scoring:** Both HSA and Roth IRA accounts utilize the **Sortino Ratio** (downside risk only) and 10Y Total Return to prioritize maximum tax-free compounding.
    *   **401k Plan Analysis:** Integrated into the account analysis flow. Discovers plan menus dynamically, ranks all funds, and generates age-aware glide-path recommendations constrained to the employer's menu.
    *   **Master Rebalancing Logic:** Uses a **🔴 Sell & Consolidate** instruction set for underperforming assets, calculated via a "Gap vs Best" metric (comparing current holdings against top recommendations).
    *   **Executive Summary (Section 0):** Opens with a ⚡ **Immediate Execution Steps** table (concise actions with priority and tax impact) followed by narrative bullets.
    *   **Global Concentration (Section 1b):** Centralized sector exposure and holding overlap analysis across the entire portfolio.
    *   **Dual Output:** Generates both interactive HTML (with sidebar TOC) and continuously-rendered PDF reports.
    *   **Risk Tolerance & Stability Blending:** 5-level risk tolerance system (very_conservative through very_aggressive) that blends raw performance score with stability score. Auto-calculated from years to retirement if not set in `investor_profile.txt`. Stability score (0-100) uses inverse max drawdown and inverse beta.
    *   **Investor Profile (Enhanced):** `investor_profile.txt` now supports `risk_tolerance`, `state` (for tax estimates), and per-account contribution amounts (`roth_ira_contribution`, `taxable_contribution`, `hsa_contribution`, `401k_contribution`). Template auto-generated on first run. Interactive setup via launcher scripts.
    *   **State Tax Integration:** `tax_rates.py` provides federal + state combined tax rates for all 50 states + DC. Used for tax impact estimation in rebalancing recommendations.

### Phase 5: Quality Assurance (Pre-Flight Pipeline)
*   **Pre-Flight Gate:** The `validator.py` script MUST run automatically before every analysis in `portfolio_analyzer.py`. If any check fails, the engine must abort immediately and print a clear diagnostic message rather than generating a corrupted report.
*   **QA Checks (`validator.py`):**
    *   **Reality Check 1 – Ingestion Validation:** Assert that the total "Current Value" parsed by Pandas matches the raw CSV sum to within $1.00 tolerance.
    *   **Reality Check 2 – API Sanity:** Fetch SPY and SCHD and assert their yield and ER are within known-good bounds. This detects if a `yfinance` API update breaks field extraction.
    *   **Reality Check 3 – Dynamic Screener QA:** Verify that the live-scraped candidate universe passes the ETF/Mutual Fund type filter (no individual stocks), and that no candidate reports perfectly `0.0%` across all return metrics (corrupted data guard).
    *   **Reality Check 4 – Asset Routing Validation:** Fetch benchmarks (SCHD, QQQ, VTI, VGT) and assert that the 4-bucket routing math classifies them correctly:
        *   SCHD (high yield) → Tax-Deferred (401k)
        *   QQQ (high growth, high beta) → Roth IRA
        *   VTI (broad market, low yield, low beta) → Taxable Brokerage
        *   VGT (high growth, high beta) → Roth IRA (also feeds HSA pool)
    *   **Reality Check 5 – Metrics Computation:** Compute Sharpe, Sortino, Max Drawdown on SPY and assert within sane bounds.
    *   **Reality Check 6 – Wash Sale Detection:** Verify cross-account identical fund detection on synthetic data.
    *   **Reality Check 7 – Asset Classification:** Verify `classify_asset_class()` returns correct classes for SPY, AGG, VXUS.
    *   **Reality Check 8 – Risk Tolerance Mapping:** Verify all 5 risk levels have valid weight dicts summing to 1.0, and auto-computation boundaries are correct.
    *   **Reality Check 9 – Allocation Normalization:** Verify `compute_allocation()` produces percentages summing to 100% ± 0.1% with 5% floor enforcement.

### Phase 6: Zero-Config Launchers & Documentation
*   **Non-Technical Executable Wrappers:** The engine MUST provide double-click launchers for both Windows and macOS that require zero terminal knowledge:
    *   **Windows:** `Portfolio_Optimizer.ps1` — a batch file that invokes `run_optimizer.ps1`, which auto-detects an active venv, activates an existing one, or creates and initializes a new venv with all dependencies if none exists. Prompts the user to confirm fresh data before running.
    *   **macOS:** `Portfolio_Optimizer_Mac.app` — a macOS `.app` bundle wrapping `Portfolio_Optimizer.command` (a shell script with the same auto-venv logic). Handles file permissions so no terminal commands are required. A standalone `Portfolio_Optimizer.command` is also provided for users who prefer the command line.
    *   Both launchers must auto-initialize the virtual environment and install all dependencies on first run, and skip activation if a venv is already active.
*   **Living "How to Use" Guide:** A centralized guide (`docs/HOW_TO_USE.md`) defining exactly how to export CSVs from your brokerage, place them in the secure `Drop_Financial_Info_Here/` folder, trigger the interfaces, and run standalone validation.
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
*   Create a mock `Test_Positions.csv` in `src/test_data/` containing artificial edge cases:
    * Lots held exactly 364 days vs 366 days (STCG vs LTCG boundary).
    * Lots with unrealized gains below the 1% de minimis threshold (must trigger "safe to reallocate").
    * Funds with known expense ratios of 0.65% (must trigger replacement evaluation via net-of-fees comparison).
*   The Optimization Engine must successfully pass 100% of these synthetic test cases before being deemed complete.
*   **Pre-Flight Pipeline:** The `validator.py` script must be actively integrated to automatically execute and assert these reality checks *before* the markdown analyzer runs.
*   **TDD Scripts:** `test_tlh_screener.py` is used to verify Phase 1 Tax Lot Unrolling, and `test_pdf_format.py` validates continuous PDF generation logic.

## 6. Technical Stack
*   **Language:** Python 3.x
*   **Data Processing:** `pandas`, `numpy`
*   **Market Data:** `yfinance`
*   **Web Scraping (Dynamic Screener):** `requests`, `re`, `lxml`
*   **PDF Parsing (401k):** `pypdf` (inline extraction via `file_ingestor.py`)
*   **Excel Parsing (Generic fallback):** `openpyxl` (used by `GenericAdapter` for `.xlsx` broker exports)
*   **Risk Metrics:** Custom `metrics.py` module (Sharpe, Sortino, Max Drawdown, Tracking Error)
*   **Output Presentation:** Markdown report generation.
*   **Diagnostics:** `er_performance_analyzer.py` quantitatively validates the 0.40% ER screening threshold by measuring net return trade-offs.

## 7. Future Extensions
*   Backtesting engine (using `scipy.optimize` to plot the Efficient Frontier and optimize the portfolio's Sharpe ratio using trailing windows appropriate to each account's time horizon).
*   Wash-sale safety period tracker (30-day countdown timers for harvested lots).
*   Automated 401k PDF re-ingestion — detect when new statement PDFs are added to `Drop_Financial_Info_Here/` and re-parse automatically instead of requiring manual re-extraction.
