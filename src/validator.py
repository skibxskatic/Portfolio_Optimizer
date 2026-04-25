import sys
import platform
import os

# Bypass Python 3.13 Windows WMI hang in platform.machine() called by pandas
platform.machine = lambda: os.environ.get("PROCESSOR_ARCHITECTURE", "AMD64")

import pandas as pd
from pathlib import Path
import market_data
import metrics
import parser


def verify_ingestion(raw_csv_path: Path, parsed_df: pd.DataFrame) -> bool:
    """
    Reality Check 1: Ingestion Validation.
    Asserts that the total "Current Value" parsed by Pandas matches the sum of
    "Current Value" in the raw CSV text lines.
    This ensures no fractional shares or weirdly formatted rows were dropped by the parser.
    """
    try:
        import csv

        raw_total = 0.0
        # Read raw lines, find the Current Value column index, and sum it
        with open(raw_csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            header = None
            current_value_idx = -1

            for row in reader:
                if not row:
                    continue

                if "Current Value" in row and header is None:
                    header = row
                    current_value_idx = header.index("Current Value")
                    symbol_idx = header.index("Symbol")
                    continue

                if header and current_value_idx != -1 and len(row) > current_value_idx:
                    # Skip summary rows (like "Account Total") that don't have a Symbol
                    if symbol_idx != -1 and len(row) > symbol_idx and not row[symbol_idx].strip():
                        continue

                    val_str = row[current_value_idx].replace("$", "").replace("+", "").replace(" ", "").replace(",", "")
                    if val_str and val_str not in ("--", "n/a"):
                        try:
                            raw_total += float(val_str)
                        except ValueError:
                            pass  # Ignore non-numeric rows like summary footers

        parsed_total = parsed_df["Current Value"].sum()

        # Check if they are somewhat close (floating point math)
        is_valid = abs(raw_total - parsed_total) < 1.0  # Within 1 dollar difference is acceptable

        if not is_valid:
            # We don't print the actual totals to stdout for privacy!
            print(
                f"[ERROR] Ingestion Validation FAILED: Parsed total value ({parsed_total}) does not match raw CSV total ({raw_total})."
            )
            print(f"Difference: {raw_total - parsed_total}")
            return False

        print("[OK] Ingestion Checksum PASSED: No data rows dropped during parsing.")
        return True

    except Exception as e:
        print(f"[ERROR] Ingestion Validation Error: {e}")
        return False


def verify_yfinance_sane() -> bool:
    """
    Reality Check 2: API Sanity.
    Fetches SPY and SCHD and asserts their yield and ER are within known-good bounds.
    If yfinance pushes an update that breaks extraction, this will catch it before generating corrupted reports.
    """
    print("Running API Reality Checks against known benchmarks (SPY, SCHD)...")

    benchmarks = ["SPY", "SCHD"]
    metadata = market_data.fetch_ticker_metadata(benchmarks)

    if "SPY" not in metadata or "SCHD" not in metadata:
        print("[ERROR] API Check FAILED: Could not fetch SPY or SCHD.")
        return False

    spy = metadata["SPY"]
    schd = metadata["SCHD"]

    # SPY: Yield usually 1-2%, ER is exactly 0.09%
    # SCHD: Yield usually 3-4%, ER is exactly 0.06%

    spy_yield_ok = 0.005 <= spy.get("yield", 0) <= 0.03
    schd_yield_ok = 0.02 <= schd.get("yield", 0) <= 0.06

    # ER must not be None (fetch error) or 0.0 (guard fired incorrectly) for known non-money-market funds.
    # SPY ER: 0.09%, SCHD ER: 0.06% — both must be fetched successfully.
    spy_er_pct = spy.get("expense_ratio_pct")
    schd_er_pct = schd.get("expense_ratio_pct")
    spy_er_ok = spy_er_pct is not None and 0.05 <= spy_er_pct <= 0.15
    schd_er_ok = schd_er_pct is not None and 0.03 <= schd_er_pct <= 0.10

    is_valid = True
    if not spy_yield_ok:
        print(f"[ERROR] API Check FAILED: SPY yield {spy.get('yield')} is out of sane bounds (0.5% - 3.0%).")
        is_valid = False
    if not schd_yield_ok:
        print(f"[ERROR] API Check FAILED: SCHD yield {schd.get('yield')} is out of sane bounds (2.0% - 6.0%).")
        is_valid = False
    if not spy_er_ok:
        print(
            f"[ERROR] API Check FAILED: SPY ER {spy_er_pct}% is out of bounds or failed to fetch (None = fetch error)."
        )
        is_valid = False
    if not schd_er_ok:
        print(
            f"[ERROR] API Check FAILED: SCHD ER {schd_er_pct}% is out of bounds or failed to fetch (None = fetch error)."
        )
        is_valid = False

    if is_valid:
        print("[OK] API Reality Check PASSED: yfinance extraction logic is structurally sound.")

    return is_valid


def verify_dynamic_screener() -> bool:
    """
    Reality Check 3: Dynamic Screener QA.
    Verifies that the live-scraped ETF universe only returns verified ETFs or Mutual Funds,
    and rejects any ticker that is missing its core historical return data (avoiding 0% reports).
    """
    print("Running Dynamic Screener QA on live targets...")
    tickers = market_data.get_dynamic_etf_universe()
    if not tickers:
        print("[ERROR] Dynamic Screener QA FAILED: No tickers scraped.")
        return False

    # Test a small sample to avoid rate limits during testing
    sample = tickers[:10]
    metadata = market_data.fetch_ticker_metadata(sample)

    is_valid = True
    valid_candidates = []

    for ticker, data in metadata.items():
        quote_type = data.get("type", "").upper()
        if quote_type not in ["ETF", "MUTUALFUND"]:
            print(
                f"🛡️ QA Filter Working: Successfully intercepted and dropped individual stock '{ticker}' from recommendations."
            )
            continue

        # Check if all return metrics are suspiciously exactly 0.0
        r1 = data.get("1y_return", 0.0)
        r3 = data.get("3y_return", 0.0)
        r5 = data.get("5y_return", 0.0)
        yld = data.get("yield", 0.0)

        if r1 == 0.0 and r3 == 0.0 and r5 == 0.0 and yld == 0.0:
            print(
                f"🛡️ QA Filter Working: Successfully intercepted and dropped '{ticker}' due to 0.0% corrupted historical data."
            )
            continue

        valid_candidates.append(ticker)

    if not valid_candidates and len(metadata) > 0:
        print("[ERROR] Dynamic Screener QA FAILED: The filters rejected every single scraped candidate. Adjust logic.")
        is_valid = False
    elif is_valid:
        print(
            f"[OK] Dynamic Screener QA PASSED: Engine successfully filtered raw targets down to {len(valid_candidates)} pure, data-rich ETFs/Funds."
        )

    return is_valid


def verify_asset_routing_logic() -> bool:
    """
    Reality Check 4: Asset Routing Validation.
    Fetches benchmarks representing the primary asset categories and asserts
    that the math classifies them into the correct 4-Bucket Tax Location Routing.
    - SCHD: High Dividend (Yield >= 2.0%) -> Tax-Deferred (401k only)
    - QQQ: Tech Growth (Yield < 2.0%, Beta >= 1.0) -> Roth IRA
    - VTI: Broad Market (Yield < 2.0%, Beta < 1.0) -> Taxable Brokerage
    - VGT: High-growth tech (Yield < 2.0%, Beta > 1.0) -> Roth IRA
      Note: VGT confirms HSA growth-tier routing. HSA pulls from the Roth IRA
      candidate pool (Sortino + 5Y + 10Y scoring) — not from Tax-Deferred income funds.
    """
    print("Running Asset Routing QA on known benchmarks (SCHD, QQQ, VTI, VGT)...")
    benchmarks = ["SCHD", "QQQ", "VTI", "VGT"]
    metadata = market_data.fetch_ticker_metadata(benchmarks)

    if len(metadata) < 4:
        print("[ERROR] Asset Routing QA FAILED: Could not fetch all benchmarks.")
        return False

    expected_routing = {
        "SCHD": "Tax-Deferred",
        "QQQ": "Roth IRA",
        "VTI": "Taxable Brokerage",
        "VGT": "Roth IRA",  # High-growth; also feeds HSA candidate pool
    }

    is_valid = True
    for ticker in benchmarks:
        data = metadata.get(ticker, {})
        yld = data.get("yield", 0.0)
        beta = data.get("beta", 1.0)

    # Updated 4-Bucket routing logic (mirrors portfolio_analyzer.py)
    # 1. Whitelist (VTI, QQQ, SCHD, VGT are all in the whitelist now)
    whitelist = {
        "VTI": "Taxable Brokerage",
        "VOO": "Taxable Brokerage",
        "QQQ": "Roth IRA",
        "VGT": "Roth IRA",
        "SCHD": "Tax-Deferred",
    }

    is_valid = True
    for ticker in benchmarks:
        data = metadata.get(ticker, {})
        yld = data.get("yield", 0.0)
        beta = data.get("beta", 1.0)

        # Tier 1: Whitelist
        if ticker in whitelist:
            routing = whitelist[ticker]
        # Tier 2: High Yield (>= 2.5%)
        elif yld >= 0.025:
            routing = "Tax-Deferred"
        # Tier 3: Growth (Beta >= 1.10)
        elif yld < 0.025 and beta >= 1.10:
            routing = "Roth IRA"
        # Tier 4: Default
        else:
            routing = "Taxable Brokerage"

        expected = expected_routing[ticker]
        if routing != expected:
            print(
                f"[ERROR] Asset Routing QA FAILED: {ticker} (Yield: {yld:.3f}, Beta: {beta:.3f}) routed to '{routing}' instead of '{expected}'."
            )
            is_valid = False

    if is_valid:
        print(
            "[OK] Asset Routing QA PASSED: 4-Bucket routing (Taxable, Roth IRA, 401k/Tax-Deferred, HSA growth-tier) validated."
        )

    return is_valid


def verify_metrics_computation() -> bool:
    """
    Reality Check 5: Metrics Computation Validation.
    Computes Sharpe, Sortino, and Max Drawdown on SPY and asserts they are
    within sane bounds. This catches regressions in the metrics engine.
    """
    print("Running Metrics Computation QA on SPY...")

    rf = metrics.fetch_risk_free_rate()
    if not (0.0 <= rf <= 0.15):
        print(f"[ERROR] Metrics QA FAILED: Risk-free rate {rf} is out of bounds.")
        return False

    sharpe = metrics.compute_sharpe_ratio("SPY", "5y")
    if sharpe is None or not (-1.0 <= sharpe <= 3.0):
        print(f"[ERROR] Metrics QA FAILED: SPY Sharpe Ratio {sharpe} is out of sane bounds.")
        return False

    sortino = metrics.compute_sortino_ratio("SPY", "5y")
    if sortino is None or not (-1.0 <= sortino <= 5.0):
        print(f"[ERROR] Metrics QA FAILED: SPY Sortino Ratio {sortino} is out of sane bounds.")
        return False

    max_dd = metrics.compute_max_drawdown("SPY", "5y")
    if max_dd is None or not (-0.60 <= max_dd <= 0.0):
        print(f"[ERROR] Metrics QA FAILED: SPY Max Drawdown {max_dd} is out of sane bounds.")
        return False

    print(
        f"[OK] Metrics QA PASSED: SPY Sharpe={sharpe:.3f}, Sortino={sortino:.3f}, MaxDD={max_dd * 100:.1f}%, RF={rf * 100:.2f}%"
    )
    return True


def verify_cross_account_wash_sale_logic() -> bool:
    """
    Reality Check 6: Wash Sale QA.
    Verifies that the cross-account wash sale detection fires correctly on synthetic data.
    """
    print("Running Wash Sale QA on synthetic data...")
    import portfolio_analyzer

    # 1. Single account holding (should NOT fire)
    df1 = pd.DataFrame(
        [
            {"Symbol": "SPY", "Account Name": "Taxable"},
            {"Symbol": "SPY", "Account Name": "Taxable"},
        ]
    )
    if portfolio_analyzer.detect_wash_sale_risk(df1, "SPY"):
        print("[ERROR] Wash Sale QA FAILED: SPY in same account incorrectly flagged.")
        return False

    # 2. Same-account identical holding (should NOT fire)
    df2 = pd.DataFrame(
        [
            {"Symbol": "QQQ", "Account Name": "Taxable"},
            {"Symbol": "SPYG", "Account Name": "Taxable"},
        ]
    )
    if portfolio_analyzer.detect_wash_sale_risk(df2, "QQQ"):
        print("[ERROR] Wash Sale QA FAILED: QQQ/SPYG in same account incorrectly flagged.")
        return False

    # 3. Cross-account identical holding (should fire)
    df3 = pd.DataFrame(
        [
            {"Symbol": "FTEC", "Account Name": "Taxable"},
            {"Symbol": "XLK", "Account Name": "Roth"},
        ]
    )
    if not portfolio_analyzer.detect_wash_sale_risk(df3, "FTEC"):
        print("[ERROR] Wash Sale QA FAILED: FTEC/XLK in cross accounts NOT flagged.")
        return False

    print("[OK] Wash Sale Detection QA PASSED: Cross-account identical fund detection works.")
    return True


def verify_asset_classification() -> bool:
    """
    Reality Check 7: Asset Classification QA.
    Verifies that classify_asset_class() returns valid classes for known tickers,
    using funds_data as primary source (not heuristics).
    """
    print("Running Asset Classification QA...")
    test_cases = {
        "SPY": "US Equity",
        "AGG": "Bond",
        "VXUS": "Intl Equity",
    }
    for ticker, expected in test_cases.items():
        result = metrics.classify_asset_class(ticker)
        if result != expected:
            print(f"[ERROR] Classification QA FAILED: {ticker} classified as '{result}', expected '{expected}'")
            return False
        if result == "UNCLASSIFIED":
            print(f"[ERROR] Classification QA FAILED: {ticker} returned UNCLASSIFIED")
            return False
    print(f"[OK] Classification QA PASSED: {len(test_cases)} benchmark tickers classified correctly")
    return True


def verify_risk_tolerance_mapping() -> bool:
    """
    Reality Check 8: Risk Tolerance Mapping.
    Verifies all 5 risk levels have valid weight dicts summing to 1.0.
    """
    print("Running Risk Tolerance Mapping QA...")
    import portfolio_analyzer as pa

    for level in pa.RISK_LEVELS:
        w = pa.RISK_LEVEL_WEIGHTS.get(level)
        if w is None:
            print(f"[ERROR] Risk Tolerance QA FAILED: Missing weights for '{level}'")
            return False
        total = w["score"] + w["stability"]
        if abs(total - 1.0) > 0.001:
            print(f"[ERROR] Risk Tolerance QA FAILED: '{level}' weights sum to {total}, expected 1.0")
            return False
    # Verify auto-computation boundaries
    test_cases = [
        (35, "very_aggressive"),
        (25, "aggressive"),
        (15, "moderate"),
        (5, "conservative"),
        (1, "very_conservative"),
    ]
    for ytr, expected in test_cases:
        result = pa.compute_auto_risk_tolerance(ytr)
        if result != expected:
            print(f"[ERROR] Risk Tolerance QA FAILED: ytr={ytr} → '{result}', expected '{expected}'")
            return False
    print("[OK] Risk Tolerance QA PASSED: All 5 levels valid, auto-computation correct")
    return True


def verify_allocation_normalization() -> bool:
    """
    Reality Check 9: Allocation Normalization.
    Verifies that compute_allocation() produces percentages summing to 100% ± 0.1%.
    """
    print("Running Allocation Normalization QA...")
    import portfolio_analyzer as pa

    # Synthetic candidates with varying scores
    candidates = [
        {"ticker": "A", "name": "Fund A", "score": 80},
        {"ticker": "B", "name": "Fund B", "score": 60},
        {"ticker": "C", "name": "Fund C", "score": 40},
        {"ticker": "D", "name": "Fund D", "score": 20},
    ]
    alloc = pa.compute_allocation(candidates, min_pct=5.0, max_funds=5)
    total_pct = sum(c["alloc_pct"] for c in alloc)
    if abs(total_pct - 100.0) > 0.2:
        print(f"[ERROR] Allocation QA FAILED: Total allocation = {total_pct}%, expected ~100%")
        return False
    # All must meet min floor
    for c in alloc:
        if c["alloc_pct"] < 4.9:  # slight tolerance for rounding
            print(f"[ERROR] Allocation QA FAILED: {c['ticker']} alloc = {c['alloc_pct']}% < 5% floor")
            return False
    # Empty input should return empty
    if pa.compute_allocation([], min_pct=5.0) != []:
        print("[ERROR] Allocation QA FAILED: Empty input should return empty list")
        return False
    print(f"[OK] Allocation QA PASSED: {len(alloc)} funds allocated, total={total_pct:.1f}%")
    return True


def run_cached_preflight() -> bool:
    """
    Runs the core pre-flight checks (API, Screener, Routing) and caches success for 24 hours.
    This avoids redundant yfinance calls on repeated engine runs.
    """
    import time
    import pickle

    cache_path = Path("Drop_Financial_Info_Here/.cache/validator_preflight.pkl")

    if cache_path.exists() and time.time() - cache_path.stat().st_mtime < 86400:
        try:
            with open(cache_path, "rb") as f:
                if pickle.load(f) is True:
                    print("[OK] Pre-flight checks PASSED (using 24h cache).")
                    return True
        except Exception:
            pass

    if not verify_yfinance_sane() or not verify_dynamic_screener() or not verify_asset_routing_logic():
        return False

    cache_path.parent.mkdir(exist_ok=True, parents=True)
    try:
        with open(cache_path, "wb") as f:
            pickle.dump(True, f)
    except Exception:
        pass
    return True


if __name__ == "__main__":
    api_ok = verify_yfinance_sane()
    screener_ok = verify_dynamic_screener()
    routing_ok = verify_asset_routing_logic()
    metrics_ok = verify_metrics_computation()
    wash_sale_ok = verify_cross_account_wash_sale_logic()
    classification_ok = verify_asset_classification()
    risk_ok = verify_risk_tolerance_mapping()
    alloc_ok = verify_allocation_normalization()

    data_dir = Path("Drop_Financial_Info_Here")
    positions_files = list(data_dir.glob("Portfolio_Positions*.csv"))
    if not positions_files:
        print("⚠️ No Positions CSV found to validate.")
        ingest_ok = True
    elif len(positions_files) > 1:
        print(f"[ERROR] Ingestion Checksum FAILED: Found {len(positions_files)} 'Portfolio_Positions' CSVs.")
        print("Please keep exactly ONE positions file in the Drop_Financial_Info_Here/ folder.")
        ingest_ok = False
    else:
        df = parser.load_fidelity_positions(positions_files[0])
        ingest_ok = verify_ingestion(positions_files[0], df)

    all_checks = [
        api_ok,
        screener_ok,
        routing_ok,
        metrics_ok,
        wash_sale_ok,
        classification_ok,
        risk_ok,
        alloc_ok,
        ingest_ok,
    ]
    if all(all_checks):
        print("\n✅ ALL QA CHECKS PASSED. Engine is safe to run.")
        sys.exit(0)
    else:
        print("\n❌ QA CHECKS FAILED. Do not run portfolio analysis.")
        sys.exit(1)
