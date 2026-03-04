import pandas as pd
from datetime import datetime
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
    
    # We expect 2 SPY lots, 2 SCHD lots, 1 FXAIX lot = 5 total lots
    if len(unrolled_lots) != 5:
        print(f"❌ TEST FAILED: Expected 5 unrolled lots, got {len(unrolled_lots)}")
        return False
        
    # Check that STCG vs LTCG categorization works (assuming today is March 2, 2026)
    today = pd.to_datetime('2026-03-02')
    unrolled_lots['Holding_Days'] = (today - unrolled_lots['Purchase Date']).dt.days
    unrolled_lots['Tax_Term'] = unrolled_lots['Holding_Days'].apply(lambda x: 'LTCG' if x > 365 else 'STCG')

    spy_lots = unrolled_lots[unrolled_lots['Symbol'] == 'SPY']
    # Check that prices match the history purchases
    if spy_lots['Cost Basis'].sum() != 800.00:
         print("❌ TEST FAILED: SPY Cost basis sum does not match expected 800.00")
         return False
         
    spy_stcg = spy_lots[spy_lots['Holding_Days'] == 364]
    spy_ltcg = spy_lots[spy_lots['Holding_Days'] == 366]
    
    if len(spy_stcg) != 1 or len(spy_ltcg) != 1:
        print("❌ TEST FAILED: The STCG/LTCG 365-day boundary test failed.")
        return False
        
    print("✅ TAX LOT UNROLLER TEST PASSED: CSVs successfully joined and edge cases handled.")
    return True

if __name__ == "__main__":
    test_tax_lot_unroller()
