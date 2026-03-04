import yfinance as yf
import pandas as pd
import numpy as np
import warnings

warnings.filterwarnings('ignore')

def analyze_tradeoffs():
    # Basket covering ultra-low fee index, mid-fee smart beta/dividend, and higher-fee active/thematic
    tickers = [
        "SCHD", "VYM", "VIG", "FDVV",    # Dividend / Value (Low-to-Mid ER)
        "JEPI", "JEPQ", "DGRW", "NOBL",  # Smart Beta / Covered Call (Mid-to-High ER)
        "SPY", "QQQ", "VTI",             # Broad Market (Ultra-Low ER)
        "ARKK", "FBGRX", "FNCMX",        # Active Growth / Thematic (High ER)
        "FELG", "FTEC"                   # Fidelity specific
    ]

    data = []
    print("Fetching historical data and metadata for analysis basket...")
    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="3y")
            if hist.empty:
                continue
                
            info = t.info
            er = info.get('netExpenseRatio', info.get('annualReportExpenseRatio', None))
            if er is None:
                continue
                
            if er < 0.05:
                er_pct = er * 100
            else:
                er_pct = er

            price_today = hist['Close'].iloc[-1]
            
            # 1Y Return calculation
            try:
                target_date_1y = hist.index[-1] - pd.DateOffset(years=1)
                idx_1y = hist.index.get_indexer([target_date_1y], method='nearest')[0]
                price_1y = hist['Close'].iloc[idx_1y]
                ret_1y = ((price_today / price_1y) - 1) * 100
            except:
                ret_1y = np.nan
                
            # 3Y Return calculation (Annualized)
            try:
                price_3y = hist['Close'].iloc[0]
                # Check if we actually got 3 years of data (approx 750 trading days)
                if len(hist) > 500: 
                    ret_3y_annualized = (((price_today / price_3y) ** (1/3)) - 1) * 100
                else:
                    ret_3y_annualized = np.nan
            except:
                ret_3y_annualized = np.nan
                
            # Yield
            yld = info.get('trailingAnnualDividendYield', info.get('yield', 0))
            if yld is None: yld = 0
            yld_pct = yld * 100 if yld < 1 else yld
            
            data.append({
                "Ticker": ticker,
                "ER (%)": er_pct,
                "Yield (%)": yld_pct,
                "Gross 1Y (%)": ret_1y,
                "Net 1Y (%)": ret_1y - er_pct,
                "Gross 3Y Ann (%)": ret_3y_annualized,
                "Net 3Y Ann (%)": ret_3y_annualized - er_pct
            })
        except Exception as e:
            pass # Skip silently for the quick check

    df = pd.DataFrame(data)
    
    print("\n=== Expense Ratio vs Performance Trade-off Analysis ===")
    print("Sorted by 3-Year Annualized NET Return (After Fees)")
    print("-" * 80)
    
    # Sort by 3Y Net Return
    df_sorted = df.sort_values(by="Net 3Y Ann (%)", ascending=False).round(2)
    
    # Format as string for printing
    print(df_sorted.to_string(index=False))
    
    print("\nAnalysis Categories:")
    print("Sub 0.15% ER Count:", len(df[df['ER (%)'] <= 0.15]))
    print("0.16% - 0.40% ER Count:", len(df[(df['ER (%)'] > 0.15) & (df['ER (%)'] <= 0.40)]))
    print("Above 0.40% ER Count:", len(df[df['ER (%)'] > 0.40]))

if __name__ == "__main__":
    analyze_tradeoffs()
