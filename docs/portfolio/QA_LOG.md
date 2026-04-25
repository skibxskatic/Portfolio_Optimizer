# QA Log

This log documents the validation checks, common issues found during testing, and the corresponding fixes implemented in `validator.py` and the core engine.

## 1. Automated Validation Suite (`validator.py`)

Every run is preceded by a "Reality Check" suite to ensure data integrity.

| Check Name | Purpose | Outcome/Fix |
|------------|---------|-------------|
| **Ingestion Checksum** | Matches raw CSV text totals with parsed DataFrame totals. | Prevents data loss during CSV parsing (e.g., dropped fractional shares). |
| **API Sanity** | Fetches benchmarks (SPY, SCHD) and verifies yield/ER bounds. | Catches breaking changes in `yfinance` scraper logic early. |
| **Dynamic Screener QA** | Filters raw ETF scrapes to ensure only pure ETFs/Funds are returned. | Prevents individual stocks from entering the recommendation pool. |
| **Asset Routing QA** | Verifies benchmarks route to correct tax buckets (Taxable, Roth, etc.). | Ensures the 6-tier routing engine is mathematically sound. |
| **Metrics QA** | Asserts Sharpe/Sortino/MaxDD for SPY are within realistic bounds. | Catches regressions in the mathematical engine. |
| **Wash Sale Detection** | Verifies cross-account identical fund detection on synthetic data. | Ensures users are alerted to IRS wash sale risks across multiple brokers. |

## 2. Platform Reliability Issues

### [QA-001] Windows WMI Startup Hang
- **Issue**: Process hangs indefinitely on startup for Windows users with Python 3.13.
- **Root Cause**: `platform.machine()` trigger a WMI call that deadlocks in certain Python 3.13 environments.
- **Fix**: Implemented a monkeypatch in `validator.py`:
  ```python
  platform.machine = lambda: os.environ.get('PROCESSOR_ARCHITECTURE', 'AMD64')
  ```

### [QA-002] Terminal Emoji Encoding
- **Issue**: Report generation crashes on Windows `cmd.exe` or older PowerShell versions due to UTF-8 emoji characters.
- **Fix**: Removed all terminal-only emojis and moved them to the HTML report layer where CSS handles rendering.

## 3. Data Integrity Issues

### [QA-003] Phantom Losses in TLH
- **Issue**: Tax-loss harvesting report showed massive losses for NVDA after its 10-for-1 split.
- **Root Cause**: The engine was using split-unadjusted cost basis from historical data but current (split-adjusted) price.
- **Fix**: Implemented `Stock Split Normalization` that pulls corporate actions from `yfinance` and adjusts historical cost basis automatically.

### [QA-004] Cross-Account Lot Mixing
- **Issue**: Buying SPY in a Roth IRA was overriding the cost basis of SPY in a Taxable Brokerage.
- **Root Cause**: The unrolling engine matched symbols globally.
- **Fix**: Added "Account Name" as a mandatory grouping key for lot matching.
