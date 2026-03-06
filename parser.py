import pandas as pd
import numpy as np
from pathlib import Path

def load_fidelity_positions(csv_path: str | Path) -> pd.DataFrame:
    """
    Loads and cleans the Fidelity 'Portfolio_Positions' CSV file.
    CRITICAL: This file MUST be a fresh export right before running the analyzer.
    The engine relies entirely on this file for true current share quantities and 
    intentionally ignores 'Sell' transactions in history exports to prevent math errors.
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Positions file not found at {path}")

    # Read the CSV. We skip the bad lines at the bottom which usually contain disclaimers and empty data.
    try:
        df = pd.read_csv(path, engine='python', index_col=False, on_bad_lines='skip')
    except Exception as e:
        # Fallback to standard read if engine='python' fails
        df = pd.read_csv(path, index_col=False, on_bad_lines='skip')

    # Clean column names (strip whitespace)
    df.columns = df.columns.str.strip()

    # Drop any entirely empty rows
    df.dropna(how='all', inplace=True)

    # Remove the summary "Pending Activity" or "Account Total" rows that Fidelity puts at the bottom
    # We look for rows where 'Symbol' is NaN or empty, but keep Cash
    df = df[df['Symbol'].notna()]
    df = df[df['Symbol'].astype(str).str.strip() != '']
    
    # Fidelity often appends '**' to core cash positions (e.g. 'SPAXX**')
    df['Symbol'] = df['Symbol'].astype(str).str.replace(r'\*+', '', regex=True)

    # Clean numeric columns (Fidelity uses '$', '%', and ',' in their numbers)
    cols_to_clean = [
        'Quantity', 'Last Price', 'Last Price Change', 'Current Value',
        'Today\'s Gain/Loss Dollar', 'Today\'s Gain/Loss Percent',
        'Total Gain/Loss Dollar', 'Total Gain/Loss Percent',
        'Percent Of Account', 'Cost Basis Total', 'Average Cost Basis'
    ]

    for col in cols_to_clean:
        if col in df.columns:
            # Remove '$', '%', ',', and '+' signs
            df[col] = df[col].astype(str).str.replace(r'[\$\%\,\+]', '', regex=True)
            # Handle '--' or 'n/a' which mean 0.0 or NaN
            df[col] = df[col].replace(['--', 'n/a', ''], np.nan)
            # Convert to numeric
            df[col] = pd.to_numeric(df[col], errors='coerce')

    return df

def load_fidelity_history(csv_path: str | Path) -> pd.DataFrame:
    """
    Loads the Fidelity account history CSV (useful for finding exact purchase dates of lots).
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"History file not found at {path}")

    # History usually has a few trailing blank lines, and starts with a BOM + a blank line
    # The safest way is to find the header row first
    with open(path, 'r', encoding='utf-8-sig') as f:
        lines = f.readlines()
        
    start_idx = 0
    for i, line in enumerate(lines):
        if 'Run Date' in line and 'Symbol' in line:
            start_idx = i
            break
            
    # Write the clean lines to a temp object and parse
    import io
    clean_csv = "".join(lines[start_idx:])
    
    try:
        df = pd.read_csv(io.StringIO(clean_csv), engine='python', on_bad_lines='skip')
    except Exception:
        df = pd.read_csv(io.StringIO(clean_csv), on_bad_lines='skip')
        
    df.columns = df.columns.str.strip()
    df.dropna(how='all', inplace=True)

    # Convert Run Date to datetime
    if 'Run Date' in df.columns:
        # Fidelity sometimes uses empty strings or weird formats
        df['Run Date'] = pd.to_datetime(df['Run Date'].str.strip(), errors='coerce')

    # Clean numeric columns
    cols_to_clean = ['Price', 'Quantity', 'Amount']
    for col in cols_to_clean:
        if col in df.columns:
            df[col] = df[col].astype(str).str.replace(r'[\$\%\,\+]', '', regex=True)
            df[col] = df[col].replace(['--', 'n/a', ''], np.nan)
            df[col] = pd.to_numeric(df[col], errors='coerce')

    return df

