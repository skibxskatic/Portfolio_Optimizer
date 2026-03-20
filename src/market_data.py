import yfinance as yf
import pandas as pd
import requests
import re
import metrics
from typing import Dict, Any

# Tickers that legitimately carry a 0.0% expense ratio as reported by yfinance.
# Includes money-market funds and Fidelity ZERO index funds.
# Excludes them from the ER fetch-error guard (which converts 0.0 → None).
KNOWN_ZERO_ER_TICKERS = {"FDRXX", "SPAXX", "FDLXX", "VMFXX", "SWVXX", "FNILX", "FZROX", "FZILX", "FZIPX"}

def get_dynamic_etf_universe() -> list[str]:
    """
    Dynamically scrapes live Top ETFs and Top Mutual Funds from Yahoo Finance.
    Provides a real-time list of candidate tickers for the optimization engine.
    """
    urls = [
        "https://finance.yahoo.com/etfs",
        "https://finance.yahoo.com/screener/predefined/top_mutual_funds"
    ]
    tickers = set()
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    
    for url in urls:
        try:
            r = requests.get(url, headers=headers, timeout=10)
            matches = re.findall(r'href="/quote/([A-Z]{2,5})[/?]', r.text)
            for m in matches:
                tickers.add(m)
        except Exception:
            pass
            
    # Always include a solid baseline of 1-3yr dividend funds 
    # to guarantee safety matches if the regex misses during UI changes
    for b in ["SCHD", "VYM", "SPYD", "VIG", "FDVV", "DGRO"]:
        tickers.add(b)
        
    return list(tickers)

def fetch_ticker_metadata(tickers: list[str]) -> Dict[str, Dict[str, Any]]:
    """
    Fetches market metadata for a list of tickers using yfinance.
    Only the ticker symbols are sent to the Yahoo Finance API.
    No user account quantities or dollar values are ever transmitted.
    """
    metadata = {}
    
    # Clean tickers (remove cash equivalents or invalid symbols)
    valid_tickers = [t for t in tickers if isinstance(t, str) and len(t) > 0 and t.upper() != "PENDING ACTIVITY" and t.upper() != "CORE"]

    for ticker in set(valid_tickers):
        try:
            # For Fidelity money market funds like SPAXX, yfinance might not have full data,
            # but we can try to fetch the basic info
            if getattr(ticker, "endswith", lambda x: False)("XX"):
                 # It's likely a mutual fund or money market
                 type_str = "MUTUALFUND"
            else:
                 type_str = "EQUITY/ETF"

            t = yf.Ticker(ticker)
            info = t.info
            
            # Extract key metrics needed for 1-3 year optimization
            # Yield handling: 'yield' is decimal, 'dividendYield' is a whole percentage (e.g. 3.51)
            raw_yield = info.get("yield")
            if raw_yield is None:
                div_yield = info.get("dividendYield", 0.0)
                raw_yield = div_yield / 100.0 if div_yield else 0.0
            
            # Expense Ratio handling: ETFs use 'netExpenseRatio' (already a percentage), Mutual Funds use 'annualReportExpenseRatio' (decimal)
            net_er = info.get("netExpenseRatio")
            ann_er = info.get("annualReportExpenseRatio")
            if net_er is not None:
                er_pct = float(net_er)
            elif ann_er is not None:
                er_pct = float(ann_er) * 100.0
            else:
                er_pct = 0.0
            # Guard: a 0.0% ER is only valid for known zero-ER funds.
            # For all others, treat it as a fetch error (None) so it is excluded
            # from weighted-average ER and ER-filter screening.
            if er_pct == 0.0 and ticker not in KNOWN_ZERO_ER_TICKERS:
                er_pct = None
                
            # 1-Year Return handling: Stocks use '52WeekChange' (decimal), ETFs use 'ytdReturn' (percent)
            ret_1y = info.get("52WeekChange")
            if ret_1y is None:
                ytd = info.get("ytdReturn", 0.0)
                ret_1y = ytd / 100.0 if ytd else 0.0
                
            # 3-Year Return handling
            ret_3y = info.get("threeYearAverageReturn", 0.0)
            if not ret_3y:
                comp_3y = metrics.compute_trailing_return_annualized(ticker, "3y")
                ret_3y = comp_3y if comp_3y is not None else 0.0

            # 5-Year Return handling
            ret_5y = info.get("fiveYearAverageReturn", 0.0)
            if not ret_5y:
                comp_5y = metrics.compute_trailing_return_annualized(ticker, "5y")
                ret_5y = comp_5y if comp_5y is not None else 0.0
                
            # Compute precise beta from historical returns instead of yfinance .info
            computed_beta = metrics.compute_beta(ticker)

            metadata[ticker] = {
                "name": info.get("shortName", ticker),
                "type": info.get("quoteType", type_str),
                "expense_ratio_pct": er_pct,
                "yield": raw_yield,
                "beta": computed_beta if computed_beta is not None else info.get("beta", 1.0),
                "previous_close": info.get("previousClose", 0.0),
                "1y_return": ret_1y,
                "3y_return": ret_3y,
                "5y_return": ret_5y,
                "net_of_fees_5y": metrics.compute_net_of_fees_return(ticker, "5y"),
                "10y_return": metrics.compute_total_return(ticker, "10y"),
                "asset_class": metrics.classify_asset_class(ticker),
            }

        except Exception as e:
            # Silently fail to avoid printing too much data, just store empty
            metadata[ticker] = {
                "name": ticker,
                "type": "UNKNOWN",
                "expense_ratio_pct": None,
                "yield": 0.0,
                "beta": 1.0,
                "previous_close": 0.0,
                "error": str(e)
            }
            
    return metadata

if __name__ == "__main__":
    # Smoke test with a few common tickers
    test_tickers = ["SPY", "VOO", "FXAIX"]
    print(f"Fetching metadata for test tickers: {test_tickers}")
    results = fetch_ticker_metadata(test_tickers)
    for ticker, data in results.items():
        print(f"{ticker}: ER = {data.get('expense_ratio_pct')}% | Yield = {data.get('yield')}")
