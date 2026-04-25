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
CORE_POSITION_TICKERS = set(market_data.KNOWN_ZERO_ER_TICKERS) | {"FCASH", "CORE", "CASH"}

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
        acct = row.get("Account Name", "")
        val = row.get("Current Value", 0.0)
        if sym in CORE_POSITION_TICKERS or metrics.classify_asset_class(sym) == "Stable Value":
            if acct not in cores:
                cores[acct] = {"ticker": sym, "value": 0.0}
            cores[acct]["value"] += val
    return cores


def get_contribution_amounts(df: pd.DataFrame, investor_profile: dict) -> dict:
    """
    Returns {account_type: dollar_amount} for each account with deployable cash.
    Uses investor_profile manual overrides first, falls back to auto-detected core positions.
    """
    core_positions = detect_core_positions(df)

    # Map core positions by account type
    auto_amounts = {}
    for acct_name, core_info in core_positions.items():
        acct_type = resolve_account_type(acct_name)
        if acct_type not in auto_amounts:
            auto_amounts[acct_type] = 0.0
        auto_amounts[acct_type] += core_info["value"]

    # Apply manual overrides from investor_profile
    result = dict(auto_amounts)
    for profile_key, acct_type in CONTRIBUTION_KEY_MAP.items():
        manual_val = investor_profile.get(profile_key)
        if manual_val is not None:
            result[acct_type] = manual_val

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

    return top


# --- New Report Sections ---


