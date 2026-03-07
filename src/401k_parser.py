"""
401k_parser.py — Dynamic Fidelity NetBenefits 401k Parser

Dynamically extracts 401k holdings and the available plan fund menu
from user-provided extracted PDF text files. No hardcoded employer data.

Tax lot analysis is NOT applicable — 401k is tax-deferred.
"""

import re
import pandas as pd
from pathlib import Path
from typing import Optional, Tuple, Dict, List


def extract_plan_menu(text: str) -> Dict[str, str]:
    """
    Dynamically extracts the full plan menu (all available investment options)
    from the Investment Options extracted text.

    Scans for all occurrences of 'FUND NAME (TICKER)' patterns.
    Returns a dict mapping display names -> ticker symbols.
    """
    # Pattern: Fund name followed by ticker in parentheses, e.g. "IS S&P 500 IDX K  (WFSPX)"
    # Tickers are 1-6 uppercase letters, sometimes with digits, inside parens
    pattern = r'([A-Z][A-Za-z0-9&\' /\-\.]+?)\s*\(([A-Z]{2,6}(?:\d{0,2})?)\)'

    matches = re.findall(pattern, text)

    # Common noise prefixes from PDF extraction
    noise_prefixes = ["Show", "mark", "ReturnsAs OfBench-mark", "ReturnsAs Of",
                      "Bench-mark", "ViewChart",
                      "Invested Balance Cost Basis YTDReturnsAs OfViewChart"]

    plan_menu = {}
    seen_tickers = set()
    for name, ticker in matches:
        name = name.strip()
        ticker = ticker.strip()

        # Skip non-fund tickers (page artifacts, URLs, etc.)
        if len(ticker) < 2 or ticker in ("HTTP", "HTTPS", "HTML", "VIEW"):
            continue

        # Strip common PDF noise from the beginning of fund names
        for prefix in noise_prefixes:
            if name.startswith(prefix):
                name = name[len(prefix):].strip()

        if not name:
            continue

        # Deduplicate (same ticker may appear multiple times with slightly different names)
        if ticker not in seen_tickers:
            plan_menu[name] = ticker
            seen_tickers.add(ticker)

    return plan_menu


def extract_current_holdings(text: str, plan_menu: Dict[str, str]) -> pd.DataFrame:
    """
    Extracts the user's current 401k holdings from the Balance Overview section
    of the Investment Options extracted text.

    The Balance Overview format is:
    FUND NAME  (TICKER)...XX.XX% $BALANCE $COST_BASIS YTD%

    Returns a DataFrame with columns:
    - Symbol, Fund Name, Current Value, Cost Basis Total, Account Name, Account Type
    """
    holdings = []

    for display_name, ticker in plan_menu.items():
        # Build a regex to find this fund in the Balance Overview section
        # The Balance Overview has: NAME (TICKER) ... XX.XX% $BALANCE $COST_BASIS
        escaped_ticker = re.escape(ticker)
        # Look for the ticker in parens, then capture the % invested, balance, cost basis
        pattern = (
            rf'{escaped_ticker}\)'        # Closing paren after ticker
            rf'.*?'                         # Anything in between (date, asset class, etc.)
            rf'([\d.]+)%'                  # Percent invested
            rf'\s*\$([\d,]+\.?\d*)'        # Balance (dollar amount)
            rf'\s*\$([\d,]+\.?\d*)'        # Cost basis (dollar amount)
        )

        match = re.search(pattern, text, re.DOTALL)
        if match:
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
                'Account Type': '401k / HSA',
            })

    df = pd.DataFrame(holdings)
    return df


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
    text = options_text_path.read_text(encoding="utf-8")

    plan_menu = extract_plan_menu(text)

    if not plan_menu:
        print("⚠️ Could not dynamically extract any fund tickers from the 401k Investment Options text.")
        return pd.DataFrame(), []

    print(f"   Dynamically extracted {len(plan_menu)} funds from 401k plan menu.")

    holdings_df = extract_current_holdings(text, plan_menu)

    if holdings_df.empty:
        print("⚠️ No current 401k holdings found in Balance Overview. The plan menu was extracted but you may not hold any positions.")
    else:
        print(f"   Found {len(holdings_df)} current 401k holdings.")

    plan_tickers = get_plan_menu_tickers(plan_menu)

    return holdings_df, plan_tickers


def find_401k_options_file(data_dir: Path) -> Optional[Path]:
    """
    Scans the data directory for an extracted 401k Investment Options text file.
    Looks for files matching: extracted_text_*Investment Options*.txt or extracted_text_*401k*Options*.txt
    """
    # The PowerShell script now moves generated text files to a .cache subfolder
    search_dirs = [
        data_dir / ".cache",
        data_dir
    ]

    for search_dir in search_dirs:
        # Try multiple common patterns
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

        # Also check for any extracted_text that contains Balance Overview
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

        # Broader fallback: any extracted 401k text that isn't a transaction history
        for p in search_dir.glob("extracted_text_*401k*.txt"):
            if "Transaction" not in str(p) and "transaction" not in str(p):
                # Check if this file contains "Investment Choices" (the plan menu section)
                try:
                    content = p.read_text(encoding="utf-8")[:2000]
                    if "Investment Choices" in content or "Balance Overview" in content:
                        return p
                except Exception:
                    pass

    return None


if __name__ == "__main__":
    print("=== 401k Parser Smoke Test ===\n")

    # Look for the extracted text in common locations
    search_dirs = [
        Path("Drop_Financial_Info_Here"),
        Path(".."),
        Path("../.."),
    ]

    options_path = None
    for d in search_dirs:
        options_path = find_401k_options_file(d)
        if options_path:
            break

    if options_path:
        print(f"Found: {options_path.name}\n")
        holdings_df, plan_tickers = parse_401k_options_file(options_path)

        if not holdings_df.empty:
            print(f"\nCurrent 401k Holdings ({len(holdings_df)}):")
            for _, row in holdings_df.iterrows():
                print(f"  {row['Symbol']:8s} | {row['Fund Name']:30s} | ${row['Current Value']:>12,.2f} | Cost: ${row['Cost Basis Total']:>12,.2f}")
            print(f"\n  Total: ${holdings_df['Current Value'].sum():>12,.2f}")

        print(f"\nFull Plan Menu ({len(plan_tickers)} tickers):")
        print(", ".join(plan_tickers))
    else:
        print("No extracted 401k Investment Options text found.")
        print("Run: py .agent/skills/pdf_extraction/scripts/extract_text.py \"Drop_Financial_Info_Here/your_401k_options.pdf\"")
