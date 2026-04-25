import platform
import os
import sys

# Bypass Python 3.13 Windows WMI hang in platform.machine() called by pandas
platform.machine = lambda: os.environ.get("PROCESSOR_ARCHITECTURE", "AMD64")

import io
import re
import webbrowser
from pathlib import Path
import pandas as pd
import parser


def consolidate_history():
    """Merges all history CSVs into one clean, deduplicated file for repo hygiene."""
    data_dir = Path("Drop_Financial_Info_Here")
    history_files = list(data_dir.glob("Accounts_History*.csv"))

    # Filter out any already consolidated files to avoid recursive merging
    history_files = [f for f in history_files if "CONSOLIDATED" not in f.name]

    if len(history_files) < 2:
        print("\n[!] Nothing to consolidate. Found fewer than 2 history files.")
        return

    print(f"\n-> Consolidating {len(history_files)} history files...")
    all_dfs = []
    for f in history_files:
        try:
            df = parser.load_fidelity_history(f)
            if not df.empty:
                all_dfs.append(df)
        except Exception as e:
            print(f"    [!] Error loading {f.name}: {e}")

    if not all_dfs:
        print("    [!] No valid records found to consolidate.")
        return

    merged_df = pd.concat(all_dfs, ignore_index=True)

    # Deduplicate: exact same record across multiple files is common in Fidelity downloads
    before_count = len(merged_df)
    merged_df = merged_df.drop_duplicates()
    after_count = len(merged_df)

    # Sort by Date descending (newest first)
    merged_df = merged_df.sort_values(by="Date", ascending=False)

    # Calculate actual date range for the filename
    oldest_str = merged_df["Date"].min().strftime("%Y-%m-%d")
    newest_str = merged_df["Date"].max().strftime("%Y-%m-%d")
    output_filename = f"Accounts_History_CONSOLIDATED_{oldest_str}_to_{newest_str}.csv"
    output_path = data_dir / output_filename

    # We save in the canonical format
    merged_df.to_csv(output_path, index=False)

    print(f"✅ Created {output_filename}")
    print(f"   Reduced {before_count} records to {after_count} unique transactions.")

    # Move original files to archived/ folder
    archived_dir = data_dir / "archived"
    archived_dir.mkdir(exist_ok=True)
    for f in history_files:
        dest = archived_dir / f.name
        # Handle filename collisions in archived folder
        if dest.exists():
            dest = archived_dir / f"{pd.Timestamp.now().strftime('%H%M%S')}_{f.name}"
        f.rename(dest)

    print(f"   Moved {len(history_files)} original files to {archived_dir}/")
    print("")


def check_history_status():
    """Lightweight check to report the date range of transaction history to the user."""
    data_dir = Path("Drop_Financial_Info_Here")
    history_files = list(data_dir.glob("Accounts_History*.csv"))

    if not history_files:
        print("\n[!] STATUS: No 'Accounts_History' CSV files detected.")
        print("    Your tax-loss harvesting and cost-basis analysis will be limited.")
        return

    all_dates = []
    for f in history_files:
        try:
            # Use the existing parser to ensure we handle the Fidelity format correctly
            h_df = parser.load_fidelity_history(f)
            if not h_df.empty and "Date" in h_df.columns:
                # Ensure the Date column is actually datetime objects
                dates = pd.to_datetime(h_df["Date"], errors="coerce")
                valid_dates = dates[pd.notna(dates)]
                if not valid_dates.empty:
                    all_dates.extend(valid_dates.tolist())
        except Exception:
            continue

    if all_dates:
        oldest = min(all_dates)
        newest = max(all_dates)
        print(f"\n>>> CURRENT HISTORY RANGE: {oldest.strftime('%Y-%m-%d')} to {newest.strftime('%Y-%m-%d')}")
        print(f">>> Action: Ensure you have reports covering both BEFORE {oldest.strftime('%Y-%m-%d')} (for old lots)")
        print(f">>>         and AFTER {newest.strftime('%Y-%m-%d')} (if you have recent activity).")

        # Suggest consolidation if multiple files are found
        raw_history_files = [f for f in history_files if "CONSOLIDATED" not in f.name]
        if len(raw_history_files) > 1:
            print(f"\n[TIP] You have {len(raw_history_files)} separate history files.")
            print("      To merge them for cleaner repo hygiene, use: py src/portfolio_analyzer.py --consolidate\n")
    else:
        print("\n[!] STATUS: History files found, but no valid transaction dates could be parsed.")


if __name__ == "__main__":
    import argparse

    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--check-history", action="store_true", help="Only check history coverage and exit")
    arg_parser.add_argument("--consolidate", action="store_true", help="Merge and archive all history CSVs")
    args, unknown = arg_parser.parse_known_args()

    if args.consolidate:
        consolidate_history()
        sys.exit(0)

    if args.check_history:
        check_history_status()
        sys.exit(0)

print("-> Loading market_data and yfinance...", flush=True)
import market_data
import metrics

import validator
import file_ingestor
from parsers import fidelity as k401_parser

print("-> Loading PDF generator...", flush=True)
from markdown_pdf import Section, MarkdownPdf
import markdown as md_lib

print("-> All modules loaded successfully!", flush=True)

# --- Configuration Constants ---

# --- Routing Logic Constants ---
# Whitelist: Hardcoded benchmarks that always route to specific buckets, overriding all math.
ROUTING_WHITELIST = {
    # Taxable Brokerage (Broad Market / Lower Vol)
    "VTI": "Taxable Brokerage",
    "VOO": "Taxable Brokerage",
    "ITOT": "Taxable Brokerage",
    "IVV": "Taxable Brokerage",
    "SPLG": "Taxable Brokerage",
    "SCHX": "Taxable Brokerage",
    "VT": "Taxable Brokerage",
    "Vanguard Total Stock Market": "Taxable Brokerage",
    # Roth IRA (High Growth / Aggressive Tech)
    "QQQ": "Roth IRA",
    "QQQM": "Roth IRA",
    "VGT": "Roth IRA",
    "FTEC": "Roth IRA",
    "VUG": "Roth IRA",
    "SCHG": "Roth IRA",
    "IWF": "Roth IRA",
    "MGK": "Roth IRA",
    # Tax-Deferred (Dividend Income / High Yield)
    "SCHD": "Tax-Deferred",
    "VYM": "Tax-Deferred",
    "VIG": "Tax-Deferred",
    "DGRO": "Tax-Deferred",
    "SPYD": "Tax-Deferred",
    "HDV": "Tax-Deferred",
    "FDVV": "Tax-Deferred",
}

# Joint Brokerage Anchors: Specific growth funds for the 3-5 year joint strategy.
# These bypass the 'High Beta -> Roth IRA' rule when held in the Joint Account.
JOINT_BROKERAGE_ANCHORS = {"VOO", "SCHG", "VBR", "VXUS"}

# Category Anchors: Direct mapping of Morningstar/Yahoo categories to buckets.
ROUTING_CATEGORY_ANCHORS = {
    "Large Blend": "Taxable Brokerage",
    "Large Value": "Taxable Brokerage",
    "Technology": "Roth IRA",
    "Large Growth": "Roth IRA",
    "Small Growth": "Roth IRA",
    "Health": "Roth IRA",
    "Financial": "Tax-Deferred",  # High dividends usually
    "Equity Energy": "Tax-Deferred",  # High dividends usually
}

ACCOUNT_TYPE_MAP = {
    "INDIVIDUAL": "Taxable Brokerage",
    "Joint Brokerage": "Taxable Brokerage",  # Added for Pia & Wes Strategy
    "Melissa Investments": "Taxable Brokerage",
    "ROTH IRA": "Roth IRA",
    "Health Savings Account": "HSA",
    "401k": "Employer 401k",
}

