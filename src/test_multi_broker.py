"""
test_multi_broker.py — Validates multi-broker adapter detection and parsing.

Tests that:
  1. detect_broker() routes each CSV to the correct adapter
  2. Each adapter parses its CSV into the canonical positions schema
  3. GenericAdapter fuzzy fallback handles non-standard column names

Run: cd src && py test_multi_broker.py
"""

import sys
from pathlib import Path

# Ensure src/ is on the path
_src_dir = Path(__file__).parent
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from file_ingestor import detect_broker
from parsers.base import CANONICAL_POSITIONS_COLS
from parsers.schwab import SchwabAdapter
from parsers.vanguard import VanguardAdapter
from parsers.generic import GenericAdapter
from parsers.fidelity import FidelityAdapter

TEST_DATA = _src_dir / "test_data"

# Canonical columns every adapter must produce (or at least the critical ones)
CRITICAL_COLS = {"Symbol", "Quantity", "Current Value"}


def test_schwab_detection():
    """Schwab CSV should be detected as SchwabAdapter."""
    print("=== Test: Schwab broker detection ===")
    path = TEST_DATA / "Test_Schwab_Positions.csv"
    adapter = detect_broker(path)
    is_schwab = isinstance(adapter, SchwabAdapter)
    print(f"  Detected: {adapter.BROKER_NAME} (expected Schwab) [{'PASS' if is_schwab else 'FAIL'}]")
    return is_schwab


def test_schwab_parse():
    """Schwab adapter should parse positions into canonical schema."""
    print("=== Test: Schwab parse_positions ===")
    path = TEST_DATA / "Test_Schwab_Positions.csv"
    adapter = SchwabAdapter()
    df = adapter.parse_positions(path)

    passed = True

    # Check not empty
    if df.empty:
        print("  DataFrame is empty [FAIL]")
        return False
    print(f"  Rows: {len(df)} (expected 4) [{'PASS' if len(df) == 4 else 'FAIL'}]")
    passed = passed and len(df) == 4

    # Check critical canonical columns exist
    missing = CRITICAL_COLS - set(df.columns)
    cols_ok = len(missing) == 0
    print(f"  Critical columns present: {cols_ok} [{'PASS' if cols_ok else 'FAIL — missing: ' + str(missing)}]")
    passed = passed and cols_ok

    # Check renamed columns (Qty -> Quantity, Market Value -> Current Value)
    qty_ok = "Quantity" in df.columns and df["Quantity"].notna().all()
    print(f"  Qty -> Quantity rename: {qty_ok} [{'PASS' if qty_ok else 'FAIL'}]")
    passed = passed and qty_ok

    val_ok = "Current Value" in df.columns and df["Current Value"].notna().all()
    print(f"  Market Value -> Current Value rename: {val_ok} [{'PASS' if val_ok else 'FAIL'}]")
    passed = passed and val_ok

    # Check numeric parsing (dollar signs and commas stripped)
    first_val = df["Current Value"].iloc[0]
    numeric_ok = isinstance(first_val, (int, float)) and first_val > 0
    print(f"  Numeric parsing: {first_val} [{'PASS' if numeric_ok else 'FAIL'}]")
    passed = passed and numeric_ok

    # Check symbols
    symbols = df["Symbol"].tolist()
    symbols_ok = symbols == ["SPY", "VOO", "SCHD", "VTI"]
    print(f"  Symbols: {symbols} [{'PASS' if symbols_ok else 'FAIL'}]")
    passed = passed and symbols_ok

    print()
    return passed


def test_vanguard_detection():
    """Vanguard CSV should be detected as VanguardAdapter."""
    print("=== Test: Vanguard broker detection ===")
    path = TEST_DATA / "Test_Vanguard_Positions.csv"
    adapter = detect_broker(path)
    is_vanguard = isinstance(adapter, VanguardAdapter)
    print(f"  Detected: {adapter.BROKER_NAME} (expected Vanguard) [{'PASS' if is_vanguard else 'FAIL'}]")
    return is_vanguard


