"""
401k_parser.py — Fidelity NetBenefits 401k PDF Parser

Extracts 401k holdings from Fidelity statement PDFs and resolves
fund names to ticker symbols using a hardcoded plan menu mapping.

Tax lot analysis is NOT applicable — 401k is tax-deferred.
"""

import pandas as pd
from pathlib import Path
from typing import Optional

# --- 401k Plan Menu ---
# Derived from the Imprivata Inc. 401(k) Plan Investment Options PDF.
# Maps fund display names (as they appear in the statement PDF) to ticker symbols.

FUND_NAME_TO_TICKER = {
    "IS S&P 500 Idx K": "WFSPX",
    "TRP Global Stock I": "TRGLX",
    "FID Mid Cap Idx": "FSMDX",
    "Dodge & Cox GLB BD I": "DODLX",
    "AF New World R6": "RNWGX",
    "AF NEW World R6": "RNWGX",
    "Brnds Intl Smcpeq R6": "BISRX",
    "UM Behavioral Val R6": "UBVFX",
    "FID Nasdaq Comp Indx": "FNCMX",
    "Congress Smcp GR RTL": "CSMVX",
    "Gughm Tot Rtn BD P": "GIBLX",
    "Gughm TOT RTN BD P": "GIBLX",
    "GUGHM TOT RTN BD P": "GIBLX",
    # Full plan menu (additional available funds not currently held)
    "COL DIVIDEND INC I3": "CDDYX",
    "INVS EQL WT S&P500 Y": "VADDX",
    "CALV US LG CP CRI I": "CISIX",
    "COL CONTRAN CORE I2": "COFRX",
    "AB LG CAP GRTH ADV": "APGYX",
    "VICTORY S EST VAL R6": "VEVRX",
    "MFS MID CAP GRTH R6": "OTCKX",
    "BTW SMALL CAP": "BOSOX",
    "AF SMALLCAP WORLD R6": "RLLGX",
    "AF TRGT DATE 2065 R6": "RFVTX",
    "AF TRGT DATE 2070 R6": "RFBFX",
    "VL ASSET ALLOC INST": "VLAIX",
    "AF BALANCED R6": "RLBGX",
    "AF CAP INC BLDR R6": "RIRGX",
    "AF TD INCOME 2010 R6": "RFTTX",
    "AF TD INCOME 2015 R6": "RFJTX",
    "AF TD INCOME 2020 R6": "RRCTX",
    "AF TD INCOME 2025 R6": "RFDTX",
    "AF TRGT DATE 2030 R6": "RFETX",
    "AF TRGT DATE 2035 R6": "RFFTX",
    "AF TRGT DATE 2040 R6": "RFGTX",
    "AF TRGT DATE 2045 R6": "RFHTX",
    "AF TRGT DATE 2050 R6": "RFITX",
    "AF TRGT DATE 2055 R6": "RFKTX",
    "AF TRGT DATE 2060 R6": "RFUTX",
    "BLKRK 20/80 TA INST": "BICPX",
    "BLKRK 40/60 TA INST": "BIMPX",
    "BLKRK 60/40 TA INST": "BIGPX",
    "BLKRK 80/20 TA INST": "BIAPX",
    "BLKRK MA INCOME INST": "BIICX",
    "LS GLOBAL ALLOC Y": "LSWWX",
    "PIMCO STABLE INC 1": "PIMCO_STABLE",  # No public ticker (institutional)
    "BLKRK HI YLD INST": "BHYIX",
    "VANG VMMR-FED MMKT": "VMFXX",
}

# All ticker symbols available in the plan
PLAN_MENU_TICKERS = sorted(set(
    t for t in FUND_NAME_TO_TICKER.values()
    if not t.startswith("PIMCO")  # Exclude non-public tickers
))


def get_plan_menu() -> list:
    """Returns the list of ticker symbols available in the 401k plan."""
    return PLAN_MENU_TICKERS.copy()


def _resolve_ticker(fund_name: str) -> Optional[str]:
    """Resolves a fund display name to its ticker symbol."""
    # Exact match
    if fund_name in FUND_NAME_TO_TICKER:
        return FUND_NAME_TO_TICKER[fund_name]

    # Case-insensitive match
    fund_upper = fund_name.upper().strip()
    for key, ticker in FUND_NAME_TO_TICKER.items():
        if key.upper().strip() == fund_upper:
            return ticker

    # Partial match (fund name might be truncated in PDF)
    for key, ticker in FUND_NAME_TO_TICKER.items():
        if key.upper().strip() in fund_upper or fund_upper in key.upper().strip():
            return ticker

    return None


