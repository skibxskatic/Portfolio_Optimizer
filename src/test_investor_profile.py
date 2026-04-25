"""
test_investor_profile.py — Validates investor profile loading, risk tolerance,
template generation, and tax rate lookups.

Run: cd src && py test_investor_profile.py
"""

import sys
import os
import tempfile
from pathlib import Path

# Ensure src is on path
sys.path.insert(0, os.path.dirname(__file__))

import portfolio_analyzer as pa
import tax_rates


def test_load_full_profile():
    """All fields set in investor_profile.txt."""
    print("=== Test: load_investor_profile (full) ===")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "investor_profile.txt"
        p.write_text(
            "birth_year = 1985\n"
            "retirement_year = 2050\n"
            "risk_tolerance = aggressive\n"
            "state = CA\n"
            "roth_ira_contribution = 7000\n"
            "taxable_contribution = 50000\n"
            "hsa_contribution = 4150\n"
            "401k_contribution = 23000\n",
            encoding="utf-8",
        )
        prof = pa.load_investor_profile(Path(td))
        checks = [
            ("birth_year", prof["birth_year"], 1985),
            ("retirement_year", prof["retirement_year"], 2050),
            ("using_defaults", prof["using_defaults"], False),
            ("risk_tolerance", prof["risk_tolerance"], "aggressive"),
            ("state", prof["state"], "CA"),
            ("roth_ira_contribution", prof["roth_ira_contribution"], 7000.0),
            ("taxable_contribution", prof["taxable_contribution"], 50000.0),
            ("hsa_contribution", prof["hsa_contribution"], 4150.0),
            ("401k_contribution", prof["401k_contribution"], 23000.0),
        ]
        passed = 0
        for name, actual, expected in checks:
            ok = actual == expected
            print(f"  {name}: {actual} {'PASS' if ok else 'FAIL'}")
            if ok:
                passed += 1
        print(f"  {passed}/{len(checks)} passed\n")
        return passed == len(checks)


def test_load_partial_profile():
    """Only birth_year and retirement_year set."""
    print("=== Test: load_investor_profile (partial) ===")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "investor_profile.txt"
        p.write_text("birth_year = 1990\nretirement_year = 2055\n", encoding="utf-8")
        prof = pa.load_investor_profile(Path(td))
        checks = [
            ("birth_year", prof["birth_year"], 1990),
            ("retirement_year", prof["retirement_year"], 2055),
            ("using_defaults", prof["using_defaults"], False),
            ("risk_tolerance is auto", prof["risk_tolerance"], prof["risk_tolerance_auto"]),
            ("state is None", prof["state"], None),
            ("roth_ira_contribution is None", prof["roth_ira_contribution"], None),
        ]
        passed = 0
        for name, actual, expected in checks:
            ok = actual == expected
            print(f"  {name}: {actual} {'PASS' if ok else 'FAIL'}")
            if ok:
                passed += 1
        print(f"  {passed}/{len(checks)} passed\n")
        return passed == len(checks)


def test_load_missing_file():
    """No investor_profile.txt — should use defaults and generate template."""
    print("=== Test: load_investor_profile (missing file) ===")
    with tempfile.TemporaryDirectory() as td:
        prof = pa.load_investor_profile(Path(td))
        template_path = Path(td) / "investor_profile.txt"
        checks = [
            ("using_defaults", prof["using_defaults"], True),
            ("birth_year default", prof["birth_year"], pa.DEFAULT_BIRTH_YEAR),
            ("retirement_year default", prof["retirement_year"], pa.DEFAULT_RETIREMENT_YEAR),
            ("template generated", template_path.exists(), True),
        ]
        # Verify template has expected content
        if template_path.exists():
            content = template_path.read_text(encoding="utf-8")
            checks.append(("template has risk_tolerance", "risk_tolerance" in content, True))
            checks.append(("template has state", "state = CA" in content, True))
            checks.append(("template has roth_ira", "roth_ira_contribution" in content, True))

        passed = 0
        for name, actual, expected in checks:
            ok = actual == expected
            print(f"  {name}: {actual} {'PASS' if ok else 'FAIL'}")
            if ok:
                passed += 1
        print(f"  {passed}/{len(checks)} passed\n")
        return passed == len(checks)


