"""
parsers/vanguard.py — Vanguard Broker Adapter

Handles Vanguard brokerage CSV exports (positions and history).
"""

from pathlib import Path
from typing import List, Tuple

import numpy as np
import pandas as pd

from parsers.base import BrokerAdapter


def _normalize_vanguard_action(raw: str) -> str:
    s = str(raw).upper()
    if "BUY" in s or "PURCHASE" in s:
        return "Buy"
    if "SELL" in s or "REDEMPTION" in s:
        return "Sell"
    if "REINVEST" in s:
        return "Reinvestment"
    if "DIVIDEND" in s or "INCOME" in s:
        return "Dividend"
    if "TRANSFER" in s or "EXCHANGE" in s:
        return "Transfer"
    return raw


class VanguardAdapter(BrokerAdapter):
    BROKER_NAME = "Vanguard"

    def detect(self, filepath: Path) -> bool:
        if filepath.suffix.lower() not in (".csv", ".txt"):
            return False
        try:
            sample = filepath.read_text(encoding="utf-8-sig", errors="ignore")[:4000]
        except Exception:
            return False
        # Positions: Vanguard uses 'Shares' + 'Share Price' + 'Current Value'
        if "Share Price" in sample and "Shares" in sample and "Current Value" in sample:
            return True
        # History: Vanguard uses 'Trade Date' + 'Transaction Type'
        if "Trade Date" in sample and "Transaction Type" in sample:
            return True
        return False

    def parse_positions(self, filepath: Path) -> pd.DataFrame:
        """Parse a Vanguard positions CSV into canonical schema."""
        path = Path(filepath)
        try:
            df = pd.read_csv(path, engine="python", on_bad_lines="skip")
        except Exception:
            df = pd.read_csv(path, on_bad_lines="skip")

        df.columns = df.columns.str.strip()
        df.dropna(how="all", inplace=True)

        numeric_cols = ["Shares", "Share Price", "Current Value", "Cost Basis"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = df[col].astype(str).str.replace(r"[\$\,\+]", "", regex=True)
                df[col] = df[col].replace(["--", "n/a", ""], np.nan)
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # Rename to canonical
        df = df.rename(
            columns={
                "Shares": "Quantity",
                "Share Price": "Last Price",
                "Cost Basis": "Cost Basis Total",
            }
        )

        # Vanguard doesn't export avg cost per share — derive it
        if "Average Cost Basis" not in df.columns and "Cost Basis Total" in df.columns and "Quantity" in df.columns:
            df["Average Cost Basis"] = df["Cost Basis Total"] / df["Quantity"].replace(0, np.nan)

        if "Expense Ratio" not in df.columns:
            df["Expense Ratio"] = np.nan
        if "Account Type" not in df.columns:
            df["Account Type"] = np.nan

        return df

    def parse_history(self, filepath: Path) -> pd.DataFrame:
        """Parse a Vanguard history CSV into canonical schema."""
        path = Path(filepath)
        try:
            df = pd.read_csv(path, engine="python", on_bad_lines="skip")
        except Exception:
            df = pd.read_csv(path, on_bad_lines="skip")

        df.columns = df.columns.str.strip()
        df.dropna(how="all", inplace=True)

        if "Trade Date" in df.columns:
            df["Trade Date"] = pd.to_datetime(df["Trade Date"].astype(str).str.strip(), errors="coerce")

        for col in ["Price", "Shares", "Net Amount"]:
            if col in df.columns:
                df[col] = df[col].astype(str).str.replace(r"[\$\,\+]", "", regex=True)
                df[col] = df[col].replace(["--", "n/a", ""], np.nan)
                df[col] = pd.to_numeric(df[col], errors="coerce")

        if "Transaction Type" in df.columns:
            df["Transaction Type"] = df["Transaction Type"].apply(_normalize_vanguard_action)

        # Rename to canonical
        df = df.rename(
            columns={
                "Trade Date": "Date",
                "Transaction Type": "Action",
                "Shares": "Quantity",
                "Net Amount": "Amount",
            }
        )

        if "Account Name" not in df.columns and "Account" in df.columns:
            df = df.rename(columns={"Account": "Account Name"})

        return df

    def detect_401k(self, filepath: Path) -> bool:
        return False

    def parse_401k(self, filepath: Path) -> Tuple[pd.DataFrame, List[str]]:
        return pd.DataFrame(), []