SUBSTANTIALLY_IDENTICAL_MAP = {
    "FTEC": "US Tech",
    "XLK": "US Tech",
    "VGT": "US Tech",
    "FNILX": "Large Cap Comp",
    "FNCMX": "Large Cap Comp",
    "ONEQ": "Large Cap Comp",
    "FELG": "Large Cap Growth",
    "QQQ": "Large Cap Growth",
    "SPYG": "Large Cap Growth",
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
    held_in = main_df[main_df["Symbol"].isin(identical_symbols)]
    accounts = held_in["Account Name"].dropna().unique()
    return len(accounts) > 1


DE_MINIMIS_GAIN_PCT = 0.01  # 1% of lot value — gains below this are safe to reallocate

# --- 401k Glide Path Constants ---
GLIDE_PATH = [
    (40, 0.90),  # 40+ yrs out: 90% equity
    (25, 0.80),  # 25 yrs: 80%
    (10, 0.60),  # 10 yrs: 60%
    (0, 0.50),  # At retirement: 50%
    (-7, 0.30),  # 7 yrs past: 30%
]
EQUITY_SPLIT = {"US Equity": 0.70, "Intl Equity": 0.30}
DEFAULT_BIRTH_YEAR = 1990
DEFAULT_RETIREMENT_YEAR = 2057
MIN_ALLOCATION_PCT = 5

# --- Risk Tolerance ---
RISK_LEVELS = ["very_conservative", "conservative", "moderate", "aggressive", "very_aggressive"]
RISK_LEVEL_WEIGHTS = {
    "very_aggressive": {"score": 0.95, "stability": 0.05},
    "aggressive": {"score": 0.75, "stability": 0.25},
    "moderate": {"score": 0.50, "stability": 0.50},
    "conservative": {"score": 0.35, "stability": 0.65},
    "very_conservative": {"score": 0.20, "stability": 0.80},
}


def compute_auto_risk_tolerance(years_to_retirement: int) -> str:
    """Auto-calculate risk tolerance from years to retirement."""
    if years_to_retirement >= 30:
        return "very_aggressive"
    elif years_to_retirement >= 20:
        return "aggressive"
    elif years_to_retirement >= 10:
        return "moderate"
    elif years_to_retirement >= 3:
        return "conservative"
    else:
        return "very_conservative"


# --- Asset Routing ---
def classify_asset_routing(ticker: str, yld: float, beta: float, account_name: str = None) -> str:
    """
    Stable 4-Bucket Tax Location Routing Engine.
    Uses a priority-based tiered system to ensure routing is less susceptible to market fluctuations.

    Priority order:
    1. Account-Specific Anchors (e.g. Joint Brokerage Strategy)
    2. Golden Whitelist (Hardcoded benchmarks)
    3. High Yield (>= 2.5%) -> Tax-Deferred (401k/HSA)
    4. Structural Category (e.g. Technology -> Roth IRA)
    5. High Growth (Beta >= 1.10) -> Roth IRA
    6. Default -> Taxable Brokerage
    """
    ticker_up = ticker.upper()

    # Tier 1: Account-Specific Anchors
    if account_name and "Joint" in account_name and ticker_up in JOINT_BROKERAGE_ANCHORS:
        return "Taxable Brokerage"

    # Tier 2: Golden Whitelist (The "Benchmarks")
    if ticker_up in ROUTING_WHITELIST:
        return ROUTING_WHITELIST[ticker_up]

    # Tier 3: High Yield (>= 2.5%) -> Tax-Deferred
    # We increased this from 2.0% to 2.5% to prioritize growth in Roth.
    if yld >= 0.025:
        return "Tax-Deferred"

    # Tier 3: Structural Category Anchors
    # We use the fund's intrinsic classification where possible.
    try:
        info = metrics._get_ticker_info(ticker)
        category = info.get("category")
        if category in ROUTING_CATEGORY_ANCHORS:
            return ROUTING_CATEGORY_ANCHORS[category]
    except Exception:
        pass

    # Tier 4: Growth/Volatility Tier (The "Dead Zone" Filter)
    # Threshold increased from 1.0 to 1.10 to ensure common market funds (Beta ~1.02)
    # stay in Taxable, reserving Roth for clear "High-Beta" winners.
    if yld < 0.025 and beta >= 1.10:
        return "Roth IRA"

    # Tier 5: Fallback — Broad market / Moderate growth -> Taxable Brokerage
    return "Taxable Brokerage"


def resolve_account_type(account_name: str) -> str:
    """Maps a Fidelity CSV Account Name to a routing bucket."""
    return ACCOUNT_TYPE_MAP.get(account_name, "Taxable Brokerage")


def _generate_profile_template(profile_path: Path):
    """Auto-generate a fully commented investor_profile.txt template."""
    template = """\
# Investor Profile for Portfolio Optimizer
# Uncomment and set values below. All fields are optional.

# Required — age-aware scoring and glide-path allocation
# birth_year = 1985
# retirement_year = 2050

# Risk tolerance (choose one):
#   very_aggressive  — Maximum growth, highest volatility tolerance
#   aggressive       — Growth-focused, comfortable with significant drawdowns
#   moderate         — Balanced growth and stability
#   conservative     — Stability-focused, limited drawdown tolerance
#   very_conservative — Capital preservation priority, minimal volatility
# If omitted, auto-calculated from years to retirement.
# risk_tolerance = moderate

# State (2-letter code) for tax impact estimates.
# If skipped, estimates use federal rates only (no state tax applied).
# state = CA

# Per-account contribution amounts (dollars to deploy).
# Default: $0 (auto-detected from core/money-market positions in your CSV).
# Only set these if you want to override the auto-detected amounts.
# roth_ira_contribution = 7000
# taxable_contribution = 50000
# hsa_contribution = 4150
# 401k_contribution = 23000
"""
    profile_path.write_text(template, encoding="utf-8")


def load_investor_profile(data_dir: Path) -> dict:
    """
    Parses investor_profile.txt from data_dir.
    Returns dict with keys: birth_year, retirement_year, using_defaults,
    risk_tolerance, risk_tolerance_auto, state, contributions.
    Falls back to defaults if file is missing or malformed.
    Auto-generates template on first run.
    """
    profile_path = data_dir / "investor_profile.txt"
    profile = {
        "birth_year": DEFAULT_BIRTH_YEAR,
        "retirement_year": DEFAULT_RETIREMENT_YEAR,
        "using_defaults": True,
        "risk_tolerance": None,  # User-specified; None = use auto
        "risk_tolerance_auto": None,  # Always computed from age
        "state": None,
        "roth_ira_contribution": None,
        "taxable_contribution": None,
        "hsa_contribution": None,
        "401k_contribution": None,
    }

    if not profile_path.exists():
        _generate_profile_template(profile_path)
        return profile

    # Contribution field mapping
    CONTRIBUTION_KEYS = {
        "roth_ira_contribution",
        "taxable_contribution",
        "hsa_contribution",
        "401k_contribution",
    }

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
                    profile["birth_year"] = int(val)
                    profile["using_defaults"] = False
                elif key == "retirement_year":
                    profile["retirement_year"] = int(val)
                    profile["using_defaults"] = False
                elif key == "risk_tolerance" and val.lower() in RISK_LEVELS:
                    profile["risk_tolerance"] = val.lower()
                elif key == "state" and len(val) == 2:
                    profile["state"] = val.upper()
                elif key in CONTRIBUTION_KEYS:
                    try:
                        profile[key] = float(val.replace(",", "").replace("$", ""))
                    except ValueError:
                        pass
    except Exception:
        pass  # Fall back to defaults on any error

    # Always compute auto risk tolerance for display comparison
    current_year = pd.Timestamp.now().year
    ytr = profile["retirement_year"] - current_year
    profile["risk_tolerance_auto"] = compute_auto_risk_tolerance(ytr)

    # If user didn't specify, use auto
    if profile["risk_tolerance"] is None:
        profile["risk_tolerance"] = profile["risk_tolerance_auto"]

    return profile


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


def score_candidate(
    ticker: str, data: dict, routing_bucket: str, years_to_retirement: int = None, risk_tolerance: str = "moderate"
) -> dict:
    """
    Scores a candidate fund using per-account metrics.
    When years_to_retirement is provided, weights shift based on age_factor
    (0.0 = at retirement, 1.0 = 40+ years out).
    risk_tolerance blends raw score with stability score per RISK_LEVEL_WEIGHTS.
    Returns the candidate dict augmented with 'score', 'raw_score', 'stability_score'.
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
            score *= 1 - penalty

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
            # Net-of-Fees: 50 (young) → 25 (near-retirement)
            # Increased from 40 to 50 for young investors to prioritize raw growth (maximize preference)
            w_nof = 25 + af * 25
            # Sharpe: 20 (young) → 45 (near-retirement)
            # Decreased from 30 to 20 for young to favor higher returns, keeping it as a quality floor
            w_sharpe = 45 - af * 25
            score = (nof * w_nof) + (sharpe * w_sharpe) + (te_penalty * 10)
        else:
            score = (nof * 45) + (sharpe * 30) + (te_penalty * 10)
        data.update({"sharpe_ratio": sharpe, "tracking_error": te})

        # Bond duration penalty: near retirement, prefer shorter duration (less rate sensitivity)
        if af is not None and af < 0.3:
            bond_dur = data.get("bond_duration")
            if bond_dur is not None and bond_dur > 5.0:
                duration_penalty = min(0.10, (bond_dur - 5.0) * 0.02)
                score *= 1 - duration_penalty

    else:
        score = nof * 100

    # Morningstar tiebreaker: small bonus for highly-rated funds (all buckets)
    ms_rating = data.get("morningstar_rating")
    if ms_rating is not None and ms_rating >= 4:
        score *= 1 + (ms_rating - 3) * 0.025  # +2.5% for 4★, +5% for 5★

    # Risk-tolerance blending: blend raw score with stability score
    raw_score = round(score, 4)
    stability = metrics.compute_stability_score(ticker)
    weights = RISK_LEVEL_WEIGHTS.get(risk_tolerance, RISK_LEVEL_WEIGHTS["moderate"])
    blended = score * weights["score"] + (stability if stability is not None else 50) * weights["stability"]

    data["raw_score"] = raw_score
    data["stability_score"] = stability
    data["score"] = round(blended, 4)
    data["net_of_fees_5y"] = nof
    return data


# --- Core Position Detection & Allocation Engine ---

# Tickers recognized as core/cash/money-market positions
CORE_POSITION_TICKERS = {"FCASH", "CORE", "CASH", "SPAXX", "FDRXX", "FDLXX"}

# Map investor_profile contribution keys to account type names
CONTRIBUTION_KEY_MAP = {
    "roth_ira_contribution": "Roth IRA",
    "taxable_contribution": "Taxable Brokerage",
    "hsa_contribution": "HSA",
    "401k_contribution": "Employer 401k",
}


def detect_core_positions(df: pd.DataFrame) -> dict:
    """
    Detect money-market/cash core positions in each account.
    Returns {account_name: {"ticker": str, "value": float}}.
    """
    cores = {}
    for _, row in df.iterrows():
        sym = str(row.get("Symbol", "")).strip().upper()
        acct = row.get("Account Name", "Unknown Account")
        val = row.get("Current Value", 0.0)
        if sym in CORE_POSITION_TICKERS or metrics.classify_asset_class(sym) == "Stable Value":
            if acct not in cores:
                cores[acct] = {"ticker": sym, "value": 0.0}
            cores[acct]["value"] += val
    return cores


def get_contribution_amounts(df: pd.DataFrame, investor_profile: dict) -> dict:
    """
    Returns {account_name: dollar_amount} for each specific account with deployable cash.
    Uses investor_profile manual overrides mapped to account type,
    but defaults to specific account-level core positions.
    """
    core_positions = detect_core_positions(df)

    # Use specific account names as keys
    auto_amounts = {acct: info["value"] for acct, info in core_positions.items()}

    # If investor profile has a contribution for an account TYPE,
    # we apply it to the first matching account of that type.
    result = dict(auto_amounts)

    # Check for manual overrides from investor_profile (which are currently by Account Type)
    # We apply these to the FIRST account name that matches the type.
    acct_to_type = {name: resolve_account_type(name) for name in df["Account Name"].dropna().unique()}

    for profile_key, target_type in CONTRIBUTION_KEY_MAP.items():
        manual_val = investor_profile.get(profile_key)
        if manual_val is not None:
            # Find the first account name that matches this type
            matching_accts = [name for name, typ in acct_to_type.items() if typ == target_type]
            if matching_accts:
                result[matching_accts[0]] = manual_val

    return result


def compute_allocation(candidates: list, min_pct: float = 5.0, max_funds: int = 5) -> list:
    """
    Score-weighted proportional allocation with minimum floor.
    Takes top max_funds candidates, assigns score-weighted %, applies floor, normalizes to 100%.
    Returns list of dicts with 'alloc_pct' added.
    """
    if not candidates:
        return []

    top = sorted(candidates, key=lambda x: x.get("score", 0), reverse=True)[:max_funds]
    total_score = sum(c.get("score", 0) for c in top) or 1.0

    for c in top:
        c["raw_alloc_pct"] = max((c.get("score", 0) / total_score) * 100, min_pct)

    total_raw = sum(c["raw_alloc_pct"] for c in top) or 100.0
    for c in top:
        c["alloc_pct"] = round(c["raw_alloc_pct"] / total_raw * 100, 1)

    # Ensure sum is exactly 100.0% by adjusting the largest allocation
    current_sum = sum(c["alloc_pct"] for c in top)
    if top and current_sum != 100.0:
        diff = round(100.0 - current_sum, 1)
        # Find index of the largest allocation to absorb the difference
        largest_idx = 0
        max_val = -1.0
        for i, c in enumerate(top):
            if c["alloc_pct"] > max_val:
                max_val = c["alloc_pct"]
                largest_idx = i
        top[largest_idx]["alloc_pct"] = round(top[largest_idx]["alloc_pct"] + diff, 1)

    return top


# --- New Report Sections ---


def _render_current_holdings_table(account_name: str, df: pd.DataFrame, metadata: dict, age_factor: float) -> str:
    """Renders the current holdings table for a specific account."""
    acct_df = df[df["Account Name"] == account_name]
    if acct_df.empty:
        return ""

    lines = [f"#### Current Holdings: {account_name}\n\n"]
    lines.append("| Symbol | Description | Current ER | Cat Avg | Rating | Suggested Action |\n")
    lines.append("|---|---|---|---|---|---|\n")

    for _, row in acct_df.iterrows():
        sym = row.get("Symbol", "")
        desc = row.get("Description", "")
        er = row.get("Expense Ratio")
        action = row.get("Action", "Keep")
        action += _get_age_flag_text(row, age_factor, metadata)
        er_str = f"{er:.3f}%" if pd.notna(er) else "N/A"
        md_info = metadata.get(sym, {})
        cat_avg = md_info.get("category_avg_er")
        cat_avg_str = f"{cat_avg:.3f}%" if cat_avg is not None else "--"
        ms = md_info.get("morningstar_rating")
        ms_str = "★" * ms if ms is not None else "--"
        lines.append(f"| {sym} | {desc} | {er_str} | {cat_avg_str} | {ms_str} | {action} |\n")
    lines.append("\n")
    return "".join(lines)


def _render_rebalance_tables(
    account_name: str, account_type: str, df: pd.DataFrame, alloc: list, cash_available: float, metadata: dict
) -> str:
    """Renders the Target Allocation and Consolidation tables for a specific account."""
    lines = []

    # Strategy Note
    if account_type in ("Roth IRA", "HSA"):
        lines.append(
            f"> **Aggressive Growth Strategy:** To maximize long-term returns in this tax-free account, we recommend consolidating your entire {account_type} balance into the top 5 high-Sortino funds listed below. **Action:** Sell all funds marked '🔴 Sell' in the second table and re-distribute 100% of the account value according to these target percentages.\n\n"
        )
    else:
        lines.append(
            "> **Tax-Efficient Growth Strategy:** This taxable account prioritizes growth with low annual tax drag. Use the table below to deploy available cash and consolidate underperforming holdings.\n\n"
        )

    if cash_available > 0:
        # Find core position ticker for this account
        core_positions = detect_core_positions(df)
        core_info = core_positions.get(account_name, {})
        core_label = core_info.get("ticker", "core position")
        lines.append(
            f"> Uninvested cash available in **{account_name}**: ${cash_available:,.2f} (from {core_label})\n\n"
        )
    else:
        lines.append(
            f"> No uninvested cash detected in **{account_name}**. Below are target percentages for rebalancing.\n\n"
        )

    # Determine pertinent metric for comparison
    pertinent_metric = "sortino_ratio" if account_type in ("Roth IRA", "HSA") else "sharpe_ratio"
    metric_label = "Sortino" if pertinent_metric == "sortino_ratio" else "Sharpe"

    lines.append(f"| Fund | Score | Stability | Target Alloc % | {metric_label} | Action |\n")
    lines.append("|---|---|---|---|---|---|\n")

    for c in alloc:
        ticker = c.get("ticker", "")
        score = c.get("score", 0)
        stab = c.get("stability_score")
        stab_str = f"{stab:.0f}" if stab is not None else "--"
        pct = c.get("alloc_pct", 0)
        metric_val = c.get(pertinent_metric)
        metric_str = f"{metric_val:.2f}" if metric_val is not None else "--"
        lines.append(f"| **{ticker}** | {score:.1f} | {stab_str} | {pct:.1f}% | {metric_str} | Buy |\n")
    lines.append("\n")

    # Existing holdings consolidation list
    acct_holdings = df[df["Account Name"] == account_name]
    acct_holdings = acct_holdings[~acct_holdings["Symbol"].isin(CORE_POSITION_TICKERS)]

    if not acct_holdings.empty:
        alloc_tickers = {c["ticker"] for c in alloc}
        existing_not_in_alloc = acct_holdings[~acct_holdings["Symbol"].isin(alloc_tickers)]
        if not existing_not_in_alloc.empty:
            lines.append(f"**Candidates for Consolidation in: {account_name}**\n\n")
            lines.append(f"| Holding | {metric_label} | Gap vs Best | Suggested Action |\n")
            lines.append("|---|---|---|---|\n")
            for _, row in existing_not_in_alloc.iterrows():
                sym = row.get("Symbol", "")
                if not sym or sym in CORE_POSITION_TICKERS:
                    continue
                fund_m = metrics.get_fund_metrics(sym, account_type)
                existing_metric = fund_m.get(pertinent_metric)
                existing_str = f"{existing_metric:.2f}" if existing_metric is not None else "--"

                # Compare with top recommended
                top_rec_metric = alloc[0].get(pertinent_metric)
                top_rec_ticker = alloc[0]["ticker"]

                if existing_metric is not None and top_rec_metric is not None:
                    gap = top_rec_metric - existing_metric
                    # Aggressive threshold
                    if existing_metric < top_rec_metric * 0.8 or gap > 0.3:
                        action = f"**🔴 Sell & Consolidate** into {top_rec_ticker}"
                        gap_str = f"**-{gap:.2f}**"
                    else:
                        action = "Hold (Acceptable)"
                        gap_str = f"-{gap:.2f}"
                else:
                    action = "Hold"
                    gap_str = "--"
                lines.append(f"| {sym} | {existing_str} | {gap_str} | {action} |\n")
            lines.append("\n")

    return "".join(lines)


def _render_concentration_analysis(df: pd.DataFrame, findings: list) -> str:
    """Renders the global Portfolio Concentration & Overlap section."""
    lines = ["\n## 1b. Portfolio Concentration & Overlap\n\n"]

    total_portfolio_val = df["Current Value"].sum() if "Current Value" in df.columns else 0
    agg_sectors = {}
    holdings_overlap = {}
    tickers_with_sectors = 0

    for _, row in df.iterrows():
        sym = row.get("Symbol", "")
        val = row.get("Current Value", 0)
        if pd.isna(sym) or sym in CORE_POSITION_TICKERS or str(sym).endswith("XX") or val <= 0:
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
                    holdings_overlap[held_sym] = {}
                holdings_overlap[held_sym][sym] = max(holdings_overlap[held_sym].get(sym, 0), held_pct)

    if agg_sectors and tickers_with_sectors > 0:
        sector_names = {
            "realestate": "Real Estate",
            "consumer_cyclical": "Consumer Cyclical",
            "basic_materials": "Basic Materials",
            "consumer_defensive": "Consumer Defensive",
            "technology": "Technology",
            "communication_services": "Communication Services",
            "financial_services": "Financial Services",
            "utilities": "Utilities",
            "industrials": "Industrials",
            "energy": "Energy",
            "healthcare": "Healthcare",
        }
        sorted_sectors = sorted(agg_sectors.items(), key=lambda x: x[1], reverse=True)
        lines.append("| Sector | Exposure | Status |\n")
        lines.append("|---|---|---|\n")
        concentrated = False
        for sector_key, pct in sorted_sectors:
            if pct < 0.01:
                continue
            name = sector_names.get(sector_key, sector_key.replace("_", " ").title())
            status = "⚠️ **Concentrated**" if pct > 0.40 else ("Elevated" if pct > 0.25 else "")
            if pct > 0.40:
                concentrated = True
            lines.append(f"| {name} | {pct * 100:.1f}% | {status} |\n")
        if concentrated:
            findings.append(
                {
                    "category": "concentration",
                    "text": "Portfolio has concentrated sector exposure (>40%)",
                    "section_ref": "1b",
                }
            )
        lines.append("\n")

    overlaps = {sym: funds_dict for sym, funds_dict in holdings_overlap.items() if len(funds_dict) >= 2}
    if overlaps:
        lines.append("**Holding Overlap:** The following stocks appear in multiple funds:\n\n")
        for held_sym, funds_dict in sorted(overlaps.items(), key=lambda x: len(x[1]), reverse=True)[:10]:
            fund_strs = [
                f"{t} ({p * 100:.1f}%)" for t, p in sorted(funds_dict.items(), key=lambda x: x[1], reverse=True)
            ]
            lines.append(f"- **{held_sym}** in {', '.join(fund_strs)}\n")
        lines.append("\n")
    return "".join(lines)


def _render_executive_summary(findings, df, tlh_agg, candidates_by_bucket) -> str:
    """Renders Section 0: Executive Summary with actionable bullets and a key action plan."""
    lines = ["## 0. Executive Summary\n\n"]

    # 0a. Key Action Plan (Concise Table)
    if df is not None and tlh_agg is not None and candidates_by_bucket is not None:
        lines.append("### ⚡ Immediate Execution Steps\n")
        lines.append("| Priority | Action | Account | Symbol | Impact |\n")
        lines.append("|---|---|---|---|---|\n")

        actions_found = 0

        # TLH Actions (High priority)
        for r in tlh_agg:
            if r["Est_Loss"] > 1000:
                lines.append(
                    f"| High | **Harvest Loss** | {r['Account Name']} | {r['Symbol']} | Save ~${r['Est_Loss'] * 0.24:,.0f} in taxes |\n"
                )
                actions_found += 1

        # High ER Actions
        for _, row in df.iterrows():
            sym = row.get("Symbol", "")
            er = row.get("Expense Ratio", 0)
            if er > 0.45:  # Focus on the really high ones for the summary
                account_type = resolve_account_type(row.get("Account Name", ""))
                bucket_key = {
                    "Taxable Brokerage": "taxable",
                    "Roth IRA": "roth",
                    "HSA": "hsa",
                    "Employer 401k": "k401",
                }.get(account_type, "taxable")
                bucket_cands = candidates_by_bucket.get(bucket_key, [])
                replacement = bucket_cands[0]["ticker"] if bucket_cands else "alt"
                lines.append(
                    f"| Med | **Replace (High Fees)** | {row.get('Account Name', '')} | {sym} → {replacement} | Lower fees by {(er - 0.1):.2f}% |\n"
                )
                actions_found += 1
                if actions_found >= 5:
                    break

        if actions_found == 0:
            lines.append("| — | No urgent rebalances detected | — | — | — |\n")

        lines.append("\n")

    # 0b. Narrative Bullets
    lines.append("### Key Findings\n")
    actionable = [f for f in findings if f.get("text")]
    if len(actionable) < 1:
        lines.append("- Your portfolio is well-optimized — no urgent action items detected.\n")
    for f in actionable[:5]:
        lines.append(f"- {f['text']} *(see Section {f['section_ref']})*\n")
    lines.append("\n")
    return "".join(lines)


def _render_next_steps(
    df, metadata, tlh_agg, candidates_by_bucket, age_factor, plan_menu_tickers, all_plan_scored=None
) -> str:
    """Renders Section 6: Next Steps with contextual how-to actions."""
    lines = ["## 6. Next Steps\n\n"]
    has_actions = False

    # 1. High-ER Replacements
    er_actions = []
    for _, row in df.iterrows():
        sym = row.get("Symbol", "")
        er = row.get("Expense Ratio")
        if er is not None and er > 0.40:
            account_name = row.get("Account Name", "Unknown")
            account_type = resolve_account_type(account_name)
            # Find best replacement in matching bucket
            bucket_key = {
                "Taxable Brokerage": "taxable",
                "Roth IRA": "roth",
                "HSA": "hsa",
                "Employer 401k": "k401",
            }.get(account_type, "taxable")
            bucket_cands = candidates_by_bucket.get(bucket_key, [])
            replacement = bucket_cands[0]["ticker"] if bucket_cands else "a lower-cost alternative"
            if isinstance(replacement, dict):
                replacement = replacement.get("ticker", replacement)
            tax_ctx = {"Roth IRA": "Tax-free swap", "Employer 401k": "Tax-deferred", "HSA": "Tax-free swap"}.get(
                account_type, "Check LTCG status first"
            )
            er_actions.append(
                f"- Replace **{sym}** → **{replacement}** in {account_name}. {tax_ctx}. *(See Section 4.)*\n"
            )
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
            sym = r["Symbol"]
            account = r["Account Name"]
            identical = get_substantially_identical_symbols(sym)
            wash_note = f"Watch wash-sale with {', '.join(identical - {sym})}." if len(identical) > 1 else ""
            lines.append(f"- Harvest loss on **{sym}** in {account}. {wash_note} *(See Section 3.)*\n")
        lines.append("\n")

    # 3. 401k Rebalancing
    if all_plan_scored and plan_menu_tickers:
        held_tickers_401k = set(df[df["Account Name"].str.contains("401k|401K", na=False)]["Symbol"].tolist())
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
        sym = row.get("Symbol", "")
        if pd.isna(sym) or sym == "CORE" or str(sym).endswith("XX"):
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
    sym = row.get("Symbol", "")
    if pd.isna(sym) or sym == "CORE" or str(sym).endswith("XX"):
        return ""
    account_type = resolve_account_type(row.get("Account Name", ""))
    ac = metadata.get(sym, {}).get("asset_class", "US Equity")
    beta = metadata.get(sym, {}).get("beta", 1.0) or 1.0
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
        sym = row.get("Symbol", "")
        if pd.isna(sym) or sym == "CORE" or str(sym).endswith("XX"):
            continue
        er = row.get("Expense Ratio")
        account_name = row.get("Account Name", "Unknown")
        account_type = resolve_account_type(account_name)
        er_str = f"{er:.2f}%" if pd.notna(er) else "N/A"

        # Determine verdict and plain-English why
        md_info = metadata.get(sym, {})
        if er is not None and er > 0.40:
            nof = md_info.get("net_of_fees_5y")
            if nof is not None and nof > 0.08:
                verdict = "**Evaluate**"
                why = "Mixed signal: high fees but strong recent performance"
            else:
                verdict = "**Replace**"
                why = f"Fees eroding ~{er:.2f}% of annual return vs alternatives"
        elif er is not None:
            cat_avg = md_info.get("category_avg_er")
            if cat_avg is not None and cat_avg > 0 and er > 2 * cat_avg:
                verdict = "**Evaluate**"
                why = f"ER is {er / cat_avg:.1f}x category average ({cat_avg:.2f}%)"
            else:
                verdict = "Keep"
                reasons = []
                if er < 0.10:
                    reasons.append("Low fees")
                else:
                    reasons.append("Reasonable fees")
                nof = md_info.get("net_of_fees_5y")
                if nof is not None and nof > 0.08:
                    reasons.append("strong 5Y growth")
                elif nof is not None and nof > 0.04:
                    reasons.append("solid 5Y returns")
                if md_info.get("asset_class") in ("Bond", "Stable Value"):
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
    """Converts markdown report to a self-contained HTML document with sticky sidebar TOC."""
    md_converter = md_lib.Markdown(extensions=["tables", "toc"], extension_configs={"toc": {"toc_depth": 3}})
    html_body = md_converter.convert(markdown_content)
    toc_html = getattr(md_converter, "toc", "")

    # Post-process DETAILS markers into <details><summary> tags
    html_body = re.sub(r"<!-- DETAILS_START: (.+?) -->", r"<details><summary>\1</summary>", html_body)
    html_body = html_body.replace("<!-- DETAILS_END -->", "</details>")

    # Load Water.css
    css_path = Path(__file__).parent / "water.min.css"
    water_css = css_path.read_text(encoding="utf-8") if css_path.exists() else ""

    scroll_spy_js = """
<script>
(function() {
  const tocLinks = document.querySelectorAll('.toc-sidebar a');
  const sections = Array.from(tocLinks).map(function(a) {
    var id = a.getAttribute('href');
    return id ? document.getElementById(id.slice(1)) : null;
  }).filter(Boolean);
  function updateActive() {
    var current = sections[0];
    for (var i = 0; i < sections.length; i++) {
      if (sections[i].getBoundingClientRect().top <= 100) current = sections[i];
    }
    tocLinks.forEach(function(a) {
      a.classList.toggle('active', a.getAttribute('href') === '#' + (current ? current.id : ''));
    });
  }
  window.addEventListener('scroll', updateActive);
  updateActive();
})();
</script>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Portfolio Optimization Report</title>
<style>
{water_css}
body {{ max-width: none; margin: 0; padding: 0; }}
{table_css}
table {{ table-layout: auto; }}
html {{ scroll-behavior: smooth; }}
.layout {{ display: flex; gap: 24px; max-width: 1300px; margin: 0 auto; padding: 16px; }}
.toc-sidebar {{
  position: sticky; top: 16px; align-self: flex-start;
  width: 240px; min-width: 200px; max-height: calc(100vh - 32px);
  overflow-y: auto; padding: 12px; background: var(--background-alt);
  border-radius: 6px; font-size: 0.85em; flex-shrink: 0;
}}
.toc-sidebar ul {{ list-style: none; padding-left: 12px; margin: 4px 0; }}
.toc-sidebar > ul {{ padding-left: 0; }}
.toc-sidebar li {{ margin: 2px 0; }}
.toc-sidebar a {{ text-decoration: none; display: block; padding: 2px 4px; border-radius: 3px; color: inherit; }}
.toc-sidebar a:hover {{ background: var(--background-body); }}
.toc-sidebar a.active {{ font-weight: bold; color: var(--links); background: var(--background-body); }}
.report-content {{ flex: 1; min-width: 0; max-width: 900px; }}
@media (max-width: 900px) {{
  .layout {{ flex-direction: column; padding: 8px; }}
  .toc-sidebar {{ position: static; width: 100%; max-height: none; }}
}}
</style>
</head>
<body>
<div class="layout">
  <aside class="toc-sidebar" id="toc-sidebar">
    <strong>Contents</strong>
    {toc_html}
  </aside>
  <main class="report-content">
    {html_body}
    <footer>
    <p>Generated locally by Portfolio Optimizer. No financial data was transmitted externally.</p>
    </footer>
  </main>
</div>
{scroll_spy_js}
</body>
</html>"""


# --- Report Generation ---


def generate_privacy_report(positions_path=None, history_path=None, report_path=None):
    findings = []
    print("--- PRE-FLIGHT QA CHECKS ---")
    if not validator.run_cached_preflight():
        print("\n❌ PRE-FLIGHT FAILED: Engine data is corrupted or filters are failing.")
        print("Aborting portfolio analysis to protect report integrity.")
        return
    print("--- ALL QA PASSED, BEGINNING ENGINE RUN ---\n")

    # Fetch live risk-free rate once at the start
    rf = metrics.fetch_risk_free_rate()
    print(f"Live Risk-Free Rate (^IRX): {rf * 100:.2f}%")

    data_dir = Path("Drop_Financial_Info_Here")

    if positions_path is None:
        positions_files = list(data_dir.glob("Portfolio_Positions*.csv"))
        if not positions_files:
            print("No Positions CSV found in Drop_Financial_Info_Here/")
            return
        if len(positions_files) > 1:
            print(f"❌ ERROR: Found {len(positions_files)} 'Portfolio_Positions' CSVs in Drop_Financial_Info_Here/.")
            print(
                "To guarantee data freshness, the engine requires exactly ONE positions file to serve as the single source of truth."
            )
            print("Please delete the older exports from the Drop_Financial_Info_Here/ folder.")
            return

        positions_path = positions_files[0]

    print(f"Loading {positions_path.name} locally...")
    df = parser.load_fidelity_positions(positions_path)

    # Auto-consolidate for repo hygiene if multiple history files exist
    history_files = list(data_dir.glob("Accounts_History*.csv"))
    raw_history_files = [f for f in history_files if "CONSOLIDATED" not in f.name]
    if len(raw_history_files) > 1:
        consolidate_history()

    if history_path is None:
        # Re-check history files after potential consolidation
        history_files = list(data_dir.glob("Accounts_History*.csv"))
        if not history_files:
            print("\n[!] WARNING: No 'Accounts_History' CSV files found in Drop_Financial_Info_Here/.")
            print("    Tax-Loss Harvesting and LTCG/STCG analysis will be skipped.")
            print("    Action: Download activity/history CSVs from your broker to enable full analysis.\n")
            from parsers.base import CANONICAL_HISTORY_COLS

            hist_df = pd.DataFrame(columns=CANONICAL_HISTORY_COLS)
        else:
            print(f"Loading {len(history_files)} Accounts_History CSV(s) locally...")
            hist_dfs = [parser.load_fidelity_history(f) for f in history_files]
            hist_df = pd.concat(hist_dfs, ignore_index=True)
    else:
        print(f"Loading {history_path.name} locally...")
        hist_df = parser.load_fidelity_history(history_path)

    # --- 401k Auto-Detection (via File Ingestor) ---
    plan_menu_tickers = []
    k401_plan_menu = {}
    k401_ticker_to_name = {}
    k401_files = file_ingestor.discover_401k_files(data_dir)
    k401_options_file = None

    if k401_files:
        k401_options_file = k401_files[0]  # Use highest-priority file (PDF > CSV > TXT)
        print(
            f"\n[PLAN] 401k data detected: {k401_options_file.name} (format: {file_ingestor.detect_format(k401_options_file)})"
        )
        k401_holdings_df, plan_menu_tickers, k401_plan_menu = file_ingestor.ingest_401k_file(k401_options_file)

        # Build reverse map for display in report
        if k401_plan_menu:
            k401_ticker_to_name = {v: k for k, v in k401_plan_menu.items()}

        if not k401_holdings_df.empty:
            # Merge 401k holdings into the main DataFrame
            k401_holdings_df["Description"] = k401_holdings_df["Fund Name"]
            k401_holdings_df["Quantity"] = 0
            k401_holdings_df["Expense Ratio"] = 0.0
            k401_holdings_df["Last Price"] = 0.0
            df = pd.concat([df, k401_holdings_df], ignore_index=True)
            print(f"   Merged {len(k401_holdings_df)} 401k holdings into the main portfolio.")
    else:
        # Fallback: check for legacy extracted text files
        k401_options_file_legacy = k401_parser.find_401k_options_file(data_dir)
        if k401_options_file_legacy:
            k401_holdings_df, plan_menu_tickers, k401_plan_menu = k401_parser.parse_401k_options_file(
                k401_options_file_legacy
            )
            if k401_plan_menu:
                k401_ticker_to_name = {v: k for k, v in k401_plan_menu.items()}
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
                k401_holdings_df["Description"] = k401_holdings_df["Fund Name"]
                k401_holdings_df["Quantity"] = 0
                k401_holdings_df["Expense Ratio"] = 0.0
                k401_holdings_df["Last Price"] = 0.0
                df = pd.concat([df, k401_holdings_df], ignore_index=True)
                print(f"   Merged {len(k401_holdings_df)} 401k holdings into the main portfolio.")
        else:
            print("\nℹ️  No 401k data found. 401k analysis will be skipped.")
            print("   To include 401k: drop a PDF, CSV, or extracted text file with '401k' in the filename.")

    # --- Investor Profile ---
    investor_profile = load_investor_profile(data_dir)
    birth_year = investor_profile["birth_year"]
    retirement_year = investor_profile["retirement_year"]
    using_profile_defaults = investor_profile["using_defaults"]
    risk_tolerance = investor_profile["risk_tolerance"]
    current_year = pd.Timestamp.now().year
    years_to_retirement = retirement_year - current_year
    age_factor = compute_age_factor(years_to_retirement)
    target_alloc = compute_target_allocation(years_to_retirement)
    if using_profile_defaults:
        print(
            f"[INFO] No investor_profile.txt found — using defaults (born {birth_year}, retiring {retirement_year}, {years_to_retirement} yrs out)."
        )
    else:
        risk_src = (
            "auto"
            if investor_profile["risk_tolerance"] == investor_profile["risk_tolerance_auto"]
            else f"override, auto={investor_profile['risk_tolerance_auto']}"
        )
        state_str = f", state={investor_profile['state']}" if investor_profile.get("state") else ""
        print(
            f"[PROFILE] Investor profile loaded: born {birth_year}, retiring {retirement_year} ({years_to_retirement} yrs), risk={risk_tolerance} ({risk_src}){state_str}."
        )

    # 1. Extract unique tickers and fetch Market Data
    symbols = df["Symbol"].dropna().unique().tolist()
    print(f"Fetching market metadata securely for {len(symbols)} unique tickers...")
    metadata = market_data.fetch_ticker_metadata(symbols)

    print("Unrolling tax lots to perform LTCG/STCG and Tax-Loss Harvesting analysis...")
    lots_df = parser.unroll_tax_lots(df, hist_df, metadata=metadata)

    # Report history coverage for actionable guidance
    if hist_df is None or hist_df.empty:
        print("\n[!] CRITICAL GAP: No transaction history loaded.")
        print("    The optimizer cannot determine when your assets were purchased.")
        print("    To fix: Download your broker's 'Activity/History' CSV and place it in the drop folder.\n")
        # Add to report findings
        findings.append(
            {
                "category": "history_gap",
                "text": "**Critical History Gap:** No transaction history loaded. Tax-Loss Harvesting and LTCG/STCG logic is disabled.",
                "section_ref": 3,
            }
        )
    else:
        oldest_hist = hist_df["Date"].min()
        if pd.notna(oldest_hist):
            missing_lots = lots_df[lots_df["Purchase Date"].isna()]
            # Filter out 401k/HSA/Cash from 'missing' warnings as they often lack detailed history in this tool
            warn_lots = missing_lots[~missing_lots["Account Name"].str.contains("401k|HSA|Cash", case=False, na=False)]

            if not warn_lots.empty:
                total_val = lots_df["Current Value"].sum()
                missing_val = warn_lots["Current Value"].sum()
                pct_missing = (missing_val / total_val * 100) if total_val > 0 else 0

                if pct_missing > 0.5:  # Report if more than 0.5% is missing
                    print(
                        f"\n[!] HISTORY GAP: {pct_missing:.1f}% of your portfolio value is missing 'Buy' transaction dates."
                    )
                    print(
                        f"    Current history ends at {oldest_hist.strftime('%Y-%m-%d')}. Download earlier reports to fix this."
                    )

                    # Group by account to be specific
                    missing_by_acct = warn_lots.groupby("Account Name")["Quantity"].count()
                    if not missing_by_acct.empty:
                        acct_list = ", ".join(missing_by_acct.index[:3])
                        print(f"    Gaps found in: {acct_list}\n")

                    # Add to report findings
                    findings.append(
                        {
                            "category": "history_gap",
                            "text": f"**History Gap:** {pct_missing:.1f}% of portfolio missing transaction history (current data goes back to {oldest_hist.strftime('%Y-%m-%d')})",
                            "section_ref": 3,
                        }
                    )

    # Calculate Holding Periods
    today = pd.to_datetime("today")
    lots_df["Holding_Days"] = (today - lots_df["Purchase Date"]).dt.days
    lots_df["Tax_Category"] = lots_df["Holding_Days"].apply(
        lambda x: "LTCG (>1yr)" if pd.notna(x) and x > 365 else ("STCG (<1yr)" if pd.notna(x) else "Unknown")
    )

    # 2. Combine portfolio data with market data
    df["Expense Ratio"] = df["Symbol"].map(lambda x: metadata.get(x, {}).get("expense_ratio_pct"))
    df["Yield"] = df["Symbol"].map(lambda x: metadata.get(x, {}).get("yield", 0.0))
    df["Type"] = df["Symbol"].map(lambda x: metadata.get(x, {}).get("type", "UNKNOWN"))

    # We only use Current Value to calculate weighted averages, but NEVER print it to stdout.
    df["Current Value"].sum()

    # Calculate Weighted Average Expense Ratio (exclude positions with no ER data)
    df_er = df[df["Expense Ratio"].notna()].copy()
    er_total_value = df_er["Current Value"].sum()
    if er_total_value > 0:
        df_er["Value_Weight"] = df_er["Current Value"] / er_total_value
        df_er["Weighted_ER"] = df_er["Expense Ratio"] * df_er["Value_Weight"]
        portfolio_weighted_er = df_er["Weighted_ER"].sum()
    else:
        portfolio_weighted_er = 0.0

    # Calculate Global Portfolio Equity Percentage
    equity_assets = df[df["Type"].isin(["ETF", "MUTUALFUND", "STOCK"])].copy()
    portfolio_equity_pct = (
        (equity_assets["Current Value"].sum() / df["Current Value"].sum() * 100) if df["Current Value"].sum() > 0 else 0
    )
    target_equity_pct = target_alloc.get("US Equity", 0) + target_alloc.get("Intl Equity", 0)
    risk_status = "Appropriate Risk"
    if portfolio_equity_pct > target_equity_pct + 15:
        risk_status = "🔴 Aggressive (High Equity)"
    elif portfolio_equity_pct < target_equity_pct - 15:
        risk_status = "🟡 Conservative (Low Equity)"

    # --- 4. SECURE CANDIDATE SCORING ---
    print("Scoring potential alternative funds for optimization...")
    taxable_universe = ["VTI", "VOO", "ITOT", "IVV", "SPLG", "SCHX", "VT", "VXUS", "VBR"]
    roth_universe = ["QQQ", "QQQM", "VGT", "FTEC", "VUG", "SCHG", "IWF", "MGK", "SMH"]
    hsa_universe = ["VTI", "QQQ", "SCHG", "VGT", "VXUS"]

    def _score_list(universe, bucket):
        scored = []
        for t in universe:
            m_data = metadata.get(t)
            if m_data:
                # Use a copy to avoid corrupting global metadata
                cand = score_candidate(t, m_data.copy(), bucket, years_to_retirement, risk_tolerance)
                cand["ticker"] = t  # Ensure ticker is present for rebalancing logic
                scored.append(cand)
        return scored

    taxable_main = _score_list(taxable_universe, "Taxable Brokerage")
    roth_main = _score_list(roth_universe, "Roth IRA")
    hsa_main = _score_list(hsa_universe, "Roth IRA")

    # Score 401k Plan Menu
    all_plan_scored = []
    if plan_menu_tickers:
        all_plan_scored = _score_list(plan_menu_tickers, "Tax-Deferred")
    k401_main = all_plan_scored if all_plan_scored else taxable_main  # Fallback

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

    with io.StringIO() as f:
        f.write("# Portfolio Optimization Report\n\n")
        timestamp = pd.Timestamp.now().strftime("%B %d, %Y at %I:%M %p")
        f.write(f"**Generated on:** {timestamp}\n\n")
        f.write(
            "> **Privacy Note:** This report was generated entirely locally. Financial quantities and dollar amounts were NOT transmitted to the cloud AI.\n\n"
        )

        # --- Section 1: Portfolio Risk & Concentration ---
        f.write("## 1. Portfolio Risk & Concentration\n\n")
        f.write(f"- **Weighted Average Expense Ratio:** `{portfolio_weighted_er:.3f}%`\n")
        if portfolio_weighted_er > 0.40:
            f.write("  - ⚠️ *Warning: Your aggregate expense ratio is above the recommended 0.40% threshold.*\n")
        else:
            f.write("  - ✅ *Excellent: Your portfolio fees are highly optimized.*\n")
        f.write(f"- **Risk-Free Rate (13-Week T-Bill):** `{rf * 100:.2f}%` *(fetched live)*\n")

        f.write(
            f"\n> **Risk Profile:** Your portfolio is **{portfolio_equity_pct:.0f}% equity** (Target for your age: **{target_equity_pct:.0f}%**). *{risk_status}*\n"
        )

        # Insert Global Concentration Analysis
        f.write(_render_concentration_analysis(df, findings))

        # --- Section 2: Tax Optimization ---
        # (Content remains global as it covers multiple taxable accounts)
        f.write("\n## 2. Tax Optimization & Loss Harvesting\n")
        f.write(
            "By tracking individual lot purchase dates via FIFO accounting, we can optimize your capital gains and find harvesting opportunities.\n\n"
        )

        # Aggregate per (Symbol, Account Name) for TLH
        tlh_lots = lots_df[lots_df["Unrealized Gain"] < 0].copy()
        tlh_lots["Account Type"] = tlh_lots["Account Name"].map(resolve_account_type)
        tlh_lots = tlh_lots[tlh_lots["Account Type"] == "Taxable Brokerage"]

        tlh_agg = []
        for (symbol, account), grp in tlh_lots.groupby(["Symbol", "Account Name"]):
            est_loss = -grp["Unrealized Gain"].sum()
            desc = grp["Description"].iloc[0] if "Description" in grp.columns else ""
            tax_cats = ", ".join(grp["Tax_Category"].dropna().unique())
            tlh_agg.append(
                {
                    "Symbol": symbol,
                    "Account Name": account,
                    "Description": desc,
                    "Tax_Category": tax_cats,
                    "Est_Loss": est_loss,
                    "Lot_Count": len(grp),
                }
            )
        tlh_agg.sort(key=lambda x: x["Est_Loss"], reverse=True)

        total_harvestable = sum(r["Est_Loss"] for r in tlh_agg)
        f.write(
            f"> **Tax Snapshot:** {len(tlh_agg)} position(s) with harvestable losses totaling (${total_harvestable:,.0f})\n\n"
        )

        f.write("### 🚨 Tax-Loss Harvesting Candidates\n")
        if tlh_agg:
            f.write(
                "| Priority | Account | Symbol | Tax Category | Est. Loss ($) | Est. Tax Savings | Wash Sale Risk |\n"
            )
            f.write("|---|---|---|---|---|---|---|\n")
            for r in tlh_agg:
                prio = "1 (High)" if r["Est_Loss"] > 3000 else ("2 (Med)" if r["Est_Loss"] > 1000 else "3 (Low)")
                risk = "⚠️ YES" if detect_wash_sale_risk(df, r["Symbol"]) else "No"
                f.write(
                    f"| {prio} | {r['Account Name']} | **{r['Symbol']}** | {r['Tax_Category']} | (${r['Est_Loss']:,.0f}) | ${r['Est_Loss'] * 0.24:,.0f} | {risk} |\n"
                )
        else:
            f.write("*No harvestable losses detected in taxable accounts.*\n")

        # --- Section 3: Account-Specific Analysis ---
        f.write("\n## 3. Detailed Account Analysis & Action Plans\n")
        f.write(
            "This section breaks down your individual accounts. Each sub-section contains your current holdings, the target allocation for that account type, and a specific list of funds to sell or consolidate.\n\n"
        )

        contribution_amounts = get_contribution_amounts(df, investor_profile)
        all_accounts = sorted(df["Account Name"].dropna().unique())

        for idx, acct_name in enumerate(all_accounts, 1):
            acct_type = resolve_account_type(acct_name)
            f.write(f"### 3.{idx} Account Analysis: {acct_name}\n\n")

            # 1. Current Holdings for THIS account
            f.write(_render_current_holdings_table(acct_name, df, metadata, age_factor))

            # 2. Rebalancing & Target Allocation for THIS account
            if acct_type == "Employer 401k":
                # Special 401k Logic (moved from section 5)
                k401_df = df[df["Account Name"] == acct_name].copy()
                if not k401_df.empty and all_plan_scored:
                    f.write("#### Recommended 401k Allocation\n")
                    f.write(
                        f"> **Strategy:** Maximize growth within your employer's specific fund menu. Your target split is {target_equity_pct:.0f}% Equity / {100 - target_equity_pct:.0f}% Bond.\n\n"
                    )

                    # (Insert the 401k-specific table logic here - simplified for this replace call)
                    f.write("| Ticker | Fund Name | Current % | Target % | Action |\n")
                    f.write("|---|---|---|---|---|\n")
                    held_pcts = {
                        r["Symbol"]: (r["Current Value"] / k401_df["Current Value"].sum() * 100)
                        for _, r in k401_df.iterrows()
                    }
                    alloc_rows = compute_allocation(all_plan_scored, min_pct=MIN_ALLOCATION_PCT, max_funds=5)
                    for r in sorted(alloc_rows, key=lambda x: x["alloc_pct"], reverse=True):
                        cur = held_pcts.get(r["ticker"], 0.0)
                        # Use original name from plan menu if available
                        display_name = k401_ticker_to_name.get(r["ticker"], r.get("name", r["ticker"]))
                        f.write(
                            f"| **{r['ticker']}** | {display_name} | {cur:.1f}% | {r['alloc_pct']:.1f}% | {'Buy' if cur == 0 else 'Hold'} |\n"
                        )
                    f.write("\n")
            else:
                # Standard Roth/HSA/Taxable Logic
                bucket_key = {"Roth IRA": "roth", "HSA": "hsa", "Taxable Brokerage": "taxable"}.get(
                    acct_type, "taxable"
                )
                acct_cands = {"roth": roth_main, "hsa": hsa_main, "taxable": taxable_main}.get(bucket_key, [])
                if acct_cands:
                    alloc = compute_allocation(acct_cands, min_pct=MIN_ALLOCATION_PCT, max_funds=5)
                    cash = contribution_amounts.get(acct_name, 0.0)
                    f.write(_render_rebalance_tables(acct_name, acct_type, df, alloc, cash, metadata))

        # --- Section 4: Next Steps ---
        candidates_by_bucket = {"taxable": taxable_main, "roth": roth_main, "hsa": hsa_main, "k401": k401_main}
        f.write(
            _render_next_steps(
                df, metadata, tlh_agg, candidates_by_bucket, age_factor, plan_menu_tickers, all_plan_scored
            )
        )

        # --- Section 5: Methodology & Scoring Details ---
        f.write("\n## 5. Methodology & Scoring Details\n")
        f.write(_render_verdict_table(df, metadata, age_factor))
        # (Append the rest of the methodology text here...)

        # Tier 2: Methodology & Scoring Details (collapsible in HTML)
        f.write("<!-- DETAILS_START: Methodology & Scoring Details -->\n\n")
        f.write("### How Each Metric is Used\n\n")
        f.write("| Metric | Used For | What It Measures | Interpretation |\n")
        f.write("|---|---|---|---|\n")
        f.write(
            "| **Net-of-Fees Return (5Y)** | All accounts | Annualized return after subtracting expense ratio | Higher is better. The single most important number — what you actually earned. |\n"
        )
        f.write(
            "| **Sharpe Ratio** | Taxable, 401k, HSA | Return per unit of *total* volatility (risk-adjusted) | > 1.0 is good, > 2.0 is excellent. Higher means better risk-adjusted returns. |\n"
        )
        f.write(
            "| **Sortino Ratio** | Roth IRA | Return per unit of *downside* volatility | Like Sharpe but ignores upside swings. > 1.0 is good. Ideal for growth funds. |\n"
        )
        f.write(
            "| **Max Drawdown** | Taxable, Roth IRA | Worst peak-to-trough decline over 5 years | A less negative number is better. -20% means the fund dropped 20% at its worst point. |\n"
        )
        f.write(
            "| **Tracking Error** | Taxable, 401k, HSA | How closely a fund follows its benchmark index | Lower is better for index funds. High TE means the fund deviates from what it claims to track. |\n"
        )
        f.write(
            "| **Total Return (10Y)** | Roth IRA | Cumulative total return over 10 years | Shows long-term compounding power. Marked 'Insufficient History' if fund is < 10 years old. |\n"
        )
        f.write(f"\n*Risk-free rate used for Sharpe/Sortino: **{rf * 100:.2f}%** (13-week T-Bill, fetched live)*\n")
        f.write(
            "\n*Tracking Error is computed against each fund's detected benchmark (e.g., SPY for S&P 500 funds, AGG for bond funds). If no benchmark can be detected, the metric is omitted.*\n"
        )
        f.write("\n### Per-Account Scoring Rationale\n\n")
        f.write(
            "- **Taxable Brokerage:** Prioritizes net returns + risk consistency (Sharpe) + low tax drag (low yield). Max Drawdown penalizes volatility that could trigger panic selling.\n"
        )
        f.write(
            "- **Roth IRA:** Maximizes total return using Sortino (ignores upside volatility). 10Y track record validates durable compounding. This is your most valuable tax shelter — put your biggest growers here.\n"
        )
        f.write(
            "- **Employer 401k:** Balances income generation with consistency (Sharpe). Tracking Error ensures index fund fidelity. Constrained to your employer's plan menu. Tax-deferred, so dividends compound without annual drag.\n"
        )
        f.write(
            "- **HSA:** Same scoring model as Roth IRA (Sortino + Net-of-Fees 5Y + 10Y Total Return). HSA's triple tax advantage makes long-term compounding the optimal strategy — not income generation. Full dynamic universe access, no plan-menu constraint.\n"
        )

        f.write("\n### Age-Aware Scoring Adjustments\n\n")
        if using_profile_defaults:
            f.write(
                f"*Using default investor profile (born {birth_year}, retiring {retirement_year}). Create `investor_profile.txt` to personalize.*\n\n"
            )
        else:
            f.write(
                f"*Investor profile: born {birth_year}, retiring {retirement_year} ({years_to_retirement} years to retirement, age factor: {age_factor:.2f}).*\n\n"
            )
        f.write("Scoring weights shift smoothly based on your time horizon:\n")
        f.write(
            "- **Young investors (40+ yrs out):** Higher weight on growth metrics (Net-of-Fees, Sortino, 10Y Return). Lower weight on defensive metrics (Max Drawdown).\n"
        )
        f.write(
            "- **Near-retirement (< 12 yrs out):** Higher weight on risk metrics (Sharpe, Max Drawdown). Lower weight on long-term total return. TLH urgency elevated.\n"
        )
        f.write(
            "- **Replacement candidates** receive a soft penalty (0.85x) if age-inappropriate for Roth IRA (e.g., bonds for young investors, high-beta for near-retirement).\n"
        )
        f.write("\n<!-- DETAILS_END -->\n")

        markdown_content = f.getvalue()

    # Splice Executive Summary before Section 1
    candidates_by_bucket = {
        "taxable": taxable_main,
        "roth": roth_main,
        "hsa": hsa_main,
        "k401": k401_main,
    }
    exec_summary = _render_executive_summary(findings, df, tlh_agg, candidates_by_bucket)
    insert_idx = markdown_content.find("## 1.")
    if insert_idx >= 0:
        markdown_content = markdown_content[:insert_idx] + exec_summary + markdown_content[insert_idx:]

    # 4. Save exact markdown to Drop_Financial_Info_Here/ cache
    with open(report_path, "w", encoding="utf-8") as md_file:
        md_file.write(markdown_content)

    # 5. Convert to PDF and HTML (dual output)
    timestamp_file = pd.Timestamp.now().strftime("%b-%d-%Y_%H-%M-%S")
    project_root = Path(".")
    pdf_path = project_root / f"Portfolio_Analysis_Report_{timestamp_file}.pdf"
    html_path = project_root / f"Portfolio_Analysis_Report_{timestamp_file}.html"

    print("Converting report to PDF...")
    pdf = MarkdownPdf(toc_level=2)
    # Strip DETAILS markers for PDF (content renders inline, markers invisible)
    pdf_markdown = markdown_content.replace("<!-- DETAILS_START: Methodology & Scoring Details -->\n\n", "")
    pdf_markdown = pdf_markdown.replace("\n<!-- DETAILS_END -->\n", "")
    estimated_height = max(210, 50 + pdf_markdown.count("\n") * 6.5)
    pdf.add_section(Section(pdf_markdown, paper_size=(297, estimated_height)), user_css=table_css)
    pdf.save(str(pdf_path))

    print("Converting report to HTML...")
    html_content = _render_html_report(markdown_content, table_css)
    html_path.write_text(html_content, encoding="utf-8")

    print("\n[OK] Report saved:")
    print(f"   -> HTML: {html_path.name} (opened)")
    print(f"   -> PDF:  {pdf_path.name}")

    try:
        webbrowser.open(html_path.as_uri())
    except Exception as e:
        print(f"[!] Could not auto-open the HTML report: {e}")
        try:
            os.startfile(str(pdf_path.absolute()))
        except Exception:
            pass


if __name__ == "__main__":
    generate_privacy_report()
