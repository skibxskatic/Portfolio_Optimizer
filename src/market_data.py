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
    urls = ["https://finance.yahoo.com/etfs", "https://finance.yahoo.com/screener/predefined/top_mutual_funds"]
    tickers = set()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    for url in urls:
        try:
            r = requests.get(url, headers=headers, timeout=10)
            matches = re.findall(r'href="/quote/([A-Z]{2,5})[/?]', r.text)
            for m in matches:
                tickers.add(m)
        except Exception:
            pass

    # Hardcoded baseline covering all 4 routing buckets so the optimizer
    # has candidates even when the Yahoo Finance scraper returns nothing.
    baseline = [
        # Tax-Deferred (401k): high yield (≥ 2%) — dividend/income funds
        "SCHD",
        "VYM",
        "SPYD",
        "VIG",
        "FDVV",
        "DGRO",
        # Roth IRA: low yield + high beta (> 1.0) — growth/tech funds
        "QQQ",
        "VGT",
        "ARKK",
        "VUG",
        "IWF",
        "SOXX",
        # Taxable Brokerage: low yield + low beta (≤ 1.0) — broad market/index funds
        "VOO",
        "VTI",
        "SPLG",
        "ITOT",
        "SPTM",
        "VT",
        # Bond: bond funds — fixed income candidates
        "BND",
        "AGG",
        "VGIT",
        "SCHZ",
        "TIP",
        "BNDX",
    ]
    for b in baseline:
        tickers.add(b)

    return list(tickers)


def fetch_ticker_metadata(tickers: list[str]) -> Dict[str, Dict[str, Any]]:
    """
    Fetches market metadata for a list of tickers using yfinance concurrently.
    Only the ticker symbols are sent to the Yahoo Finance API.
    No user account quantities or dollar values are ever transmitted.
    """
    metadata = {}

    # Clean tickers (remove cash equivalents or invalid symbols)
    valid_tickers = [
        t
        for t in tickers
        if isinstance(t, str) and len(t) > 0 and t.upper() != "PENDING ACTIVITY" and t.upper() != "CORE"
    ]
    valid_tickers = list(set(valid_tickers))

    def _fetch_single(ticker: str) -> tuple[str, Dict[str, Any]]:
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

            # Category average ER from fund_operations
            category_avg_er = None
            try:
                fd_for_meta = metrics._get_funds_data(ticker)
                if fd_for_meta is not None:
                    fund_ops = fd_for_meta.fund_operations
                    if fund_ops is not None and not fund_ops.empty:
                        cat_avg_raw = fund_ops.loc["Annual Report Expense Ratio", "Category Average"]
                        if cat_avg_raw is not None and not pd.isna(cat_avg_raw):
                            category_avg_er = round(float(cat_avg_raw) * 100.0, 4)
            except Exception:
                pass

            # Fund inception date → years since inception
            inception_years = None
            inception_ts = info.get("fundInceptionDate")
            if inception_ts is not None:
                from datetime import datetime

                inception_years = round((datetime.now() - datetime.fromtimestamp(inception_ts)).days / 365.25, 1)

            # Capital gains yield for tax efficiency
            last_cg = info.get("lastCapGain")
            prev_close = info.get("previousClose", 0.0)
            cap_gain_yield = None
            if last_cg is not None and prev_close and prev_close > 0:
                cap_gain_yield = round(abs(last_cg) / prev_close, 4)

            asset_class = metrics.classify_asset_class(ticker)

            # Bond-specific metrics
            bond_duration = None
            bond_maturity = None
            if asset_class == "Bond":
                bm = metrics.get_bond_metrics(ticker)
                if bm:
                    bond_duration = bm.get("duration")
                    bond_maturity = bm.get("maturity")

            return ticker, {
                "name": info.get("shortName", ticker),
                "type": info.get("quoteType", type_str),
                "expense_ratio_pct": er_pct,
                "category_avg_er": category_avg_er,
                "yield": raw_yield,
                "beta": computed_beta
                if computed_beta is not None
                else (info.get("beta3Year") or info.get("beta", 1.0)),
                "previous_close": info.get("previousClose", 0.0),
                "1y_return": ret_1y,
                "3y_return": ret_3y,
                "5y_return": ret_5y,
                "net_of_fees_5y": metrics.compute_net_of_fees_return(ticker, "5y"),
                "10y_return": metrics.compute_total_return(ticker, "10y"),
                "asset_class": asset_class,
                "turnover": info.get("annualHoldingsTurnover"),
                "morningstar_rating": info.get("morningStarOverallRating"),
                "net_assets": info.get("netAssets") or info.get("totalAssets"),
                "inception_years": inception_years,
                "cap_gain_yield": cap_gain_yield,
                "bond_duration": bond_duration,
                "bond_maturity": bond_maturity,
                "splits": metrics._get_ticker_splits(ticker),  # Use cached split history from metrics
            }

        except Exception as e:
            # Silently fail to avoid printing too much data, just store empty
            return ticker, {
                "name": ticker,
                "type": "UNKNOWN",
                "expense_ratio_pct": None,
                "yield": 0.0,
                "beta": 1.0,
                "previous_close": 0.0,
                "error": str(e),
            }

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_ticker = {executor.submit(_fetch_single, t): t for t in valid_tickers}
        total = len(valid_tickers)
        done = 0
        for future in concurrent.futures.as_completed(future_to_ticker):
            t = future_to_ticker[future]
            done += 1
            print(f"  [{done}/{total}] Fetched metadata for {t}", flush=True)
            try:
                ticker, data = future.result()
                metadata[ticker] = data
            except Exception as exc:
                print(f"Error fetching {t}: {exc}")
                metadata[t] = {"error": str(exc)}

    return metadata


if __name__ == "__main__":
    # Smoke test with a few common tickers
    test_tickers = ["SPY", "VOO", "FXAIX"]
    print(f"Fetching metadata for test tickers: {test_tickers}")
    results = fetch_ticker_metadata(test_tickers)
    for ticker, data in results.items():
        print(f"{ticker}: ER = {data.get('expense_ratio_pct')}% | Yield = {data.get('yield')}")