def unroll_tax_lots(positions_df: pd.DataFrame, history_df: pd.DataFrame) -> pd.DataFrame:
    """
    Takes the aggregated Portfolio Positions and the Account History and reconstructs 
    individual tax lots using standard FIFO (First-In-First-Out) accounting.
    This is necessary because standard Fidelity Positions CSVs aggregate everything into 'Average Cost'.
    """
    unrolled_lots = []
    
    # Filter history for buys only (YOU BOUGHT or REINVESTMENT)
    buys_df = history_df[history_df['Action'].astype(str).str.contains('BUY|BOUGHT|REINVEST', case=False, na=False)].copy()
    
    for _, pos in positions_df.iterrows():
        symbol = pos.get('Symbol')
        current_qty = pos.get('Quantity', 0)
        
        if pd.isna(symbol) or current_qty <= 0:
            continue
            
        # Get all buys for this symbol, sort newest to oldest (DESCENDING)
        # Because under FIFO, the shares you still hold today are the ones you bought most recently
        sym_buys = buys_df[buys_df['Symbol'] == symbol].sort_values(by='Run Date', ascending=False)
        
        shares_needed = current_qty
        
        for _, buy in sym_buys.iterrows():
            if shares_needed <= 0:
                break
                
            buy_qty = float(buy.get('Quantity', 0))
            if buy_qty <= 0:
                continue
                
            qty_to_take = min(shares_needed, buy_qty)
            shares_needed -= qty_to_take
            
            # Create a discrete lot record
            unit_price = float(buy.get('Price', 0))
            unrolled_lots.append({
                'Symbol': symbol,
                'Description': pos.get('Description'),
                'Purchase Date': buy.get('Run Date'),
                'Quantity': qty_to_take,
                'Unit Cost': unit_price,
                'Cost Basis': qty_to_take * unit_price,
                'Current Unit Price': pos.get('Last Price', 0),
                'Current Value': qty_to_take * pos.get('Last Price', 0),
                'Unrealized Gain': (qty_to_take * pos.get('Last Price', 0)) - (qty_to_take * unit_price)
            })
            
        # If we couldn't find enough history (perhaps they transferred assets in), just dump the rest as one lot
        if shares_needed > 0.001: # allow tiny fractional rounding errors
            unrolled_lots.append({
                'Symbol': symbol,
                'Description': pos.get('Description'),
                'Purchase Date': pd.NaT, # Missing history
                'Quantity': shares_needed,
                'Unit Cost': pos.get('Average Cost Basis', 0),
                'Cost Basis': shares_needed * pos.get('Average Cost Basis', 0),
                'Current Unit Price': pos.get('Last Price', 0),
                'Current Value': shares_needed * pos.get('Last Price', 0),
                'Unrealized Gain': (shares_needed * pos.get('Last Price', 0)) - (shares_needed * pos.get('Average Cost Basis', 0))
            })
            
    return pd.DataFrame(unrolled_lots)
    
if __name__ == "__main__":
    # Test script to verify parsing
    data_dir = Path("data")
    positions_file = list(data_dir.glob("Portfolio_Positions*.csv"))
    history_file = list(data_dir.glob("Accounts_History*.csv"))

    if positions_file:
        print(f"Loading {positions_file[0].name}...")
        pos_df = load_fidelity_positions(positions_file[0])
        print(f"Loaded {len(pos_df)} positions.")
        print(pos_df[['Symbol', 'Description', 'Quantity', 'Current Value', 'Total Gain/Loss Percent']].head())
    
    if history_file:
        print(f"\nLoading {history_file[0].name}...")
        hist_df = load_fidelity_history(history_file[0])
        print(f"Loaded {len(hist_df)} historical records.")
        print(hist_df[['Run Date', 'Action', 'Symbol', 'Amount']].head())
