import pandas as pd
from pathlib import Path
import parser


def test_tax_lot_unroller():
    """
    TDD Test for Phase 1 Tax Lot Unrolling.
    Asserts that the aggregate position (e.g., 2 shares of SPY) correctly unrolls
    into two distinct 1-share lots based on Accounts_History.
    """
    print("Running Phase 1 Verification: Tax Lot Unroller...")

    pos_path = Path("test_data/Test_Positions.csv")
    hist_path = Path("test_data/Test_History.csv")

    positions_df = parser.load_fidelity_positions(pos_path)
    history_df = parser.load_fidelity_history(hist_path)

    # Run the unroller (which we will build in parser.py)
    unrolled_lots = parser.unroll_tax_lots(positions_df, history_df)

    # We expect:
    # 2 SPY lots + 2 SCHD lots + 1 FXAIX lot + 2 QQQ lots + 1 VTI lot + 1 VOO lot + 2 VIG lots = 11 total
    expected_lot_count = 11
    if len(unrolled_lots) != expected_lot_count:
        print(f"❌ TEST FAILED: Expected {expected_lot_count} unrolled lots, got {len(unrolled_lots)}")
        return False

    # Check that STCG vs LTCG categorization works (assuming today is March 2, 2026)
    today = pd.to_datetime("2026-03-02")
    unrolled_lots["Holding_Days"] = (today - unrolled_lots["Purchase Date"]).dt.days
    unrolled_lots["Tax_Term"] = unrolled_lots["Holding_Days"].apply(lambda x: "LTCG" if x > 365 else "STCG")

    spy_lots = unrolled_lots[unrolled_lots["Symbol"] == "SPY"]
    # Check that prices match the history purchases
    if spy_lots["Cost Basis"].sum() != 800.00:
        print("❌ TEST FAILED: SPY Cost basis sum does not match expected 800.00")
        return False

    spy_stcg = spy_lots[spy_lots["Holding_Days"] == 364]
    spy_ltcg = spy_lots[spy_lots["Holding_Days"] == 366]

    if len(spy_stcg) != 1 or len(spy_ltcg) != 1:
        print("❌ TEST FAILED: The STCG/LTCG 365-day boundary test failed.")
        return False

    print("✅ TAX LOT UNROLLER TEST PASSED: CSVs successfully joined and edge cases handled.")
    return True


def test_multi_account_routing():
    """
    Test that positions from different accounts are parsed and account names are correct.
    """
    print("\nRunning Multi-Account Routing Test...")

    pos_path = Path("test_data/Test_Positions.csv")
    positions_df = parser.load_fidelity_positions(pos_path)

    # Check account names present
    account_names = set(positions_df["Account Name"].unique())
    expected_accounts = {"INDIVIDUAL", "ROTH IRA", "Health Savings Account", "Melissa Investments"}

    missing = expected_accounts - account_names
    if missing:
        print(f"❌ TEST FAILED: Missing account names: {missing}")
        return False

    # Check specific tickers in correct accounts
    roth_positions = positions_df[positions_df["Account Name"] == "ROTH IRA"]
    if "QQQ" not in roth_positions["Symbol"].values:
        print("❌ TEST FAILED: QQQ not found in ROTH IRA account")
        return False

    hsa_positions = positions_df[positions_df["Account Name"] == "Health Savings Account"]
    if "VTI" not in hsa_positions["Symbol"].values:
        print("❌ TEST FAILED: VTI not found in Health Savings Account")
        return False

    melissa_positions = positions_df[positions_df["Account Name"] == "Melissa Investments"]
    if "VIG" not in melissa_positions["Symbol"].values:
        print("❌ TEST FAILED: VIG not found in Melissa Investments account")
        return False

    print("✅ MULTI-ACCOUNT ROUTING TEST PASSED: All 4 account types parsed correctly.")
    return True


def test_de_minimis_threshold():
    """
    Test that the de minimis gain detection works correctly.
    VOO has a $2.00 unrealized gain on a $510 value = 0.39%, which is below the 1% threshold.
    """
    print("\nRunning De Minimis Threshold Test...")

    pos_path = Path("test_data/Test_Positions.csv")
    positions_df = parser.load_fidelity_positions(pos_path)

    voo = positions_df[positions_df["Symbol"] == "VOO"]
    if voo.empty:
        print("❌ TEST FAILED: VOO not found in test positions")
        return False

    voo_row = voo.iloc[0]
    gain = voo_row["Total Gain/Loss Dollar"]
    value = voo_row["Current Value"]

    DE_MINIMIS_GAIN_PCT = 0.01
    gain_pct = gain / value if value > 0 else 0

    if gain_pct >= DE_MINIMIS_GAIN_PCT:
        print(
            f"❌ TEST FAILED: VOO gain % ({gain_pct * 100:.2f}%) should be below de minimis threshold ({DE_MINIMIS_GAIN_PCT * 100:.0f}%)"
        )
        return False

    print(
        f"✅ DE MINIMIS TEST PASSED: VOO gain ({gain_pct * 100:.2f}%) is below {DE_MINIMIS_GAIN_PCT * 100:.0f}% threshold — safe to reallocate."
    )
    return True


if __name__ == "__main__":
    lot_ok = test_tax_lot_unroller()
    account_ok = test_multi_account_routing()
    de_minimis_ok = test_de_minimis_threshold()

    print("\n--- TEST SUMMARY ---")
    results = {
        "Tax Lot Unroller": lot_ok,
        "Multi-Account Routing": account_ok,
        "De Minimis Threshold": de_minimis_ok,
    }
    for name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}: {name}")
