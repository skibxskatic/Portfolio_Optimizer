import parser
import market_data
import pandas as pd
from pathlib import Path
import validator

def generate_privacy_report(positions_path=None, history_path=None, report_path=None):
    print("--- PRE-FLIGHT QA CHECKS ---")
    if not validator.verify_yfinance_sane() or not validator.verify_dynamic_screener():
        print("\n❌ PRE-FLIGHT FAILED: Engine data is corrupted or filters are failing.")
        print("Aborting portfolio analysis to protect report integrity.")
        return
    print("--- ALL QA PASSED, BEGINNING ENGINE RUN ---\n")

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
        f.write("> **Privacy Note:** This report was generated entirely locally. Financial quantities and dollar amounts were NOT transmitted to the cloud AI.\n\n")
        
        f.write("## 1. High-Level Metrics\n")
        f.write(f"- **Weighted Average Expense Ratio:** `{portfolio_weighted_er:.3f}%`\n")
        if portfolio_weighted_er > 0.40:
            f.write("  - ⚠️ *Warning: Your aggregate expense ratio is above the recommended 0.40% threshold for passive long-term indexing.*\n")
        else:
            f.write("  - ✅ *Excellent: Your portfolio fees are highly optimized.*\n")
            
        f.write("\n## 2. Asset Holding Breakdown\n")
        f.write("| Symbol | Account Name | Description | Current ER | Suggested Action |\n")
        f.write("|---|---|---|---|---|\n")
        
        # Precompute Action so we can sort by it
        def get_action_for_row(row):
            sym = row.get('Symbol', '')
            er = row.get('Expense Ratio', 0.0)
            is_cash = pd.isna(sym) or sym == 'CORE' or str(sym).endswith("XX")
            if is_cash:
                return "Core Cash Position"
            elif er is not None and er > 0.40:
                return "**Replace (High ER)**. See *Alternatives* below."
            return "Keep"
            
        df['Action'] = df.apply(get_action_for_row, axis=1)
        
        # Sort by Account Name then Action
        df['Account Name'] = df['Account Name'].fillna('Unknown Account')
        df_sorted = df.sort_values(by=['Account Name', 'Action', 'Symbol'])
        
        for idx, row in df_sorted.iterrows():
            sym = row.get('Symbol', '')
            desc = row.get('Description', '')
            account_name = row['Account Name']
            er = row.get('Expense Ratio', 0.0)
            action = row['Action']
            if action == "Core Cash Position":
                er = 0.0
            
            f.write(f"| {sym} | {account_name} | {desc} | {er:.3f}% | {action} |\n")
            
        f.write("\n## 3. Tax Optimization & Loss Harvesting\n")
        f.write("By tracking individual lot purchase dates via FIFO accounting, we can optimize your short-term/long-term capital gains classification and find tax loss harvesting opportunities.\n\n")
        
        # TLH Opportunities
        tlh_lots = lots_df[lots_df['Unrealized Gain'] < 0].copy()
        f.write("### 🚨 Tax-Loss Harvesting Candidates\n")
        if not tlh_lots.empty:
            f.write("The following lots are currently held at a loss. Selling these will harvest the loss to offset your other capital gains (up to $3,000 against ordinary income).\n\n")
            f.write("| Symbol | Description | Tax Category | Underwater Lots |\n")
            f.write("|---|---|---|---|\n")
            
            # Privacy: aggregate lot counts instead of printing dollar amounts
            harvestable = tlh_lots.groupby(['Symbol', 'Description', 'Tax_Category']).size().reset_index(name='Lot Count')
            for _, row in harvestable.iterrows():
                f.write(f"| **{row['Symbol']}** | {row['Description']} | {row['Tax_Category']} | {row['Lot Count']} lot(s) underwater |\n")
        else:
            f.write("*Amazing! No assets are currently held at a loss. No TLH opportunities exist right now.*\n")
            
        f.write("\n### ⏳ Capital Gains 'One-Year Wait' Screener\n")
        f.write("Profitable lots held for under 365 days are subject to your ordinary income tax rate. Waiting 1 year drops this to the much lower LTCG (15-20%) bracket.\n\n")
        f.write("| Symbol | Lots Held < 365 Days (STCG - AVOID SELLING) | Lots Held > 365 Days (LTCG - SAFE) |\n")
        f.write("|---|---|---|\n")
        
        prof_lots = lots_df[lots_df['Unrealized Gain'] > 0]
        if not prof_lots.empty:
            for sym in prof_lots['Symbol'].dropna().unique():
                sym_lots = prof_lots[prof_lots['Symbol'] == sym]
                stcg_count = len(sym_lots[sym_lots['Tax_Category'] == 'STCG (<1yr)'])
                ltcg_count = len(sym_lots[sym_lots['Tax_Category'] == 'LTCG (>1yr)'])
                f.write(f"| **{sym}** | {stcg_count} Lots Pending | {ltcg_count} Lots Safe to Sell |\n")
        else:
            f.write("| N/A | No profitable lots exist | - |\n")

        f.write("\n## 4. Recommended Replacements (1-3 Year Horizon)\n")
        f.write("For your goal of **1-3 year high percentage returns with minimal expenses and high dividends**, volatility mitigation via strong cash flow is key. The following 5 funds were dynamically selected today based on live market data, ranking highest in yield and 1-year momentum while strictly keeping Expense Ratios below `0.40%`:\n\n")
        
        print("Fetching a dynamic universe of replacement candidates from live market data...")
        candidate_tickers = market_data.get_dynamic_etf_universe()
        print(f"Discovered {len(candidate_tickers)} candidates. Fetching full historical metadata...")
        candidate_data = market_data.fetch_ticker_metadata(candidate_tickers)
        
        # Filter and Score Candidates
        scored_candidates = []
        for ticker, data in candidate_data.items():
            # STRICT QA: Must be an ETF or Mutual Fund (no individual stocks!)
            quote_type = data.get("type", "").upper()
            if quote_type not in ["ETF", "MUTUALFUND"]:
                continue
                
            er = data.get("expense_ratio_pct", 100.0)
            yld = data.get("yield", 0.0) or 0.0
            ret_1y = data.get("1y_return", 0.0) or 0.0
            ret_3y = data.get("3y_return", 0.0) or 0.0
            ret_5y = data.get("5y_return", 0.0) or 0.0
            
            # STRICT QA: Reject corrupted/empty historical data
            if ret_1y == 0.0 and ret_3y == 0.0 and ret_5y == 0.0 and yld == 0.0:
                continue
            
            # Strict constraint: ER must be <= 0.40% (or 100% means we couldn't fetch it, skip)
            if er <= 0.40:
                # Composite score optimizing for 1-3yr horizon:
                # Balances yield, heavily weights 3Y trailing return, and includes 1Y momentum
                score = (yld * 100 * 2) + (ret_3y * 100 * 1.5) + (ret_1y * 100)
                scored_candidates.append({
                    "ticker": ticker,
                    "name": data.get("name", ticker),
                    "er": er,
                    "yield": yld,
                    "1y_return": ret_1y,
                    "3y_return": ret_3y,
                    "5y_return": ret_5y,
                    "score": score
                })
                
        # Sort by best score descending and take top 5
        scored_candidates.sort(key=lambda x: x["score"], reverse=True)
        top_5 = scored_candidates[:5]
        
        f.write("| Ticker | Fund Name | Expense Ratio | Yield | 1-Year | 3-Year (Avg) | 5-Year (Avg) |\n")
        f.write("|---|---|---|---|---|---|---|\n")
        
        if not top_5:
            f.write("| N/A | No funds matched the strict ER < 0.40% criteria today. | - | - | - | - | - |\n")
            
        for c in top_5:
            r1 = f"+{c['1y_return']*100:.2f}%" if c['1y_return'] > 0 else f"{c['1y_return']*100:.2f}%"
            r3 = f"+{c['3y_return']*100:.2f}%" if c['3y_return'] > 0 else f"{c['3y_return']*100:.2f}%"
            r5 = f"+{c['5y_return']*100:.2f}%" if c['5y_return'] > 0 else f"{c['5y_return']*100:.2f}%"
            
            f.write(f"| **{c['ticker']}** | {c['name']} | `{c['er']:.2f}%` | *{c['yield']*100:.2f}%* | {r1} | {r3} | {r5} |\n")

    print(f"\n✅ Privacy-safe report successfully generated at: {report_path.absolute()}")
    print("Please open this markdown file locally to view your optimization insights.")

if __name__ == "__main__":
    generate_privacy_report()
