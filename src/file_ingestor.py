"""
file_ingestor.py — File Format Auto-Dispatcher

3-layer detection pipeline for ingesting 401k data from any file format:
  Layer 1 — Extension: .csv/.xlsx → pandas, .pdf → inline pypdf extract, .txt → Layer 2
  Layer 2 — Content Sniff: Delimiter test (CSV?) vs ticker pattern test (extracted PDF text?)
  Layer 3 — Column Validation: For CSV/Excel, require ticker-like + value-like columns
"""

import re
import pandas as pd
from pathlib import Path
from typing import Optional, Tuple, List
import importlib
k401_parser = importlib.import_module('401k_parser')


def detect_format(path: Path) -> str:
    """
    Detects the format of a file using a 3-layer pipeline.
    Returns: "csv" | "excel" | "pdf" | "extracted_text" | "unknown"
    """
    ext = path.suffix.lower()

    # Layer 1: Extension-based detection
    if ext == '.csv':
        return "csv"
    elif ext in ('.xlsx', '.xls'):
        return "excel"
    elif ext == '.pdf':
        return "pdf"
    elif ext == '.txt':
        # Layer 2: Content sniffing for .txt files
        return _sniff_text_content(path)
    else:
        return "unknown"


def _sniff_text_content(path: Path) -> str:
    """
    Layer 2: Sniffs text file content to determine if it's a CSV or extracted PDF text.
    """
    try:
        sample = path.read_text(encoding='utf-8', errors='ignore')[:3000]
    except Exception:
        return "unknown"

    # Check for CSV-like structure (comma/tab delimited with consistent columns)
    lines = sample.strip().split('\n')
    if len(lines) >= 2:
        # Count delimiters in first few lines
        comma_counts = [line.count(',') for line in lines[:5]]
        tab_counts = [line.count('\t') for line in lines[:5]]

        # If consistent comma/tab count across lines, likely CSV
        if len(set(comma_counts)) <= 2 and comma_counts[0] >= 2:
            return "csv"
        if len(set(tab_counts)) <= 2 and tab_counts[0] >= 2:
            return "csv"

    # Check for ticker patterns typical of extracted PDF text
    ticker_pattern = r'\([A-Z]{2,6}\)'
    ticker_matches = re.findall(ticker_pattern, sample)
    if len(ticker_matches) >= 3:
        return "extracted_text"

    # Check for balance/investment keywords
    keywords = ['Investment Choices', 'Balance Overview', 'Fund Name', 'Ticker']
    if any(kw in sample for kw in keywords):
        return "extracted_text"

    return "unknown"


def _extract_pdf_text(path: Path) -> Optional[str]:
    """
    Inline PDF text extraction using pypdf.
    Returns the full extracted text, or None on failure.
    """
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
        if text_parts:
            return '\n'.join(text_parts)
        return None
    except Exception as e:
        print(f"⚠️ PDF extraction failed for {path.name}: {e}")
        return None


def _validate_csv_columns(df: pd.DataFrame) -> bool:
    """
    Layer 3: Column validation for CSV/Excel files.
    Requires at least one ticker-like column and one value-like column.
    """
    cols_lower = [c.lower() for c in df.columns]

    has_ticker = any(k in cols_lower for k in ['symbol', 'ticker', 'fund', 'fund name'])
    has_value = any(k in cols_lower for k in [
        'current value', 'balance', 'market value', 'value',
        'shares', 'quantity', 'units'
    ])

    return has_ticker and has_value


def ingest_401k_file(path: Path) -> Tuple[pd.DataFrame, List[str]]:
    """
    Dispatches to the correct parser based on file format.
    Returns: (holdings_df, plan_menu_tickers)
    """
    fmt = detect_format(path)

    if fmt == "pdf":
        # Inline PDF extraction → parse as extracted text
        text = _extract_pdf_text(path)
        if text is None:
            print(f"   Could not extract text from {path.name}")
            return pd.DataFrame(), []

        # Cache the extracted text for future runs
        cache_dir = path.parent / ".cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / f"extracted_text_{path.stem}.txt"
        cache_path.write_text(text, encoding='utf-8')
        print(f"   Cached extracted PDF text to {cache_path.name}")

        return _parse_extracted_text(text)

    elif fmt == "extracted_text":
        text = path.read_text(encoding='utf-8')
        return _parse_extracted_text(text)

    elif fmt in ("csv", "excel"):
        return _parse_structured_file(path, fmt)

    else:
        print(f"   Unsupported file format for {path.name}")
        return pd.DataFrame(), []