def _render_executive_summary(findings: list, df=None, tlh_agg=None, candidates_by_bucket=None) -> str:
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
            k401_holdings_df, plan_menu_tickers, k401_plan_menu = k401_parser.parse_401k_options_file(k401_options_file_legacy)
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
                    print(f"\n[!] HISTORY GAP: {pct_missing:.1f}% of your portfolio value is missing 'Buy' transaction dates.")
                    print(f"    Current history ends at {oldest_hist.strftime('%Y-%m-%d')}. Download earlier reports to fix this.")

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
        f.write(
            "> **Privacy Note:** This report was generated entirely locally. Financial quantities and dollar amounts were NOT transmitted to the cloud AI.\n\n"
        )

        # --- Section 1: High-Level Metrics ---
        f.write("## 1. High-Level Metrics\n")
        f.write(f"- **Weighted Average Expense Ratio:** `{portfolio_weighted_er:.3f}%`\n")
        if portfolio_weighted_er > 0.40:
            f.write(
                "  - ⚠️ *Warning: Your aggregate expense ratio is above the recommended 0.40% threshold for passive long-term indexing.*\n"
            )
        else:
            f.write("  - ✅ *Excellent: Your portfolio fees are highly optimized.*\n")

        # Finding: High-ER holdings (absolute + relative)
        high_er_count = (
            len(df[df["Expense Ratio"].notna() & (df["Expense Ratio"] > 0.40)]) if "Expense Ratio" in df.columns else 0
        )
        relative_er_count = 0
        for _, row in df.iterrows():
            sym = row.get("Symbol", "")
            er = row.get("Expense Ratio")
            if er is not None and er <= 0.40:
                cat_avg = metadata.get(sym, {}).get("category_avg_er")
                if cat_avg is not None and cat_avg > 0 and er > 2 * cat_avg:
                    relative_er_count += 1
        total_er_flags = high_er_count + relative_er_count
        if total_er_flags > 0:
            findings.append(
                {
                    "category": "high_er",
                    "text": f"**{total_er_flags} holding(s)** have elevated expense ratios (above 0.40% or >2x category average) — consider lower-cost alternatives",
                    "section_ref": 2,
                }
            )
        f.write(f"- **Risk-Free Rate (13-Week T-Bill):** `{rf * 100:.2f}%` *(fetched live)*\n")

        # Portfolio Risk Profile — aggregate equity % vs glide-path target
        equity_value = 0.0
        total_value_for_risk = 0.0
        for _, row in df.iterrows():
            sym = row.get("Symbol", "")
            val = row.get("Current Value", 0) or 0
            if pd.isna(sym) or sym == "CORE" or str(sym).endswith("XX"):
                continue
            total_value_for_risk += val
            ac = metadata.get(sym, {}).get("asset_class", "US Equity")
            if ac in ("US Equity", "Intl Equity"):
                equity_value += val
        portfolio_equity_pct = (equity_value / total_value_for_risk * 100) if total_value_for_risk > 0 else 0
        target_equity_pct = target_alloc["US Equity"] + target_alloc["Intl Equity"]
        risk_status = "Aligned" if abs(portfolio_equity_pct - target_equity_pct) <= 10 else "Rebalance needed"
        risk_icon = "✅" if risk_status == "Aligned" else "⚠️"
        f.write(
            f"\n> **Portfolio Risk Profile:** Your portfolio is **{portfolio_equity_pct:.0f}% equity** — target for your age is **{target_equity_pct:.0f}%**. {risk_icon} *{risk_status}*\n"
        )

        # Finding: Risk alignment
        if risk_status == "Rebalance needed":
            findings.append(
                {
                    "category": "risk",
                    "text": f"Portfolio equity allocation ({portfolio_equity_pct:.0f}%) deviates from age-based target ({target_equity_pct:.0f}%) — rebalance recommended",
                    "section_ref": 1,
                }
            )
        if using_profile_defaults:
            f.write("> *Target based on default profile. Create `investor_profile.txt` for a personalized target.*\n")

        # --- Section 2: Asset Holding Breakdown ---
        f.write("\n## 2. Asset Holding Breakdown\n")

        def get_action_for_row(row):
            sym = row.get("Symbol", "")
            er = row.get("Expense Ratio", 0.0)
            is_cash = pd.isna(sym) or sym == "CORE" or str(sym).endswith("XX")
            if is_cash:
                return "Core Cash Position"

            md_info = metadata.get(sym, {})
            flags = []

            # Net-of-fees expense evaluation (absolute threshold)
            if er is not None and er > 0.40:
                nof = md_info.get("net_of_fees_5y")
                if nof is not None:
                    flags.append(f"**Evaluate** (ER {er:.2f}%, Net 5Y: {nof * 100:.1f}%)")
                else:
                    flags.append("**Replace (High ER)**. See *Alternatives* below.")
            # Relative ER check: flag if >2x category average
            elif er is not None:
                cat_avg = md_info.get("category_avg_er")
                if cat_avg is not None and cat_avg > 0 and er > 2 * cat_avg:
                    flags.append(f"**Evaluate** (ER is {er / cat_avg:.1f}x category avg)")

            # Small fund closure risk
            net_assets = md_info.get("net_assets")
            if net_assets is not None and net_assets < 100_000_000:
                flags.append("⚠ Small fund (<$100M)")

            # Cap gains risk for taxable accounts
            account_type = resolve_account_type(row.get("Account Name", ""))
            if account_type == "Taxable Brokerage":
                cgy = md_info.get("cap_gain_yield")
                if cgy is not None and cgy > 0.05:
                    flags.append("*High cap gains risk*")

            return " | ".join(flags) if flags else "Keep"

        def get_age_flag(row, age_factor, metadata):
            """Returns italic age-appropriate flag text, or empty string."""
            sym = row.get("Symbol", "")
            if pd.isna(sym) or sym == "CORE" or str(sym).endswith("XX"):
                return ""
            account_type = resolve_account_type(row.get("Account Name", ""))
            ac = metadata.get(sym, {}).get("asset_class", "US Equity")
            beta = metadata.get(sym, {}).get("beta", 1.0) or 1.0
            # Young investor + Bond/Stable Value in Roth/HSA
            if age_factor > 0.7 and ac in ("Bond", "Stable Value") and account_type in ("Roth IRA", "HSA"):
                return " *— Consider higher-growth funds for your horizon*"
            # Near-retirement + high-beta in Taxable/Roth
            if age_factor < 0.3 and beta > 1.2 and account_type in ("Taxable Brokerage", "Roth IRA"):
                return " *— Consider lower-volatility for your horizon*"
            return ""

        df["Action"] = df.apply(get_action_for_row, axis=1)
        df["Account Name"] = df["Account Name"].fillna("Unknown Account")
        df["Account Type"] = df["Account Name"].map(resolve_account_type)
        df_sorted = df.sort_values(by=["Account Type", "Account Name", "Action", "Symbol"])

        # Group by Account Type with sub-headers; suppress 401k detail (covered in Section 5)
        section2_order = ["Taxable Brokerage", "Roth IRA", "HSA", "Employer 401k"]
        for account_type in section2_order:
            group = df_sorted[df_sorted["Account Type"] == account_type]
            if group.empty:
                continue

            f.write(f"\n### {account_type}\n")

            if account_type == "Employer 401k":
                k401_count = len(group)
                f.write(
                    f"> 📋 {k401_count} fund(s) held in your 401k. See **Section 5: 401k Plan Analysis** for detailed scoring, rebalance opportunities, and underperforming holdings.\n"
                )
                continue

            f.write("| Symbol | Account Name | Description | Current ER | Cat Avg | Rating | Suggested Action |\n")
            f.write("|---|---|---|---|---|---|---|\n")

            for idx, row in group.iterrows():
                sym = row.get("Symbol", "")
                desc = row.get("Description", "")
                account_name = row["Account Name"]
                er = row.get("Expense Ratio")
                action = row["Action"]
                if action == "Core Cash Position":
                    er = 0.0
                action += get_age_flag(row, age_factor, metadata)
                er_str = f"{er:.3f}%" if pd.notna(er) else "N/A"
                md_info = metadata.get(sym, {})
                cat_avg = md_info.get("category_avg_er")
                cat_avg_str = f"{cat_avg:.3f}%" if cat_avg is not None else "--"
                ms = md_info.get("morningstar_rating")
                ms_str = "★" * ms if ms is not None else "--"
                f.write(f"| {sym} | {account_name} | {desc} | {er_str} | {cat_avg_str} | {ms_str} | {action} |\n")

        # Finding: Age-inappropriate holdings
        age_inappropriate_count = sum(1 for _, row in df.iterrows() if _get_age_flag_text(row, age_factor, metadata))
        if age_inappropriate_count > 0:
            findings.append(
                {
                    "category": "age_inappropriate",
                    "text": f"**{age_inappropriate_count} holding(s)** may be age-inappropriate for your investment horizon",
                    "section_ref": 2,
                }
            )

        # --- Section 2a: Portfolio Concentration Analysis ---
        f.write("\n### Portfolio Concentration Analysis\n\n")

        # Aggregate sector exposure across held tickers, weighted by portfolio value
        total_portfolio_val = df["Current Value"].sum() if "Current Value" in df.columns else 0
        agg_sectors = {}
        holdings_overlap = {}  # symbol -> [(ticker, pct)]
        tickers_with_sectors = 0
        for _, row in df.iterrows():
            sym = row.get("Symbol", "")
            val = row.get("Current Value", 0)
            if pd.isna(sym) or sym == "CORE" or str(sym).endswith("XX") or val <= 0:
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
                    # Deduplicate: if the same fund is held in multiple accounts,
                    # we just want to know its weight in that fund once.
                    holdings_overlap[held_sym][sym] = max(holdings_overlap[held_sym].get(sym, 0), held_pct)

        if agg_sectors and tickers_with_sectors > 0:
            # Normalize sector names for display
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

            f.write("| Sector | Exposure | Status |\n")
            f.write("|---|---|---|\n")
            concentrated = False
            for sector_key, pct in sorted_sectors:
                if pct < 0.01:
                    continue
                name = sector_names.get(sector_key, sector_key.replace("_", " ").title())
                status = "⚠️ **Concentrated**" if pct > 0.40 else ("Elevated" if pct > 0.25 else "")
                if pct > 0.40:
                    concentrated = True
                f.write(f"| {name} | {pct * 100:.1f}% | {status} |\n")

            if concentrated:
                findings.append(
                    {
                        "category": "concentration",
                        "text": "Portfolio has concentrated sector exposure (>40% in a single sector)",
                        "section_ref": 2,
                    }
                )
            f.write("\n")
        else:
            f.write("*Sector data not available for current holdings.*\n\n")

        # Holding overlap detection
        overlaps = {sym: funds_dict for sym, funds_dict in holdings_overlap.items() if len(funds_dict) >= 2}
        if overlaps:
            f.write("**Holding Overlap:** The following stocks appear in multiple funds:\n\n")
            # Sort by number of funds and then by underlying symbol
            for held_sym, funds_dict in sorted(overlaps.items(), key=lambda x: len(x[1]), reverse=True)[:10]:
                fund_strs = [
                    f"{t} ({p * 100:.1f}%)" for t, p in sorted(funds_dict.items(), key=lambda x: x[1], reverse=True)
                ]
                f.write(f"- **{held_sym}** in {', '.join(fund_strs)}\n")
            f.write("\n")

        # --- Section 3: Tax Optimization ---
        f.write("\n## 3. Tax Optimization & Loss Harvesting\n")
        f.write(
            "By tracking individual lot purchase dates via FIFO accounting, we can optimize your short-term/long-term capital gains classification and find tax loss harvesting opportunities.\n\n"
        )

        # TLH Opportunities — taxable accounts only (401k, Roth IRA, HSA losses have no tax benefit)
        tlh_lots = lots_df[lots_df["Unrealized Gain"] < 0].copy()
        tlh_lots["Account Type"] = tlh_lots["Account Name"].map(
            lambda a: resolve_account_type(a) if pd.notna(a) else "Unknown"
        )
        tlh_lots = tlh_lots[tlh_lots["Account Type"] == "Taxable Brokerage"]

        # Aggregate per (Symbol, Account Name) before writing callout
        tlh_agg = []
        for (symbol, account), grp in tlh_lots.groupby(["Symbol", "Account Name"]):
            est_loss = -grp["Unrealized Gain"].sum()  # positive: loss magnitude
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

        # Compute STCG count for the summary callout
        prof_lots_stcg = lots_df[(lots_df["Unrealized Gain"] > 0) & (lots_df["Tax_Category"] == "STCG (<1yr)")]
        sym_to_account_type = df.set_index("Symbol")["Account Name"].map(resolve_account_type).to_dict()
        stcg_taxable = prof_lots_stcg[
            prof_lots_stcg["Symbol"].map(lambda s: sym_to_account_type.get(s, "Unknown")) == "Taxable Brokerage"
        ]
        stcg_symbol_count = stcg_taxable["Symbol"].nunique()

        # Tax Snapshot callout
        total_harvestable = sum(r["Est_Loss"] for r in tlh_agg)
        tlh_position_count = len(tlh_agg)
        f.write(
            f"> **Tax Snapshot:** {tlh_position_count} position(s) with harvestable losses totaling (${total_harvestable:,.0f}) | {stcg_symbol_count} position(s) with pending STCG exposure\n\n"
        )

        # Finding: TLH opportunities
        if tlh_position_count > 0:
            findings.append(
                {
                    "category": "tlh",
                    "text": f"**{tlh_position_count} position(s)** with harvestable tax losses available",
                    "section_ref": 3,
                }
            )
        # Finding: STCG exposure
        if stcg_symbol_count > 0:
            findings.append(
                {
                    "category": "stcg",
                    "text": f"**{stcg_symbol_count} position(s)** have short-term capital gains exposure — consider holding past 1 year",
                    "section_ref": 3,
                }
            )

        f.write("### 🚨 Tax-Loss Harvesting Candidates\n")
        if tlh_agg:
            f.write(
                "The following lots are currently held at a loss. Selling these will harvest the loss to offset your other capital gains (up to $3,000 against ordinary income).\n\n"
            )
            f.write(
                "*401k, Roth IRA, and HSA accounts are excluded — losses in tax-advantaged accounts have no tax benefit.*\n\n"
            )

            if age_factor < 0.3:
                f.write(
                    "> ⚠️ **Near-Retirement Alert:** Shorter window to utilize harvested losses — prioritize harvesting now.\n\n"
                )

            f.write(
                "| Priority | Account | Symbol | Description | Tax Category | Est. Loss ($) | Est. Tax Savings | Underwater Lots | Wash Sale Risk |\n"
            )
            f.write("|---|---|---|---|---|---|---|---|---|\n")

            # Determine urgency label based on age_factor
            if age_factor < 0.3:
                pass
            elif age_factor <= 0.6:
                pass
            else:
                pass

            for rank, row in enumerate(tlh_agg, 1):
                sym = row["Symbol"]
                account = row["Account Name"]
                desc = row["Description"]
                loss = row["Est_Loss"]
                lots = row["Lot_Count"]
                tax_cat = row["Tax_Category"]

                # Higher priority for larger losses
                if loss > 3000:
                    priority = "1 (High)"
                elif loss > 1000:
                    priority = "2 (Med)"
                else:
                    priority = "3 (Low)"

                est_savings = f"${loss * 0.24:,.0f}*"  # Assume 24% marginal bracket for estimate

                risk = detect_wash_sale_risk(df, sym)
                risk_str = "⚠️ YES (Cross-Account)" if risk else "No"
                f.write(
                    f"| {priority} | {account} | **{sym}** | {desc} | {tax_cat} | (${loss:,.0f}) | {est_savings} | {lots} lot(s) | {risk_str} |\n"
                )

            f.write(
                "\n*> Estimated savings assumes 24% marginal tax bracket. Actual savings depends on your total income and filing status.*\n"
            )
        else:
            f.write(
                "*Amazing! No assets are currently held at a loss in your taxable accounts. No TLH opportunities exist right now.*\n"
            )
            f.write(
                "\n*401k, Roth IRA, and HSA accounts are excluded — losses in tax-advantaged accounts have no tax benefit.*\n"
            )

        # Capital Gains Screener with De Minimis Override
        f.write("\n### ⏳ Capital Gains 'One-Year Wait' Screener\n")
        f.write(
            "Profitable lots held for under 365 days are subject to your ordinary income tax rate. Waiting 1 year drops this to the much lower LTCG (15-20%) bracket.\n\n"
        )
        f.write(
            f"**De Minimis Threshold:** Lots with STCG gains below **{DE_MINIMIS_GAIN_PCT * 100:.0f}% of lot value** are flagged as safe to reallocate.\n\n"
        )
        f.write("| Account Name | Symbol | Lots STCG | Lots LTCG | De Minimis (Safe to Reallocate) |\n")
        f.write("|---|---|---|---|---|\n")

        prof_lots = lots_df[lots_df["Unrealized Gain"] > 0]
        if not prof_lots.empty:
            # First map symbols to their originating account names from the main df
            sym_to_account = df.set_index("Symbol")["Account Name"].to_dict()

            screener_rows = []

            for sym in prof_lots["Symbol"].dropna().unique():
                account_name = sym_to_account.get(sym, "Unknown Account")

                # Check 1: Is this account even subject to capital gains tax?
                account_type = resolve_account_type(account_name)  # Using resolve_account_type from earlier in the code
                if account_type != "Taxable Brokerage":
                    continue  # Skip Roth IRAs, HSAs, 401ks (tax-advantaged)

                sym_lots = prof_lots[prof_lots["Symbol"] == sym]
                stcg_lots = sym_lots[sym_lots["Tax_Category"] == "STCG (<1yr)"]
                ltcg_count = len(sym_lots[sym_lots["Tax_Category"] == "LTCG (>1yr)"])

                # De minimis check: gain < DE_MINIMIS_GAIN_PCT of current value
                de_minimis_count = 0
                regular_stcg_count = 0
                for _, lot in stcg_lots.iterrows():
                    gain = lot.get("Unrealized Gain", 0)
                    value = lot.get("Current Value", 1)
                    if value > 0 and gain / value < DE_MINIMIS_GAIN_PCT:
                        de_minimis_count += 1
                    else:
                        regular_stcg_count += 1

                if regular_stcg_count == 0 and ltcg_count == 0 and de_minimis_count == 0:
                    continue

                de_min_text = f"✅ {de_minimis_count} lot(s) — gain < 1%" if de_minimis_count > 0 else "—"

                screener_rows.append(
                    {
                        "Account": account_name,
                        "Symbol": sym,
                        "STCG": f"{regular_stcg_count} Pending",
                        "LTCG": f"{ltcg_count} Safe",
                        "DeMinimis": de_min_text,
                    }
                )

            # Sort by Account Name then Symbol
            screener_rows = sorted(screener_rows, key=lambda x: (x["Account"], x["Symbol"]))

            if not screener_rows:
                f.write(
                    "*Amazing! No assets are currently held at a short-term capital gain in your Taxable accounts.*\n"
                )
            else:
                for row in screener_rows:
                    f.write(
                        f"| {row['Account']} | **{row['Symbol']}** | {row['STCG']} | {row['LTCG']} | {row['DeMinimis']} |\n"
                    )
        else:
            f.write("*Amazing! No assets are currently held at a short-term capital gain in your Taxable accounts.*\n")

        # --- Section 4: Recommended Replacements (4-Bucket) ---
        f.write("\n## 4. Recommended Replacement Funds\n")
        f.write(
            "Funds dynamically selected today based on live market data, scored using per-account metrics aligned to each account's investment objective.\n\n"
        )

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
            routing = classify_asset_routing(ticker, yld, beta)

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
            cand = score_candidate(
                ticker, cand, routing, years_to_retirement=years_to_retirement, risk_tolerance=risk_tolerance
            )

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
        roth_main = [c for c in roth_candidates if not c.get("insufficient_history")]
        roth_emerging = [c for c in roth_candidates if c.get("insufficient_history")]
        k401_main = [c for c in k401_candidates if not c.get("insufficient_history")]
        k401_emerging = [c for c in k401_candidates if c.get("insufficient_history")]
        hsa_main = [c for c in hsa_candidates if not c.get("insufficient_history")]
        hsa_emerging = [c for c in hsa_candidates if c.get("insufficient_history")]
        taxable_main = [c for c in taxable_candidates if not c.get("insufficient_history")]
        taxable_emerging = [c for c in taxable_candidates if c.get("insufficient_history")]

        # --- 401k Plan Menu Constraint ---
        # If a 401k plan menu was detected, constrain ONLY 401k candidates to the plan menu.
        # HSA candidates remain unconstrained (HSA holders can invest in anything).
        if plan_menu_tickers:
            plan_constrained = [c for c in k401_candidates if c["ticker"] in plan_menu_tickers]
            if plan_constrained:
                k401_main = [c for c in plan_constrained if not c.get("insufficient_history")]
                k401_emerging = [c for c in plan_constrained if c.get("insufficient_history")]
                print(
                    f"   401k replacement candidates constrained to {len(plan_constrained)} funds from your employer's plan menu."
                )
            else:
                print(
                    "   ⚠️ No plan menu funds matched the dynamic candidate universe. Showing unconstrained 401k results."
                )
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
                nof = c.get("net_of_fees_5y", 0)
                r1 = f"{c['1y_return'] * 100:+.2f}%"
                r3 = f"{c['3y_return'] * 100:+.2f}%"
                r5 = f"{c['5y_return'] * 100:+.2f}%"
                nof_str = f"{nof * 100:+.2f}%" if nof else "N/A"
                name = c["name"] + (f" {label_suffix}" if label_suffix else "")
                row = f"| **{c['ticker']}** | {name} | `{c['er']:.2f}%` | *{c['yield'] * 100:.2f}%* | {nof_str} |"
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
                            row += f" {val * 100:+.2f}% |" if "return" in key else f" {val * 100:.2f}% |"
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
                f.write(
                    "*Scored on available history only — < 3 years of data. Not ranked against established funds.*\n\n"
                )
                _write_fund_rows(emerging, header, divider, extra_cols, label_suffix="⚠️ < 3Y History")

        write_fund_table(
            roth_main,
            "🚀 Roth IRA — Maximum Growth",
            "These funds maximize total return. All growth is permanently tax-free. Scored by Sortino Ratio + Net-of-Fees 5Y Return + 10Y Total Return.",
            extra_cols=["Sortino (5Y)", "10Y Ret"],
            emerging=roth_emerging,
        )
        # Determine 401k objective based on years to retirement
        if years_to_retirement > 15:
            k401_title = "🚀 Employer 401k — Maximum Growth"
            k401_desc = "Maximum-growth funds for your employer 401k. All growth is tax-deferred. Scored by Sortino Ratio + Net-of-Fees 5Y Return + 10Y Total Return."
            k401_cols = ["Sortino (5Y)", "10Y Ret"]
        elif years_to_retirement > 5:
            k401_title = "📈 Employer 401k — Balanced Growth"
            k401_desc = "Core growth funds with moderate stability for your mid-horizon 401k. Scored by Sharpe Ratio + Net-of-Fees 5Y Return."
            k401_cols = ["Sharpe (5Y)"]
        else:
            k401_title = "💼 Employer 401k — Income & Dividends (Plan-Constrained)"
            k401_desc = "High-yield, low-volatility funds for your near-retirement 401k. Scored by Sharpe Ratio + Net-of-Fees 5Y Return."
            k401_cols = ["Sharpe (5Y)"]

        write_fund_table(
            k401_main,
            k401_title,
            k401_desc,
            extra_cols=k401_cols,
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
            if "Account Type" in df.columns and "Account Name" in df.columns:
                k401_df = df[df["Account Name"].str.contains("401k|401K", na=False)].copy()
            else:
                k401_df = pd.DataFrame()

            if not k401_df.empty:
                total_401k = k401_df["Current Value"].sum()
                f.write("### Your Current 401k Holdings\n\n")

                f.write("| Ticker | Fund Name | Balance | Weight | ER | 1Y Return | 3Y Return | 5Y Return |\n")
                f.write("|---|---|---|---|---|---|---|---|\n")
                for _, row in k401_df.iterrows():
                    sym = row.get("Symbol", "")
                    md = candidate_data.get(sym, {})
                    r1 = md.get("1y_return")
                    r3 = md.get("3y_return")
                    r5 = md.get("5y_return")
                    er = md.get("expense_ratio_pct", row.get("Expense Ratio", 0.0))
                    val = row.get("Current Value", 0)
                    pct = (val / total_401k * 100) if total_401k > 0 else 0
                    r1s = f"{r1 * 100:+.2f}%" if r1 else "N/A"
                    r3s = f"{r3 * 100:+.2f}%" if r3 else "N/A"
                    r5s = f"{r5 * 100:+.2f}%" if r5 else "N/A"
                    
                    # Use original name from plan menu if available
                    name = k401_ticker_to_name.get(sym, row.get("Description", sym))
                    f.write(
                        f"| **{sym}** | {name} | ${val:,.2f} | {pct:.1f}% | `{er:.2f}%` | {r1s} | {r3s} | {r5s} |\n"
                    )

                f.write(f"\n**Total 401k Value:** ${total_401k:,.2f}\n\n")

            # 5b. Full Plan Menu Scorecard — rank every fund in the plan
            f.write("### Plan Menu Scorecard — All Available Funds Ranked\n")
            f.write(
                "Every fund your employer offers, scored by the engine's 401k optimization formula (Sharpe Ratio + Net-of-Fees Return + Tracking Error). "
            )
            f.write("Funds you currently hold are marked with ✅.\n\n")

            held_tickers = set(k401_df["Symbol"].tolist()) if not k401_df.empty else set()

            # Score all plan menu funds using the 401k scoring formula
            all_plan_scored = []
            for ticker in plan_menu_tickers:
                md = candidate_data.get(ticker, {})
                if not md:
                    continue
                er = md.get("expense_ratio_pct", 0.0)
                yld = md.get("yield", 0.0) or 0.0
                r1 = md.get("1y_return", 0.0) or 0.0
                r3 = md.get("3y_return", 0.0) or 0.0
                r5 = md.get("5y_return", 0.0) or 0.0
                
                # Use original name from plan menu if available
                name = k401_ticker_to_name.get(ticker, md.get("name", ticker))
                cand = {
                    "ticker": ticker,
                    "name": name,
                    "er": er,
                    "yield": yld,
                    "1y_return": r1,
                    "3y_return": r3,
                    "5y_return": r5,
                    "routing": "Tax-Deferred",
                }
                cand = score_candidate(
                    ticker, cand, "Tax-Deferred", years_to_retirement=years_to_retirement, risk_tolerance=risk_tolerance
                )
                all_plan_scored.append(cand)

            all_plan_scored.sort(key=lambda x: x["score"], reverse=True)

            f.write("| Rank | Held | Ticker | Fund Name | Score | ER | Sharpe | 1Y | 3Y | 5Y |\n")
            f.write("|---|---|---|---|---|---|---|---|---|---|\n")

            for i, c in enumerate(all_plan_scored, 1):
                held = "✅" if c["ticker"] in held_tickers else "—"
                sharpe = c.get("sharpe_ratio")
                sharpe_s = f"{sharpe:.3f}" if sharpe else "N/A"
                r1 = f"{c['1y_return'] * 100:+.2f}%"
                r3 = f"{c['3y_return'] * 100:+.2f}%"
                r5 = f"{c['5y_return'] * 100:+.2f}%"
                f.write(
                    f"| {i} | {held} | **{c['ticker']}** | {c['name']} | {c['score']:.1f} | `{c['er']:.2f}%` | {sharpe_s} | {r1} | {r3} | {r5} |\n"
                )

            f.write("\n")

            # 5c. Rebalance Opportunities
            top_not_held = [c for c in all_plan_scored if c["ticker"] not in held_tickers][:5]

            # Finding: 401k rebalance
            if top_not_held:
                findings.append(
                    {
                        "category": "k401_rebalance",
                        "text": f"**{len(top_not_held)} higher-scoring fund(s)** in your 401k plan that you don't currently hold",
                        "section_ref": 5,
                    }
                )

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
                        reason.append(f"High net return ({nof * 100:.1f}%)")
                    if c.get("1y_return", 0) > 0.15:
                        reason.append("Hot 1Y momentum")
                    reason_text = "; ".join(reason) if reason else "Diversification opportunity"
                    f.write(
                        f"| **{c['ticker']}** | {c['name']} | {c['score']:.1f} | `{c['er']:.2f}%` | {sharpe_s} | {reason_text} |\n"
                    )
                f.write("\n")

            # 5d. Weakest holdings check
            if not k401_df.empty and len(all_plan_scored) > 5:
                worst_held = [c for c in reversed(all_plan_scored) if c["ticker"] in held_tickers][:3]
                if worst_held and worst_held[0]["score"] < all_plan_scored[len(all_plan_scored) // 2]["score"]:
                    f.write("### ⚠️ Underperforming Holdings\n")
                    f.write(
                        "These funds you currently hold rank in the **bottom half** of your plan menu. Consider reducing allocation.\n\n"
                    )
                    f.write("| Ticker | Fund Name | Plan Rank | Score | ER | 1Y | Suggestion |\n")
                    f.write("|---|---|---|---|---|---|---|\n")
                    for c in worst_held:
                        rank = next((i for i, x in enumerate(all_plan_scored, 1) if x["ticker"] == c["ticker"]), "?")
                        r1 = f"{c['1y_return'] * 100:+.2f}%"
                        f.write(
                            f"| **{c['ticker']}** | {c['name']} | #{rank} of {len(all_plan_scored)} | {c['score']:.1f} | `{c['er']:.2f}%` | {r1} | Reduce allocation |\n"
                        )
                    f.write("\n")

        # --- Section 5e: Recommended 401k Allocation ---
        if plan_menu_tickers and k401_options_file and all_plan_scored:
            f.write("### Recommended Allocation\n\n")

            profile_note = "default profile" if using_profile_defaults else "investor profile"
            equity_total = target_alloc["US Equity"] + target_alloc["Intl Equity"]
            bond_total = target_alloc["Bond"] + target_alloc["Stable Value"]
            f.write(
                f"Based on {profile_note} (born {birth_year}, retiring {retirement_year}, {years_to_retirement} years out):\n"
            )
            f.write(f"**Target split: {equity_total:.0f}% Equity / {bond_total:.0f}% Bond**\n\n")
            if using_profile_defaults:
                f.write(
                    "> *Using default assumptions. Create `Drop_Financial_Info_Here/investor_profile.txt` with `birth_year` and `retirement_year` to personalize.*\n\n"
                )

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
                    alloc_rows.append(
                        {
                            "ticker": c["ticker"],
                            "name": c["name"],
                            "asset_class": asset_class,
                            "raw_pct": raw_pct,
                        }
                    )

            # Apply minimum floor and normalize to 100%
            for row in alloc_rows:
                row["raw_pct"] = max(row["raw_pct"], MIN_ALLOCATION_PCT)
            total_raw = sum(r["raw_pct"] for r in alloc_rows) or 100.0
            
            # Normalize and round individually
            for row in alloc_rows:
                row["target_pct"] = round(row["raw_pct"] / total_raw * 100, 1)

            # Ensure sum is exactly 100.0% by adjusting the largest allocation
            current_sum = sum(r["target_pct"] for r in alloc_rows)
            if alloc_rows and current_sum != 100.0:
                diff = round(100.0 - current_sum, 1)
                # Find index of the largest allocation to absorb the difference
                largest_idx = 0
                max_val = -1.0
                for i, r in enumerate(alloc_rows):
                    if r["target_pct"] > max_val:
                        max_val = r["target_pct"]
                        largest_idx = i
                alloc_rows[largest_idx]["target_pct"] = round(alloc_rows[largest_idx]["target_pct"] + diff, 1)

            # Compute current % from k401_df
            total_401k = k401_df["Current Value"].sum() if not k401_df.empty else 0
            held_pcts = {}
            if total_401k > 0:
                for _, row in k401_df.iterrows():
                    sym = row.get("Symbol", "")
                    held_pcts[sym] = round(row.get("Current Value", 0) / total_401k * 100, 1)

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
                f.write(
                    f"| **{ticker}** | {row['name']} | {row['asset_class']} | {dur_str} | {current_pct:.1f}% | {target_pct:.1f}% | {delta_str} | {action} |\n"
                )

            # Funds currently held but not in target allocation
            target_tickers = {r["ticker"] for r in alloc_rows}
            for sym, pct in held_pcts.items():
                if sym not in target_tickers and pct > 0:
                    md = candidate_data.get(sym, {})
                    name = md.get("name", sym)
                    ac = md.get("asset_class", "US Equity")
                    # Added '--' for Duration to keep columns aligned
                    f.write(f"| **{sym}** | {name} | {ac} | -- | {pct:.1f}% | 0.0% | -{pct:.1f}% | **Remove** |\n")

            f.write("\n")

            # Summary: current vs target equity/bond split
            current_equity = 0.0
            current_bond = 0.0
            if total_401k > 0:
                for _, row in k401_df.iterrows():
                    sym = row.get("Symbol", "")
                    val_pct = row.get("Current Value", 0) / total_401k * 100
                    ac = candidate_data.get(sym, {}).get("asset_class", "US Equity")
                    if ac in ("US Equity", "Intl Equity"):
                        current_equity += val_pct
                    else:
                        current_bond += val_pct

            status = "✅ Aligned" if abs(current_equity - equity_total) <= 5 else "⚠️ Rebalance needed"
            f.write(f"**Current split:** {current_equity:.0f}% Equity / {current_bond:.0f}% Bond | ")
            f.write(f"**Target:** {equity_total:.0f}% Equity / {bond_total:.0f}% Bond | {status}\n\n")

            f.write(
                "> *Illustrative model based on a standard target-date glide path. Consult a financial advisor before making changes to your 401k allocations.*\n\n"
            )

        # --- Section 5f: Portfolio Rebalancing Plan ---
        contribution_amounts = get_contribution_amounts(df, investor_profile)
        bucket_candidates = {
            "Roth IRA": roth_main,
            "Taxable Brokerage": taxable_main,
            "HSA": hsa_main,
        }
        has_any_allocation = False
        for acct_type, acct_cands in bucket_candidates.items():
            cash_available = contribution_amounts.get(acct_type, 0.0)
            if not acct_cands:
                continue

            alloc = compute_allocation(acct_cands, min_pct=MIN_ALLOCATION_PCT, max_funds=5)
            if not alloc:
                continue

            if not has_any_allocation:
                f.write("### 5f. Portfolio Rebalancing Plan\n\n")
                f.write(f"*Risk tolerance: **{risk_tolerance}***")
                if investor_profile.get("risk_tolerance") != investor_profile.get("risk_tolerance_auto"):
                    f.write(
                        f" *(auto-recommendation: {investor_profile['risk_tolerance_auto']} based on {years_to_retirement} years to retirement)*"
                    )
                f.write("\n\n")
                has_any_allocation = True

            f.write(f"#### {acct_type}\n\n")
            if cash_available > 0:
                # Find core position ticker for this account
                core_pos = detect_core_positions(df)
                core_tickers = [v["ticker"] for k, v in core_pos.items() if resolve_account_type(k) == acct_type]
                core_label = core_tickers[0] if core_tickers else "core position"
                f.write(f"> Uninvested cash from {core_label}: available for deployment\n\n")
            else:
                f.write("> No uninvested cash detected. Below are target allocation percentages for rebalancing.\n\n")

            # Determine pertinent metric for comparison
            pertinent_metric = "sortino_ratio" if acct_type in ("Roth IRA", "HSA") else "sharpe_ratio"
            metric_label = "Sortino" if pertinent_metric == "sortino_ratio" else "Sharpe"

            f.write(f"| Fund | Score | Stability | Alloc % | {metric_label} | Action |\n")
            f.write("|---|---|---|---|---|---|\n")

            for c in alloc:
                ticker = c.get("ticker", "")
                name = c.get("name", ticker)
                score = c.get("score", 0)
                stab = c.get("stability_score")
                stab_str = f"{stab:.0f}" if stab is not None else "--"
                pct = c.get("alloc_pct", 0)
                metric_val = c.get(pertinent_metric)
                metric_str = f"{metric_val:.2f}" if metric_val is not None else "--"
                f.write(f"| **{ticker}** | {score:.1f} | {stab_str} | {pct:.0f}% | {metric_str} | Buy |\n")

            f.write("\n")

            # Existing holdings in this account — show comparison
            acct_holdings = df[df["Account Name"].apply(lambda x: resolve_account_type(x) == acct_type)]
            acct_holdings = acct_holdings[~acct_holdings["Symbol"].isin(CORE_POSITION_TICKERS)]
            if not acct_holdings.empty:
                alloc_tickers = {c["ticker"] for c in alloc}
                existing_not_in_alloc = acct_holdings[~acct_holdings["Symbol"].isin(alloc_tickers)]
                if not existing_not_in_alloc.empty:
                    f.write("**Existing holdings not in recommendation:**\n\n")
                    f.write(f"| Holding | {metric_label} | Suggested Action |\n")
                    f.write("|---|---|---|\n")
                    for _, row in existing_not_in_alloc.iterrows():
                        sym = row.get("Symbol", "")
                        if not sym or sym in CORE_POSITION_TICKERS:
                            continue
                        fund_m = metrics.get_fund_metrics(sym, acct_type)
                        existing_metric = fund_m.get(pertinent_metric)
                        existing_str = f"{existing_metric:.2f}" if existing_metric is not None else "--"
                        # Compare with top recommended
                        top_rec_metric = alloc[0].get(pertinent_metric)
                        if (
                            existing_metric is not None
                            and top_rec_metric is not None
                            and existing_metric < top_rec_metric * 0.7
                        ):
                            action = f"Evaluate replacing ({metric_label} {existing_str} vs {alloc[0]['ticker']}: {top_rec_metric:.2f})"
                        else:
                            action = "Hold"
                        f.write(f"| {sym} | {existing_str} | {action} |\n")
                    f.write("\n")

        if has_any_allocation:
            f.write(
                "> *Allocations are illustrative based on scoring engine output and risk tolerance. Consult a financial advisor before making changes.*\n\n"
            )

        # --- Section 6: Next Steps ---
        candidates_by_bucket = {
            "taxable": taxable_main,
            "roth": roth_main,
            "hsa": hsa_main,
            "k401": k401_main,
        }
        next_steps_md = _render_next_steps(
            df,
            metadata,
            tlh_agg,
            candidates_by_bucket,
            age_factor,
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
