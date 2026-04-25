"""
file_ingestor.py — File Format Auto-Dispatcher

3-layer detection pipeline for ingesting 401k data from any file format:
  Layer 1 — Extension: .csv/.xlsx → pandas, .pdf → inline pypdf extract, .txt → Layer 2
  Layer 2 — Content Sniff: Delimiter test (CSV?) vs ticker pattern test (extracted PDF text?)
  Layer 3 — Column Validation: For CSV/Excel, require ticker-like + value-like columns

Now broker-agnostic: uses ADAPTER_REGISTRY to route 401k files to the correct adapter.
"""

import re
import sys
from typing import Dict, List, Optional, Tuple

import pandas as pd
from pathlib import Path

# Add src directory to path so adapters can import each other
_src_dir = Path(__file__).parent
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from parsers import ADAPTER_REGISTRY
from parsers.base import BrokerAdapter


# ---------------------------------------------------------------------------
# Broker detection
# ---------------------------------------------------------------------------


def detect_broker(filepath: Path) -> BrokerAdapter:
    """
    Iterate through the adapter registry and return the first adapter
    whose detect() returns True. GenericAdapter is always last and always
    returns True, so this never returns None.
    """
    for adapter in ADAPTER_REGISTRY:
        if adapter.detect(filepath):
            return adapter
    # Should never reach here — GenericAdapter always matches
    from parsers.generic import GenericAdapter

    return GenericAdapter()


def _detect_401k_adapter(filepath: Path) -> Optional[BrokerAdapter]:
    """
    Iterate through the adapter registry and return the first adapter
    whose detect_401k() returns True for this file. Returns None if none match.
    """
    for adapter in ADAPTER_REGISTRY:
        if adapter.detect_401k(filepath):
            return adapter
    return None


# ---------------------------------------------------------------------------
# Format detection (kept for backward compat and CSV/Excel dispatch)
# ---------------------------------------------------------------------------


def detect_format(path: Path) -> str:
    """
    Detects the format of a file using a 3-layer pipeline.
    Returns: "csv" | "excel" | "pdf" | "extracted_text" | "unknown"
    """
    ext = path.suffix.lower()

    if ext == ".csv":
        return "csv"
    elif ext in (".xlsx", ".xls"):
        return "excel"
    elif ext == ".pdf":
        return "pdf"
    elif ext == ".txt":
        return _sniff_text_content(path)
    else:
        return "unknown"


def _sniff_text_content(path: Path) -> str:
    """Layer 2: Sniffs text file content to determine if CSV or extracted PDF text."""
    try:
        sample = path.read_text(encoding="utf-8", errors="ignore")[:3000]
    except Exception:
        return "unknown"

    lines = sample.strip().split("\n")
    if len(lines) >= 2:
        comma_counts = [line.count(",") for line in lines[:5]]
        tab_counts = [line.count("\t") for line in lines[:5]]
        if len(set(comma_counts)) <= 2 and comma_counts[0] >= 2:
            return "csv"
        if len(set(tab_counts)) <= 2 and tab_counts[0] >= 2:
            return "csv"

    ticker_pattern = r"\([A-Z]{2,6}\)"
    ticker_matches = re.findall(ticker_pattern, sample)
    if len(ticker_matches) >= 3:
        return "extracted_text"

    keywords = ["Investment Choices", "Balance Overview", "Fund Name", "Ticker"]
    if any(kw in sample for kw in keywords):
        return "extracted_text"

    return "unknown"


def _extract_pdf_text(path: Path) -> Optional[str]:
    """Inline PDF text extraction using pypdf."""
    try:
        from pypdf import PdfReader
    except ImportError:
        print("⚠️ pypdf not installed. Install with: pip install pypdf")
        return None

    try:
        reader = PdfReader(str(path))
        text_parts = []
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
        return "\n".join(text_parts) if text_parts else None
    except Exception as e:
        print(f"⚠️ PDF extraction failed for {path.name}: {e}")
        return None


def _validate_csv_columns(df: pd.DataFrame) -> bool:
    """Layer 3: Column validation for CSV/Excel files."""
    cols_lower = [c.lower() for c in df.columns]
    has_ticker = any(k in cols_lower for k in ["symbol", "ticker", "fund", "fund name"])
    has_value = any(
        k in cols_lower
        for k in [
            "current value",
            "balance",
            "market value",
            "value",
            "shares",
            "quantity",
            "units",
        ]
    )
    return has_ticker and has_value


# ---------------------------------------------------------------------------
# 401k ingestion (public API — unchanged signatures)
# ---------------------------------------------------------------------------


def ingest_401k_file(path: Path) -> Tuple[pd.DataFrame, List[str], Optional[Dict[str, str]]]:
    """
    Dispatches to the correct adapter based on broker detection and file format.
    Returns: (holdings_df, plan_menu_tickers, plan_menu_dict)
    """
    fmt = detect_format(path)

    if fmt == "pdf":
        # For PDFs: extract text, cache it, then find the right adapter
        text = _extract_pdf_text(path)
        if text is None:
            print(f"   Could not extract text from {path.name}")
            return pd.DataFrame(), [], None

        # Cache the extracted text
        cache_dir = path.parent / ".cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / f"extracted_text_{path.stem}.txt"
        cache_path.write_text(text, encoding="utf-8")
        print(f"   Cached extracted PDF text to {cache_path.name}")

        # Try to find an adapter for the cached text file
        adapter = _detect_401k_adapter(cache_path)
        if adapter:
            return adapter.parse_401k(cache_path)
        # Fallback: parse as generic extracted text
        return _parse_extracted_text(text)

    elif fmt == "extracted_text":
        adapter = _detect_401k_adapter(path)
        if adapter:
            return adapter.parse_401k(path)
        text = path.read_text(encoding="utf-8")
        return _parse_extracted_text(text)

    elif fmt in ("csv", "excel"):
        # Try broker-specific parsing first
        adapter = _detect_401k_adapter(path)
        if adapter:
            return adapter.parse_401k(path)
        return _parse_structured_file(path, fmt)

    else:
        print(f"   Unsupported file format for {path.name}")
        return pd.DataFrame(), [], None


