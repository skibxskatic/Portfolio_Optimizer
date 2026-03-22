import os
import io
import re
import webbrowser
import parser
import market_data
import metrics
import pandas as pd
from pathlib import Path
import validator
import importlib
k401_parser = importlib.import_module('401k_parser')
import file_ingestor
from markdown_pdf import Section, MarkdownPdf
import markdown as md_lib

# --- Configuration Constants ---

ACCOUNT_TYPE_MAP = {
    "INDIVIDUAL": "Taxable Brokerage",
    "Melissa Investments": "Taxable Brokerage",
    "ROTH IRA": "Roth IRA",
    "Health Savings Account": "HSA",
    "401k": "Employer 401k",
}

SUBSTANTIALLY_IDENTICAL_MAP = {
    "FTEC": "US Tech", "XLK": "US Tech", "VGT": "US Tech",
    "FNILX": "Large Cap Comp", "FNCMX": "Large Cap Comp", "ONEQ": "Large Cap Comp",
    "FELG": "Large Cap Growth", "QQQ": "Large Cap Growth", "SPYG": "Large Cap Growth"
}

def get_substantially_identical_symbols(symbol: str) -> set:
    """Returns a set of all tickers in the same substantially identical category."""
    group = SUBSTANTIALLY_IDENTICAL_MAP.get(symbol)
    if not group:
        return {symbol}
    return {k for k, v in SUBSTANTIALLY_IDENTICAL_MAP.items() if v == group}

def detect_wash_sale_risk(main_df: pd.DataFrame, candidate_symbol: str) -> bool:
    """
    Checks if the candidate_symbol or a substantially identical symbol is held in more
    than one distinct 'Account Name' in the overall portfolio.
    """
    identical_symbols = get_substantially_identical_symbols(candidate_symbol)
    held_in = main_df[main_df['Symbol'].isin(identical_symbols)]
    accounts = held_in['Account Name'].dropna().unique()
    return len(accounts) > 1

DE_MINIMIS_GAIN_PCT = 0.01  # 1% of lot value — gains below this are safe to reallocate

# --- 401k Glide Path Constants ---
GLIDE_PATH = [
    (40, 0.90),  # 40+ yrs out: 90% equity
    (25, 0.80),  # 25 yrs: 80%
    (10, 0.60),  # 10 yrs: 60%
    (0,  0.50),  # At retirement: 50%
    (-7, 0.30),  # 7 yrs past: 30%
]
EQUITY_SPLIT = {"US Equity": 0.70, "Intl Equity": 0.30}
DEFAULT_BIRTH_YEAR = 1990
DEFAULT_RETIREMENT_YEAR = 2057
MIN_ALLOCATION_PCT = 5

# --- Asset Routing ---

def classify_routing_bucket(yld: float, beta: float) -> str:
    """
    4-Bucket Tax Location Strategy.
    Classifies a fund into its optimal tax-location bucket.
    High-yield funds route to "Tax-Deferred" which covers both 401k and HSA.

    Priority order (highest wins): Tax-Deferred → Roth IRA → Taxable Brokerage

    Boundary behavior:
      - yield == 2.0%: Tax-Deferred wins (>= threshold)
      - yield < 2.0% and beta == 1.0: Taxable Brokerage wins (beta must be
        strictly > 1.0 for Roth IRA)
      - yield < 2.0% and beta > 1.0: Roth IRA
      - Everything else: Taxable Brokerage (default/fallback bucket)
    """
    # Priority 1: High yield (>= 2%) → shelter income in tax-deferred accounts.
    # The >= means funds exactly at the 2% boundary route here, not to Roth.
    if yld >= 0.02:
        return "Tax-Deferred"
    # Priority 2: Low yield + high growth (beta strictly > 1.0) → Roth IRA.
    # Funds exactly at beta=1.0 fall through to Taxable Brokerage.
    elif yld < 0.02 and beta > 1.0:
        return "Roth IRA"
    # Priority 3: Default — low yield + low/moderate beta → Taxable Brokerage.
    else:
        return "Taxable Brokerage"


def resolve_account_type(account_name: str) -> str:
    """Maps a Fidelity CSV Account Name to a routing bucket."""
    return ACCOUNT_TYPE_MAP.get(account_name, "Taxable Brokerage")


def load_investor_profile(data_dir: Path) -> tuple:
    """
    Parses investor_profile.txt from data_dir for birth_year and retirement_year.
    Returns (birth_year, retirement_year, using_defaults) tuple.
    Falls back to defaults if file is missing or malformed.
    """
    profile_path = data_dir / "investor_profile.txt"
    birth_year = DEFAULT_BIRTH_YEAR
    retirement_year = DEFAULT_RETIREMENT_YEAR
    using_defaults = True

    if profile_path.exists():
        try:
            text = profile_path.read_text(encoding="utf-8")
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip().lower()
                    val = val.strip()
                    if key == "birth_year":
                        birth_year = int(val)
                        using_defaults = False
                    elif key == "retirement_year":
                        retirement_year = int(val)
                        using_defaults = False
        except Exception:
            pass  # Fall back to defaults on any error

    return birth_year, retirement_year, using_defaults


def compute_target_allocation(years_to_retirement: int) -> dict:
    """
    Interpolates the glide path to compute target allocation percentages.
    Returns dict: {"US Equity": pct, "Intl Equity": pct, "Bond": pct, "Stable Value": pct}
    All values sum to 100.
    """
    # Determine equity percentage from piecewise linear glide path
    if years_to_retirement >= GLIDE_PATH[0][0]:
        equity_pct = GLIDE_PATH[0][1]
    elif years_to_retirement <= GLIDE_PATH[-1][0]:
        equity_pct = GLIDE_PATH[-1][1]
    else:
        # Find the two bracketing points and interpolate
        for i in range(len(GLIDE_PATH) - 1):
            upper_yr, upper_eq = GLIDE_PATH[i]
            lower_yr, lower_eq = GLIDE_PATH[i + 1]
            if lower_yr <= years_to_retirement <= upper_yr:
                ratio = (years_to_retirement - lower_yr) / (upper_yr - lower_yr)
                equity_pct = lower_eq + ratio * (upper_eq - lower_eq)
                break

    bond_pct = 1.0 - equity_pct
    # Split equity between US and Intl
    us_eq = equity_pct * EQUITY_SPLIT["US Equity"]
    intl_eq = equity_pct * EQUITY_SPLIT["Intl Equity"]
    # Split bonds: mostly bonds, small stable value allocation
    stable_value = min(bond_pct * 0.15, 0.05)  # Up to 5% stable value
    bond = bond_pct - stable_value

    return {
        "US Equity": round(us_eq * 100, 1),
        "Intl Equity": round(intl_eq * 100, 1),
        "Bond": round(bond * 100, 1),
        "Stable Value": round(stable_value * 100, 1),
    }


def compute_age_factor(years_to_retirement: int) -> float:
    """0.0 = at retirement, 1.0 = 40+ years out. Linear interpolation."""
    return max(0.0, min(1.0, years_to_retirement / 40.0))


# --- Scoring ---

def score_candidate(ticker: str, data: dict, routing_bucket: str, years_to_retirement: int = None) -> dict:
    """
    Scores a candidate fund using per-account metrics.
    When years_to_retirement is provided, weights shift based on age_factor
    (0.0 = at retirement, 1.0 = 40+ years out).
    Returns the candidate dict augmented with 'score' and metric values.
    """
    fund_metrics = metrics.get_fund_metrics(ticker, routing_bucket)
    nof = fund_metrics.get("net_of_fees_5y") or 0.0

    af = compute_age_factor(years_to_retirement) if years_to_retirement is not None else None

    if routing_bucket == "Taxable Brokerage":
        sharpe = fund_metrics.get("sharpe_ratio") or 0.0
        max_dd = fund_metrics.get("max_drawdown") or 0.0
        yld = data.get("yield", 0.0) or 0.0
        low_yield_bonus = max(0, (0.02 - yld) * 100)  # up to 2 points

        if af is not None:
            # Max Drawdown weight: 5 (young) → 15 (near-retirement)
            w_dd = 5 + (1 - af) * 10
            # Net-of-Fees weight: 45 (young) → 35 (near-retirement)
            w_nof = 45 - (1 - af) * 10
            score = (nof * w_nof) + (sharpe * 30) + (low_yield_bonus * 20) + ((1 + max_dd) * w_dd)
        else:
            score = (nof * 40) + (sharpe * 30) + (low_yield_bonus * 20) + ((1 + max_dd) * 10)
        data.update({"sharpe_ratio": sharpe, "max_drawdown": max_dd})

        # Turnover penalty: high-turnover funds generate more taxable cap gains
        turnover = data.get("turnover")
        if turnover is not None and turnover > 0.50:
            penalty = min(0.10, (turnover - 0.50) * 0.20)
            score *= (1 - penalty)

    elif routing_bucket == "Roth IRA":
        sortino = fund_metrics.get("sortino_ratio") or 0.0
        max_dd = fund_metrics.get("max_drawdown") or 0.0
        total_10y = fund_metrics.get("total_return_10y")

        if af is not None:
            # Sortino: 40 (young) → 25 (near-retirement)
            w_sortino = 25 + af * 15
            # Net-of-Fees: 30 (young) → 40 (near-retirement)
            w_nof = 40 - af * 10
            # 10Y Return: 30 (young) → 0 (near-retirement)
            w_10y = af * 30
            # Max Drawdown: 0 (young) → 10 (near-retirement)
            w_dd = (1 - af) * 10
            t10_score = (total_10y * w_10y) if total_10y is not None else 0.0
            score = (nof * w_nof) + (sortino * w_sortino) + t10_score + ((1 + max_dd) * w_dd)
        else:
            t10_score = (total_10y * 30) if total_10y is not None else 0.0
            score = (nof * 35) + (sortino * 35) + t10_score
        data.update({"sortino_ratio": sortino, "max_drawdown": max_dd, "total_return_10y": total_10y})

    elif routing_bucket == "Tax-Deferred":
        sharpe = fund_metrics.get("sharpe_ratio") or 0.0
        te = fund_metrics.get("tracking_error")
        te_penalty = max(0, 1 - (te * 10)) if te is not None else 0.5

        if af is not None:
            # Net-of-Fees: 40 (young) → 25 (near-retirement)
            w_nof = 25 + af * 15
            # Sharpe: 30 (young) → 45 (near-retirement)
            w_sharpe = 45 - af * 15
            score = (nof * w_nof) + (sharpe * w_sharpe) + (te_penalty * 10)
        else:
            score = (nof * 35) + (sharpe * 35) + (te_penalty * 10)
        data.update({"sharpe_ratio": sharpe, "tracking_error": te})

        # Bond duration penalty: near retirement, prefer shorter duration (less rate sensitivity)
        if af is not None and af < 0.3:
            bond_dur = data.get("bond_duration")
            if bond_dur is not None and bond_dur > 5.0:
                duration_penalty = min(0.10, (bond_dur - 5.0) * 0.02)
                score *= (1 - duration_penalty)

    else:
        score = nof * 100

    # Morningstar tiebreaker: small bonus for highly-rated funds (all buckets)
    ms_rating = data.get("morningstar_rating")
    if ms_rating is not None and ms_rating >= 4:
        score *= 1 + (ms_rating - 3) * 0.025  # +2.5% for 4★, +5% for 5★

    data["score"] = round(score, 4)
    data["net_of_fees_5y"] = nof
    return data


