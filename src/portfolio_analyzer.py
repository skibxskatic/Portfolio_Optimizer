import os
import io
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

# --- Configuration Constants ---

ACCOUNT_TYPE_MAP = {
    "INDIVIDUAL": "Taxable Brokerage",
    "Melissa Investments": "Taxable Brokerage",
    "ROTH IRA": "Roth IRA",
    "Health Savings Account": "HSA",
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

# --- Asset Routing ---

def classify_routing_bucket(yld: float, beta: float) -> str:
    """
    4-Bucket Tax Location Strategy.
    Classifies a fund into its optimal tax-location bucket.
    High-yield funds route to "Tax-Deferred" which covers both 401k and HSA.
    """
    if yld >= 0.02:
        return "Tax-Deferred"
    elif yld < 0.02 and beta > 1.0:
        return "Roth IRA"
    else:
        return "Taxable Brokerage"


def resolve_account_type(account_name: str) -> str:
    """Maps a Fidelity CSV Account Name to a routing bucket."""
    return ACCOUNT_TYPE_MAP.get(account_name, "Taxable Brokerage")


# --- Scoring ---

def score_candidate(ticker: str, data: dict, routing_bucket: str) -> dict:
    """
    Scores a candidate fund using per-account metrics.
    Returns the candidate dict augmented with 'score' and metric values.
    """
    fund_metrics = metrics.get_fund_metrics(ticker, routing_bucket)
    nof = fund_metrics.get("net_of_fees_5y") or 0.0

    if routing_bucket == "Taxable Brokerage":
        sharpe = fund_metrics.get("sharpe_ratio") or 0.0
        max_dd = fund_metrics.get("max_drawdown") or 0.0
        yld = data.get("yield", 0.0) or 0.0
        # Lower yield = better for taxable (less tax drag)
        low_yield_bonus = max(0, (0.02 - yld) * 100)  # up to 2 points
        score = (nof * 40) + (sharpe * 30) + (low_yield_bonus * 20) + ((1 + max_dd) * 10)
        data.update({"sharpe_ratio": sharpe, "max_drawdown": max_dd})

    elif routing_bucket == "Roth IRA":
        sortino = fund_metrics.get("sortino_ratio") or 0.0
        total_10y = fund_metrics.get("total_return_10y")
        t10_score = (total_10y * 30) if total_10y is not None else 0.0
        score = (nof * 35) + (sortino * 35) + t10_score
        data.update({"sortino_ratio": sortino, "total_return_10y": total_10y})

    elif routing_bucket == "Tax-Deferred":
        sharpe = fund_metrics.get("sharpe_ratio") or 0.0
        te = fund_metrics.get("tracking_error")
        # Lower tracking error = better (fund tracks its index well)
        te_penalty = max(0, 1 - (te * 10)) if te is not None else 0.5
        score = (nof * 35) + (sharpe * 35) + (te_penalty * 10)
        data.update({"sharpe_ratio": sharpe, "tracking_error": te})

    else:
        score = nof * 100

    data["score"] = round(score, 4)
    data["net_of_fees_5y"] = nof
    return data


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
        f.write(f"- **Risk-Free Rate (13-Week T-Bill):** `{rf*100:.2f}%` *(fetched live)*\n")

        # --- Section 2: Asset Holding Breakdown ---
        f.write("\n## 2. Asset Holding Breakdown\n")
        f.write("| Symbol | Account Name | Account Type | Description | Current ER | Suggested Action |\n")
        f.write("|---|---|---|---|---|---|\n")

        def get_action_for_row(row):
            sym = row.get('Symbol', '')
            er = row.get('Expense Ratio', 0.0)
            is_cash = pd.isna(sym) or sym == 'CORE' or str(sym).endswith("XX")
            if is_cash:
                return "Core Cash Position"

            # Net-of-fees expense evaluation
            if er is not None and er > 0.40:
                nof = metadata.get(sym, {}).get('net_of_fees_5y')
                if nof is not None:
                    return f"**Evaluate** (ER {er:.2f}%, Net 5Y: {nof*100:.1f}%)"
                return "**Replace (High ER)**. See *Alternatives* below."
            return "Keep"

        df['Action'] = df.apply(get_action_for_row, axis=1)
        df['Account Name'] = df['Account Name'].fillna('Unknown Account')
        df['Account Type'] = df['Account Name'].map(resolve_account_type)
        df_sorted = df.sort_values(by=['Account Type', 'Account Name', 'Action', 'Symbol'])

        for idx, row in df_sorted.iterrows():
            sym = row.get('Symbol', '')
            desc = row.get('Description', '')
            account_name = row['Account Name']
            account_type = row['Account Type']
            er = row.get('Expense Ratio')
            action = row['Action']
            if action == "Core Cash Position":
                er = 0.0
            er_str = f"{er:.3f}%" if er is not None else "N/A"
            f.write(f"| {sym} | {account_name} | {account_type} | {desc} | {er_str} | {action} |\n")

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

        f.write("### 🚨 Tax-Loss Harvesting Candidates\n")
        if tlh_agg:
            f.write("The following lots are currently held at a loss. Selling these will harvest the loss to offset your other capital gains (up to $3,000 against ordinary income).\n\n")
            f.write("*401k, Roth IRA, and HSA accounts are excluded — losses in tax-advantaged accounts have no tax benefit.*\n\n")
            f.write("| Priority | Account | Symbol | Description | Tax Category | Est. Loss ($) | Underwater Lots | Wash Sale Risk |\n")
            f.write("|---|---|---|---|---|---|---|---|\n")

            for rank, row in enumerate(tlh_agg, 1):
                risk = detect_wash_sale_risk(df, row['Symbol'])
                risk_str = "⚠️ YES (Cross-Account)" if risk else "No"
                est_loss = row['Est_Loss']
                f.write(f"| {rank} | {row['Account Name']} | **{row['Symbol']}** | {row['Description']} | {row['Tax_Category']} | (${est_loss:,.0f}) | {row['Lot_Count']} lot(s) | {risk_str} |\n")
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
            cand = score_candidate(ticker, cand, routing)

            # Flag funds with < 3 years of price history — scored on limited data
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
                cand = score_candidate(ticker, cand, "Tax-Deferred")
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

        # --- Section 6: Evaluation Metrics Summary ---
        f.write("## 6. Evaluation Metrics Summary\n\n")
        f.write("### How Each Metric is Used\n\n")
        f.write("| Metric | Used For | What It Measures | Interpretation |\n")
        f.write("|---|---|---|---|\n")
        f.write("| **Net-of-Fees Return (5Y)** | All accounts | Annualized return after subtracting expense ratio | Higher is better. The single most important number — what you actually earned. |\n")
        f.write("| **Sharpe Ratio** | Taxable, 401k, HSA | Return per unit of *total* volatility (risk-adjusted) | > 1.0 is good, > 2.0 is excellent. Higher means better risk-adjusted returns. |\n")
        f.write("| **Sortino Ratio** | Roth IRA | Return per unit of *downside* volatility | Like Sharpe but ignores upside swings. > 1.0 is good. Ideal for growth funds. |\n")
        f.write("| **Max Drawdown** | Taxable | Worst peak-to-trough decline over 5 years | A less negative number is better. -20% means the fund dropped 20% at its worst point. |\n")
        f.write("| **Tracking Error** | Taxable, 401k, HSA | How closely a fund follows its benchmark index | Lower is better for index funds. High TE means the fund deviates from what it claims to track. |\n")
        f.write("| **Total Return (10Y)** | Roth IRA | Cumulative total return over 10 years | Shows long-term compounding power. Marked 'Insufficient History' if fund is < 10 years old. |\n")
        f.write(f"\n*Risk-free rate used for Sharpe/Sortino: **{rf*100:.2f}%** (13-week T-Bill, fetched live)*\n")
        f.write(f"\n*Tracking Error is computed against each fund's detected benchmark (e.g., SPY for S&P 500 funds, AGG for bond funds). If no benchmark can be detected, the metric is omitted.*\n")
        f.write("\n### Per-Account Scoring Rationale\n\n")
        f.write("- **Taxable Brokerage:** Prioritizes net returns + risk consistency (Sharpe) + low tax drag (low yield). Max Drawdown penalizes volatility that could trigger panic selling.\n")
        f.write("- **Roth IRA:** Maximizes total return using Sortino (ignores upside volatility). 10Y track record validates durable compounding. This is your most valuable tax shelter — put your biggest growers here.\n")
        f.write("- **Employer 401k:** Balances income generation with consistency (Sharpe). Tracking Error ensures index fund fidelity. Constrained to your employer's plan menu. Tax-deferred, so dividends compound without annual drag.\n")
        f.write("- **HSA:** Same scoring model as Roth IRA (Sortino + Net-of-Fees 5Y + 10Y Total Return). HSA's triple tax advantage makes long-term compounding the optimal strategy — not income generation. Full dynamic universe access, no plan-menu constraint.\n")

        markdown_content = f.getvalue()

    # 4. Save exact markdown to Drop_Financial_Info_Here/ cache
    with open(report_path, "w", encoding="utf-8") as md_file:
        md_file.write(markdown_content)

    # 5. Convert to PDF and auto-open (Non-Tech Friendly Pattern)
    timestamp_file = pd.Timestamp.now().strftime("%b-%d-%Y_%H-%M-%S")
    pdf_path = cache_dir / f"Portfolio_Analysis_Report_{timestamp_file}.pdf"
    
    print("Converting report to PDF...")
    pdf = MarkdownPdf(toc_level=2)
    # Estimate height based on line count to completely avoid massive blank spaces at the bottom
    # Assuming ~6.5mm height per text line + 50mm padding, enforcing a minimum of 210mm (A4 Landscape)
    estimated_height = max(210, 50 + markdown_content.count('\n') * 6.5)
    pdf.add_section(Section(markdown_content, paper_size=(297, estimated_height)), user_css=table_css)
    pdf.save(str(pdf_path))

    print(f"\n✅ Privacy-safe PDF report successfully generated at: {pdf_path.absolute()}")
    print("Opening your personalized report...")
    
    try:
        os.startfile(str(pdf_path.absolute()))
    except Exception as e:
        print(f"⚠️ Could not auto-open the PDF: {e}")

if __name__ == "__main__":
    generate_privacy_report()
