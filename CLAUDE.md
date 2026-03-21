# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Run the full optimizer (end-user flow):**
```
# Windows: Double-click Portfolio_Optimizer.bat, or run directly:
py src/portfolio_analyzer.py

# macOS: Double-click Portfolio_Optimizer_Mac.app, or run directly:
./Portfolio_Optimizer.command
```

**Run the PowerShell launcher (activates venv, prompts for fresh data confirmation):**
```powershell
PowerShell.exe -NoProfile -ExecutionPolicy Bypass -File src\run_optimizer.ps1
```

> Note: Both `Portfolio_Optimizer.bat` (via `run_optimizer.ps1`) and `Portfolio_Optimizer.command` auto-detect an active venv, activate an existing one (syncing any new `requirements.txt` deps), or create and initialize a new venv with all dependencies if none exists.

**Run validator standalone:**
```
cd src && py -c "import validator; validator.run_all_checks()"
```

**Run individual test scripts:**
```
cd src && py test_tlh_screener.py
cd src && py test_pdf_format.py
```

**Set up the virtual environment:**
```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
pip install pandas numpy yfinance requests lxml openpyxl
```
> Note: `requirements.txt` lists `markdown-pdf`, `pypdf`, and `markdown>=3.5`. The core data dependencies (`pandas`, `numpy`, `yfinance`, `requests`, `lxml`) must be installed separately. `openpyxl` is required by `GenericAdapter` for `.xlsx` broker exports.

**Run the ER diagnostic tool:**
```
cd src && py er_performance_analyzer.py
```

## Architecture

The engine follows a sequential 6-phase pipeline, all orchestrated from `src/portfolio_analyzer.py`:

### Data Flow
```
Drop_Financial_Info_Here/          ← User drops CSVs and 401k PDF here
    ├── Portfolio_Positions.csv    ← Source of truth for current quantities
    ├── Accounts_History*.csv      ← Transaction history (auto-aggregated)
    ├── investor_profile.txt           ← birth_year + retirement_year for age-aware scoring & glide-path allocation
    └── [401k Investment Options PDF]

file_ingestor.py → parsers/ (adapter layer) → portfolio_analyzer.py
                                                        ↓
                                              market_data.py + metrics.py
                                                        ↓
                                              Portfolio_Analysis_Report_*.{pdf,html}
```

### Key Files

| File | Role |
|------|------|
| `src/portfolio_analyzer.py` | Main orchestrator. Runs validator pre-flight, ingests data, applies all scoring/routing logic, generates the markdown+PDF+HTML report. |
| `src/water.min.css` | Embedded Water.css (light theme) for self-contained HTML reports. Loaded at runtime by `_render_html_report()`. |
| `src/file_ingestor.py` | 3-layer auto-dispatcher. Detects file format and broker; routes to the correct adapter. Uses `ADAPTER_REGISTRY` for 401k files. |
| `src/parser.py` | Backward-compat shim. Delegates to `FidelityAdapter` — `portfolio_analyzer.py` still calls `load_fidelity_positions()` / `load_fidelity_history()` unchanged. |
| `src/401k_parser.py` | Backward-compat shim. Re-exports 401k parsing functions from `parsers.fidelity`. |
| `src/parsers/base.py` | Abstract `BrokerAdapter` class + canonical schema constants (`CANONICAL_POSITIONS_COLS`, `CANONICAL_HISTORY_COLS`). All adapters inherit from here. |
| `src/parsers/fidelity.py` | `FidelityAdapter` — full positions/history/401k parsing logic. Normalizes actions (`YOU BOUGHT`→`Buy`) and renames columns (`Run Date`→`Date`). Also exports `unroll_tax_lots()`. |
| `src/parsers/schwab.py` | `SchwabAdapter` — positions/history parsing for Schwab CSV exports. |
| `src/parsers/vanguard.py` | `VanguardAdapter` — positions/history parsing for Vanguard CSV exports. |
| `src/parsers/troweprice.py` | `TRowePriceAdapter` — 401k PDF/text parsing for T. Rowe Price statements. |
| `src/parsers/principal.py` | `PrincipalAdapter` — 401k PDF/text parsing for Principal statements. |
| `src/parsers/generic.py` | `GenericAdapter` — fuzzy column-name fallback; last in registry, always matches. |
| `src/parsers/__init__.py` | `ADAPTER_REGISTRY` list: `[Fidelity, Schwab, Vanguard, TRowePrice, Principal, Generic]`. |
| `src/market_data.py` | `yfinance`-based market data fetcher. Scrapes live ETF/fund universe from Yahoo Finance screener pages with fallback to a hardcoded 6-fund baseline. `KNOWN_ZERO_ER_TICKERS` allowlist (money-market + Fidelity ZERO funds) bypasses the 0.0% ER fetch-error guard. |
| `src/metrics.py` | Computes Sharpe, Sortino, Max Drawdown, Tracking Error, Net-of-Fees returns, and `classify_asset_class()` (4-class fund taxonomy) from daily price history. Internal caching prevents redundant API calls. Falls back to computed annualized returns if Yahoo's trailing summaries are missing. |
| `src/validator.py` | Pre-flight gate. 4 reality checks (ingestion checksum, API sanity, dynamic screener QA, asset routing validation). Aborts `portfolio_analyzer.py` on any failure. |
| `src/er_performance_analyzer.py` | Diagnostic tool to validate the 0.40% ER screening threshold via net-return trade-off analysis. |

