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

> Note: Both `Portfolio_Optimizer.bat` (via `run_optimizer.ps1`) and `Portfolio_Optimizer.command` auto-detect an active venv, activate an existing one, or create and initialize a new venv with all dependencies if none exists.

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
> Note: `requirements.txt` only lists `markdown-pdf` and `pypdf`. The core data dependencies (`pandas`, `numpy`, `yfinance`, `requests`, `lxml`) must be installed separately. `openpyxl` is required by `GenericAdapter` for `.xlsx` broker exports.

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
    └── [401k Investment Options PDF]

file_ingestor.py → parsers/ (adapter layer) → portfolio_analyzer.py
                                                        ↓
                                              market_data.py + metrics.py
                                                        ↓
                                              Portfolio_Analysis_Report_*.pdf
```

### Key Files

| File | Role |
|------|------|
| `src/portfolio_analyzer.py` | Main orchestrator. Runs validator pre-flight, ingests data, applies all scoring/routing logic, generates the markdown+PDF report. |
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
| `src/market_data.py` | `yfinance`-based market data fetcher. Scrapes live ETF/fund universe from Yahoo Finance screener pages with fallback to a hardcoded 6-fund baseline. |
| `src/metrics.py` | Computes Sharpe, Sortino, Max Drawdown, Tracking Error, and Net-of-Fees returns from daily price history. Internal caching prevents redundant API calls. Falls back to computed annualized returns if Yahoo's trailing summaries are missing. |
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

**Per-Account Scoring (`score_candidate`):**
- Taxable Brokerage: Sharpe Ratio + Net-of-Fees 5Y Return (tiebreaker: Max Drawdown, Tracking Error)
- Roth IRA: Sortino Ratio + Net-of-Fees 5Y Return (tiebreaker: 10Y Total Return)
- HSA: Sortino Ratio + Net-of-Fees 5Y Return (tiebreaker: 10Y Total Return) — same growth tier as Roth IRA
- 401k: Sharpe Ratio + Net-of-Fees 5Y Return (tiebreaker: Tracking Error)

**Key constants:**
- `DE_MINIMIS_GAIN_PCT = 0.01` — STCG gains below 1% of lot value are flagged safe to reallocate
- `SUBSTANTIALLY_IDENTICAL_MAP` — maps tickers to groups for wash-sale cross-account detection
- `ACCOUNT_TYPE_MAP` — CSV account name → routing bucket

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
The engine outputs `Portfolio_Analysis_Report_<timestamp>.pdf` to `Drop_Financial_Info_Here/.cache/`. The PDF uses a continuous single-page format with dynamic height (`max(210, 50 + line_count * 6.5)` mm) to eliminate page breaks cutting through tables.

### Privacy Constraint
No raw financial data (dollar amounts, account numbers) may be printed to stdout during execution. Only anonymized ticker symbols are sent to external APIs via `yfinance`.
