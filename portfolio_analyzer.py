import parser
import market_data
import metrics
import pandas as pd
from pathlib import Path
import validator

# --- Configuration Constants ---

ACCOUNT_TYPE_MAP = {
    "INDIVIDUAL": "Taxable Brokerage",
    "Melissa Investments": "Taxable Brokerage",
    "ROTH IRA": "Roth IRA",
    "Health Savings Account": "401k / HSA",
}

DE_MINIMIS_GAIN_PCT = 0.01  # 1% of lot value — gains below this are safe to reallocate

# --- Asset Routing ---

def classify_routing_bucket(yld: float, beta: float) -> str:
    """
    3-Bucket Tax Location Strategy.
    Classifies a fund into its optimal tax-location bucket.
    """
    if yld >= 0.02:
        return "401k / HSA"
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

    elif routing_bucket == "401k / HSA":
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

    data_dir = Path("data")

    if positions_path is None:
        positions_files = list(data_dir.glob("Portfolio_Positions*.csv"))
        if not positions_files:
            print("No Positions CSV found in data/")
            return
        positions_path = positions_files[0]

    print(f"Loading {positions_path.name} locally...")
    df = parser.load_fidelity_positions(positions_path)

    if history_path is None:
        history_files = list(data_dir.glob("Accounts_History*.csv"))
        if not history_files:
            print("No History CSV found in data/")
            return

        print(f"Loading {len(history_files)} Accounts_History CSV(s) locally...")
        hist_dfs = [parser.load_fidelity_history(f) for f in history_files]
        hist_df = pd.concat(hist_dfs, ignore_index=True)
    else:
        print(f"Loading {history_path.name} locally...")
        hist_df = parser.load_fidelity_history(history_path)

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
    df['Expense Ratio'] = df['Symbol'].map(lambda x: metadata.get(x, {}).get('expense_ratio_pct', 0.0))
    df['Yield'] = df['Symbol'].map(lambda x: metadata.get(x, {}).get('yield', 0.0))
    df['Type'] = df['Symbol'].map(lambda x: metadata.get(x, {}).get('type', 'UNKNOWN'))

    # We only use Current Value to calculate weighted averages, but NEVER print it to stdout.
    total_portfolio_value = df['Current Value'].sum()

    # Calculate Weighted Average Expense Ratio
    df['Value_Weight'] = df['Current Value'] / total_portfolio_value
    df['Weighted_ER'] = df['Expense Ratio'] * df['Value_Weight']
    portfolio_weighted_er = df['Weighted_ER'].sum()

    # 3. Write analysis to a local Markdown file
    if report_path is None:
        report_path = data_dir / "Portfolio_Analysis_Report.md"

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# Fidelity Portfolio Optimization Report\n\n")

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
            er = row.get('Expense Ratio', 0.0)
            action = row['Action']
            if action == "Core Cash Position":
                er = 0.0
            f.write(f"| {sym} | {account_name} | {account_type} | {desc} | {er:.3f}% | {action} |\n")

        # --- Section 3: Tax Optimization ---
        f.write("\n## 3. Tax Optimization & Loss Harvesting\n")
        f.write("By tracking individual lot purchase dates via FIFO accounting, we can optimize your short-term/long-term capital gains classification and find tax loss harvesting opportunities.\n\n")

        # TLH Opportunities
        tlh_lots = lots_df[lots_df['Unrealized Gain'] < 0].copy()
        f.write("### 🚨 Tax-Loss Harvesting Candidates\n")
        if not tlh_lots.empty:
            f.write("The following lots are currently held at a loss. Selling these will harvest the loss to offset your other capital gains (up to $3,000 against ordinary income).\n\n")
            f.write("| Symbol | Description | Tax Category | Underwater Lots |\n")
            f.write("|---|---|---|---|\n")

            harvestable = tlh_lots.groupby(['Symbol', 'Description', 'Tax_Category']).size().reset_index(name='Lot Count')
            for _, row in harvestable.iterrows():
                f.write(f"| **{row['Symbol']}** | {row['Description']} | {row['Tax_Category']} | {row['Lot Count']} lot(s) underwater |\n")
        else:
            f.write("*Amazing! No assets are currently held at a loss. No TLH opportunities exist right now.*\n")

        # Capital Gains Screener with De Minimis Override
        f.write("\n### ⏳ Capital Gains 'One-Year Wait' Screener\n")
        f.write(f"Profitable lots held for under 365 days are subject to your ordinary income tax rate. Waiting 1 year drops this to the much lower LTCG (15-20%) bracket.\n\n")
        f.write(f"**De Minimis Threshold:** Lots with STCG gains below **{DE_MINIMIS_GAIN_PCT*100:.0f}% of lot value** are flagged as safe to reallocate.\n\n")
        f.write("| Symbol | Lots STCG | Lots LTCG | De Minimis (Safe to Reallocate) |\n")
        f.write("|---|---|---|---|\n")

        prof_lots = lots_df[lots_df['Unrealized Gain'] > 0]
        if not prof_lots.empty:
            for sym in prof_lots['Symbol'].dropna().unique():
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

                de_minimis_msg = f"✅ {de_minimis_count} lot(s) — gain < {DE_MINIMIS_GAIN_PCT*100:.0f}%" if de_minimis_count > 0 else "—"
                f.write(f"| **{sym}** | {regular_stcg_count} Pending | {ltcg_count} Safe | {de_minimis_msg} |\n")
        else:
            f.write("| N/A | No profitable lots exist | - | - |\n")

        # --- Section 4: Recommended Replacements (3-Bucket) ---
        f.write("\n## 4. Recommended Replacement Funds\n")
        f.write("Funds dynamically selected today based on live market data, scored using per-account metrics aligned to each account's investment objective.\n\n")

        print("Fetching a dynamic universe of replacement candidates from live market data...")
        candidate_tickers = market_data.get_dynamic_etf_universe()
        print(f"Discovered {len(candidate_tickers)} candidates. Fetching full historical metadata...")
        candidate_data = market_data.fetch_ticker_metadata(candidate_tickers)

        # Classify, filter, and score candidates into 3 buckets
        roth_candidates = []
        k401_hsa_candidates = []
        taxable_candidates = []

        for ticker, data in candidate_data.items():
            # STRICT QA: Must be an ETF or Mutual Fund
            quote_type = data.get("type", "").upper()
            if quote_type not in ["ETF", "MUTUALFUND"]:
                continue

            er = data.get("expense_ratio_pct", 100.0)
            yld = data.get("yield", 0.0) or 0.0
            ret_1y = data.get("1y_return", 0.0) or 0.0
            ret_3y = data.get("3y_return", 0.0) or 0.0
            ret_5y = data.get("5y_return", 0.0) or 0.0

            # Reject corrupted data
            if ret_1y == 0.0 and ret_3y == 0.0 and ret_5y == 0.0 and yld == 0.0:
                continue

            # ER filter
            if er > 0.40:
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

            if routing == "Roth IRA":
                roth_candidates.append(cand)
            elif routing == "401k / HSA":
                k401_hsa_candidates.append(cand)
            else:
                taxable_candidates.append(cand)

        roth_candidates.sort(key=lambda x: x["score"], reverse=True)
        k401_hsa_candidates.sort(key=lambda x: x["score"], reverse=True)
        taxable_candidates.sort(key=lambda x: x["score"], reverse=True)

        def write_fund_table(funds, title, description, extra_cols=None):
            f.write(f"### {title}\n")
            f.write(f"{description}\n\n")

            header = "| Ticker | Fund Name | ER | Yield | Net 5Y | 1Y | 3Y | 5Y |"
            divider = "|---|---|---|---|---|---|---|---|"
            if extra_cols:
                for col_name in extra_cols:
                    header += f" {col_name} |"
                    divider += "---|"
            f.write(header + "\n")
            f.write(divider + "\n")

            if not funds:
                f.write("| N/A | No funds matched criteria | - | - | - | - | - | - |")
                if extra_cols:
                    f.write(" - |" * len(extra_cols))
                f.write("\n")
            for c in funds[:5]:
                nof = c.get('net_of_fees_5y', 0)
                r1 = f"{c['1y_return']*100:+.2f}%"
                r3 = f"{c['3y_return']*100:+.2f}%"
                r5 = f"{c['5y_return']*100:+.2f}%"
                nof_str = f"{nof*100:+.2f}%" if nof else "N/A"
                row = f"| **{c['ticker']}** | {c['name']} | `{c['er']:.2f}%` | *{c['yield']*100:.2f}%* | {nof_str} | {r1} | {r3} | {r5} |"
                if extra_cols:
                    for col_key in extra_cols:
                        key = col_key.lower().replace(" ", "_").replace("(", "").replace(")", "")
                        val = c.get(key)
                        if val is None:
                            row += " N/A |"
                        elif isinstance(val, float) and abs(val) < 1:
                            row += f" {val:.3f} |"
                        elif isinstance(val, float):
                            row += f" {val*100:.2f}% |"
                        else:
                            row += f" {val} |"
                f.write(row + "\n")
            f.write("\n")

        write_fund_table(
            roth_candidates,
            "🚀 Roth IRA — Maximum Growth",
            "These funds maximize total return. All growth is permanently tax-free. Scored by Sortino Ratio + Net-of-Fees 5Y Return + 10Y Total Return.",
            extra_cols=["Sortino_Ratio"]
        )
        write_fund_table(
            k401_hsa_candidates,
            "💰 401k / HSA — Income & Dividends",
            "High-yield funds for tax-deferred accounts. Dividends compound without annual drag. Scored by Sharpe Ratio + Net-of-Fees 5Y Return.",
            extra_cols=["Sharpe_Ratio"]
        )
        write_fund_table(
            taxable_candidates,
            "🏦 Taxable Brokerage — Tax-Efficient Growth",
            "Low-distribution growth funds that minimize taxable events. Scored by Sharpe Ratio + Net-of-Fees 5Y Return + low-yield bonus.",
            extra_cols=["Sharpe_Ratio", "Max_Drawdown"]
        )

        # --- Section 5: Evaluation Metrics Summary ---
        f.write("## 5. Evaluation Metrics Summary\n\n")
        f.write("### How Each Metric is Used\n\n")
        f.write("| Metric | Used For | What It Measures | Interpretation |\n")
        f.write("|---|---|---|---|\n")
        f.write("| **Net-of-Fees Return (5Y)** | All accounts | Annualized return after subtracting expense ratio | Higher is better. The single most important number — what you actually earned. |\n")
        f.write("| **Sharpe Ratio** | Taxable, 401k/HSA | Return per unit of *total* volatility (risk-adjusted) | > 1.0 is good, > 2.0 is excellent. Higher means better risk-adjusted returns. |\n")
        f.write("| **Sortino Ratio** | Roth IRA | Return per unit of *downside* volatility | Like Sharpe but ignores upside swings. > 1.0 is good. Ideal for growth funds. |\n")
        f.write("| **Max Drawdown** | Taxable | Worst peak-to-trough decline over 5 years | A less negative number is better. -20% means the fund dropped 20% at its worst point. |\n")
        f.write("| **Tracking Error** | Taxable, 401k/HSA | How closely a fund follows its benchmark index | Lower is better for index funds. High TE means the fund deviates from what it claims to track. |\n")
        f.write("| **Total Return (10Y)** | Roth IRA | Cumulative total return over 10 years | Shows long-term compounding power. Marked 'Insufficient History' if fund is < 10 years old. |\n")
        f.write(f"\n*Risk-free rate used for Sharpe/Sortino: **{rf*100:.2f}%** (13-week T-Bill, fetched live)*\n")
        f.write(f"\n*Tracking Error is computed against each fund's detected benchmark (e.g., SPY for S&P 500 funds, AGG for bond funds). If no benchmark can be detected, the metric is omitted.*\n")
        f.write("\n### Per-Account Scoring Rationale\n\n")
        f.write("- **Taxable Brokerage:** Prioritizes net returns + risk consistency (Sharpe) + low tax drag (low yield). Max Drawdown penalizes volatility that could trigger panic selling.\n")
        f.write("- **Roth IRA:** Maximizes total return using Sortino (ignores upside volatility). 10Y track record validates durable compounding. This is your most valuable tax shelter — put your biggest growers here.\n")
        f.write("- **401k / HSA:** Balances income generation with consistency (Sharpe). Tracking Error ensures index fund fidelity. Tax-deferred, so dividends compound without annual drag.\n")

    print(f"\n✅ Privacy-safe report successfully generated at: {report_path.absolute()}")
    print("Please open this markdown file locally to view your optimization insights.")

if __name__ == "__main__":
    generate_privacy_report()
