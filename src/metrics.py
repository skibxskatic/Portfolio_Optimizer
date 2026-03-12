"""
metrics.py — Risk-Adjusted Performance Metrics Engine

Computes Sharpe Ratio, Sortino Ratio, Max Drawdown, Tracking Error,
Total Return, and Net-of-Fees Return from yfinance historical price data.

All functions share an internal price history cache to avoid redundant API calls.
"""

import yfinance as yf
import numpy as np
import pandas as pd
from typing import Optional, Dict, Any

# --- Internal Cache ---
_price_cache: Dict[str, pd.DataFrame] = {}
_info_cache: Dict[str, dict] = {}
_risk_free_rate_cache: Optional[float] = None


def _get_price_history(ticker: str, period: str = "5y") -> Optional[pd.DataFrame]:
    """
    Fetches daily closing prices for a ticker from yfinance, with caching.
    Returns a DataFrame with 'Close' column indexed by date, or None on failure.
    """
    cache_key = f"{ticker}_{period}"
    if cache_key in _price_cache:
        return _price_cache[cache_key]

    try:
        t = yf.Ticker(ticker)
        hist = t.history(period=period)
        if hist.empty or len(hist) < 30:
            return None
        _price_cache[cache_key] = hist
        return hist
    except Exception:
        return None


def _get_ticker_info(ticker: str) -> dict:
    """Fetches and caches yfinance .info for a ticker."""
    if ticker in _info_cache:
        return _info_cache[ticker]
    try:
        t = yf.Ticker(ticker)
        info = t.info
        _info_cache[ticker] = info
        return info
    except Exception:
        return {}


def fetch_risk_free_rate() -> float:
    """
    Fetches the current risk-free rate from the 13-week Treasury Bill yield (^IRX).
    Returns the annualized rate as a decimal (e.g., 0.045 for 4.5%).
    Falls back to 0.04 if the fetch fails.
    """
    global _risk_free_rate_cache
    if _risk_free_rate_cache is not None:
        return _risk_free_rate_cache

    try:
        irx = yf.Ticker("^IRX")
        hist = irx.history(period="5d")
        if not hist.empty:
            # ^IRX quotes yield as a percentage (e.g., 4.5 = 4.5%)
            rate = hist['Close'].iloc[-1] / 100.0
            if 0.0 <= rate <= 0.15:  # Sanity: 0% to 15%
                _risk_free_rate_cache = rate
                return rate
    except Exception:
        pass

    _risk_free_rate_cache = 0.04  # Fallback
    return _risk_free_rate_cache


def compute_beta(ticker: str, market: str = "SPY", period: str = "1y") -> Optional[float]:
    """
    Computes beta from historical daily returns using Covariance / Variance.
    More precise than the rounded yfinance .info beta field.
    Returns None if insufficient data.
    """
    fund_hist = _get_price_history(ticker, period)
    market_hist = _get_price_history(market, period)
    if fund_hist is None or market_hist is None:
        return None

    try:
        fund_returns = fund_hist['Close'].pct_change().dropna()
        market_returns = market_hist['Close'].pct_change().dropna()

        aligned = pd.DataFrame({
            'fund': fund_returns,
            'market': market_returns
        }).dropna()

        if len(aligned) < 30:
            return None

        cov = aligned['fund'].cov(aligned['market'])
        var = aligned['market'].var()
        if var == 0:
            return None

        beta = cov / var
        return round(float(beta), 3)
    except Exception:
        return None


def compute_sharpe_ratio(ticker: str, period: str = "5y") -> Optional[float]:
    """
    Computes the annualized Sharpe Ratio for a ticker.
    Sharpe = (Annualized Return - Risk-Free Rate) / Annualized Volatility
    Returns None if insufficient data.
    """
    hist = _get_price_history(ticker, period)
    if hist is None or len(hist) < 60:
        return None

    try:
        daily_returns = hist['Close'].pct_change().dropna()
        if daily_returns.std() == 0:
            return None

        annualized_return = daily_returns.mean() * 252
        annualized_vol = daily_returns.std() * np.sqrt(252)
        rf = fetch_risk_free_rate()

        sharpe = (annualized_return - rf) / annualized_vol
        return round(float(sharpe), 3)
    except Exception:
        return None


def compute_sortino_ratio(ticker: str, period: str = "5y") -> Optional[float]:
    """
    Computes the annualized Sortino Ratio for a ticker.
    Sortino = (Annualized Return - Risk-Free Rate) / Annualized Downside Deviation
    Only penalizes downside volatility — upside swings are welcome.
    Returns None if insufficient data.
    """
    hist = _get_price_history(ticker, period)
    if hist is None or len(hist) < 60:
        return None

    try:
        daily_returns = hist['Close'].pct_change().dropna()

        # Downside deviation: only negative returns
        negative_returns = daily_returns[daily_returns < 0]
        if len(negative_returns) == 0:
            return None  # No downside days — can't compute

        downside_dev = negative_returns.std() * np.sqrt(252)
        if downside_dev == 0:
            return None

        annualized_return = daily_returns.mean() * 252
        rf = fetch_risk_free_rate()

        sortino = (annualized_return - rf) / downside_dev
        return round(float(sortino), 3)
    except Exception:
        return None