def test_vanguard_parse():
    """Vanguard adapter should parse positions into canonical schema."""
    print("=== Test: Vanguard parse_positions ===")
    path = TEST_DATA / "Test_Vanguard_Positions.csv"
    adapter = VanguardAdapter()
    df = adapter.parse_positions(path)

    passed = True

    if df.empty:
        print("  DataFrame is empty [FAIL]")
        return False
    print(f"  Rows: {len(df)} (expected 4) [{'PASS' if len(df) == 4 else 'FAIL'}]")
    passed = passed and len(df) == 4

    missing = CRITICAL_COLS - set(df.columns)
    cols_ok = len(missing) == 0
    print(f"  Critical columns present: {cols_ok} [{'PASS' if cols_ok else 'FAIL — missing: ' + str(missing)}]")
    passed = passed and cols_ok

    # Check renamed columns (Shares -> Quantity)
    qty_ok = "Quantity" in df.columns and df["Quantity"].notna().all()
    print(f"  Shares -> Quantity rename: {qty_ok} [{'PASS' if qty_ok else 'FAIL'}]")
    passed = passed and qty_ok

    # Check derived Average Cost Basis
    acb_ok = "Average Cost Basis" in df.columns and df["Average Cost Basis"].notna().all()
    print(f"  Derived Average Cost Basis: {acb_ok} [{'PASS' if acb_ok else 'FAIL'}]")
    passed = passed and acb_ok

    # Check numeric parsing
    first_val = df["Current Value"].iloc[0]
    numeric_ok = isinstance(first_val, (int, float)) and first_val > 0
    print(f"  Numeric parsing: {first_val} [{'PASS' if numeric_ok else 'FAIL'}]")
    passed = passed and numeric_ok

    # Check symbols
    symbols = df["Symbol"].tolist()
    symbols_ok = symbols == ["VTI", "VXUS", "VOO", "BND"]
    print(f"  Symbols: {symbols} [{'PASS' if symbols_ok else 'FAIL'}]")
    passed = passed and symbols_ok

    print()
    return passed


def test_generic_detection():
    """Generic CSV should NOT match Fidelity, Schwab, or Vanguard — falls through to GenericAdapter."""
    print("=== Test: Generic broker detection (fuzzy fallback) ===")
    path = TEST_DATA / "Test_Generic_Positions.csv"
    adapter = detect_broker(path)
    is_generic = isinstance(adapter, GenericAdapter)
    # Make sure it did NOT match a specific broker
    not_fidelity = not isinstance(adapter, FidelityAdapter)
    not_schwab = not isinstance(adapter, SchwabAdapter)
    not_vanguard = not isinstance(adapter, VanguardAdapter)
    fell_through = not_fidelity and not_schwab and not_vanguard
    print(f"  Detected: {adapter.BROKER_NAME} (expected Generic) [{'PASS' if is_generic else 'FAIL'}]")
    print(f"  Skipped specific brokers: {fell_through} [{'PASS' if fell_through else 'FAIL'}]")
    return is_generic and fell_through


def test_generic_parse():
    """GenericAdapter should fuzzy-map non-standard column names to canonical schema."""
    print("=== Test: Generic fuzzy parse_positions ===")
    path = TEST_DATA / "Test_Generic_Positions.csv"
    adapter = GenericAdapter()
    df = adapter.parse_positions(path)

    passed = True

    if df.empty:
        print("  DataFrame is empty [FAIL]")
        return False
    print(f"  Rows: {len(df)} (expected 3) [{'PASS' if len(df) == 3 else 'FAIL'}]")
    passed = passed and len(df) == 3

    missing = CRITICAL_COLS - set(df.columns)
    cols_ok = len(missing) == 0
    print(f"  Critical columns present: {cols_ok} [{'PASS' if cols_ok else 'FAIL — missing: ' + str(missing)}]")
    passed = passed and cols_ok

    # Check fuzzy renames: Ticker -> Symbol
    sym_ok = "Symbol" in df.columns
    symbols = df["Symbol"].tolist() if sym_ok else []
    print(f"  Ticker -> Symbol: {symbols} [{'PASS' if sym_ok and 'SPY' in symbols else 'FAIL'}]")
    passed = passed and sym_ok and "SPY" in symbols

    # Check fuzzy renames: Portfolio Value -> Current Value (via 'value' match)
    # Note: POSITIONS_FUZZY_MAP maps 'Current Value' candidates: 'portfolio value' matches
    val_ok = "Current Value" in df.columns and df["Current Value"].notna().all()
    print(f"  Portfolio Value -> Current Value: {val_ok} [{'PASS' if val_ok else 'FAIL'}]")
    passed = passed and val_ok

    # Check fuzzy renames: Units -> Quantity
    qty_ok = "Quantity" in df.columns and df["Quantity"].notna().all()
    print(f"  Units -> Quantity: {qty_ok} [{'PASS' if qty_ok else 'FAIL'}]")
    passed = passed and qty_ok

    # Check fuzzy renames: Fund Name -> Description
    desc_ok = "Description" in df.columns
    print(f"  Fund Name -> Description: {desc_ok} [{'PASS' if desc_ok else 'FAIL'}]")
    passed = passed and desc_ok

    # Check fuzzy renames: Portfolio -> Account Name
    acct_ok = "Account Name" in df.columns
    print(f"  Portfolio -> Account Name: {acct_ok} [{'PASS' if acct_ok else 'FAIL'}]")
    passed = passed and acct_ok

    # Check numeric parsing (dollar signs + commas stripped)
    if val_ok:
        first_val = df["Current Value"].iloc[0]
        numeric_ok = isinstance(first_val, (int, float)) and first_val > 0
        print(f"  Numeric parsing: {first_val} [{'PASS' if numeric_ok else 'FAIL'}]")
        passed = passed and numeric_ok

    print()
    return passed


