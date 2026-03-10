"""
parsers/fidelity.py — Fidelity Investments Broker Adapter

Handles:
- Fidelity Portfolio_Positions.csv  → parse_positions()
- Fidelity Accounts_History*.csv    → parse_history()
- Fidelity 401k extracted text/PDF  → detect_401k() / parse_401k()

All output columns conform to the canonical schema defined in parsers/base.py.
"""

import io
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from parsers.base import BrokerAdapter, CANONICAL_POSITIONS_COLS, CANONICAL_HISTORY_COLS


# ---------------------------------------------------------------------------
# Action normalization map
# ---------------------------------------------------------------------------

def _normalize_fidelity_action(raw: str) -> str:
    """Map verbose Fidelity action strings to canonical action values."""
    s = str(raw).upper()
    if 'BUY' in s or 'BOUGHT' in s:
        return 'Buy'
    if 'SOLD' in s or 'SELL' in s:
        return 'Sell'
    if 'REINVEST' in s:
        return 'Reinvestment'
    if 'DIVIDEND' in s:
        return 'Dividend'
    if 'TRANSFER' in s:
        return 'Transfer'
    return raw  # keep original if no match


# ---------------------------------------------------------------------------
# Fidelity Adapter
# ---------------------------------------------------------------------------

class FidelityAdapter(BrokerAdapter):
    BROKER_NAME = "Fidelity"

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def detect(self, filepath: Path) -> bool:
        """Return True if the file looks like a Fidelity positions or history export."""
        if filepath.suffix.lower() not in ('.csv', '.txt'):
            return False
        try:
            sample = filepath.read_text(encoding='utf-8-sig', errors='ignore')[:4000]
        except Exception:
            return False
        # Positions: distinctive Fidelity columns
        if 'Cost Basis Total' in sample and 'Account Number' in sample:
            return True
        # History: Run Date + Settlement Date
        if 'Run Date' in sample and 'Settlement Date' in sample:
            return True
        return False

    def detect_401k(self, filepath: Path) -> bool:
        """Return True if this file looks like a Fidelity 401k options/balance file."""
        if filepath.suffix.lower() not in ('.txt', '.pdf', '.csv'):
            return False
        try:
            sample = filepath.read_text(encoding='utf-8', errors='ignore')[:3000]
        except Exception:
            return False
        return 'Investment Choices' in sample or 'Balance Overview' in sample

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    def parse_positions(self, filepath: Path) -> pd.DataFrame:
        """
        Loads and cleans a Fidelity Portfolio_Positions CSV.
        CRITICAL: This file must be a fresh export right before running the analyzer.
        """
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Positions file not found at {path}")

        try:
            df = pd.read_csv(path, engine='python', index_col=False, on_bad_lines='skip')
        except Exception:
            df = pd.read_csv(path, index_col=False, on_bad_lines='skip')

        df.columns = df.columns.str.strip()
        df.dropna(how='all', inplace=True)

        # Remove summary rows (Account Total, Pending Activity)
        df = df[df['Symbol'].notna()]
        df = df[df['Symbol'].astype(str).str.strip() != '']

        # Strip Fidelity's '**' suffix from cash tickers (e.g. 'SPAXX**')
        df['Symbol'] = df['Symbol'].astype(str).str.replace(r'\*+', '', regex=True)

        # Clean numeric columns
        cols_to_clean = [
            'Quantity', 'Last Price', 'Last Price Change', 'Current Value',
            "Today's Gain/Loss Dollar", "Today's Gain/Loss Percent",
            'Total Gain/Loss Dollar', 'Total Gain/Loss Percent',
            'Percent Of Account', 'Cost Basis Total', 'Average Cost Basis',
        ]
        for col in cols_to_clean:
            if col in df.columns:
                df[col] = df[col].astype(str).str.replace(r'[\$\%\,\+]', '', regex=True)
                df[col] = df[col].replace(['--', 'n/a', ''], np.nan)
                df[col] = pd.to_numeric(df[col], errors='coerce')

        # Fidelity positions already use canonical column names:
        # Account Name, Current Value, Cost Basis Total, Average Cost Basis ✓
        # Ensure Expense Ratio column exists (will be filled by market_data later)
        if 'Expense Ratio' not in df.columns:
            df['Expense Ratio'] = np.nan

        return df

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def parse_history(self, filepath: Path) -> pd.DataFrame:
        """
        Loads a Fidelity Accounts_History CSV and returns a canonical history DataFrame.
        Renames: Run Date → Date, Account → Account Name.
        Normalizes Action strings to canonical values.
        """
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"History file not found at {path}")

        with open(path, 'r', encoding='utf-8-sig') as f:
            lines = f.readlines()

        # Find the header row
        start_idx = 0
        for i, line in enumerate(lines):
            if 'Run Date' in line and 'Symbol' in line:
                start_idx = i
                break

        clean_csv = "".join(lines[start_idx:])
        try:
            df = pd.read_csv(io.StringIO(clean_csv), engine='python', on_bad_lines='skip')
        except Exception:
            df = pd.read_csv(io.StringIO(clean_csv), on_bad_lines='skip')

        df.columns = df.columns.str.strip()
        df.dropna(how='all', inplace=True)

        # Parse date
        if 'Run Date' in df.columns:
            df['Run Date'] = pd.to_datetime(df['Run Date'].astype(str).str.strip(), errors='coerce')

        # Clean numeric columns
        for col in ['Price', 'Quantity', 'Amount']:
            if col in df.columns:
                df[col] = df[col].astype(str).str.replace(r'[\$\%\,\+]', '', regex=True)
                df[col] = df[col].replace(['--', 'n/a', ''], np.nan)
                df[col] = pd.to_numeric(df[col], errors='coerce')

        # Normalize action strings to canonical values
        if 'Action' in df.columns:
            df['Action'] = df['Action'].apply(_normalize_fidelity_action)

        # Rename to canonical column names
        df = df.rename(columns={
            'Run Date': 'Date',
            'Account': 'Account Name',
        })

        return df

    # ------------------------------------------------------------------
    # 401k
    # ------------------------------------------------------------------

    def parse_401k(self, filepath: Path) -> Tuple[pd.DataFrame, List[str]]:
        """
        Parses a Fidelity 401k Investment Options extracted text file.
        Delegates to the module-level functions below.
        """
        return parse_401k_options_file(filepath)