def compute_max_drawdown(ticker: str, period: str = "5y") -> Optional[float]:
    """
    Computes the Maximum Drawdown (worst peak-to-trough decline) for a ticker.
    Returns a negative percentage (e.g., -0.35 for a 35% drawdown).
    Returns None if insufficient data.
    """
    hist = _get_price_history(ticker, period)
    if hist is None or len(hist) < 30:
        return None

    try:
        prices = hist['Close']
        cumulative_max = prices.cummax()
        drawdown = (prices - cumulative_max) / cumulative_max
        max_dd = drawdown.min()
        return round(float(max_dd), 4)
    except Exception:
        return None


def detect_benchmark(ticker: str) -> Optional[str]:
    """
    Attempts to detect the appropriate benchmark index for a fund.
    Uses yfinance fund info fields to determine the benchmark.
    Returns the benchmark ticker symbol, or None if detection fails.
    """
    info = _get_ticker_info(ticker)

    # 1. Direct benchmark field (some funds have this)
    benchmark = info.get("benchmarkTickerSymbol")
    if benchmark and isinstance(benchmark, str) and len(benchmark) > 0:
        return benchmark

    # 2. Infer from category
    category = (info.get("category") or "").lower()
    fund_name = (info.get("shortName") or "").lower()

    # Large-cap / S&P 500
    if any(k in category for k in ["large blend", "large cap", "s&p 500", "large growth", "large value"]):
        return "SPY"
    if "s&p 500" in fund_name or "500 index" in fund_name:
        return "SPY"

    # Mid-cap
    if "mid-cap" in category or "mid cap" in category:
        return "IJH"  # iShares Core S&P MidCap 400

    # Small-cap
    if "small" in category:
        return "IJR"  # iShares Core S&P SmallCap 600

    # International / Global
    if any(k in category for k in ["foreign", "international", "world", "global", "emerging"]):
        return "VXUS"  # Vanguard Total International

    # Bond / Fixed Income
    if any(k in category for k in ["bond", "fixed income", "income", "intermediate"]):
        return "AGG"  # iShares Core US Aggregate Bond

    # Nasdaq
    if "nasdaq" in fund_name or "nasdaq" in category:
        return "QQQ"

    # Total market
    if "total market" in fund_name or "total stock" in fund_name:
        return "VTI"

    return None


def compute_tracking_error(ticker: str, benchmark: Optional[str] = None, period: str = "5y") -> Optional[float]:
    """
    Computes the annualized Tracking Error vs. benchmark.
    Tracking Error = Annualized Std Dev of (Fund Return - Benchmark Return).
    If no benchmark is provided, attempts to detect one.
    Returns None if benchmark detection fails or data is insufficient.
    """
    if benchmark is None:
        benchmark = detect_benchmark(ticker)
    if benchmark is None:
        return None

    fund_hist = _get_price_history(ticker, period)
    bench_hist = _get_price_history(benchmark, period)
    if fund_hist is None or bench_hist is None:
        return None

    try:
        fund_returns = fund_hist['Close'].pct_change().dropna()
        bench_returns = bench_hist['Close'].pct_change().dropna()

        # Align dates
        aligned = pd.DataFrame({
            'fund': fund_returns,
            'bench': bench_returns
        }).dropna()

        if len(aligned) < 60:
            return None

        tracking_diff = aligned['fund'] - aligned['bench']
        te = tracking_diff.std() * np.sqrt(252)
        return round(float(te), 4)
    except Exception:
        return None


def compute_total_return(ticker: str, period: str = "10y") -> Optional[float]:
    """
    Computes the total cumulative return over the given period.
    Returns the return as a decimal (e.g., 1.5 for 150% total return).
    Returns None if the fund has less than the requested history.
    """
    hist = _get_price_history(ticker, period)
    if hist is None:
        return None

    try:
        # Check if we actually got enough data for the requested period
        years_map = {"10y": 9, "5y": 4, "3y": 2}
        min_years = years_map.get(period, 4)
        actual_days = (hist.index[-1] - hist.index[0]).days
        if actual_days < min_years * 365:
            return None  # Insufficient history

        total_return = (hist['Close'].iloc[-1] / hist['Close'].iloc[0]) - 1
        return round(float(total_return), 4)
    except Exception:
        return None

