"""
parsers/schwab.py — Charles Schwab Broker Adapter

Handles Schwab brokerage CSV exports (positions and history).
Schwab 401k is handled separately if needed via a dedicated provider adapter.
"""

from pathlib import Path
from typing import List, Tuple

import numpy as np
import pandas as pd

from parsers.base import BrokerAdapter


def _normalize_schwab_action(raw: str) -> str:
    s = str(raw).upper()
    if 'BUY' in s or 'BOUGHT' in s:
        return 'Buy'
    if 'SELL' in s or 'SOLD' in s:
        return 'Sell'
    if 'REINVEST' in s:
        return 'Reinvestment'
    if 'DIVIDEND' in s or 'QUAL DIV' in s or 'CASH DIV' in s:
        return 'Dividend'
    if 'TRANSFER' in s or 'JOURNAL' in s:
        return 'Transfer'
    return raw


class SchwabAdapter(BrokerAdapter):
    BROKER_NAME = "Schwab"

    def detect(self, filepath: Path) -> bool:
        if filepath.suffix.lower() not in ('.csv', '.txt'):
            return False
        try:
            sample = filepath.read_text(encoding='utf-8-sig', errors='ignore')[:4000]
        except Exception:
            return False
        # Positions: Schwab-specific column names
        if 'Unrealized Gain/Loss ($)' in sample and 'Qty' in sample:
            return True
        # History: Schwab history marker
        if 'Fees & Comm' in sample and 'Date' in sample and 'Action' in sample:
            return True
        return False

    def parse_positions(self, filepath: Path) -> pd.DataFrame:
        """Parse a Schwab positions CSV into canonical schema."""
        path = Path(filepath)
        try:
            df = pd.read_csv(path, engine='python', on_bad_lines='skip')
        except Exception:
            df = pd.read_csv(path, on_bad_lines='skip')

        df.columns = df.columns.str.strip()
        df.dropna(how='all', inplace=True)

        # Clean numeric columns
        numeric_cols = ['Market Value', 'Qty', 'Cost Basis', 'Avg Cost/Share', 'Price']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = df[col].astype(str).str.replace(r'[\$\,\+]', '', regex=True)
                df[col] = df[col].replace(['--', 'n/a', ''], np.nan)
                df[col] = pd.to_numeric(df[col], errors='coerce')

        # Rename to canonical
        df = df.rename(columns={
            'Market Value': 'Current Value',
            'Qty': 'Quantity',
            'Cost Basis': 'Cost Basis Total',
            'Avg Cost/Share': 'Average Cost Basis',
        })

        if 'Expense Ratio' not in df.columns:
            df['Expense Ratio'] = np.nan
        if 'Account Type' not in df.columns:
            df['Account Type'] = np.nan

        return df

    def parse_history(self, filepath: Path) -> pd.DataFrame:
        """Parse a Schwab history CSV into canonical schema."""
        path = Path(filepath)
        try:
            df = pd.read_csv(path, engine='python', on_bad_lines='skip')
        except Exception:
            df = pd.read_csv(path, on_bad_lines='skip')

        df.columns = df.columns.str.strip()
        df.dropna(how='all', inplace=True)

        if 'Date' in df.columns:
            df['Date'] = pd.to_datetime(df['Date'].astype(str).str.strip(), errors='coerce')

        for col in ['Price', 'Quantity', 'Amount']:
            if col in df.columns:
                df[col] = df[col].astype(str).str.replace(r'[\$\,\+]', '', regex=True)
                df[col] = df[col].replace(['--', 'n/a', ''], np.nan)
                df[col] = pd.to_numeric(df[col], errors='coerce')

        if 'Action' in df.columns:
            df['Action'] = df['Action'].apply(_normalize_schwab_action)

        # Schwab uses 'Description' already; ensure Account Name exists
        if 'Account Name' not in df.columns and 'Account' in df.columns:
            df = df.rename(columns={'Account': 'Account Name'})

        return df

    def detect_401k(self, filepath: Path) -> bool:
        return False

    def parse_401k(self, filepath: Path) -> Tuple[pd.DataFrame, List[str]]:
        return pd.DataFrame(), []
