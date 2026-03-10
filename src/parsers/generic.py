"""
parsers/generic.py — Generic Fuzzy-Match Fallback Adapter

Last resort in the registry. Tries to map unknown broker exports to the
canonical schema using fuzzy column name matching. If critical columns
(Symbol, Current Value, Quantity) cannot be found, returns an empty
DataFrame with a warning rather than corrupted data.
"""

from pathlib import Path
from typing import List, Tuple

import numpy as np
import pandas as pd

from parsers.base import BrokerAdapter


# ---------------------------------------------------------------------------
# Fuzzy column name lookup tables
# ---------------------------------------------------------------------------

POSITIONS_FUZZY_MAP = {
    'Current Value':    ['market value', 'mkt val', 'value', 'portfolio value', 'current value'],
    'Quantity':         ['shares', 'units', 'qty', 'shares held', 'quantity'],
    'Cost Basis Total': ['cost basis', 'total cost', 'adjusted cost basis', 'cost basis total'],
    'Average Cost Basis': ['avg cost', 'average cost', 'cost per share', 'average cost basis'],
    'Account Name':     ['account', 'account title', 'portfolio', 'account name'],
    'Symbol':           ['symbol', 'ticker', 'fund'],
    'Description':      ['description', 'fund name', 'name', 'security'],
}

HISTORY_FUZZY_MAP = {
    'Date':        ['run date', 'trade date', 'transaction date', 'date', 'settlement date'],
    'Action':      ['transaction', 'transaction type', 'activity', 'action'],
    'Symbol':      ['symbol', 'ticker'],
    'Description': ['description', 'fund name', 'name', 'security'],
    'Quantity':    ['quantity', 'shares', 'units', 'qty'],
    'Price':       ['price', 'unit price', 'share price'],
    'Amount':      ['net amount', 'total amount', 'transaction amount', 'amount'],
    'Account Name': ['account', 'account name', 'account title', 'portfolio'],
}

CRITICAL_POSITIONS_COLS = {'Symbol', 'Current Value', 'Quantity'}
CRITICAL_HISTORY_COLS = {'Date', 'Symbol', 'Action'}


def _fuzzy_rename(df: pd.DataFrame, fuzzy_map: dict, critical_cols: set) -> pd.DataFrame:
    """
    Attempt to rename df columns to canonical names using the fuzzy lookup map.
    Returns the renamed DataFrame, or an empty DataFrame if critical columns are missing.
    """
    cols_lower = {c.lower().strip(): c for c in df.columns}
    rename_map = {}

    for canonical, candidates in fuzzy_map.items():
        if canonical in df.columns:
            continue  # already canonical
        for cand in candidates:
            if cand.lower() in cols_lower:
                rename_map[cols_lower[cand.lower()]] = canonical
                break

    df = df.rename(columns=rename_map)

    # Check critical columns
    missing_critical = critical_cols - set(df.columns)
    for col in missing_critical:
        print(f"⚠️ Could not map critical column '{col}' — check your broker's export format")

    if missing_critical:
        return pd.DataFrame()

    return df


def _normalize_action_generic(raw: str) -> str:
    s = str(raw).upper()
    if 'BUY' in s or 'BOUGHT' in s or 'PURCHASE' in s:
        return 'Buy'
    if 'SELL' in s or 'SOLD' in s or 'REDEMPTION' in s:
        return 'Sell'
    if 'REINVEST' in s:
        return 'Reinvestment'
    if 'DIVIDEND' in s or 'INCOME' in s or 'DIST' in s:
        return 'Dividend'
    if 'TRANSFER' in s or 'EXCHANGE' in s or 'JOURNAL' in s:
        return 'Transfer'
    return raw


class GenericAdapter(BrokerAdapter):
    """
    Fallback adapter — always returns True from detect().
    Must be last in the ADAPTER_REGISTRY.
    """

    BROKER_NAME = "Generic"

    def detect(self, filepath: Path) -> bool:
        """Always returns True — this is the guaranteed fallback."""
        return True

    def parse_positions(self, filepath: Path) -> pd.DataFrame:
        """Fuzzy-map an unknown positions CSV to canonical schema."""
        path = Path(filepath)
        if path.suffix.lower() not in ('.csv', '.txt', '.xlsx', '.xls'):
            return pd.DataFrame()

        try:
            if path.suffix.lower() in ('.xlsx', '.xls'):
                df = pd.read_excel(path)
            else:
                df = pd.read_csv(path, engine='python', on_bad_lines='skip')
        except Exception as e:
            print(f"⚠️ GenericAdapter: could not read {path.name}: {e}")
            return pd.DataFrame()

        df.columns = df.columns.str.strip()
        df.dropna(how='all', inplace=True)

        df = _fuzzy_rename(df, POSITIONS_FUZZY_MAP, CRITICAL_POSITIONS_COLS)
        if df.empty:
            return df

        # Clean numeric columns that are now canonical
        for col in ['Current Value', 'Quantity', 'Cost Basis Total', 'Average Cost Basis']:
            if col in df.columns:
                df[col] = df[col].astype(str).str.replace(r'[\$\%\,\+]', '', regex=True)
                df[col] = df[col].replace(['--', 'n/a', ''], np.nan)
                df[col] = pd.to_numeric(df[col], errors='coerce')

        if 'Expense Ratio' not in df.columns:
            df['Expense Ratio'] = np.nan
        if 'Account Type' not in df.columns:
            df['Account Type'] = np.nan

        return df

    def parse_history(self, filepath: Path) -> pd.DataFrame:
        """Fuzzy-map an unknown history CSV to canonical schema."""
        path = Path(filepath)
        if path.suffix.lower() not in ('.csv', '.txt', '.xlsx', '.xls'):
            return pd.DataFrame()

        try:
            if path.suffix.lower() in ('.xlsx', '.xls'):
                df = pd.read_excel(path)
            else:
                df = pd.read_csv(path, engine='python', on_bad_lines='skip')
        except Exception as e:
            print(f"⚠️ GenericAdapter: could not read {path.name}: {e}")
            return pd.DataFrame()

        df.columns = df.columns.str.strip()
        df.dropna(how='all', inplace=True)

        df = _fuzzy_rename(df, HISTORY_FUZZY_MAP, CRITICAL_HISTORY_COLS)
        if df.empty:
            return df

        if 'Date' in df.columns:
            df['Date'] = pd.to_datetime(df['Date'].astype(str).str.strip(), errors='coerce')

        for col in ['Price', 'Quantity', 'Amount']:
            if col in df.columns:
                df[col] = df[col].astype(str).str.replace(r'[\$\,\+]', '', regex=True)
                df[col] = df[col].replace(['--', 'n/a', ''], np.nan)
                df[col] = pd.to_numeric(df[col], errors='coerce')

        if 'Action' in df.columns:
            df['Action'] = df['Action'].apply(_normalize_action_generic)

        return df

    def detect_401k(self, filepath: Path) -> bool:
        return False

    def parse_401k(self, filepath: Path) -> Tuple[pd.DataFrame, List[str]]:
        return pd.DataFrame(), []