def compute_trailing_return_annualized(ticker: str, period: str) -> Optional[float]:
    """
    Computes the annualized trailing return over the given period.
    Returns the annualized return as a decimal (e.g., 0.12 for 12% annualized return).
    Returns None if insufficient history.
    """
    hist = _get_price_history(ticker, period)
    if hist is None:
        return None

    try:
        actual_days = (hist.index[-1] - hist.index[0]).days
        if actual_days < 365:
            return None
        
        years = actual_days / 365.25
        gross_total = (hist['Close'].iloc[-1] / hist['Close'].iloc[0])
        annualized_gross = gross_total ** (1 / years) - 1
        return round(float(annualized_gross), 4)
    except Exception:
        return None


def get_history_days(ticker: str, period: str = "10y") -> int:
    """
    Returns the number of calendar days of available price history for a ticker.
    Uses the internal cache — no extra API calls if the ticker was already scored.
    Returns 0 if history is unavailable.
    """
    hist = _get_price_history(ticker, period)
    if hist is None or len(hist) < 2:
        return 0
    return (hist.index[-1] - hist.index[0]).days


def compute_net_of_fees_return(ticker: str, period: str = "5y") -> Optional[float]:
    """
    Computes the annualized net-of-fees return.
    Net Return = Annualized Gross Return - Expense Ratio
    Returns the annualized return as a decimal (e.g., 0.12 for 12%).
    """
    hist = _get_price_history(ticker, period)
    if hist is None:
        return None

    try:
        actual_days = (hist.index[-1] - hist.index[0]).days
        if actual_days < 365:
            return None

        years = actual_days / 365.25
        gross_total = (hist['Close'].iloc[-1] / hist['Close'].iloc[0])
        annualized_gross = gross_total ** (1 / years) - 1

        # Get expense ratio
        info = _get_ticker_info(ticker)
        net_er = info.get("netExpenseRatio")
        ann_er = info.get("annualReportExpenseRatio")
        if net_er is not None:
            er = float(net_er) / 100.0  # netExpenseRatio is already percentage
        elif ann_er is not None:
            er = float(ann_er)  # annualReportExpenseRatio is decimal
        else:
            er = 0.0

        net_return = annualized_gross - er
        return round(float(net_return), 4)
    except Exception:
        return None


def get_fund_metrics(ticker: str, account_type: str) -> Dict[str, Any]:
    """
    Returns the evaluation metrics relevant to the given account type.

    Account types: "Taxable Brokerage", "Roth IRA", "Tax-Deferred"

    Returns a dict with metric names as keys and computed values.
    Metrics that cannot be computed are set to None.
    """
    result = {
        "ticker": ticker,
        "account_type": account_type,
        "net_of_fees_5y": compute_net_of_fees_return(ticker, "5y"),
    }

    if account_type == "Taxable Brokerage":
        result["sharpe_ratio"] = compute_sharpe_ratio(ticker, "5y")
        result["max_drawdown"] = compute_max_drawdown(ticker, "5y")
        result["tracking_error"] = compute_tracking_error(ticker, period="5y")

    elif account_type == "Roth IRA":
        result["sortino_ratio"] = compute_sortino_ratio(ticker, "5y")
        total_10y = compute_total_return(ticker, "10y")
        result["total_return_10y"] = total_10y
        result["total_return_10y_available"] = total_10y is not None

    elif account_type == "Tax-Deferred":
        result["sharpe_ratio"] = compute_sharpe_ratio(ticker, "5y")
        result["tracking_error"] = compute_tracking_error(ticker, period="5y")

    return result


def clear_cache():
    """Clears all internal caches. Useful between analysis runs."""
    global _price_cache, _info_cache, _risk_free_rate_cache
    _price_cache = {}
    _info_cache = {}
    _risk_free_rate_cache = None


if __name__ == "__main__":
    # Smoke test
    print("=== Metrics Engine Smoke Test ===\n")

    rf = fetch_risk_free_rate()
    print(f"Risk-Free Rate (^IRX): {rf*100:.2f}%\n")

    test_tickers = {"SPY": "Taxable Brokerage", "QQQ": "Roth IRA", "SCHD": "Tax-Deferred"}

    for ticker, acct in test_tickers.items():
        print(f"--- {ticker} ({acct}) ---")
        metrics = get_fund_metrics(ticker, acct)
        for key, val in metrics.items():
            if key in ("ticker", "account_type"):
                continue
            if val is None:
                print(f"  {key}: N/A")
            elif isinstance(val, float):
                if "return" in key or "drawdown" in key:
                    print(f"  {key}: {val*100:.2f}%")
                else:
                    print(f"  {key}: {val:.3f}")
            else:
                print(f"  {key}: {val}")
        print()
