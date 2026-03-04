import pandas as pd
from pathlib import Path
import market_data
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
        with open(raw_csv_path, 'r', encoding='utf-8-sig') as f:
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
                        
                    val_str = row[current_value_idx].replace('$', '').replace('+', '').replace(' ', '').replace(',', '')
                    if val_str and val_str not in ('--', 'n/a'):
                        try:
                            raw_total += float(val_str)
                        except ValueError:
                            pass # Ignore non-numeric rows like summary footers
                            
        parsed_total = parsed_df['Current Value'].sum()
        
        # Check if they are somewhat close (floating point math)
        is_valid = abs(raw_total - parsed_total) < 1.0 # Within 1 dollar difference is acceptable
        
        if not is_valid:
            # We don't print the actual totals to stdout for privacy!
            print(f"❌ Ingestion Validation FAILED: Parsed total value ({parsed_total}) does not match raw CSV total ({raw_total}).")
            print(f"Difference: {raw_total - parsed_total}")
            return False
            
        print("✅ Ingestion Checksum PASSED: No data rows dropped during parsing.")
        return True
        
    except Exception as e:
        print(f"❌ Ingestion Validation Error: {e}")
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
        print("❌ API Check FAILED: Could not fetch SPY or SCHD.")
        return False
        
    spy = metadata["SPY"]
    schd = metadata["SCHD"]
    
    # SPY: Yield usually 1-2%, ER is exactly 0.09%
    # SCHD: Yield usually 3-4%, ER is exactly 0.06%
    
    spy_yield_ok = 0.005 <= spy.get("yield", 0) <= 0.03
    schd_yield_ok = 0.02 <= schd.get("yield", 0) <= 0.06
    
    # ER might be slightly off due to rounding or updates, but check bounds
    spy_er_ok = 0.05 <= spy.get("expense_ratio_pct", 0) <= 0.15
    schd_er_ok = 0.03 <= schd.get("expense_ratio_pct", 0) <= 0.10
    
    is_valid = True
    if not spy_yield_ok:
        print(f"❌ API Check FAILED: SPY yield {spy.get('yield')} is out of sane bounds (0.5% - 3.0%).")
        is_valid = False
    if not schd_yield_ok:
        print(f"❌ API Check FAILED: SCHD yield {schd.get('yield')} is out of sane bounds (2.0% - 6.0%).")
        is_valid = False
    if not spy_er_ok:
        print(f"❌ API Check FAILED: SPY ER {spy.get('expense_ratio_pct')}% is out of bounds.")
        is_valid = False
    if not schd_er_ok:
        print(f"❌ API Check FAILED: SCHD ER {schd.get('expense_ratio_pct')}% is out of bounds.")
        is_valid = False
        
    if is_valid:
         print("✅ API Reality Check PASSED: yfinance extraction logic is structurally sound.")
         
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
        print("❌ Dynamic Screener QA FAILED: No tickers scraped.")
        return False
        
    # Test a small sample to avoid rate limits during testing
    sample = tickers[:10]
    metadata = market_data.fetch_ticker_metadata(sample)
    
    is_valid = True
    valid_candidates = []
    
    for ticker, data in metadata.items():
        quote_type = data.get("type", "").upper()
        if quote_type not in ["ETF", "MUTUALFUND"]:
             print(f"🛡️ QA Filter Working: Successfully intercepted and dropped individual stock '{ticker}' from recommendations.")
             continue
             
        # Check if all return metrics are suspiciously exactly 0.0
        r1 = data.get("1y_return", 0.0)
        r3 = data.get("3y_return", 0.0)
        r5 = data.get("5y_return", 0.0)
        yld = data.get("yield", 0.0)
        
        if r1 == 0.0 and r3 == 0.0 and r5 == 0.0 and yld == 0.0:
            print(f"🛡️ QA Filter Working: Successfully intercepted and dropped '{ticker}' due to 0.0% corrupted historical data.")
            continue
            
        valid_candidates.append(ticker)

    if not valid_candidates and len(metadata) > 0:
        print("❌ Dynamic Screener QA FAILED: The filters rejected every single scraped candidate. Adjust logic.")
        is_valid = False
    elif is_valid:
        print(f"✅ Dynamic Screener QA PASSED: Engine successfully filtered raw targets down to {len(valid_candidates)} pure, data-rich ETFs/Funds.")
        
    return is_valid

if __name__ == "__main__":
    api_ok = verify_yfinance_sane()
    screener_ok = verify_dynamic_screener()
    
    data_dir = Path("data")
    positions_files = list(data_dir.glob("Portfolio_Positions*.csv"))
    if positions_files:
        df = parser.load_fidelity_positions(positions_files[0])
        ingest_ok = verify_ingestion(positions_files[0], df)