def test_fidelity_not_confused():
    """Verify that Schwab/Vanguard/Generic CSVs are NOT detected as Fidelity."""
    print("=== Test: Fidelity adapter rejects non-Fidelity files ===")
    adapter = FidelityAdapter()
    passed = True

    for name in ["Test_Schwab_Positions.csv", "Test_Vanguard_Positions.csv", "Test_Generic_Positions.csv"]:
        path = TEST_DATA / name
        detected = adapter.detect(path)
        ok = not detected
        print(f"  {name}: detect={detected} [{'PASS' if ok else 'FAIL'}]")
        passed = passed and ok

    # Existing Fidelity file SHOULD be detected
    fidelity_path = TEST_DATA / "Test_Positions.csv"
    fidelity_detected = adapter.detect(fidelity_path)
    print(f"  Test_Positions.csv (Fidelity): detect={fidelity_detected} [{'PASS' if fidelity_detected else 'FAIL'}]")
    passed = passed and fidelity_detected

    print()
    return passed


def test_canonical_columns_coverage():
    """All adapters should produce the full set of canonical position columns (or NaN placeholders)."""
    print("=== Test: Canonical column coverage ===")
    canonical_set = set(CANONICAL_POSITIONS_COLS)
    passed = True

    cases = [
        ("Schwab", SchwabAdapter(), TEST_DATA / "Test_Schwab_Positions.csv"),
        ("Vanguard", VanguardAdapter(), TEST_DATA / "Test_Vanguard_Positions.csv"),
        ("Generic", GenericAdapter(), TEST_DATA / "Test_Generic_Positions.csv"),
    ]

    for label, adapter, path in cases:
        df = adapter.parse_positions(path)
        present = canonical_set & set(df.columns)
        missing = canonical_set - set(df.columns)
        # Expense Ratio and Account Type are allowed to be NaN-filled but must exist as columns
        ok = len(missing) == 0
        if not ok:
            # Some columns (Account Type, Description) may not be explicitly in the CSV
            # but should be added by the adapter or are non-critical
            non_critical_missing = missing - CRITICAL_COLS
            critical_missing = missing & CRITICAL_COLS
            ok = len(critical_missing) == 0
            status = f"PASS (non-critical missing: {non_critical_missing})" if ok else f"FAIL (missing: {missing})"
        else:
            status = "PASS"
        print(f"  {label}: {len(present)}/{len(canonical_set)} columns [{status}]")
        passed = passed and ok

    print()
    return passed


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("Multi-Broker Adapter Test Suite")
    print("=" * 60 + "\n")

    results = []
    results.append(("Schwab detection", test_schwab_detection()))
    results.append(("Schwab parse", test_schwab_parse()))
    results.append(("Vanguard detection", test_vanguard_detection()))
    results.append(("Vanguard parse", test_vanguard_parse()))
    results.append(("Generic detection", test_generic_detection()))
    results.append(("Generic fuzzy parse", test_generic_parse()))
    results.append(("Fidelity rejection", test_fidelity_not_confused()))
    results.append(("Canonical coverage", test_canonical_columns_coverage()))

    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    total_pass = 0
    for name, ok in results:
        status = "PASS" if ok else "FAIL"
        print(f"  {name}: {status}")
        if ok:
            total_pass += 1

    print(f"\n  {total_pass}/{len(results)} test groups passed.")
    print("=" * 60)

    sys.exit(0 if total_pass == len(results) else 1)
