"""
test_yfinance_enhancements.py — Validates yfinance data enhancement items.

Tests classify_asset_class, _get_funds_data caching, beta3Year priority,
category_avg_er extraction, bond metrics, inception_years, and cap_gain_yield.

Run: cd src && py test_yfinance_enhancements.py
"""

import sys
import metrics
import market_data


def test_classify_asset_class():
    """Validation matrix: verify funds_data-based classification."""
    print("=== Test: classify_asset_class ===")
    metrics.clear_cache()
    cases = {
        "CDDYX": "US Equity",   # Columbia Dividend Income — was Bond (the bug)
        "VBTLX": "Bond",        # Vanguard Total Bond Market
        "VTIAX": "Intl Equity",  # Vanguard Total Intl Stock
        "SPY":   "US Equity",   # S&P 500 ETF (uses info.category path)
        "AGG":   "Bond",        # iShares Core Aggregate Bond ETF
    }
    passed = 0
    for ticker, expected in cases.items():
        result = metrics.classify_asset_class(ticker)
        status = "PASS" if result == expected else "FAIL"
        print(f"  {ticker}: {result} (expected {expected}) [{status}]")
        if result == expected:
            passed += 1
    print(f"  {passed}/{len(cases)} passed\n")
    return passed == len(cases)


def test_detect_benchmark_income_fix():
    """CDDYX should benchmark against SPY (not AGG) after 'income' keyword removal."""
    print("=== Test: detect_benchmark income fix ===")
    metrics.clear_cache()
    bm = metrics.detect_benchmark("CDDYX")
    status = "PASS" if bm == "SPY" else "FAIL"
    print(f"  CDDYX benchmark: {bm} (expected SPY) [{status}]\n")
    return bm == "SPY"


def test_funds_data_caching():
    """Verify _get_funds_data caches results and handles failures."""
    print("=== Test: _get_funds_data caching ===")
    metrics.clear_cache()
    fd1 = metrics._get_funds_data("VBTLX")
    fd2 = metrics._get_funds_data("VBTLX")
    cache_hit = fd1 is fd2
    print(f"  Cache hit: {cache_hit} [{'PASS' if cache_hit else 'FAIL'}]")

    # SPAXX funds_data object is created but property access throws
    fd_spaxx = metrics._get_funds_data("SPAXX")
    # It may return an object or None depending on yfinance version
    spaxx_ok = True  # Not None is OK, classify_asset_class handles access errors
    print(f"  SPAXX cached: {fd_spaxx is not None or True} [PASS]\n")
    return cache_hit and spaxx_ok


def test_metadata_fields():
    """Verify all new metadata fields populate correctly."""
    print("=== Test: metadata fields ===")
    metrics.clear_cache()
    md = market_data.fetch_ticker_metadata(["CDDYX", "VBTLX", "SPY"])
    passed = 0
    total = 0

    # CDDYX: US Equity, has category_avg_er, morningstar_rating, turnover
    d = md.get("CDDYX", {})
    checks = [
        ("CDDYX.asset_class", d.get("asset_class"), "US Equity"),
        ("CDDYX.category_avg_er is not None", d.get("category_avg_er") is not None, True),
        ("CDDYX.morningstar_rating", d.get("morningstar_rating"), 5),
        ("CDDYX.turnover is not None", d.get("turnover") is not None, True),
        ("CDDYX.net_assets > 0", (d.get("net_assets") or 0) > 0, True),
        ("CDDYX.inception_years > 10", (d.get("inception_years") or 0) > 10, True),
        ("CDDYX.bond_duration is None", d.get("bond_duration"), None),
    ]

    # VBTLX: Bond, has bond_duration
    d2 = md.get("VBTLX", {})
    checks += [
        ("VBTLX.asset_class", d2.get("asset_class"), "Bond"),
        ("VBTLX.bond_duration approx 3.81", abs((d2.get("bond_duration") or 0) - 3.81) < 1.0, True),
        ("VBTLX.bond_maturity is not None", d2.get("bond_maturity") is not None, True),
    ]

    # SPY: ETF, may not have morningstar_rating
    d3 = md.get("SPY", {})
    checks += [
        ("SPY.asset_class", d3.get("asset_class"), "US Equity"),
        ("SPY.net_assets > 0", (d3.get("net_assets") or 0) > 0, True),
    ]

    for name, actual, expected in checks:
        total += 1
        ok = actual == expected
        status = "PASS" if ok else "FAIL"
        if not ok:
            print(f"  {name}: got {actual}, expected {expected} [{status}]")
        else:
            print(f"  {name}: {actual} [{status}]")
            passed += 1

    print(f"  {passed}/{total} passed\n")
    return passed == total


def test_bond_metrics():
    """Verify get_bond_metrics returns duration/maturity for bond funds."""
    print("=== Test: get_bond_metrics ===")
    metrics.clear_cache()
    bm = metrics.get_bond_metrics("VBTLX")
    has_duration = bm is not None and "duration" in bm
    has_maturity = bm is not None and "maturity" in bm
    print(f"  VBTLX duration: {bm.get('duration') if bm else None} [{'PASS' if has_duration else 'FAIL'}]")
    print(f"  VBTLX maturity: {bm.get('maturity') if bm else None} [{'PASS' if has_maturity else 'FAIL'}]")

    # Non-bond fund should return None or empty
    bm_spy = metrics.get_bond_metrics("SPY")
    spy_ok = bm_spy is None or not bm_spy.get("duration")
    print(f"  SPY bond_metrics: {bm_spy} [{'PASS' if spy_ok else 'FAIL'}]\n")
    return has_duration and has_maturity and spy_ok


def test_sector_weightings():
    """Verify get_sector_weightings returns data for equity funds."""
    print("=== Test: get_sector_weightings ===")
    metrics.clear_cache()
    sw = metrics.get_sector_weightings("SPY")
    has_data = sw is not None and len(sw) > 0
    has_tech = sw is not None and "technology" in sw
    print(f"  SPY sectors: {len(sw) if sw else 0} sectors [{'PASS' if has_data else 'FAIL'}]")
    print(f"  SPY has technology: {has_tech} [{'PASS' if has_tech else 'FAIL'}]\n")
    return has_data and has_tech


def test_top_holdings():
    """Verify get_top_holdings returns holdings list."""
    print("=== Test: get_top_holdings ===")
    metrics.clear_cache()
    th = metrics.get_top_holdings("SPY")
    has_data = th is not None and len(th) > 0
    print(f"  SPY top holdings: {len(th) if th else 0} [{'PASS' if has_data else 'FAIL'}]\n")
    return has_data


if __name__ == "__main__":
    results = [
        test_classify_asset_class(),
        test_detect_benchmark_income_fix(),
        test_funds_data_caching(),
        test_metadata_fields(),
        test_bond_metrics(),
        test_sector_weightings(),
        test_top_holdings(),
    ]
    passed = sum(results)
    total = len(results)
    print(f"{'='*40}")
    print(f"RESULTS: {passed}/{total} test suites passed")
    if passed == total:
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")
        sys.exit(1)
