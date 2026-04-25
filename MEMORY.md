# Portfolio Optimizer - Shared Memory

## Project Overview
The **Portfolio Optimizer** is a local, privacy-first Python engine for analyzing investment portfolios, identifying tax-loss harvesting (TLH) opportunities, and recommending tax-efficient fund placements. See [[PRD]] and [[HOW_IT_WORKS]] for details.

## Architecture & Core Logic

### Data Flow
- `file_ingestor.py` → `parsers/` (adapter layer) → `portfolio_analyzer.py`
- Main orchestrator: `src/portfolio_analyzer.py`

### 6-Tier Stable Routing (v2 Engine)
- **Account-Specific Anchors:** (NEW) Account-level whitelist (e.g., Joint Brokerage) for targeted 3-5 year growth strategies.
- **Whitelist:** Anchors core funds (VTI, QQQ, VOO) to optimal accounts permanently.
- **High-Yield Anchors:** Category-based override for REITs and BDCs.
- **Category Anchoring:** Long-term type-based routing for stability.
- **3Y Beta Fallback:** Uses 3-year volatility lookback to ignore short-term spikes.
- **Default Taxable:** Final fallback for unknown/unmatched assets.

### Scoring Logic
- **Taxable:** Sharpe Ratio + Net-of-Fees 5Y Return.
- **Roth/HSA:** Sortino Ratio + Net-of-Fees 5Y Return + Max Drawdown.
- **Risk Tolerance:** 5 levels (very_aggressive to very_conservative) blending score and stability.

### Tax Lot Unrolling
- FIFO accounting.
- **Stock Split Normalization:** (NEW) Automatically adjusts historical purchase quantity and price for corporate actions (splits) using authoritative data from `yfinance`. Prevents "phantom losses" in TLH reports.
- **Account-Level Isolation:** (NEW) Ensures historical buys are matched only to positions within the same account (Individual vs. Roth vs. Melissa). Prevents cross-account lot matching errors in multi-account portfolios.
- **TLH is filtered to Taxable Brokerage accounts only.**
- Sells are ignored from history (positions file is the source of truth for quantity).

### Development Conventions
1. **Privacy:** Never log raw dollar amounts or account numbers.
2. **Buy-and-Hold:** Long-term efficiency focus.
3. **Validation:** `src/validator.py` must pass before any analysis run.
4. **Python Command:** Use `py` on Windows.

## Key Files & Roles
- `src/portfolio_analyzer.py`: Main orchestrator.
- `src/market_data.py`: `yfinance` data fetcher (uses concurrent.futures).
- `src/metrics.py`: Mathematical module with disk-based prefetching.
- `src/validator.py`: Pre-flight gatekeeper with 24h caching.
- `src/tax_rates.py`: Bracket-aware federal/state tax lookup.
- `src/tax_brackets.py`: High-precision tax bracket logic (2026 data).

## Recent Optimizations
- **Concurrency:** `market_data.py` uses `ThreadPoolExecutor` for parallel ticker metadata fetching.
- **Caching:** `metrics.py` implements a 24h disk-based cache (`.yfinance_cache`) and `prefetch_histories()`. Now includes a `_splits_cache` that extracts corporate actions (stock splits) from historical data to enable offline normalization. `validator.py` caches successful preflight runs for 24h.
- **Tax Precision:** Replaced static capital gains estimates with full 2026 IRS tax tables for precise marginal rate lookups.
- **Unification:** `401k_parser.py` legacy code removed from `portfolio_analyzer.py`, routing all ingestion through `file_ingestor.py`.
- **Launcher:** Replaced legacy Windows batch file with a native `Portfolio_Optimizer.ps1` execution script.
- **Stable Routing Engine (v2):** Expanded to a 6-tier hierarchy (Account-Specific -> Whitelist -> Yield -> Category -> Beta) to support strategic goals like the "Joint Brokerage" growth plan without triggering tax-inefficiency flags.
- **Professional Report Logic:** Deduplicated "Holding Overlap" analysis, added dollar-based TLH prioritization with tax savings estimates, and implemented an age-aware "Action Plan" summary table.
- **Corporate Action Integrity:** Implemented authoritative stock split normalization in the unrolling engine (`parsers/fidelity.py`) to ensure TLH accuracy for split-adjusted tickers (e.g. VGT, AAPL, NVDA). Uses cached split history to function in local-only environments.
- **Windows Reliability:** Removed all terminal emojis and implemented a Python 3.13 WMI monkeypatch to prevent encoding errors and startup hangs on Windows.