### Canonical Schema (all adapters must produce)

**Positions:** `Symbol`, `Description`, `Account Name`, `Account Type`, `Quantity`, `Current Value`, `Cost Basis Total`, `Average Cost Basis`, `Expense Ratio`

**History:** `Date` (datetime), `Action` (`Buy` | `Sell` | `Reinvestment` | `Dividend` | `Transfer`), `Symbol`, `Description`, `Quantity`, `Price`, `Amount`, `Account Name`

### Core Business Logic in `portfolio_analyzer.py`

**4-Bucket Routing (`classify_routing_bucket`):**
- High yield (≥ 2%) → `Tax-Deferred` (401k only)
- Low yield + high beta (> 1.0) → `Roth IRA` (candidates also populate HSA pool — HSA uses Roth IRA growth-scoring tier)
- Low yield + low beta → `Taxable Brokerage`

**Account Name → Bucket Mapping (`ACCOUNT_TYPE_MAP`):**
- `INDIVIDUAL`, `Melissa Investments` → Taxable Brokerage
- `ROTH IRA` → Roth IRA
- `Health Savings Account` → HSA
- `401k` → Employer 401k

**Per-Account Scoring (`score_candidate`):**
- Taxable Brokerage: Sharpe Ratio + Net-of-Fees 5Y Return (tiebreaker: Max Drawdown, Tracking Error)
- Roth IRA: Sortino Ratio + Net-of-Fees 5Y Return + Max Drawdown (tiebreaker: 10Y Total Return)
- HSA: Same as Roth IRA — same growth tier
- 401k: Sharpe Ratio + Net-of-Fees 5Y Return (tiebreaker: Tracking Error)
- All weights shift smoothly via `age_factor` when `years_to_retirement` is provided

**Key constants:**
- `DE_MINIMIS_GAIN_PCT = 0.01` — STCG gains below 1% of lot value are flagged safe to reallocate
- `SUBSTANTIALLY_IDENTICAL_MAP` — maps tickers to groups for wash-sale cross-account detection
- `ACCOUNT_TYPE_MAP` — CSV account name → routing bucket
- `GLIDE_PATH` — piecewise linear equity/bond curve: `[(40, 0.90), (25, 0.80), (10, 0.60), (0, 0.50), (-7, 0.30)]`
- `EQUITY_SPLIT` — within equity allocation: 70% US Equity, 30% Intl Equity
- `DEFAULT_BIRTH_YEAR = 1990`, `DEFAULT_RETIREMENT_YEAR = 2057` — used when `investor_profile.txt` is absent
- `MIN_ALLOCATION_PCT = 5` — minimum per-fund allocation floor in Section 5e