def _parse_extracted_text(text: str) -> Tuple[pd.DataFrame, List[str]]:
    """Parses extracted PDF text using the 401k parser."""
    plan_menu = k401_parser.extract_plan_menu(text)
    if not plan_menu:
        print("   ⚠️ Could not extract any fund tickers from the text.")
        return pd.DataFrame(), []

    print(f"   Dynamically extracted {len(plan_menu)} funds from 401k plan menu.")
    holdings_df = k401_parser.extract_current_holdings(text, plan_menu)
    plan_tickers = k401_parser.get_plan_menu_tickers(plan_menu)

    if holdings_df.empty:
        print("   ⚠️ No current holdings found. Plan menu was extracted.")
    else:
        print(f"   Found {len(holdings_df)} current 401k holdings.")

    return holdings_df, plan_tickers


def _parse_structured_file(path: Path, fmt: str) -> Tuple[pd.DataFrame, List[str]]:
    """
    Parses a CSV/Excel file containing 401k data.
    Auto-detects column mappings for ticker and value columns.
    """
    try:
        if fmt == "csv":
            df = pd.read_csv(path)
        else:
            df = pd.read_excel(path)
    except Exception as e:
        print(f"   Error reading {path.name}: {e}")
        return pd.DataFrame(), []

    if not _validate_csv_columns(df):
        print(f"   ⚠️ {path.name} does not contain recognizable ticker + value columns.")
        return pd.DataFrame(), []

    # Auto-map columns
    cols = {c.lower(): c for c in df.columns}
    ticker_col = cols.get('symbol') or cols.get('ticker') or cols.get('fund')
    value_col = cols.get('current value') or cols.get('balance') or cols.get('market value') or cols.get('value')

    if not ticker_col or not value_col:
        return pd.DataFrame(), []

    # Extract plan menu tickers
    tickers = df[ticker_col].dropna().astype(str).str.strip().tolist()
    tickers = [t for t in tickers if re.match(r'^[A-Z]{1,6}$', t)]

    # Build holdings DataFrame
    holdings = []
    for _, row in df.iterrows():
        sym = str(row.get(ticker_col, '')).strip()
        if not re.match(r'^[A-Z]{1,6}$', sym):
            continue

        name_col = cols.get('fund name') or cols.get('description') or cols.get('name')
        name = str(row.get(name_col, sym)) if name_col else sym
        val = float(row.get(value_col, 0))

        cost_col = cols.get('cost basis') or cols.get('cost basis total')
        cost = float(row.get(cost_col, 0)) if cost_col else 0.0

        holdings.append({
            'Symbol': sym,
            'Fund Name': name,
            'Description': name,
            'Current Value': val,
            'Cost Basis Total': cost,
            'Account Name': '401k',
            'Account Type': 'Employer 401k',
        })

    holdings_df = pd.DataFrame(holdings)
    print(f"   Parsed {len(holdings_df)} holdings and {len(tickers)} plan menu tickers from {path.name}.")

    return holdings_df, sorted(set(tickers))


def discover_401k_files(data_dir: Path) -> List[Path]:
    """
    Scans the drop folder for any file with '401k' in the name.
    Returns a list of discovered file paths, prioritizing PDFs over text.
    """
    found = []
    search_dirs = [data_dir, data_dir / ".cache"]

    for d in search_dirs:
        if not d.exists():
            continue
        for f in d.iterdir():
            if not f.is_file():
                continue
            name_lower = f.name.lower()
            if '401k' not in name_lower and '401' not in name_lower:
                continue
            if f.suffix.lower() in ('.csv', '.xlsx', '.xls', '.pdf', '.txt'):
                found.append(f)

    # Sort: PDFs first, then CSVs, then text files
    priority = {'.pdf': 0, '.csv': 1, '.xlsx': 2, '.xls': 3, '.txt': 4}
    found.sort(key=lambda p: priority.get(p.suffix.lower(), 5))

    return found


if __name__ == "__main__":
    print("=== File Ingestor Smoke Test ===\n")
    data_dir = Path("Drop_Financial_Info_Here")

    files = discover_401k_files(data_dir)
    if files:
        print(f"Discovered {len(files)} 401k file(s):")
        for f in files:
            fmt = detect_format(f)
            print(f"  {f.name} → {fmt}")

        # Try ingesting the first one
        print(f"\nIngesting: {files[0].name}")
        holdings_df, tickers = ingest_401k_file(files[0])
        if not holdings_df.empty:
            print(f"\nHoldings ({len(holdings_df)}):")
            for _, row in holdings_df.iterrows():
                print(f"  {row['Symbol']:8s} | ${row['Current Value']:>12,.2f}")
        print(f"\nPlan Menu: {', '.join(tickers[:10])}{'...' if len(tickers) > 10 else ''}")
    else:
        print("No 401k files found in Drop_Financial_Info_Here/")