# --- New Report Sections ---

def _render_executive_summary(findings: list) -> str:
    """Renders Section 0: Executive Summary with 3-5 actionable bullets."""
    lines = ["## 0. Executive Summary\n\n"]
    actionable = [f for f in findings if f.get("text")]
    if len(actionable) < 3:
        lines.append("- Your portfolio is well-optimized — no urgent action items detected.\n")
    for f in actionable[:5]:
        lines.append(f"- {f['text']} *(see Section {f['section_ref']})*\n")
    lines.append("\n")
    return "".join(lines)


def _render_next_steps(df, metadata, tlh_agg, candidates_by_bucket, age_factor, plan_menu_tickers, all_plan_scored=None) -> str:
    """Renders Section 6: Next Steps with contextual how-to actions."""
    lines = ["## 6. Next Steps\n\n"]
    has_actions = False

    # 1. High-ER Replacements
    er_actions = []
    for _, row in df.iterrows():
        sym = row.get('Symbol', '')
        er = row.get('Expense Ratio')
        if er is not None and er > 0.40:
            account_name = row.get('Account Name', 'Unknown')
            account_type = resolve_account_type(account_name)
            # Find best replacement in matching bucket
            bucket_key = {"Taxable Brokerage": "taxable", "Roth IRA": "roth", "HSA": "hsa", "Employer 401k": "k401"}.get(account_type, "taxable")
            bucket_cands = candidates_by_bucket.get(bucket_key, [])
            replacement = bucket_cands[0]["ticker"] if bucket_cands else "a lower-cost alternative"
            if isinstance(replacement, dict):
                replacement = replacement.get("ticker", replacement)
            tax_ctx = {"Roth IRA": "Tax-free swap", "Employer 401k": "Tax-deferred", "HSA": "Tax-free swap"}.get(account_type, "Check LTCG status first")
            er_actions.append(f"- Replace **{sym}** → **{replacement}** in {account_name}. {tax_ctx}. *(See Section 4.)*\n")
    if er_actions:
        has_actions = True
        lines.append("### High-ER Replacements\n\n")
        lines.extend(er_actions)
        lines.append("\n")

    # 2. TLH Actions
    if tlh_agg:
        has_actions = True
        lines.append("### Tax-Loss Harvesting Actions\n\n")
        for r in tlh_agg[:5]:
            sym = r['Symbol']
            account = r['Account Name']
            identical = get_substantially_identical_symbols(sym)
            wash_note = f"Watch wash-sale with {', '.join(identical - {sym})}." if len(identical) > 1 else ""
            lines.append(f"- Harvest loss on **{sym}** in {account}. {wash_note} *(See Section 3.)*\n")
        lines.append("\n")

    # 3. 401k Rebalancing
    if all_plan_scored and plan_menu_tickers:
        held_tickers_401k = set(df[df['Account Name'].str.contains('401k|401K', na=False)]['Symbol'].tolist())
        top_not_held = [c for c in all_plan_scored if c["ticker"] not in held_tickers_401k][:3]
        if top_not_held:
            has_actions = True
            lines.append("### 401k Rebalancing\n\n")
            for c in top_not_held:
                lines.append(f"- Add **{c['ticker']}** to 401k elections. No tax impact. *(See Section 5.)*\n")
            lines.append("\n")

    # 4. Age-Inappropriate Holdings
    age_flags = []
    for _, row in df.iterrows():
        sym = row.get('Symbol', '')
        if pd.isna(sym) or sym == 'CORE' or str(sym).endswith("XX"):
            continue
        flag = _get_age_flag_text(row, age_factor, metadata)
        if flag:
            age_flags.append(f"- Evaluate **{sym}**{flag} *(See Section 2.)*\n")
    if age_flags:
        has_actions = True
        lines.append("### Age-Inappropriate Holdings\n\n")
        lines.extend(age_flags[:5])
        lines.append("\n")

    if not has_actions:
        lines.append("No immediate action items. Your portfolio is well-positioned.\n\n")

    return "".join(lines)


def _get_age_flag_text(row, age_factor, metadata):
    """Returns age-appropriate flag text, or empty string. Used by next steps."""
    sym = row.get('Symbol', '')
    if pd.isna(sym) or sym == 'CORE' or str(sym).endswith("XX"):
        return ""
    account_type = resolve_account_type(row.get('Account Name', ''))
    ac = metadata.get(sym, {}).get('asset_class', 'US Equity')
    beta = metadata.get(sym, {}).get('beta', 1.0) or 1.0
    if age_factor > 0.7 and ac in ("Bond", "Stable Value") and account_type in ("Roth IRA", "HSA"):
        return " — Consider higher-growth funds for your horizon."
    if age_factor < 0.3 and beta > 1.2 and account_type in ("Taxable Brokerage", "Roth IRA"):
        return " — Consider lower-volatility for your horizon."
    return ""


def _render_verdict_table(df, metadata, age_factor) -> str:
    """Renders Section 7 Tier 1: Plain-English verdict table."""
    lines = []
    lines.append("### Fund-by-Fund Verdict\n\n")
    lines.append("| Symbol | Account | Current ER | Verdict | Why |\n")
    lines.append("|---|---|---|---|---|\n")

    for _, row in df.iterrows():
        sym = row.get('Symbol', '')
        if pd.isna(sym) or sym == 'CORE' or str(sym).endswith("XX"):
            continue
        er = row.get('Expense Ratio')
        account_name = row.get('Account Name', 'Unknown')
        account_type = resolve_account_type(account_name)
        er_str = f"{er:.2f}%" if pd.notna(er) else "N/A"

        # Determine verdict and plain-English why
        md_info = metadata.get(sym, {})
        if er is not None and er > 0.40:
            nof = md_info.get('net_of_fees_5y')
            if nof is not None and nof > 0.08:
                verdict = "**Evaluate**"
                why = "Mixed signal: high fees but strong recent performance"
            else:
                verdict = "**Replace**"
                why = f"Fees eroding ~{er:.2f}% of annual return vs alternatives"
        elif er is not None:
            cat_avg = md_info.get('category_avg_er')
            if cat_avg is not None and cat_avg > 0 and er > 2 * cat_avg:
                verdict = "**Evaluate**"
                why = f"ER is {er/cat_avg:.1f}x category average ({cat_avg:.2f}%)"
            else:
                verdict = "Keep"
                reasons = []
                if er < 0.10:
                    reasons.append("Low fees")
                else:
                    reasons.append("Reasonable fees")
                nof = md_info.get('net_of_fees_5y')
                if nof is not None and nof > 0.08:
                    reasons.append("strong 5Y growth")
                elif nof is not None and nof > 0.04:
                    reasons.append("solid 5Y returns")
                if md_info.get('asset_class') in ('Bond', 'Stable Value'):
                    reasons.append("income/stability role")
                why = ", ".join(reasons) if reasons else "Meets current criteria"
        else:
            verdict = "Keep"
            why = "Meets current criteria"

        # Check age flag
        flag = _get_age_flag_text(row, age_factor, metadata)
        if flag:
            why += f" {flag.strip()}"

        lines.append(f"| {sym} | {account_type} | {er_str} | {verdict} | {why} |\n")

    lines.append("\n")
    return "".join(lines)


def _render_html_report(markdown_content: str, table_css: str) -> str:
    """Converts markdown report to a self-contained HTML document."""
    md_converter = md_lib.Markdown(extensions=['tables', 'toc'])
    html_body = md_converter.convert(markdown_content)
    toc_html = getattr(md_converter, 'toc', '')

    # Post-process DETAILS markers into <details><summary> tags
    html_body = re.sub(
        r'<!-- DETAILS_START: (.+?) -->',
        r'<details><summary>\1</summary>',
        html_body
    )
    html_body = html_body.replace('<!-- DETAILS_END -->', '</details>')

    # Load Water.css
    css_path = Path(__file__).parent / "water.min.css"
    water_css = css_path.read_text(encoding="utf-8") if css_path.exists() else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Portfolio Optimization Report</title>