# ---------------------------------------------------------------------------
# 401k Parsing Logic (formerly in 401k_parser.py)
# ---------------------------------------------------------------------------

def extract_plan_menu(text: str) -> Dict[str, str]:
    """
    Dynamically extracts the full plan menu (all available investment options)
    from Investment Options extracted text.

    Scans for all occurrences of 'FUND NAME (TICKER)' patterns.
    Returns a dict mapping display names → ticker symbols.
    """
    pattern = r'([A-Z][A-Za-z0-9&\' /\-\.]+?)\s*\(([A-Z]{2,6}(?:\d{0,2})?)\)'
    matches = re.findall(pattern, text)

    noise_prefixes = [
        "Show", "mark", "ReturnsAs OfBench-mark", "ReturnsAs Of",
        "Bench-mark", "ViewChart", "View", "Select",
        "Invested Balance Cost Basis YTDReturnsAs OfViewChart",
        "Performance", "Details", "Add to Watchlist",
    ]

    plan_menu: Dict[str, str] = {}
    seen_tickers: set = set()
    for name, ticker in matches:
        name = name.strip()
        ticker = ticker.strip()

        if len(ticker) < 2 or ticker in ("HTTP", "HTTPS", "HTML", "VIEW"):
            continue

        for prefix in noise_prefixes:
            if name.startswith(prefix):
                name = name[len(prefix):].strip()

        if not name:
            continue

        if ticker not in seen_tickers:
            plan_menu[name] = ticker
            seen_tickers.add(ticker)

    return plan_menu


def extract_current_holdings(text: str, plan_menu: Dict[str, str]) -> pd.DataFrame:
    """
    Extracts the user's current 401k holdings from the Balance Overview section.

    Returns a DataFrame with canonical columns:
    Symbol, Description, Current Value, Cost Basis Total, Account Name, Account Type
    """
    holdings = []

    for display_name, ticker in plan_menu.items():
        escaped_ticker = re.escape(ticker)
        pattern = (
            rf'{escaped_ticker}\)'
            rf'.*?'
            rf'([\d.]+)%'
            rf'\s*\$([\d,]+\.?\d*)'
            rf'\s*\$([\d,]+\.?\d*)'
        )
        match = re.search(pattern, text, re.DOTALL)
        if not match:
            # Strategy B: relaxed fallback
            pattern_b = rf'{escaped_ticker}.*?\$([\d,]+\.?\d*)'
            match_b = re.search(pattern_b, text, re.DOTALL)
            if match_b:
                balance = float(match_b.group(1).replace(',', ''))
                holdings.append({
                    'Symbol': ticker,
                    'Fund Name': display_name,
                    'Description': display_name,
                    'Current Value': balance,
                    'Cost Basis Total': 0.0,
                    'Pct Invested': 0.0,
                    'Account Name': '401k',
                    'Account Type': 'Employer 401k',
                })
            continue

        pct_invested = float(match.group(1))
        balance = float(match.group(2).replace(',', ''))
        cost_basis = float(match.group(3).replace(',', ''))
        holdings.append({
            'Symbol': ticker,
            'Fund Name': display_name,
            'Description': display_name,
            'Current Value': balance,
            'Cost Basis Total': cost_basis,
            'Pct Invested': pct_invested,
            'Account Name': '401k',
            'Account Type': 'Employer 401k',
        })

    return pd.DataFrame(holdings)


def get_plan_menu_tickers(plan_menu: Dict[str, str]) -> List[str]:
    """Returns a sorted list of all ticker symbols available in the plan."""
    return sorted(set(plan_menu.values()))