**Age-Aware Engine:**
- `compute_age_factor(years_to_retirement)` — returns 0.0 (at retirement) to 1.0 (40+ years out); linear interpolation
- `score_candidate()` accepts optional `years_to_retirement` — shifts per-account weights smoothly via `age_factor`
- Section 1: Portfolio Risk Profile callout (actual equity % vs glide-path target)
- Section 2: `get_age_flag()` appends italic age-appropriate warnings to Suggested Action column
- Section 3: TLH urgency labels (High/Normal/Low) based on age_factor; near-retirement alert callout
- Section 4: 0.85x penalty for age-inappropriate Roth IRA candidates
- Section 6: Next Steps — contextual action items grouped by category (ER replacements, TLH, 401k, age-inappropriate)
- Section 7: Why These Recommendations — Tier 1 plain-English verdict table + Tier 2 methodology (collapsible in HTML via `<!-- DETAILS_START/END -->` markers)

**401k Allocation Engine (Section 5e):**
- `load_investor_profile(data_dir)` — parses `investor_profile.txt` for `birth_year` and `retirement_year`; returns defaults if missing
- `compute_target_allocation(years_to_retirement)` — interpolates glide path → `{US Equity, Intl Equity, Bond, Stable Value}` percentages summing to 100
- `classify_asset_class(ticker)` (in `metrics.py`) — classifies funds into 4 classes via yfinance `category` + fund name keywords
- Section 5e renders a recommended allocation table with Current %, Target %, Change, and Action columns

**Findings Collector & New Report Sections:**
- `findings = []` list populated at 6 points during report generation (high-ER, risk alignment, age-inappropriate, TLH, STCG, 401k rebalance)
- `_render_executive_summary(findings)` — Section 0, 3-5 auto-generated bullets with section refs; spliced before Section 1
- `_render_next_steps(...)` — Section 6, grouped action items with tax context (ER replacements, TLH, 401k, age-inappropriate)
- `_render_verdict_table(df, metadata, age_factor)` — Section 7 Tier 1, plain-English Keep/Replace/Evaluate per holding
- `_render_html_report(markdown_content, table_css)` — converts markdown to self-contained HTML with TOC, collapsible `<details>` for Tier 2 methodology, embedded Water.css

### Known Open Constraints (`docs/CONSTRAINTS.md`)

These are tracked architectural issues that have not yet been implemented:

- **[ADVISORY-1]** `Melissa Investments` needs formal `managed_advisory` account type with partitioned reporting, isolated TLH, and excluded from primary user's portfolio-level metrics.

### Tax Lot Unrolling Rules
- Source of truth for current shares: `Portfolio_Positions.csv` (must be fresh per run)
- The unroller **intentionally ignores sell transactions** from history CSVs — sells are already reflected in the positions file; processing them would double-count share depletion.
- `Account Name` is copied from `positions_df` into every lot record (both buy-matched and fallback lots) so downstream TLH logic can filter and group by account.
- FIFO accounting for lot ordering.
- 401k accounts are exempt from tax lot analysis (tax-deferred).
- **TLH is filtered to `Taxable Brokerage` accounts only** — losses in Roth IRA, HSA, and 401k have no tax benefit and are excluded from TLH output.

### Output
The engine outputs dual reports to `Drop_Financial_Info_Here/.cache/`:
- **HTML** (`Portfolio_Analysis_Report_<timestamp>.html`): Self-contained with embedded Water.css, clickable TOC, collapsible methodology section via `<details>`. Auto-opened in browser.
- **PDF** (`Portfolio_Analysis_Report_<timestamp>.pdf`): Continuous single-page format with dynamic height (`max(210, 50 + line_count * 6.5)` mm). DETAILS markers stripped; all content renders inline.

### Privacy Constraint
No raw financial data (dollar amounts, account numbers) may be printed to stdout during execution. Only anonymized ticker symbols are sent to external APIs via `yfinance`.
