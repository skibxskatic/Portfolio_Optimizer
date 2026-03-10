"""
parsers/principal.py — Principal Financial Group Adapter

Primary use case: 401k PDF statements from Principal.
Principal is a 401k-only provider for most users — no brokerage CSV.
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from parsers.base import BrokerAdapter


class PrincipalAdapter(BrokerAdapter):
    BROKER_NAME = "Principal"

    _DETECT_KEYWORDS = ['Principal', 'principal.com', 'Principal Financial']

    def detect(self, filepath: Path) -> bool:
        name_lower = filepath.name.lower()
        if 'principal' in name_lower:
            return True
        if filepath.suffix.lower() in ('.txt', '.pdf'):
            try:
                if filepath.suffix.lower() == '.txt':
                    sample = filepath.read_text(encoding='utf-8', errors='ignore')[:2000]
                    return any(kw.lower() in sample.lower() for kw in self._DETECT_KEYWORDS)
                return filepath.suffix.lower() == '.pdf'
            except Exception:
                pass
        return False

    def detect_401k(self, filepath: Path) -> bool:
        return self.detect(filepath)

    def parse_positions(self, filepath: Path) -> pd.DataFrame:
        """Principal has no brokerage CSV — return empty canonical DataFrame."""
        return pd.DataFrame(columns=[
            'Symbol', 'Description', 'Account Name', 'Account Type',
            'Quantity', 'Current Value', 'Cost Basis Total',
            'Average Cost Basis', 'Expense Ratio',
        ])

    def parse_history(self, filepath: Path) -> pd.DataFrame:
        return pd.DataFrame()

    def parse_401k(self, filepath: Path) -> Tuple[pd.DataFrame, List[str]]:
        """Parse a Principal 401k PDF or extracted text statement."""
        path = Path(filepath)
        if path.suffix.lower() == '.pdf':
            text = _extract_pdf_text(path)
            if not text:
                return pd.DataFrame(), []
        elif path.suffix.lower() == '.txt':
            try:
                text = path.read_text(encoding='utf-8')
            except Exception:
                return pd.DataFrame(), []
        else:
            return pd.DataFrame(), []

        return _parse_principal_text(text)


def _extract_pdf_text(path: Path) -> Optional[str]:
    try:
        from pypdf import PdfReader
    except ImportError:
        print("⚠️ pypdf not installed. Install with: pip install pypdf")
        return None
    try:
        reader = PdfReader(str(path))
        return '\n'.join(
            page.extract_text() for page in reader.pages if page.extract_text()
        )
    except Exception as e:
        print(f"⚠️ PDF extraction failed for {path.name}: {e}")
        return None


def _parse_principal_text(text: str) -> Tuple[pd.DataFrame, List[str]]:
    """
    Extract holdings and plan menu from Principal statement text.
    Looks for fund name + ticker patterns and associated balances.
    """
    pattern = r'([A-Z][A-Za-z0-9&\' /\-\.]+?)\s*\(([A-Z]{2,6}(?:\d{0,2})?)\)'
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
        print("⚠️ Could not extract fund tickers from Principal statement.")
        return pd.DataFrame(), []

    holdings = []
    for display_name, ticker in plan_menu.items():
        escaped = re.escape(ticker)
        m = re.search(rf'{escaped}.*?\$([\d,]+\.?\d*)', text, re.DOTALL)
        if m:
            balance = float(m.group(1).replace(',', ''))
            holdings.append({
                'Symbol': ticker,
                'Description': display_name,
                'Current Value': balance,
                'Cost Basis Total': 0.0,
                'Account Name': '401k',
                'Account Type': 'Employer 401k',
            })

    holdings_df = pd.DataFrame(holdings)
    plan_tickers = sorted(set(plan_menu.values()))
    return holdings_df, plan_tickers