def parse_401k_options_file(options_text_path: Path) -> Tuple[pd.DataFrame, List[str]]:
    """
    Master entry point: parses an Investment Options extracted text file.

    Returns:
    - holdings_df: DataFrame of the user's current 401k holdings
    - plan_menu_tickers: List of all ticker symbols available in the plan
    """
    text = options_text_path.read_text(encoding='utf-8')
    plan_menu = extract_plan_menu(text)

    if not plan_menu:
        print("⚠️ Could not dynamically extract any fund tickers from the 401k Investment Options text.")
        return pd.DataFrame(), []

    print(f"   Dynamically extracted {len(plan_menu)} funds from 401k plan menu.")
    holdings_df = extract_current_holdings(text, plan_menu)

    if holdings_df.empty:
        print("⚠️ No current 401k holdings found in Balance Overview.")
    else:
        print(f"   Found {len(holdings_df)} current 401k holdings.")

    plan_tickers = get_plan_menu_tickers(plan_menu)
    return holdings_df, plan_tickers


def find_401k_options_file(data_dir: Path) -> Optional[Path]:
    """
    Scans the data directory for an extracted 401k Investment Options text file.
    Kept for backward compatibility — used by the shim in 401k_parser.py.
    """
    search_dirs = [data_dir / ".cache", data_dir]

    for search_dir in search_dirs:
        patterns = [
            "extracted_text_*Investment Options*.txt",
            "extracted_text_*investment options*.txt",
            "extracted_text_*401k*Options*.txt",
            "extracted_text_*401k*options*.txt",
        ]
        for pattern in patterns:
            matches = list(search_dir.glob(pattern))
            if matches:
                return matches[0]

        for pattern in ["extracted_text_*401k*.txt", "extracted_text_*.txt"]:
            for p in search_dir.glob(pattern):
                if "Transaction" in str(p) or "transaction" in str(p):
                    continue
                try:
                    content = p.read_text(encoding='utf-8')[:2000]
                    if 'Investment Choices' in content or 'Balance Overview' in content:
                        return p
                except Exception:
                    pass

        for p in search_dir.glob("extracted_text_*401k*.txt"):
            if "Transaction" not in str(p) and "transaction" not in str(p):
                try:
                    content = p.read_text(encoding='utf-8')[:2000]
                    if "Investment Choices" in content or "Balance Overview" in content:
                        return p
                except Exception:
                    pass

    return None


# ---------------------------------------------------------------------------
# Tax Lot Unrolling (uses canonical column names)
# ---------------------------------------------------------------------------

def unroll_tax_lots(positions_df: pd.DataFrame, history_df: pd.DataFrame) -> pd.DataFrame:
    """
    Reconstructs individual tax lots from positions + history using FIFO accounting.

    Expects canonical column names:
    - history_df: 'Date' (datetime), 'Action' (normalized: 'Buy' or 'Reinvestment')
    - positions_df: 'Average Cost Basis', 'Last Price', 'Quantity', 'Symbol'
    """
    unrolled_lots = []

    # Filter history for canonical buy actions only
    buy_actions = {'Buy', 'Reinvestment'}
    buys_df = history_df[history_df['Action'].isin(buy_actions)].copy()

    for _, pos in positions_df.iterrows():
        symbol = pos.get('Symbol')
        current_qty = pos.get('Quantity', 0)

        if pd.isna(symbol) or current_qty <= 0:
            continue

        # Sort newest-to-oldest under FIFO (shares still held = most recently bought)
        sym_buys = buys_df[buys_df['Symbol'] == symbol].sort_values(
            by='Date', ascending=False
        )

        shares_needed = current_qty

        for _, buy in sym_buys.iterrows():
            if shares_needed <= 0:
                break
            buy_qty = float(buy.get('Quantity', 0))
            if buy_qty <= 0:
                continue

            qty_to_take = min(shares_needed, buy_qty)
            shares_needed -= qty_to_take
            unit_price = float(buy.get('Price', 0))

            unrolled_lots.append({
                'Symbol': symbol,
                'Description': pos.get('Description'),
                'Purchase Date': buy.get('Date'),
                'Quantity': qty_to_take,
                'Unit Cost': unit_price,
                'Cost Basis': qty_to_take * unit_price,
                'Current Unit Price': pos.get('Last Price', 0),
                'Current Value': qty_to_take * pos.get('Last Price', 0),
                'Unrealized Gain': (
                    (qty_to_take * pos.get('Last Price', 0))
                    - (qty_to_take * unit_price)
                ),
            })

        # Fallback lot for shares with no matching history (transfers, etc.)
        if shares_needed > 0.001:
            unrolled_lots.append({
                'Symbol': symbol,
                'Description': pos.get('Description'),
                'Purchase Date': pd.NaT,
                'Quantity': shares_needed,
                'Unit Cost': pos.get('Average Cost Basis', 0),
                'Cost Basis': shares_needed * pos.get('Average Cost Basis', 0),
                'Current Unit Price': pos.get('Last Price', 0),
                'Current Value': shares_needed * pos.get('Last Price', 0),
                'Unrealized Gain': (
                    (shares_needed * pos.get('Last Price', 0))
                    - (shares_needed * pos.get('Average Cost Basis', 0))
                ),
            })

    return pd.DataFrame(unrolled_lots)