def parse_401k_statement(pdf_text_path: Path) -> pd.DataFrame:
    """
    Parses a pre-extracted 401k statement text file to extract current holdings.
    Expects the text file created by the PDF extraction skill.

    Returns a DataFrame with columns:
    - Symbol (ticker)
    - Fund Name
    - Shares
    - Market Value
    - Cost Basis (from the investment options PDF if available)
    - Account Name (always '401k')
    - Account Type (always '401k / HSA')
    """
    holdings = []

    text = pdf_text_path.read_text(encoding="utf-8")

    # Parse the "Market Value of Your Account" section
    # Format: FundName Shares_Start Shares_End Price_Start Price_End Value_Start Value_End
    import re

    # Pattern for holdings lines in the statement
    # Look for fund names followed by share/price/value data
    # The PDF text is messy, so we'll look for known fund names and extract their data
    for fund_name, ticker in FUND_NAME_TO_TICKER.items():
        # Try to find the fund and its market value in the text
        # The statement format has: FundName followed by numbers
        pattern = re.escape(fund_name)

        matches = list(re.finditer(pattern, text, re.IGNORECASE))
        if not matches:
            continue

        # Look for the Balance Overview section data (has tickers)
        # Format: FundName (TICKER)date Asset Category %Invested Balance CostBasis YTDReturns
        ticker_pattern = rf'{re.escape(fund_name)}\s*\({re.escape(ticker)}\)'
        balance_match = re.search(ticker_pattern, text, re.IGNORECASE)

        if balance_match:
            # Extract the data after the match
            after_text = text[balance_match.end():balance_match.end() + 300]

            # Try to find dollar amounts (format: $XXX,XXX.XX)
            dollar_amounts = re.findall(r'\$[\d,]+\.?\d*', after_text)
            pct_match = re.search(r'([\d.]+)%', after_text)

            if len(dollar_amounts) >= 2:
                balance_str = dollar_amounts[0].replace('$', '').replace(',', '')
                cost_basis_str = dollar_amounts[1].replace('$', '').replace(',', '')

                try:
                    balance = float(balance_str)
                    cost_basis = float(cost_basis_str)
                except ValueError:
                    continue

                # Try to find share count from the market value section
                shares = 0.0
                shares_pattern = rf'{re.escape(fund_name)}.*?([\d,]+\.\d{{3}})'
                shares_match = re.search(shares_pattern, text, re.IGNORECASE)
                if shares_match:
                    try:
                        shares = float(shares_match.group(1).replace(',', ''))
                    except ValueError:
                        pass

                holdings.append({
                    'Symbol': ticker,
                    'Fund Name': fund_name,
                    'Shares': shares,
                    'Current Value': balance,
                    'Cost Basis Total': cost_basis,
                    'Account Name': '401k',
                    'Account Type': '401k / HSA',
                })

    if not holdings:
        print("⚠️ No 401k holdings could be parsed. Falling back to manual entry if needed.")

    df = pd.DataFrame(holdings)
    return df


if __name__ == "__main__":
    print("=== 401k Parser Smoke Test ===\n")

    # Try to parse the extracted statement text
    extracted = Path("../../extracted_text_20250306 to 20260305 - Fidelity Imprivata 401k.txt")
    options = Path("../../extracted_text_Fidelity Imprivata 401k Investment Options.txt")

    if not extracted.exists():
        # Try alternate paths
        for p in Path("../..").glob("extracted_text*401k*.txt"):
            if "Transaction" not in str(p) and "Options" not in str(p):
                extracted = p
                break

    if extracted.exists():
        print(f"Parsing: {extracted.name}")
        # Use the investment options text since it has the clean Balance Overview
        if options.exists():
            df = parse_401k_statement(options)
        else:
            df = parse_401k_statement(extracted)

        if not df.empty:
            print(f"\nFound {len(df)} holdings:\n")
            for _, row in df.iterrows():
                print(f"  {row['Symbol']:8s} | {row['Fund Name']:30s} | ${row['Current Value']:>12,.2f} | Cost: ${row['Cost Basis Total']:>12,.2f}")
            print(f"\n  Total: ${df['Current Value'].sum():>12,.2f}")
        else:
            print("No holdings parsed.")
    else:
        print("No extracted 401k text found. Run PDF extraction first.")

    print(f"\n401k Plan Menu ({len(PLAN_MENU_TICKERS)} tickers):")
    print(", ".join(PLAN_MENU_TICKERS))