<style>
{water_css}
body {{ max-width: 1100px; }}
{table_css}
table {{ table-layout: auto; }}
html {{ scroll-behavior: smooth; }}
nav {{ background: var(--background-alt); padding: 12px 16px; border-radius: 6px; margin-bottom: 24px; }}
nav ul {{ list-style: none; padding: 0; margin: 0; }}
nav ul li {{ margin: 4px 0; }}
nav a {{ font-weight: 600; }}
</style>
</head>
<body>
<nav>
<strong>Contents</strong>
{toc_html}
</nav>
{html_body}
<footer>
<p>Generated locally by Portfolio Optimizer. No financial data was transmitted externally.</p>
</footer>
</body>
</html>"""


# --- Report Generation ---

def generate_privacy_report(positions_path=None, history_path=None, report_path=None):
    print("--- PRE-FLIGHT QA CHECKS ---")
    if not validator.verify_yfinance_sane() or not validator.verify_dynamic_screener() or not validator.verify_asset_routing_logic():
        print("\n❌ PRE-FLIGHT FAILED: Engine data is corrupted or filters are failing.")
        print("Aborting portfolio analysis to protect report integrity.")
        return
    print("--- ALL QA PASSED, BEGINNING ENGINE RUN ---\n")

    # Fetch live risk-free rate once at the start
    rf = metrics.fetch_risk_free_rate()
    print(f"Live Risk-Free Rate (^IRX): {rf*100:.2f}%")

    data_dir = Path("Drop_Financial_Info_Here")

    if positions_path is None:
        positions_files = list(data_dir.glob("Portfolio_Positions*.csv"))
        if not positions_files:
            print("No Positions CSV found in Drop_Financial_Info_Here/")
            return
        if len(positions_files) > 1:
            print(f"❌ ERROR: Found {len(positions_files)} 'Portfolio_Positions' CSVs in Drop_Financial_Info_Here/.")
            print("To guarantee data freshness, the engine requires exactly ONE positions file to serve as the single source of truth.")
            print("Please delete the older exports from the Drop_Financial_Info_Here/ folder.")
            return

        positions_path = positions_files[0]

    print(f"Loading {positions_path.name} locally...")
    df = parser.load_fidelity_positions(positions_path)

    if history_path is None:
        history_files = list(data_dir.glob("Accounts_History*.csv"))
        if not history_files:
            print("No History CSV found in Drop_Financial_Info_Here/")
            return

        print(f"Loading {len(history_files)} Accounts_History CSV(s) locally...")
        hist_dfs = [parser.load_fidelity_history(f) for f in history_files]
        hist_df = pd.concat(hist_dfs, ignore_index=True)
    else:
        print(f"Loading {history_path.name} locally...")
        hist_df = parser.load_fidelity_history(history_path)

    # --- 401k Auto-Detection (via File Ingestor) ---
    plan_menu_tickers = []
    k401_files = file_ingestor.discover_401k_files(data_dir)
    k401_options_file = None

    if k401_files:
        k401_options_file = k401_files[0]  # Use highest-priority file (PDF > CSV > TXT)
        print(f"\n📋 401k data detected: {k401_options_file.name} (format: {file_ingestor.detect_format(k401_options_file)})")
        k401_holdings_df, plan_menu_tickers = file_ingestor.ingest_401k_file(k401_options_file)

        if not k401_holdings_df.empty:
            # Merge 401k holdings into the main DataFrame
            k401_holdings_df['Description'] = k401_holdings_df['Fund Name']
            k401_holdings_df['Quantity'] = 0
            k401_holdings_df['Expense Ratio'] = 0.0
            k401_holdings_df['Last Price'] = 0.0
            df = pd.concat([df, k401_holdings_df], ignore_index=True)
            print(f"   Merged {len(k401_holdings_df)} 401k holdings into the main portfolio.")
    else:
        # Fallback: check for legacy extracted text files
        k401_options_file_legacy = k401_parser.find_401k_options_file(data_dir)
        if k401_options_file_legacy is None:
            for parent in [data_dir.parent, data_dir.parent.parent]:
                k401_options_file_legacy = k401_parser.find_401k_options_file(parent)
                if k401_options_file_legacy:
                    break

        if k401_options_file_legacy:
            k401_options_file = k401_options_file_legacy
            print(f"\n📋 401k Investment Options detected (legacy): {k401_options_file.name}")
            k401_holdings_df, plan_menu_tickers = k401_parser.parse_401k_options_file(k401_options_file)

            if not k401_holdings_df.empty:
                k401_holdings_df['Description'] = k401_holdings_df['Fund Name']
                k401_holdings_df['Quantity'] = 0
                k401_holdings_df['Expense Ratio'] = 0.0
                k401_holdings_df['Last Price'] = 0.0
                df = pd.concat([df, k401_holdings_df], ignore_index=True)
                print(f"   Merged {len(k401_holdings_df)} 401k holdings into the main portfolio.")
        else:
            print("\nℹ️  No 401k data found. 401k analysis will be skipped.")
            print("   To include 401k: drop a PDF, CSV, or extracted text file with '401k' in the filename.")

    # --- Investor Profile (for 401k glide-path allocation) ---
    birth_year, retirement_year, using_profile_defaults = load_investor_profile(data_dir)
    current_year = pd.Timestamp.now().year
    years_to_retirement = retirement_year - current_year
    age_factor = compute_age_factor(years_to_retirement)
    target_alloc = compute_target_allocation(years_to_retirement)
    if using_profile_defaults:
        print(f"ℹ️  No investor_profile.txt found — using defaults (born {birth_year}, retiring {retirement_year}, {years_to_retirement} yrs out).")
    else:
        print(f"📋 Investor profile loaded: born {birth_year}, retiring {retirement_year} ({years_to_retirement} yrs to retirement).")

    print("Unrolling tax lots to perform LTCG/STCG and Tax-Loss Harvesting analysis...")
    lots_df = parser.unroll_tax_lots(df, hist_df)

    # Calculate Holding Periods
    today = pd.to_datetime('today')
    lots_df['Holding_Days'] = (today - lots_df['Purchase Date']).dt.days
    lots_df['Tax_Category'] = lots_df['Holding_Days'].apply(
        lambda x: 'LTCG (>1yr)' if pd.notna(x) and x > 365 else ('STCG (<1yr)' if pd.notna(x) else 'Unknown')
    )

    # 1. Extract unique tickers and fetch Market Data
    symbols = df['Symbol'].dropna().unique().tolist()
    print(f"Fetching market metadata securely for {len(symbols)} unique tickers...")
    metadata = market_data.fetch_ticker_metadata(symbols)

    # 2. Combine portfolio data with market data
    df['Expense Ratio'] = df['Symbol'].map(lambda x: metadata.get(x, {}).get('expense_ratio_pct'))
    df['Yield'] = df['Symbol'].map(lambda x: metadata.get(x, {}).get('yield', 0.0))
    df['Type'] = df['Symbol'].map(lambda x: metadata.get(x, {}).get('type', 'UNKNOWN'))

    # We only use Current Value to calculate weighted averages, but NEVER print it to stdout.
    total_portfolio_value = df['Current Value'].sum()

    # Calculate Weighted Average Expense Ratio (exclude positions with no ER data)
    df_er = df[df['Expense Ratio'].notna()].copy()
    er_total_value = df_er['Current Value'].sum()
    if er_total_value > 0:
        df_er['Value_Weight'] = df_er['Current Value'] / er_total_value
        df_er['Weighted_ER'] = df_er['Expense Ratio'] * df_er['Value_Weight']
        portfolio_weighted_er = df_er['Weighted_ER'].sum()
    else:
        portfolio_weighted_er = 0.0

    # 3. Write analysis to a local Markdown file
    cache_dir = data_dir / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    if report_path is None:
        report_path = cache_dir / "Portfolio_Analysis_Report.md"

    # CSS for table borders in the PDF output
    table_css = (
        "table { border-collapse: collapse; width: 100%; margin-bottom: 20px; font-size: 10px; table-layout: auto; }\n"
        "th, td { border: 1px solid #000; padding: 4px 6px; text-align: left; word-wrap: break-word; }\n"
        "th { background-color: #f2f2f2; font-weight: bold; }\n"
    )

    findings = []

    with io.StringIO() as f:
        f.write("# Portfolio Optimization Report\n\n")

        # Add generation timestamp
        timestamp = pd.Timestamp.now().strftime("%B %d, %Y at %I:%M %p")
        f.write(f"**Generated on:** {timestamp}\n\n")
        f.write(f"> **Privacy Note:** This report was generated entirely locally. Financial quantities and dollar amounts were NOT transmitted to the cloud AI.\n\n")

        # --- Section 1: High-Level Metrics ---
        f.write("## 1. High-Level Metrics\n")
        f.write(f"- **Weighted Average Expense Ratio:** `{portfolio_weighted_er:.3f}%`\n")
        if portfolio_weighted_er > 0.40:
            f.write("  - ⚠️ *Warning: Your aggregate expense ratio is above the recommended 0.40% threshold for passive long-term indexing.*\n")
        else:
            f.write("  - ✅ *Excellent: Your portfolio fees are highly optimized.*\n")

        # Finding: High-ER holdings (absolute + relative)
        high_er_count = len(df[df['Expense Ratio'].notna() & (df['Expense Ratio'] > 0.40)]) if 'Expense Ratio' in df.columns else 0
        relative_er_count = 0
        for _, row in df.iterrows():
            sym = row.get('Symbol', '')
            er = row.get('Expense Ratio')
            if er is not None and er <= 0.40:
                cat_avg = metadata.get(sym, {}).get('category_avg_er')
                if cat_avg is not None and cat_avg > 0 and er > 2 * cat_avg:
                    relative_er_count += 1
        total_er_flags = high_er_count + relative_er_count
        if total_er_flags > 0:
            findings.append({"category": "high_er", "text": f"**{total_er_flags} holding(s)** have elevated expense ratios (above 0.40% or >2x category average) — consider lower-cost alternatives", "section_ref": 2})
        f.write(f"- **Risk-Free Rate (13-Week T-Bill):** `{rf*100:.2f}%` *(fetched live)*\n")

        # Portfolio Risk Profile — aggregate equity % vs glide-path target
        equity_value = 0.0
        total_value_for_risk = 0.0
        for _, row in df.iterrows():
            sym = row.get('Symbol', '')
            val = row.get('Current Value', 0) or 0
            if pd.isna(sym) or sym == 'CORE' or str(sym).endswith("XX"):
                continue
            total_value_for_risk += val
            ac = metadata.get(sym, {}).get('asset_class', 'US Equity')
            if ac in ("US Equity", "Intl Equity"):
                equity_value += val
        portfolio_equity_pct = (equity_value / total_value_for_risk * 100) if total_value_for_risk > 0 else 0
        target_equity_pct = target_alloc["US Equity"] + target_alloc["Intl Equity"]
        risk_status = "Aligned" if abs(portfolio_equity_pct - target_equity_pct) <= 10 else "Rebalance needed"
        risk_icon = "✅" if risk_status == "Aligned" else "⚠️"
        f.write(f"\n> **Portfolio Risk Profile:** Your portfolio is **{portfolio_equity_pct:.0f}% equity** — target for your age is **{target_equity_pct:.0f}%**. {risk_icon} *{risk_status}*\n")

        # Finding: Risk alignment
        if risk_status == "Rebalance needed":
            findings.append({"category": "risk", "text": f"Portfolio equity allocation ({portfolio_equity_pct:.0f}%) deviates from age-based target ({target_equity_pct:.0f}%) — rebalance recommended", "section_ref": 1})
        if using_profile_defaults:
            f.write(f"> *Target based on default profile. Create `investor_profile.txt` for a personalized target.*\n")

        # --- Section 2: Asset Holding Breakdown ---
        f.write("\n## 2. Asset Holding Breakdown\n")

        def get_action_for_row(row):
            sym = row.get('Symbol', '')
            er = row.get('Expense Ratio', 0.0)
            is_cash = pd.isna(sym) or sym == 'CORE' or str(sym).endswith("XX")
            if is_cash:
                return "Core Cash Position"

            md_info = metadata.get(sym, {})
            flags = []

            # Net-of-fees expense evaluation (absolute threshold)
            if er is not None and er > 0.40:
                nof = md_info.get('net_of_fees_5y')
                if nof is not None:
                    flags.append(f"**Evaluate** (ER {er:.2f}%, Net 5Y: {nof*100:.1f}%)")
                else:
                    flags.append("**Replace (High ER)**. See *Alternatives* below.")
            # Relative ER check: flag if >2x category average
            elif er is not None:
                cat_avg = md_info.get('category_avg_er')
                if cat_avg is not None and cat_avg > 0 and er > 2 * cat_avg:
                    flags.append(f"**Evaluate** (ER is {er/cat_avg:.1f}x category avg)")

            # Small fund closure risk
            net_assets = md_info.get('net_assets')
            if net_assets is not None and net_assets < 100_000_000:
                flags.append("⚠ Small fund (<$100M)")

            # Cap gains risk for taxable accounts
            account_type = resolve_account_type(row.get('Account Name', ''))
            if account_type == "Taxable Brokerage":
                cgy = md_info.get('cap_gain_yield')
                if cgy is not None and cgy > 0.05:
                    flags.append("*High cap gains risk*")

            return " | ".join(flags) if flags else "Keep"

        def get_age_flag(row, age_factor, metadata):
            """Returns italic age-appropriate flag text, or empty string."""
            sym = row.get('Symbol', '')
            if pd.isna(sym) or sym == 'CORE' or str(sym).endswith("XX"):
                return ""
            account_type = resolve_account_type(row.get('Account Name', ''))
            ac = metadata.get(sym, {}).get('asset_class', 'US Equity')
            beta = metadata.get(sym, {}).get('beta', 1.0) or 1.0
            # Young investor + Bond/Stable Value in Roth/HSA
            if age_factor > 0.7 and ac in ("Bond", "Stable Value") and account_type in ("Roth IRA", "HSA"):
                return " *— Consider higher-growth funds for your horizon*"
            # Near-retirement + high-beta in Taxable/Roth
            if age_factor < 0.3 and beta > 1.2 and account_type in ("Taxable Brokerage", "Roth IRA"):
                return " *— Consider lower-volatility for your horizon*"
            return ""

        df['Action'] = df.apply(get_action_for_row, axis=1)
        df['Account Name'] = df['Account Name'].fillna('Unknown Account')
        df['Account Type'] = df['Account Name'].map(resolve_account_type)
        df_sorted = df.sort_values(by=['Account Type', 'Account Name', 'Action', 'Symbol'])

        # Group by Account Type with sub-headers; suppress 401k detail (covered in Section 5)
        section2_order = ["Taxable Brokerage", "Roth IRA", "HSA", "Employer 401k"]
        for account_type in section2_order:
            group = df_sorted[df_sorted['Account Type'] == account_type]
            if group.empty:
                continue

            f.write(f"\n### {account_type}\n")

            if account_type == "Employer 401k":
                k401_count = len(group)
                f.write(f"> 📋 {k401_count} fund(s) held in your 401k. See **Section 5: 401k Plan Analysis** for detailed scoring, rebalance opportunities, and underperforming holdings.\n")
                continue

            f.write("| Symbol | Account Name | Description | Current ER | Cat Avg | Rating | Suggested Action |\n")
            f.write("|---|---|---|---|---|---|---|\n")

            for idx, row in group.iterrows():
                sym = row.get('Symbol', '')
                desc = row.get('Description', '')
                account_name = row['Account Name']
                er = row.get('Expense Ratio')
                action = row['Action']
                if action == "Core Cash Position":
                    er = 0.0
                action += get_age_flag(row, age_factor, metadata)
                er_str = f"{er:.3f}%" if pd.notna(er) else "N/A"
                md_info = metadata.get(sym, {})
                cat_avg = md_info.get('category_avg_er')
                cat_avg_str = f"{cat_avg:.3f}%" if cat_avg is not None else "--"
                ms = md_info.get('morningstar_rating')
                ms_str = "★" * ms if ms is not None else "--"
                f.write(f"| {sym} | {account_name} | {desc} | {er_str} | {cat_avg_str} | {ms_str} | {action} |\n")

        # Finding: Age-inappropriate holdings
        age_inappropriate_count = sum(1 for _, row in df.iterrows() if _get_age_flag_text(row, age_factor, metadata))
        if age_inappropriate_count > 0:
            findings.append({"category": "age_inappropriate", "text": f"**{age_inappropriate_count} holding(s)** may be age-inappropriate for your investment horizon", "section_ref": 2})

        # --- Section 2a: Portfolio Concentration Analysis ---
        f.write("\n### Portfolio Concentration Analysis\n\n")

        # Aggregate sector exposure across held tickers, weighted by portfolio value
        total_portfolio_val = df['Current Value'].sum() if 'Current Value' in df.columns else 0
        agg_sectors = {}
        holdings_overlap = {}  # symbol -> [(ticker, pct)]
        tickers_with_sectors = 0
        for _, row in df.iterrows():
            sym = row.get('Symbol', '')
            val = row.get('Current Value', 0)
            if pd.isna(sym) or sym == 'CORE' or str(sym).endswith("XX") or val <= 0:
                continue
            weight = val / total_portfolio_val if total_portfolio_val > 0 else 0
            sw = metrics.get_sector_weightings(sym)
            if sw:
                tickers_with_sectors += 1
                for sector, pct in sw.items():
                    agg_sectors[sector] = agg_sectors.get(sector, 0) + pct * weight
            th = metrics.get_top_holdings(sym)
            if th:
                for held_sym, held_pct in th:
                    if held_sym not in holdings_overlap:
                        holdings_overlap[held_sym] = []
                    holdings_overlap[held_sym].append((sym, held_pct))

        if agg_sectors and tickers_with_sectors > 0:
            # Normalize sector names for display
            sector_names = {
                'realestate': 'Real Estate', 'consumer_cyclical': 'Consumer Cyclical',
                'basic_materials': 'Basic Materials', 'consumer_defensive': 'Consumer Defensive',
                'technology': 'Technology', 'communication_services': 'Communication Services',
                'financial_services': 'Financial Services', 'utilities': 'Utilities',
                'industrials': 'Industrials', 'energy': 'Energy', 'healthcare': 'Healthcare',
            }
            sorted_sectors = sorted(agg_sectors.items(), key=lambda x: x[1], reverse=True)

            f.write("| Sector | Exposure | Status |\n")
            f.write("|---|---|---|\n")
            concentrated = False
            for sector_key, pct in sorted_sectors:
                if pct < 0.01:
                    continue
                name = sector_names.get(sector_key, sector_key.replace('_', ' ').title())
                status = "⚠️ **Concentrated**" if pct > 0.40 else ("Elevated" if pct > 0.25 else "")
                if pct > 0.40:
                    concentrated = True
                f.write(f"| {name} | {pct*100:.1f}% | {status} |\n")

            if concentrated:
                findings.append({"category": "concentration", "text": "Portfolio has concentrated sector exposure (>40% in a single sector)", "section_ref": 2})
            f.write("\n")
        else:
            f.write("*Sector data not available for current holdings.*\n\n")

        # Holding overlap detection
        overlaps = {sym: funds for sym, funds in holdings_overlap.items() if len(funds) >= 2}
        if overlaps:
            f.write("**Holding Overlap:** The following stocks appear in multiple funds:\n\n")
            for held_sym, funds in sorted(overlaps.items(), key=lambda x: len(x[1]), reverse=True)[:10]:
                fund_strs = [f"{t} ({p*100:.1f}%)" for t, p in funds]
                f.write(f"- **{held_sym}** in {', '.join(fund_strs)}\n")
            f.write("\n")

        # --- Section 3: Tax Optimization ---
        f.write("\n## 3. Tax Optimization & Loss Harvesting\n")
        f.write("By tracking individual lot purchase dates via FIFO accounting, we can optimize your short-term/long-term capital gains classification and find tax loss harvesting opportunities.\n\n")

        # TLH Opportunities — taxable accounts only (401k, Roth IRA, HSA losses have no tax benefit)
        tlh_lots = lots_df[lots_df['Unrealized Gain'] < 0].copy()
        tlh_lots['Account Type'] = tlh_lots['Account Name'].map(
            lambda a: resolve_account_type(a) if pd.notna(a) else 'Unknown'
        )
        tlh_lots = tlh_lots[tlh_lots['Account Type'] == 'Taxable Brokerage']

        # Aggregate per (Symbol, Account Name) before writing callout
        tlh_agg = []
        for (symbol, account), grp in tlh_lots.groupby(['Symbol', 'Account Name']):
            est_loss = -grp['Unrealized Gain'].sum()  # positive: loss magnitude
            desc = grp['Description'].iloc[0] if 'Description' in grp.columns else ''
            tax_cats = ', '.join(grp['Tax_Category'].dropna().unique())
            tlh_agg.append({
                'Symbol': symbol,
                'Account Name': account,
                'Description': desc,
                'Tax_Category': tax_cats,
                'Est_Loss': est_loss,
                'Lot_Count': len(grp),
            })
        tlh_agg.sort(key=lambda x: x['Est_Loss'], reverse=True)

        # Compute STCG count for the summary callout
        prof_lots_stcg = lots_df[
            (lots_df['Unrealized Gain'] > 0) & (lots_df['Tax_Category'] == 'STCG (<1yr)')
        ]
        sym_to_account_type = df.set_index('Symbol')['Account Name'].map(resolve_account_type).to_dict()
        stcg_taxable = prof_lots_stcg[
            prof_lots_stcg['Symbol'].map(lambda s: sym_to_account_type.get(s, 'Unknown')) == 'Taxable Brokerage'
        ]
        stcg_symbol_count = stcg_taxable['Symbol'].nunique()

        # Tax Snapshot callout
        total_harvestable = sum(r['Est_Loss'] for r in tlh_agg)
        tlh_position_count = len(tlh_agg)
        f.write(f"> **Tax Snapshot:** {tlh_position_count} position(s) with harvestable losses totaling (${total_harvestable:,.0f}) | {stcg_symbol_count} position(s) with pending STCG exposure\n\n")

        # Finding: TLH opportunities
        if tlh_position_count > 0:
            findings.append({"category": "tlh", "text": f"**{tlh_position_count} position(s)** with harvestable tax losses available", "section_ref": 3})
        # Finding: STCG exposure
        if stcg_symbol_count > 0:
            findings.append({"category": "stcg", "text": f"**{stcg_symbol_count} position(s)** have short-term capital gains exposure — consider holding past 1 year", "section_ref": 3})

        f.write("### 🚨 Tax-Loss Harvesting Candidates\n")
        if tlh_agg:
            f.write("The following lots are currently held at a loss. Selling these will harvest the loss to offset your other capital gains (up to $3,000 against ordinary income).\n\n")
            f.write("*401k, Roth IRA, and HSA accounts are excluded — losses in tax-advantaged accounts have no tax benefit.*\n\n")

            if age_factor < 0.3:
                f.write("> ⚠️ **Near-Retirement Alert:** Shorter window to utilize harvested losses — prioritize harvesting now.\n\n")

            f.write("| Priority | Account | Symbol | Description | Tax Category | Est. Loss ($) | Underwater Lots | Wash Sale Risk |\n")
            f.write("|---|---|---|---|---|---|---|---|\n")

            # Determine urgency label based on age_factor
            if age_factor < 0.3:
                urgency = "High"
            elif age_factor <= 0.6:
                urgency = "Normal"
            else:
                urgency = "Low"

            for rank, row in enumerate(tlh_agg, 1):
                risk = detect_wash_sale_risk(df, row['Symbol'])
                risk_str = "⚠️ YES (Cross-Account)" if risk else "No"
                est_loss = row['Est_Loss']
                f.write(f"| {rank} ({urgency}) | {row['Account Name']} | **{row['Symbol']}** | {row['Description']} | {row['Tax_Category']} | (${est_loss:,.0f}) | {row['Lot_Count']} lot(s) | {risk_str} |\n")
        else:
            f.write("*Amazing! No assets are currently held at a loss in your taxable accounts. No TLH opportunities exist right now.*\n")
            f.write("\n*401k, Roth IRA, and HSA accounts are excluded — losses in tax-advantaged accounts have no tax benefit.*\n")

        # Capital Gains Screener with De Minimis Override
        f.write("\n### ⏳ Capital Gains 'One-Year Wait' Screener\n")
        f.write(f"Profitable lots held for under 365 days are subject to your ordinary income tax rate. Waiting 1 year drops this to the much lower LTCG (15-20%) bracket.\n\n")
        f.write(f"**De Minimis Threshold:** Lots with STCG gains below **{DE_MINIMIS_GAIN_PCT*100:.0f}% of lot value** are flagged as safe to reallocate.\n\n")
        f.write("| Account Name | Symbol | Lots STCG | Lots LTCG | De Minimis (Safe to Reallocate) |\n")
        f.write("|---|---|---|---|---|\n")

        prof_lots = lots_df[lots_df['Unrealized Gain'] > 0]
        if not prof_lots.empty:
            # First map symbols to their originating account names from the main df
            sym_to_account = df.set_index('Symbol')['Account Name'].to_dict()
            
            screener_rows = []

            for sym in prof_lots['Symbol'].dropna().unique():
                account_name = sym_to_account.get(sym, 'Unknown Account')
                
                # Check 1: Is this account even subject to capital gains tax?
                account_type = resolve_account_type(account_name) # Using resolve_account_type from earlier in the code
                if account_type != "Taxable Brokerage":
                    continue # Skip Roth IRAs, HSAs, 401ks (tax-advantaged)
                
                sym_lots = prof_lots[prof_lots['Symbol'] == sym]
                stcg_lots = sym_lots[sym_lots['Tax_Category'] == 'STCG (<1yr)']
                ltcg_count = len(sym_lots[sym_lots['Tax_Category'] == 'LTCG (>1yr)'])

                # De minimis check: gain < DE_MINIMIS_GAIN_PCT of current value
                de_minimis_count = 0
                regular_stcg_count = 0
                for _, lot in stcg_lots.iterrows():
                    gain = lot.get('Unrealized Gain', 0)
                    value = lot.get('Current Value', 1)
                    if value > 0 and gain / value < DE_MINIMIS_GAIN_PCT:
                        de_minimis_count += 1
                    else:
                        regular_stcg_count += 1

                if regular_stcg_count == 0 and ltcg_count == 0 and de_minimis_count == 0:
                    continue

                de_min_text = f"✅ {de_minimis_count} lot(s) — gain < 1%" if de_minimis_count > 0 else "—"
                
                screener_rows.append({
                    "Account": account_name,
                    "Symbol": sym,
                    "STCG": f"{regular_stcg_count} Pending",
                    "LTCG": f"{ltcg_count} Safe",
                    "DeMinimis": de_min_text
                })

            # Sort by Account Name then Symbol
            screener_rows = sorted(screener_rows, key=lambda x: (x["Account"], x["Symbol"]))

            if not screener_rows:
                f.write("*Amazing! No assets are currently held at a short-term capital gain in your Taxable accounts.*\n")
            else:
                for row in screener_rows:
                    f.write(f"| {row['Account']} | **{row['Symbol']}** | {row['STCG']} | {row['LTCG']} | {row['DeMinimis']} |\n")
        else:
            f.write("*Amazing! No assets are currently held at a short-term capital gain in your Taxable accounts.*\n")

        # --- Section 4: Recommended Replacements (4-Bucket) ---
        f.write("\n## 4. Recommended Replacement Funds\n")
        f.write("Funds dynamically selected today based on live market data, scored using per-account metrics aligned to each account's investment objective.\n\n")

        print("Fetching a dynamic universe of replacement candidates from live market data...")
        dynamic_tickers = market_data.get_dynamic_etf_universe()
        candidate_tickers = list(dynamic_tickers)
        
        # Ensure that ALL funds offered in the 401k plan are included in the evaluation
        if plan_menu_tickers:
            candidate_tickers.extend(plan_menu_tickers)
            candidate_tickers = list(set(candidate_tickers))
            
        print(f"Discovered {len(candidate_tickers)} candidates. Fetching full historical metadata...")
        candidate_data = market_data.fetch_ticker_metadata(candidate_tickers)

        # Classify, filter, and score candidates into 4 buckets
        roth_candidates = []
        k401_candidates = []
        hsa_candidates = []
        taxable_candidates = []

        for ticker, data in candidate_data.items():
            is_plan_menu = bool(plan_menu_tickers and ticker in plan_menu_tickers)
            is_dynamic = ticker in dynamic_tickers
            
            # STRICT QA: Must be an ETF or Mutual Fund (exempt 401k plan funds)
            quote_type = data.get("type", "").upper()
            if not is_plan_menu and quote_type not in ["ETF", "MUTUALFUND"]:
                continue

            er = data.get("expense_ratio_pct", 100.0)
            yld = data.get("yield", 0.0) or 0.0
            ret_1y = data.get("1y_return", 0.0) or 0.0
            ret_3y = data.get("3y_return", 0.0) or 0.0
            ret_5y = data.get("5y_return", 0.0) or 0.0

            # Reject corrupted data (exempt 401k plan funds)
            if not is_plan_menu and ret_1y == 0.0 and ret_3y == 0.0 and ret_5y == 0.0 and yld == 0.0:
                continue

            # ER filter (exempt 401k plan funds since users have no other choice)
            if not is_plan_menu and er > 0.40:
                continue

            beta = data.get("beta", 1.0)
            routing = classify_routing_bucket(yld, beta)

            cand = {
                "ticker": ticker,
                "name": data.get("name", ticker),
                "er": er,
                "yield": yld,
                "1y_return": ret_1y,
                "3y_return": ret_3y,
                "5y_return": ret_5y,
                "routing": routing,
            }

            # Score per-account
            cand = score_candidate(ticker, cand, routing, years_to_retirement=years_to_retirement)

            # Age-appropriateness penalty for Roth IRA candidates
            if routing == "Roth IRA":
                cand_ac = candidate_data.get(ticker, {}).get("asset_class", "US Equity")
                cand_beta = candidate_data.get(ticker, {}).get("beta", 1.0) or 1.0
                if age_factor < 0.3 and cand_beta > 1.2:
                    cand["score"] = round(cand["score"] * 0.85, 4)
                elif age_factor > 0.7 and cand_ac in ("Bond", "Stable Value"):
                    cand["score"] = round(cand["score"] * 0.85, 4)

            # Flag funds with < 3 years of history — prefer inception date, fall back to price data
            inception_yrs = candidate_data.get(ticker, {}).get("inception_years")
            if inception_yrs is not None:
                cand["insufficient_history"] = inception_yrs < 3.0
            else:
                history_days = metrics.get_history_days(ticker)
                cand["insufficient_history"] = history_days < 1095

            if routing == "Roth IRA":
                if is_dynamic:
                    roth_candidates.append(cand)
                    # HSA uses same growth-scoring tier as Roth IRA (Sortino + 5Y + 10Y).
                    # Triple tax advantage makes HSA optimal for long-term compounding, not income.
                    hsa_candidates.append(cand)
            elif routing == "Tax-Deferred":
                k401_candidates.append(cand)
            else:
                if is_dynamic:
                    taxable_candidates.append(cand)

        roth_candidates.sort(key=lambda x: x["score"], reverse=True)
        k401_candidates.sort(key=lambda x: x["score"], reverse=True)
        hsa_candidates.sort(key=lambda x: x["score"], reverse=True)
        taxable_candidates.sort(key=lambda x: x["score"], reverse=True)

        # Split each bucket into established (≥ 3Y history) and emerging (< 3Y)
        roth_main =    [c for c in roth_candidates    if not c.get("insufficient_history")]
        roth_emerging = [c for c in roth_candidates   if c.get("insufficient_history")]
        k401_main =    [c for c in k401_candidates    if not c.get("insufficient_history")]
        k401_emerging = [c for c in k401_candidates   if c.get("insufficient_history")]
        hsa_main =     [c for c in hsa_candidates     if not c.get("insufficient_history")]
        hsa_emerging =  [c for c in hsa_candidates    if c.get("insufficient_history")]
        taxable_main =  [c for c in taxable_candidates if not c.get("insufficient_history")]
        taxable_emerging = [c for c in taxable_candidates if c.get("insufficient_history")]

        # --- 401k Plan Menu Constraint ---
        # If a 401k plan menu was detected, constrain ONLY 401k candidates to the plan menu.
        # HSA candidates remain unconstrained (HSA holders can invest in anything).
        if plan_menu_tickers:
            plan_constrained = [c for c in k401_candidates if c["ticker"] in plan_menu_tickers]
            if plan_constrained:
                k401_main = [c for c in plan_constrained if not c.get("insufficient_history")]
                k401_emerging = [c for c in plan_constrained if c.get("insufficient_history")]
                print(f"   401k replacement candidates constrained to {len(plan_constrained)} funds from your employer's plan menu.")
            else:
                print("   ⚠️ No plan menu funds matched the dynamic candidate universe. Showing unconstrained 401k results.")
            print(f"   HSA replacement candidates: {len(hsa_candidates)} (growth-scored, full dynamic universe).")

        def _write_fund_rows(funds, header, divider, extra_cols, label_suffix=""):
            """Writes fund table rows. label_suffix is appended to fund names if set."""
            f.write(header + "\n")
            f.write(divider + "\n")
            if not funds:
                f.write("| N/A | No funds matched criteria | - | - | - |")
                if extra_cols:
                    f.write(" - |" * len(extra_cols))
                f.write(" - | - | - |\n")
            for c in funds[:5]:
                nof = c.get('net_of_fees_5y', 0)
                r1 = f"{c['1y_return']*100:+.2f}%"
                r3 = f"{c['3y_return']*100:+.2f}%"
                r5 = f"{c['5y_return']*100:+.2f}%"
                nof_str = f"{nof*100:+.2f}%" if nof else "N/A"
                name = c['name'] + (f" {label_suffix}" if label_suffix else "")
                row = f"| **{c['ticker']}** | {name} | `{c['er']:.2f}%` | *{c['yield']*100:.2f}%* | {nof_str} |"
                if extra_cols:
                    for col_key in extra_cols:
                        if "10Y" in col_key:
                            key = "total_return_10y"
                        elif "Sharpe" in col_key:
                            key = "sharpe_ratio"
                        elif "Sortino" in col_key:
                            key = "sortino_ratio"
                        elif "Max DD" in col_key:
                            key = "max_drawdown"
                        else:
                            key = col_key.lower().replace(" ", "_").replace("(", "").replace(")", "")
                        val = c.get(key)
                        if val is None:
                            row += " N/A |"
                        elif "return" in key or "drawdown" in key:
                            row += f" {val*100:+.2f}% |" if "return" in key else f" {val*100:.2f}% |"
                        elif isinstance(val, float):
                            row += f" {val:.3f} |"
                        else:
                            row += f" {val} |"
                row += f" {r1} | {r3} | {r5} |"
                f.write(row + "\n")
            f.write("\n")

        def write_fund_table(funds, title, description, extra_cols=None, emerging=None):
            f.write(f"### {title}\n")
            f.write(f"{description}\n\n")

            # Rearrange columns: ER, Yield, Net 5Y Ret, [Extra Metrics], 1Y Ret, 3Y Ret, 5Y Ret
            header = "| Ticker | Fund Name | ER | Yield | Net 5Y Ret |"
            divider = "|---|---|---|---|---|"

            if extra_cols:
                for col_name in extra_cols:
                    header += f" {col_name} |"
                    divider += "---|"

            header += " 1Y Ret | 3Y Ret | 5Y Ret |"
            divider += "---|---|---|"

            _write_fund_rows(funds, header, divider, extra_cols)

            if emerging:
                f.write("#### Emerging Funds (Limited Track Record)\n")
                f.write("*Scored on available history only — < 3 years of data. Not ranked against established funds.*\n\n")
                _write_fund_rows(emerging, header, divider, extra_cols, label_suffix="⚠️ < 3Y History")

        write_fund_table(
            roth_main,
            "🚀 Roth IRA — Maximum Growth",
            "These funds maximize total return. All growth is permanently tax-free. Scored by Sortino Ratio + Net-of-Fees 5Y Return + 10Y Total Return.",
            extra_cols=["Sortino (5Y)", "10Y Ret"],
            emerging=roth_emerging,
        )
        write_fund_table(
            k401_main,
            "💼 Employer 401k — Income & Dividends (Plan-Constrained)",
            "High-yield funds for your employer 401k. Constrained to your plan menu. Scored by Sharpe Ratio + Net-of-Fees 5Y Return.",
            extra_cols=["Sharpe (5Y)"],
            emerging=k401_emerging,
        )
        write_fund_table(
            hsa_main,
            "🏥 HSA — Maximum Growth (Full Universe)",
            "Maximum-growth funds for your Health Savings Account. HSA's triple tax advantage (pre-tax contributions, tax-free growth, tax-free qualified withdrawals) makes it optimal for long-term compounding — not income. Full dynamic universe, no plan menu constraint. Scored by Sortino Ratio + Net-of-Fees 5Y Return + 10Y Total Return.",
            extra_cols=["Sortino (5Y)", "10Y Ret"],
            emerging=hsa_emerging,
        )
        write_fund_table(
            taxable_main,
            "🏦 Taxable Brokerage — Tax-Efficient Growth",
            "Low-distribution growth funds that minimize taxable events. Scored by Sharpe Ratio + Net-of-Fees 5Y Return + low-yield bonus.",
            extra_cols=["Sharpe (5Y)", "Max DD (5Y)"],
            emerging=taxable_emerging,
        )

        # --- Section 5: 401k Plan Analysis ---
        all_plan_scored = []
        if plan_menu_tickers and k401_options_file:
            print("Generating dedicated 401k Plan Analysis section...")
            f.write("\n## 5. 401k Plan Analysis\n\n")

            # 5a. Current Holdings Table
            # Filter specifically for 'Employer 401k' to segregate it from HSA accounts
            # which were previously merged into the 'Tax-Deferred' routing bucket.
            if 'Account Type' in df.columns and 'Account Name' in df.columns:
                k401_df = df[df['Account Name'].str.contains('401k|401K', na=False)].copy()
            else:
                k401_df = pd.DataFrame()

            if not k401_df.empty:
                total_401k = k401_df['Current Value'].sum()
                f.write(f"### Your Current 401k Holdings\n\n")

                f.write("| Ticker | Fund Name | Balance | Weight | ER | 1Y Return | 3Y Return | 5Y Return |\n")
                f.write("|---|---|---|---|---|---|---|---|\n")
                for _, row in k401_df.iterrows():
                    sym = row.get('Symbol', '')
                    md = candidate_data.get(sym, {})
                    r1 = md.get('1y_return')
                    r3 = md.get('3y_return')
                    r5 = md.get('5y_return')
                    er = md.get('expense_ratio_pct', row.get('Expense Ratio', 0.0))
                    val = row.get('Current Value', 0)
                    pct = (val / total_401k * 100) if total_401k > 0 else 0
                    r1s = f"{r1*100:+.2f}%" if r1 else "N/A"
                    r3s = f"{r3*100:+.2f}%" if r3 else "N/A"
                    r5s = f"{r5*100:+.2f}%" if r5 else "N/A"
                    f.write(f"| **{sym}** | {row.get('Description', sym)} | ${val:,.2f} | {pct:.1f}% | `{er:.2f}%` | {r1s} | {r3s} | {r5s} |\n")

                f.write(f"\n**Total 401k Value:** ${total_401k:,.2f}\n\n")

            # 5b. Full Plan Menu Scorecard — rank every fund in the plan
            f.write("### Plan Menu Scorecard — All Available Funds Ranked\n")
            f.write("Every fund your employer offers, scored by the engine's 401k optimization formula (Sharpe Ratio + Net-of-Fees Return + Tracking Error). ")
            f.write("Funds you currently hold are marked with ✅.\n\n")

            held_tickers = set(k401_df['Symbol'].tolist()) if not k401_df.empty else set()

            # Score all plan menu funds using the 401k scoring formula
            all_plan_scored = []
            for ticker in plan_menu_tickers:
                md = candidate_data.get(ticker, {})
                if not md:
                    continue
                er = md.get('expense_ratio_pct', 0.0)
                yld = md.get('yield', 0.0) or 0.0
                r1 = md.get('1y_return', 0.0) or 0.0
                r3 = md.get('3y_return', 0.0) or 0.0
                r5 = md.get('5y_return', 0.0) or 0.0
                name = md.get('name', ticker)
                cand = {
                    "ticker": ticker, "name": name, "er": er,
                    "yield": yld, "1y_return": r1, "3y_return": r3,
                    "5y_return": r5, "routing": "Tax-Deferred",
                }
                cand = score_candidate(ticker, cand, "Tax-Deferred", years_to_retirement=years_to_retirement)
                all_plan_scored.append(cand)

            all_plan_scored.sort(key=lambda x: x["score"], reverse=True)

            f.write("| Rank | Held | Ticker | Fund Name | Score | ER | Sharpe | 1Y | 3Y | 5Y |\n")
            f.write("|---|---|---|---|---|---|---|---|---|---|\n")

            for i, c in enumerate(all_plan_scored, 1):
                held = "✅" if c["ticker"] in held_tickers else "—"
                sharpe = c.get("sharpe_ratio")
                sharpe_s = f"{sharpe:.3f}" if sharpe else "N/A"
                r1 = f"{c['1y_return']*100:+.2f}%"
                r3 = f"{c['3y_return']*100:+.2f}%"
                r5 = f"{c['5y_return']*100:+.2f}%"
                f.write(f"| {i} | {held} | **{c['ticker']}** | {c['name']} | {c['score']:.1f} | `{c['er']:.2f}%` | {sharpe_s} | {r1} | {r3} | {r5} |\n")

            f.write("\n")

            # 5c. Rebalance Opportunities
            top_not_held = [c for c in all_plan_scored if c["ticker"] not in held_tickers][:5]

            # Finding: 401k rebalance
            if top_not_held:
                findings.append({"category": "k401_rebalance", "text": f"**{len(top_not_held)} higher-scoring fund(s)** in your 401k plan that you don't currently hold", "section_ref": 5})

            if top_not_held:
                f.write("### 🔄 Rebalance Opportunities\n")
                f.write("These are the **highest-scoring funds in your plan that you don't currently hold**. ")
                f.write("Consider reallocating some of your 401k contribution elections toward these funds.\n\n")

                f.write("| Ticker | Fund Name | Score | ER | Sharpe | Why Consider |\n")
                f.write("|---|---|---|---|---|---|\n")
                for c in top_not_held:
                    sharpe = c.get("sharpe_ratio")
                    sharpe_s = f"{sharpe:.3f}" if sharpe else "N/A"
                    nof = c.get("net_of_fees_5y", 0)
                    reason = []
                    if c.get("er", 1.0) < 0.10:
                        reason.append("Ultra-low fees")
                    if sharpe and sharpe > 1.0:
                        reason.append(f"Strong Sharpe ({sharpe:.2f})")
                    if nof and nof > 0.10:
                        reason.append(f"High net return ({nof*100:.1f}%)")
                    if c.get("1y_return", 0) > 0.15:
                        reason.append("Hot 1Y momentum")
                    reason_text = "; ".join(reason) if reason else "Diversification opportunity"
                    f.write(f"| **{c['ticker']}** | {c['name']} | {c['score']:.1f} | `{c['er']:.2f}%` | {sharpe_s} | {reason_text} |\n")
                f.write("\n")

            # 5d. Weakest holdings check
            if not k401_df.empty and len(all_plan_scored) > 5:
                worst_held = [c for c in reversed(all_plan_scored) if c["ticker"] in held_tickers][:3]
                if worst_held and worst_held[0]["score"] < all_plan_scored[len(all_plan_scored) // 2]["score"]:
                    f.write("### ⚠️ Underperforming Holdings\n")
                    f.write("These funds you currently hold rank in the **bottom half** of your plan menu. Consider reducing allocation.\n\n")
                    f.write("| Ticker | Fund Name | Plan Rank | Score | ER | 1Y | Suggestion |\n")
                    f.write("|---|---|---|---|---|---|---|\n")
                    for c in worst_held:
                        rank = next((i for i, x in enumerate(all_plan_scored, 1) if x["ticker"] == c["ticker"]), "?")
                        r1 = f"{c['1y_return']*100:+.2f}%"
                        f.write(f"| **{c['ticker']}** | {c['name']} | #{rank} of {len(all_plan_scored)} | {c['score']:.1f} | `{c['er']:.2f}%` | {r1} | Reduce allocation |\n")
                    f.write("\n")

        # --- Section 5e: Recommended 401k Allocation ---
        if plan_menu_tickers and k401_options_file and all_plan_scored:
            f.write("### Recommended Allocation\n\n")

            profile_note = "default profile" if using_profile_defaults else "investor profile"
            equity_total = target_alloc["US Equity"] + target_alloc["Intl Equity"]
            bond_total = target_alloc["Bond"] + target_alloc["Stable Value"]
            f.write(f"Based on {profile_note} (born {birth_year}, retiring {retirement_year}, {years_to_retirement} years out):\n")
            f.write(f"**Target split: {equity_total:.0f}% Equity / {bond_total:.0f}% Bond**\n\n")
            if using_profile_defaults:
                f.write(f"> *Using default assumptions. Create `Drop_Financial_Info_Here/investor_profile.txt` with `birth_year` and `retirement_year` to personalize.*\n\n")

            # Classify each scored fund by asset class
            class_funds = {"US Equity": [], "Intl Equity": [], "Bond": [], "Stable Value": []}
            for c in all_plan_scored:
                ac = candidate_data.get(c["ticker"], {}).get("asset_class", "US Equity")
                if ac in class_funds:
                    class_funds[ac].append(c)

            # Handle empty classes: roll into fallback
            if not class_funds["Intl Equity"]:
                target_alloc["US Equity"] += target_alloc["Intl Equity"]
                target_alloc["Intl Equity"] = 0.0
            if not class_funds["Stable Value"]:
                target_alloc["Bond"] += target_alloc["Stable Value"]
                target_alloc["Stable Value"] = 0.0
            if not class_funds["Bond"] and not class_funds["Stable Value"]:
                target_alloc["US Equity"] += target_alloc["Bond"]
                target_alloc["Bond"] = 0.0

            # Take top 3 per class, compute score-weighted allocation
            alloc_rows = []
            for asset_class, class_target_pct in target_alloc.items():
                if class_target_pct <= 0 or not class_funds.get(asset_class):
                    continue
                top_funds = class_funds[asset_class][:3]
                total_score = sum(c["score"] for c in top_funds) or 1.0
                for c in top_funds:
                    raw_pct = (c["score"] / total_score) * class_target_pct
                    alloc_rows.append({
                        "ticker": c["ticker"],
                        "name": c["name"],
                        "asset_class": asset_class,
                        "raw_pct": raw_pct,
                    })

            # Apply minimum floor and normalize to 100%
            for row in alloc_rows:
                row["raw_pct"] = max(row["raw_pct"], MIN_ALLOCATION_PCT)
            total_raw = sum(r["raw_pct"] for r in alloc_rows) or 100.0
            for row in alloc_rows:
                row["target_pct"] = round(row["raw_pct"] / total_raw * 100, 1)

            # Compute current % from k401_df
            total_401k = k401_df['Current Value'].sum() if not k401_df.empty else 0
            held_pcts = {}
            if total_401k > 0:
                for _, row in k401_df.iterrows():
                    sym = row.get('Symbol', '')
                    held_pcts[sym] = round(row.get('Current Value', 0) / total_401k * 100, 1)

            f.write("| Ticker | Fund Name | Asset Class | Duration | Current % | Target % | Change | Action |\n")
            f.write("|---|---|---|---|---|---|---|---|\n")

            for row in sorted(alloc_rows, key=lambda x: x["target_pct"], reverse=True):
                ticker = row["ticker"]
                current_pct = held_pcts.get(ticker, 0.0)
                target_pct = row["target_pct"]
                delta = target_pct - current_pct

                if current_pct == 0.0:
                    action = "**Add**"
                elif delta > 2.0:
                    action = "Increase"
                elif delta < -2.0:
                    action = "Reduce"
                else:
                    action = "Hold"

                # Bond duration column (only meaningful for bond funds)
                dur = candidate_data.get(ticker, {}).get("bond_duration")
                dur_str = f"{dur:.1f}yr" if dur is not None else "--"

                delta_str = f"{delta:+.1f}%" if current_pct > 0 else f"+{target_pct:.1f}%"
                f.write(f"| **{ticker}** | {row['name']} | {row['asset_class']} | {dur_str} | {current_pct:.1f}% | {target_pct:.1f}% | {delta_str} | {action} |\n")

            # Funds currently held but not in target allocation
            target_tickers = {r["ticker"] for r in alloc_rows}
            for sym, pct in held_pcts.items():
                if sym not in target_tickers and pct > 0:
                    md = candidate_data.get(sym, {})
                    name = md.get("name", sym)
                    ac = md.get("asset_class", "US Equity")
                    f.write(f"| **{sym}** | {name} | {ac} | {pct:.1f}% | 0.0% | -{pct:.1f}% | **Remove** |\n")

            f.write("\n")

            # Summary: current vs target equity/bond split
            current_equity = 0.0
            current_bond = 0.0
            if total_401k > 0:
                for _, row in k401_df.iterrows():
                    sym = row.get('Symbol', '')
                    val_pct = row.get('Current Value', 0) / total_401k * 100
                    ac = candidate_data.get(sym, {}).get("asset_class", "US Equity")
                    if ac in ("US Equity", "Intl Equity"):
                        current_equity += val_pct
                    else:
                        current_bond += val_pct

            status = "✅ Aligned" if abs(current_equity - equity_total) <= 5 else "⚠️ Rebalance needed"
            f.write(f"**Current split:** {current_equity:.0f}% Equity / {current_bond:.0f}% Bond | ")
            f.write(f"**Target:** {equity_total:.0f}% Equity / {bond_total:.0f}% Bond | {status}\n\n")

            f.write("> *Illustrative model based on a standard target-date glide path. Consult a financial advisor before making changes to your 401k allocations.*\n\n")

        # --- Section 6: Next Steps ---
        candidates_by_bucket = {
            "taxable": taxable_main,
            "roth": roth_main,
            "hsa": hsa_main,
            "k401": k401_main,
        }
        next_steps_md = _render_next_steps(
            df, metadata, tlh_agg, candidates_by_bucket, age_factor,
            plan_menu_tickers,
            all_plan_scored=all_plan_scored if (plan_menu_tickers and k401_options_file) else None,
        )
        f.write(next_steps_md)

        # --- Section 7: Why These Recommendations ---
        f.write("## 7. Why These Recommendations\n\n")

        # Tier 1: Plain-English verdict table
        verdict_md = _render_verdict_table(df, metadata, age_factor)
        f.write(verdict_md)

        # Tier 2: Methodology & Scoring Details (collapsible in HTML)
        f.write("<!-- DETAILS_START: Methodology & Scoring Details -->\n\n")
        f.write("### How Each Metric is Used\n\n")
        f.write("| Metric | Used For | What It Measures | Interpretation |\n")
        f.write("|---|---|---|---|\n")
        f.write("| **Net-of-Fees Return (5Y)** | All accounts | Annualized return after subtracting expense ratio | Higher is better. The single most important number — what you actually earned. |\n")
        f.write("| **Sharpe Ratio** | Taxable, 401k, HSA | Return per unit of *total* volatility (risk-adjusted) | > 1.0 is good, > 2.0 is excellent. Higher means better risk-adjusted returns. |\n")
        f.write("| **Sortino Ratio** | Roth IRA | Return per unit of *downside* volatility | Like Sharpe but ignores upside swings. > 1.0 is good. Ideal for growth funds. |\n")
        f.write("| **Max Drawdown** | Taxable, Roth IRA | Worst peak-to-trough decline over 5 years | A less negative number is better. -20% means the fund dropped 20% at its worst point. |\n")
        f.write("| **Tracking Error** | Taxable, 401k, HSA | How closely a fund follows its benchmark index | Lower is better for index funds. High TE means the fund deviates from what it claims to track. |\n")
        f.write("| **Total Return (10Y)** | Roth IRA | Cumulative total return over 10 years | Shows long-term compounding power. Marked 'Insufficient History' if fund is < 10 years old. |\n")
        f.write(f"\n*Risk-free rate used for Sharpe/Sortino: **{rf*100:.2f}%** (13-week T-Bill, fetched live)*\n")
        f.write(f"\n*Tracking Error is computed against each fund's detected benchmark (e.g., SPY for S&P 500 funds, AGG for bond funds). If no benchmark can be detected, the metric is omitted.*\n")
        f.write("\n### Per-Account Scoring Rationale\n\n")
        f.write("- **Taxable Brokerage:** Prioritizes net returns + risk consistency (Sharpe) + low tax drag (low yield). Max Drawdown penalizes volatility that could trigger panic selling.\n")
        f.write("- **Roth IRA:** Maximizes total return using Sortino (ignores upside volatility). 10Y track record validates durable compounding. This is your most valuable tax shelter — put your biggest growers here.\n")
        f.write("- **Employer 401k:** Balances income generation with consistency (Sharpe). Tracking Error ensures index fund fidelity. Constrained to your employer's plan menu. Tax-deferred, so dividends compound without annual drag.\n")
        f.write("- **HSA:** Same scoring model as Roth IRA (Sortino + Net-of-Fees 5Y + 10Y Total Return). HSA's triple tax advantage makes long-term compounding the optimal strategy — not income generation. Full dynamic universe access, no plan-menu constraint.\n")

        f.write("\n### Age-Aware Scoring Adjustments\n\n")
        if using_profile_defaults:
            f.write(f"*Using default investor profile (born {birth_year}, retiring {retirement_year}). Create `investor_profile.txt` to personalize.*\n\n")
        else:
            f.write(f"*Investor profile: born {birth_year}, retiring {retirement_year} ({years_to_retirement} years to retirement, age factor: {age_factor:.2f}).*\n\n")
        f.write("Scoring weights shift smoothly based on your time horizon:\n")
        f.write("- **Young investors (40+ yrs out):** Higher weight on growth metrics (Net-of-Fees, Sortino, 10Y Return). Lower weight on defensive metrics (Max Drawdown).\n")
        f.write("- **Near-retirement (< 12 yrs out):** Higher weight on risk metrics (Sharpe, Max Drawdown). Lower weight on long-term total return. TLH urgency elevated.\n")
        f.write("- **Replacement candidates** receive a soft penalty (0.85x) if age-inappropriate for Roth IRA (e.g., bonds for young investors, high-beta for near-retirement).\n")
        f.write("\n<!-- DETAILS_END -->\n")

        markdown_content = f.getvalue()

    # Splice Executive Summary before Section 1
    exec_summary = _render_executive_summary(findings)
    insert_idx = markdown_content.find("## 1.")
    if insert_idx >= 0:
        markdown_content = markdown_content[:insert_idx] + exec_summary + markdown_content[insert_idx:]

    # 4. Save exact markdown to Drop_Financial_Info_Here/ cache
    with open(report_path, "w", encoding="utf-8") as md_file:
        md_file.write(markdown_content)

    # 5. Convert to PDF and HTML (dual output)
    timestamp_file = pd.Timestamp.now().strftime("%b-%d-%Y_%H-%M-%S")
    pdf_path = cache_dir / f"Portfolio_Analysis_Report_{timestamp_file}.pdf"
    html_path = cache_dir / f"Portfolio_Analysis_Report_{timestamp_file}.html"

    print("Converting report to PDF...")
    pdf = MarkdownPdf(toc_level=2)
    # Strip DETAILS markers for PDF (content renders inline, markers invisible)
    pdf_markdown = markdown_content.replace("<!-- DETAILS_START: Methodology & Scoring Details -->\n\n", "")
    pdf_markdown = pdf_markdown.replace("\n<!-- DETAILS_END -->\n", "")
    estimated_height = max(210, 50 + pdf_markdown.count('\n') * 6.5)
    pdf.add_section(Section(pdf_markdown, paper_size=(297, estimated_height)), user_css=table_css)
    pdf.save(str(pdf_path))

    print("Converting report to HTML...")
    html_content = _render_html_report(markdown_content, table_css)
    html_path.write_text(html_content, encoding="utf-8")

    print(f"\n✅ Report saved:")
    print(f"   → HTML: {html_path.name} (opened)")
    print(f"   → PDF:  {pdf_path.name}")

    try:
        webbrowser.open(html_path.as_uri())
    except Exception as e:
        print(f"⚠️ Could not auto-open the HTML report: {e}")
        try:
            os.startfile(str(pdf_path.absolute()))
        except Exception:
            pass

if __name__ == "__main__":
    generate_privacy_report()