def _parse_extracted_text(text: str) -> Tuple[pd.DataFrame, List[str], Dict[str, str]]:
    """Fallback: parse extracted PDF text using the Fidelity adapter's 401k logic."""
    from parsers.fidelity import extract_plan_menu, extract_current_holdings, get_plan_menu_tickers

    plan_menu = extract_plan_menu(text)
    if not plan_menu:
        print("   ⚠️ Could not extract any fund tickers from the text.")
        return pd.DataFrame(), [], {}

    print(f"   Dynamically extracted {len(plan_menu)} funds from 401k plan menu.")
    holdings_df = extract_current_holdings(text, plan_menu)
    plan_tickers = get_plan_menu_tickers(plan_menu)

    if holdings_df.empty:
        print("   ⚠️ No current holdings found. Plan menu was extracted.")
    else:
        print(f"   Found {len(holdings_df)} current 401k holdings.")

    return holdings_df, plan_tickers, plan_menu


def _parse_structured_file(path: Path, fmt: str) -> Tuple[pd.DataFrame, List[str], Dict[str, str]]:
    """Fallback: parse a CSV/Excel 401k file with auto-detected column mapping."""
    try:
        df = pd.read_csv(path) if fmt == "csv" else pd.read_excel(path)
    except Exception as e:
        print(f"   Error reading {path.name}: {e}")
        return pd.DataFrame(), [], {}

    if not _validate_csv_columns(df):
        print(f"   ⚠️ {path.name} does not contain recognizable ticker + value columns.")
        return pd.DataFrame(), [], {}

    cols = {c.lower(): c for c in df.columns}
    ticker_col = cols.get("symbol") or cols.get("ticker") or cols.get("fund")
    value_col = cols.get("current value") or cols.get("balance") or cols.get("market value") or cols.get("value")

    if not ticker_col or not value_col:
        return pd.DataFrame(), [], {}

    # Extract original names if available
    name_col = cols.get("fund name") or cols.get("description") or cols.get("name")

    holdings = []
    plan_menu = {}

    for _, row in df.iterrows():
        sym = str(row.get(ticker_col, "")).strip()
        if not re.match(r"^[A-Z]{1,6}$", sym):
            continue

        name = str(row.get(name_col, sym)) if name_col else sym
        plan_menu[name] = sym
        val = float(row.get(value_col, 0))

        cost_col = cols.get("cost basis") or cols.get("cost basis total")
        cost = float(row.get(cost_col, 0)) if cost_col else 0.0

        holdings.append(
            {
                "Symbol": sym,
                "Fund Name": name,
                "Description": name,
                "Current Value": val,
                "Cost Basis Total": cost,
                "Account Name": "401k",
                "Account Type": "Employer 401k",
            }
        )

    holdings_df = pd.DataFrame(holdings)
    tickers = sorted(set(plan_menu.values()))
    print(f"   Parsed {len(holdings_df)} holdings and {len(tickers)} plan menu tickers from {path.name}.")
    return holdings_df, tickers, plan_menu


# ---------------------------------------------------------------------------
# 401k file discovery (public API — unchanged signature)
# ---------------------------------------------------------------------------


def discover_401k_files(data_dir: Path) -> List[Path]:
    """
    Scans the drop folder for any file that any adapter recognizes as a 401k file,
    plus files with '401k' in the name. Returns a sorted list (PDFs first).
    """
    found = set()
    search_dirs = [data_dir, data_dir / ".cache"]

    for d in search_dirs:
        if not d.exists():
            continue
        for f in d.iterdir():
            if not f.is_file():
                continue
            name_lower = f.name.lower()
            if "transaction" in name_lower:
                continue
            if f.suffix.lower() not in (".csv", ".xlsx", ".xls", ".pdf", ".txt"):
                continue

            # Include if filename matches 401k pattern
            if "401k" in name_lower or "401" in name_lower:
                found.add(f)
                continue

            # Include if any adapter claims this as a 401k file
            if _detect_401k_adapter(f) is not None:
                found.add(f)

    priority = {".pdf": 0, ".csv": 1, ".xlsx": 2, ".xls": 3, ".txt": 4}

    def sort_key(p: Path) -> Tuple[int, int]:
        ext_score = priority.get(p.suffix.lower(), 5)
        name_score = 0 if "options" in p.name.lower() else 1
        return (ext_score, name_score)

    result = sorted(found, key=sort_key)
    return result


if __name__ == "__main__":
    print("=== File Ingestor Smoke Test ===\n")
    data_dir = Path("Drop_Financial_Info_Here")

    files = discover_401k_files(data_dir)
    if files:
        print(f"Discovered {len(files)} 401k file(s):")
        for f in files:
            fmt = detect_format(f)
            print(f"  {f.name} → {fmt}")

        print(f"\nIngesting: {files[0].name}")
        holdings_df, tickers, plan_dict = ingest_401k_file(files[0])
        if not holdings_df.empty:
            print(f"\nHoldings ({len(holdings_df)}):")
            for _, row in holdings_df.iterrows():
                print(f"  {row['Symbol']:8s} | ${row['Current Value']:>12,.2f}")
        print(f"\nPlan Menu: {', '.join(tickers[:10])}{'...' if len(tickers) > 10 else ''}")
    else:
        print("No 401k files found in Drop_Financial_Info_Here/")