def test_commented_out_fields():
    """All fields commented out — should use defaults."""
    print("=== Test: load_investor_profile (commented out) ===")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "investor_profile.txt"
        p.write_text(
            "# birth_year = 1985\n# retirement_year = 2050\n# risk_tolerance = aggressive\n",
            encoding="utf-8",
        )
        prof = pa.load_investor_profile(Path(td))
        ok = prof["using_defaults"] is True
        print(f"  using_defaults: {prof['using_defaults']} {'PASS' if ok else 'FAIL'}\n")
        return ok


def test_auto_risk_tolerance_boundaries():
    """Verify compute_auto_risk_tolerance at each boundary."""
    print("=== Test: compute_auto_risk_tolerance boundaries ===")
    cases = [
        (35, "very_aggressive"),
        (30, "very_aggressive"),
        (25, "aggressive"),
        (20, "aggressive"),
        (15, "moderate"),
        (10, "moderate"),
        (5, "conservative"),
        (3, "conservative"),
        (2, "very_conservative"),
        (0, "very_conservative"),
        (-5, "very_conservative"),
    ]
    passed = 0
    for ytr, expected in cases:
        result = pa.compute_auto_risk_tolerance(ytr)
        ok = result == expected
        print(f"  ytr={ytr:3d}: {result:20s} {'PASS' if ok else f'FAIL (expected {expected})'}")
        if ok:
            passed += 1
    print(f"  {passed}/{len(cases)} passed\n")
    return passed == len(cases)


def test_risk_level_weights():
    """Verify all 5 risk levels have weights summing to 1.0."""
    print("=== Test: RISK_LEVEL_WEIGHTS validation ===")
    passed = 0
    for level in pa.RISK_LEVELS:
        w = pa.RISK_LEVEL_WEIGHTS[level]
        total = w["score"] + w["stability"]
        ok = abs(total - 1.0) < 0.001
        print(
            f"  {level:20s}: score={w['score']:.2f} + stability={w['stability']:.2f} = {total:.2f} {'PASS' if ok else 'FAIL'}"
        )
        if ok:
            passed += 1
    print(f"  {passed}/{len(pa.RISK_LEVELS)} passed\n")
    return passed == len(pa.RISK_LEVELS)


def test_state_tax_lookups():
    """Test tax rate lookups for various states."""
    print("=== Test: tax_rates lookups ===")
    checks = []

    # CA — high tax state
    fed, state, combined = tax_rates.get_combined_tax_rate("CA", "LTCG")
    checks.append(("CA LTCG fed", fed, 0.15))
    checks.append(("CA LTCG state", state, 0.133))
    checks.append(("CA LTCG combined", round(combined, 4), 0.283))

    # TX — no state tax
    fed, state, combined = tax_rates.get_combined_tax_rate("TX", "LTCG")
    checks.append(("TX LTCG state=0", state, 0.0))

    # STCG rates
    fed, state, combined = tax_rates.get_combined_tax_rate("NY", "STCG")
    checks.append(("NY STCG fed", fed, 0.24))
    checks.append(("NY STCG state", state, 0.109))

    # No state specified
    fed, state, combined = tax_rates.get_combined_tax_rate(None, "LTCG")
    checks.append(("None state=0", state, 0.0))

    # Invalid state
    fed, state, combined = tax_rates.get_combined_tax_rate("XX", "LTCG")
    checks.append(("XX state=0", state, 0.0))

    # Format description
    desc_ca = tax_rates.format_tax_rate_description("CA", "LTCG")
    checks.append(("CA desc has CA", "CA" in desc_ca, True))
    desc_tx = tax_rates.format_tax_rate_description("TX", "LTCG")
    checks.append(("TX desc no state tax", "no state tax" in desc_tx, True))
    desc_none = tax_rates.format_tax_rate_description(None, "LTCG")
    checks.append(("None desc fed only", desc_none, "15% fed"))

    passed = 0
    for name, actual, expected in checks:
        ok = actual == expected
        print(f"  {name}: {actual} {'PASS' if ok else f'FAIL (expected {expected})'}")
        if ok:
            passed += 1
    print(f"  {passed}/{len(checks)} passed\n")
    return passed == len(checks)


if __name__ == "__main__":
    results = [
        test_load_full_profile(),
        test_load_partial_profile(),
        test_load_missing_file(),
        test_commented_out_fields(),
        test_auto_risk_tolerance_boundaries(),
        test_risk_level_weights(),
        test_state_tax_lookups(),
    ]
    passed = sum(results)
    total = len(results)
    print(f"{'=' * 40}")
    print(f"RESULTS: {passed}/{total} test suites passed")
    if passed == total:
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")
        sys.exit(1)
