# Decision Log

This document records the key architectural and design decisions for the **Portfolio Optimizer**, providing context and rationale for each.

## [D-001] Local-Only Privacy Focus
- **Status**: Accepted
- **Context**: Financial data is extremely sensitive. Users are hesitant to upload CSVs to cloud services.
- **Decision**: The engine must be 100% local-only. No data leaves the machine except for ticker-only metadata requests to Yahoo Finance.
- **Consequences**: No cloud database or web interface (unless hosted locally). Data persistence must use local files (Pickle/JSON).

## [D-002] yfinance Caching Strategy
- **Status**: Accepted
- **Context**: Frequent calls to Yahoo Finance can lead to rate limiting and slow report generation.
- **Decision**: Implement a 24-hour disk-based cache (`.yfinance_cache/`).
- **Rationale**: Ticker metadata (expense ratios, yields) and historical data don't change frequently enough to warrant per-run fetches. 24 hours provides a good balance between fresh data and performance.

## [D-003] Account Isolation for Tax Lot Unrolling
- **Status**: Accepted
- **Context**: In multi-broker/multi-account setups, a user might buy $SPY in a Roth IRA and an Individual Brokerage.
- **Decision**: Historical purchase lots must be matched only to positions within the *same* account name.
- **Rationale**: Prevents "phantom wash sale" warnings or cost-basis errors that occur when the engine tries to apply a Taxable lot to a Roth position.

## [D-004] Stock Split Normalization
- **Status**: Accepted
- **Context**: Tickers like NVDA or AAPL undergo splits, making historical cost-basis look artificially high if not adjusted.
- **Decision**: Use `yfinance` to fetch authoritative corporate action history and adjust all historical lots before calculating gains/losses.
- **Rationale**: Ensures the Tax-Loss Harvesting (TLH) report is accurate and doesn't recommend selling "losses" that are actually gains after split adjustment.

## [D-005] Python 3.13 WMI Monkeypatch
- **Status**: Accepted
- **Context**: Python 3.13 on Windows has a known bug where `platform.machine()` (called by pandas/numpy) can hang the entire process due to WMI deadlocks.
- **Decision**: Implement a monkeypatch in `validator.py` that intercepts `platform.machine()` and returns an environment variable instead of calling WMI.
- **Rationale**: Ensures the application remains usable on the latest Python versions without waiting for upstream fixes.

## [D-006] Choice of Sortino vs. Sharpe
- **Status**: Accepted
- **Context**: Different accounts have different risk profiles.
- **Decision**: Use Sortino for tax-free accounts (Roth/HSA) and Sharpe for taxable accounts.
- **Rationale**: Sortino focuses on downside risk, which is more critical in accounts where you cannot "deduct" losses and want to maximize compounding.
