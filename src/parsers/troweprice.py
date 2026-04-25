"""
parsers/troweprice.py — T. Rowe Price Broker Adapter

Primary use case: 401k/retirement plan PDF statements.
T. Rowe Price is primarily a retirement provider, not a brokerage.
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from parsers.base import BrokerAdapter


class TRowePriceAdapter(BrokerAdapter):
    BROKER_NAME = "T. Rowe Price"

    _DETECT_KEYWORDS = ["T. Rowe Price", "troweprice", "T.RowePrice", "TROWEPRICE"]

    def detect(self, filepath: Path) -> bool:
        name_lower = filepath.name.lower()
        if "troweprice" in name_lower or "t rowe" in name_lower or "t_rowe" in name_lower:
            return True
        if filepath.suffix.lower() in (".txt", ".csv"):
            try:
                sample = filepath.read_text(encoding="utf-8", errors="ignore")[:2000]
                return any(kw.lower() in sample.lower() for kw in self._DETECT_KEYWORDS)
            except Exception:
                pass
        return False

    def detect_401k(self, filepath: Path) -> bool:
        if not self.detect(filepath):
            return False
        if filepath.suffix.lower() in (".pdf", ".txt"):
            try:
                if filepath.suffix.lower() == ".txt":
                    sample = filepath.read_text(encoding="utf-8", errors="ignore")[:3000]
                    return "Balance" in sample or "Fund" in sample or "Investment" in sample
            except Exception:
                pass
            return filepath.suffix.lower() == ".pdf"
        return False

    def parse_positions(self, filepath: Path) -> pd.DataFrame:
        """Basic CSV fallback for T. Rowe Price CSV exports."""
        path = Path(filepath)
        if not path.exists() or path.suffix.lower() not in (".csv",):
            return pd.DataFrame()

        try:
            df = pd.read_csv(path, engine="python", on_bad_lines="skip")
        except Exception:
            return pd.DataFrame()

        df.columns = df.columns.str.strip()
        df.dropna(how="all", inplace=True)

        # Generic column mapping
        col_map = {}
        cols_lower = {c.lower(): c for c in df.columns}
        for canonical, candidates in [
            ("Current Value", ["market value", "balance", "value"]),
            ("Quantity", ["shares", "units", "qty"]),
            ("Cost Basis Total", ["cost basis", "total cost"]),
            ("Average Cost Basis", ["avg cost", "average cost", "cost per share"]),
            ("Account Name", ["account", "account title"]),
        ]:
            for cand in candidates:
                if cand in cols_lower:
                    col_map[cols_lower[cand]] = canonical
                    break

        df = df.rename(columns=col_map)
        if "Expense Ratio" not in df.columns:
            df["Expense Ratio"] = np.nan
        if "Account Type" not in df.columns:
            df["Account Type"] = "Employer 401k"

        return df

    def parse_history(self, filepath: Path) -> pd.DataFrame:
        return pd.DataFrame()

    def parse_401k(self, filepath: Path) -> Tuple[pd.DataFrame, List[str]]:
        """
        Parse a T. Rowe Price 401k statement.
        For PDF files: extract text inline then parse for fund tickers and balances.
        For TXT files: parse directly.
        """
        path = Path(filepath)
        if path.suffix.lower() == ".pdf":
            text = _extract_pdf_text(path)
            if not text:
                return pd.DataFrame(), []
        elif path.suffix.lower() == ".txt":
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                return pd.DataFrame(), []
        else:
            return pd.DataFrame(), []

        return _parse_trp_text(text)


def _extract_pdf_text(path: Path) -> Optional[str]:
    try:
        from pypdf import PdfReader
    except ImportError:
        print("⚠️ pypdf not installed. Install with: pip install pypdf")
        return None
    try:
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() for page in reader.pages if page.extract_text())
    except Exception as e:
        print(f"⚠️ PDF extraction failed for {path.name}: {e}")
        return None


def _parse_trp_text(text: str) -> Tuple[pd.DataFrame, List[str]]:
    """
    Extract holdings and plan menu from T. Rowe Price statement text.
    Looks for fund name + ticker patterns and associated balances.
    """
    # Reuse the same regex pattern used by the Fidelity adapter
    pattern = r"([A-Z][A-Za-z0-9&\' /\-\.]+?)\s*\(([A-Z]{2,6}(?:\d{0,2})?)\)"
    matches = re.findall(pattern, text)

    plan_menu: Dict[str, str] = {}
    seen_tickers: set = set()
    for name, ticker in matches:
        name = name.strip()
        ticker = ticker.strip()
        if len(ticker) < 2 or ticker in ("HTTP", "HTTPS", "HTML", "VIEW"):
            continue
        if ticker not in seen_tickers:
            plan_menu[name] = ticker
            seen_tickers.add(ticker)

    if not plan_menu:
        print("⚠️ Could not extract fund tickers from T. Rowe Price statement.")
        return pd.DataFrame(), []

    holdings = []
    for display_name, ticker in plan_menu.items():
        escaped = re.escape(ticker)
        # Look for dollar balance near the ticker
        m = re.search(rf"{escaped}.*?\$([\d,]+\.?\d*)", text, re.DOTALL)
        if m:
            balance = float(m.group(1).replace(",", ""))
            holdings.append(
                {
                    "Symbol": ticker,
                    "Description": display_name,
                    "Current Value": balance,
                    "Cost Basis Total": 0.0,
                    "Account Name": "401k",
                    "Account Type": "Employer 401k",
                }
            )

    holdings_df = pd.DataFrame(holdings)
    plan_tickers = sorted(set(plan_menu.values()))
    return holdings_df, plan_tickers
