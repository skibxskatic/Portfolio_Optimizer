import pandas as pd
from parsers.fidelity import unroll_tax_lots


def test_vgt_split_normalization():
    print("Running Stock Split Normalization Test (VGT Example)...")

    # 1. Mock Positions (Current Post-Split State)
    # Total shares: 72.968, Current Price: $101.02
    positions_df = pd.DataFrame(
        [
            {
                "Symbol": "VGT",
                "Quantity": 72.968,
                "Last Price": 101.02,
                "Average Cost Basis": 81.72,
                "Description": "VANGUARD WORLD FD INF TECH ETF",
                "Account Name": "INDIVIDUAL",
            }
        ]
    )

    # 2. Mock History (Raw Pre-Split Transactions)
    # Buy 9 shares at $653.45 (Pre-8:1 split)
    history_df = pd.DataFrame(
        [
            {
                "Date": pd.to_datetime("2025-06-26"),
                "Symbol": "VGT",
                "Action": "Buy",
                "Quantity": 9.0,
                "Price": 653.45,
                "Account Name": "INDIVIDUAL",
            }
        ]
    )

    # 3. Mock Metadata with official split info
    # VGT had an 8:1 split (ratio=8.0) in late 2025
    vgt_splits = pd.Series([8.0], index=[pd.to_datetime("2025-10-01")])
    metadata = {"VGT": {"splits": vgt_splits}}

    # 4. Run Unrolling
    unrolled = unroll_tax_lots(positions_df, history_df, metadata=metadata)

    # 5. Assertions
    lot = unrolled.iloc[0]

    print(f"Original Qty: 9.0  -> Normalized Qty: {lot['Quantity']}")
    print(f"Original Price: $653.45 -> Normalized Price: ${lot['Unit Cost']:.2f}")
    print(f"Calculated Gain: ${lot['Unrealized Gain']:.2f}")

    # Normalized Qty should be 9 * 8 = 72
    # Normalized Price should be 653.45 / 8 = 81.68
    # Total shares in positions is 72.968.
    # 72 shares should come from history, 0.968 from fallback (avg cost basis).

    assert abs(lot["Quantity"] - 72.0) < 0.01, "Quantity normalization failed!"
    assert abs(lot["Unit Cost"] - 81.68) < 0.05, "Price normalization failed!"
    assert lot["Unrealized Gain"] > 0, "Phantom loss still exists! Gain should be positive."

    print("\n✅ SUCCESS: Stock split normalization working correctly.")


if __name__ == "__main__":
    test_vgt_split_normalization()
