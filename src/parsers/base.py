"""
parsers/base.py — Abstract Broker Adapter Base Class

Defines the canonical schema and the interface all broker adapters must implement.
The analysis engine (portfolio_analyzer.py, metrics.py, etc.) only ever consumes
the canonical column names defined here.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd


# ---------------------------------------------------------------------------
# Canonical Schema
# ---------------------------------------------------------------------------

CANONICAL_POSITIONS_COLS: List[str] = [
    "Symbol",
    "Description",
    "Account Name",
    "Account Type",
    "Quantity",
    "Current Value",
    "Cost Basis Total",
    "Average Cost Basis",
    "Expense Ratio",
]

CANONICAL_HISTORY_COLS: List[str] = [
    "Date",  # datetime
    "Action",  # normalized: Buy | Sell | Reinvestment | Dividend | Transfer
    "Symbol",
    "Description",
    "Quantity",
    "Price",
    "Amount",
    "Account Name",
]

# Normalized action values — all adapters must map to one of these
CANONICAL_ACTIONS = {"Buy", "Sell", "Reinvestment", "Dividend", "Transfer"}


# ---------------------------------------------------------------------------
# Abstract Base
# ---------------------------------------------------------------------------


class BrokerAdapter(ABC):
    """Abstract base class for broker-specific file parsers.

    All concrete adapters must:
    1. Implement detect() to identify whether a file came from this broker.
    2. Implement parse_positions() to return a DataFrame with CANONICAL_POSITIONS_COLS.
    3. Implement parse_history() to return a DataFrame with CANONICAL_HISTORY_COLS,
       with Date as datetime and Action normalized to CANONICAL_ACTIONS values.
    4. Optionally override detect_401k() and parse_401k() for retirement plan files.
    """

    BROKER_NAME: str = "Unknown"

    @abstractmethod
    def detect(self, filepath: Path) -> bool:
        """Return True if this file appears to be from this broker."""
        ...

    @abstractmethod
    def parse_positions(self, filepath: Path) -> pd.DataFrame:
        """Parse a positions/holdings file into the canonical positions schema."""
        ...

    @abstractmethod
    def parse_history(self, filepath: Path) -> pd.DataFrame:
        """Parse a transaction history file into the canonical history schema."""
        ...

    def detect_401k(self, filepath: Path) -> bool:
        """Return True if this file is a 401k/retirement plan file from this broker."""
        return False

    def parse_401k(self, filepath: Path) -> Tuple[pd.DataFrame, List[str], Optional[Dict[str, str]]]:
        """Parse a 401k file. Returns (holdings_df, plan_menu_tickers, plan_menu_dict)."""
        return pd.DataFrame(), [], None
