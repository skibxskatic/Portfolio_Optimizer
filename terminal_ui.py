import parser
import market_data
import pandas as pd
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
import validator

console = Console()

def run_terminal_ui():
    """
    Terminal UI for the Fidelity Optimizer.
    Strictly follows the Privacy Guard rule: NEVER print raw dollar amounts to stdout.
    """
    console.print(Panel("[bold blue]Fidelity Portfolio Optimizer[/bold blue]\n[green]Initializing Local Data Engine...[/green]"))
    
    # PRE-FLIGHT QA: Run all reality checks before any analysis.
    # This ensures the data and API are clean before displaying results.
    print("--- PRE-FLIGHT QA CHECKS ---")
    if not validator.verify_yfinance_sane() or not validator.verify_dynamic_screener():
        console.print("\n[red]❌ PRE-FLIGHT FAILED: Engine data is corrupted or filters are failing.[/red]")
        console.print("[red]Aborting terminal analysis to protect data integrity.[/red]")
        return
    print("--- ALL QA PASSED, BEGINNING ENGINE RUN ---\n")

    data_dir = Path("data")
    positions_files = list(data_dir.glob("Portfolio_Positions*.csv"))
    history_files = list(data_dir.glob("Accounts_History*.csv"))
    
    if not positions_files or not history_files:
        console.print("[red]Error: Could not find Portfolio_Positions.csv or Accounts_History.csv in data/[/red]")
        return
        
    with console.status("[bold green]Loading and parsing local CSV data...[/bold green]") as status:
        df = parser.load_fidelity_positions(positions_files[0])
        
        hist_dfs = [parser.load_fidelity_history(f) for f in history_files]
        hist_df = pd.concat(hist_dfs, ignore_index=True) if hist_dfs else pd.DataFrame()
        
        lots_df = parser.unroll_tax_lots(df, hist_df)
        
        today = pd.to_datetime('today')
        lots_df['Holding_Days'] = (today - lots_df['Purchase Date']).dt.days
        lots_df['Tax_Category'] = lots_df['Holding_Days'].apply(
            lambda x: 'LTCG (>1yr)' if pd.notna(x) and x > 365 else ('STCG (<1yr)' if pd.notna(x) else 'Unknown')
        )
        
        symbols = df['Symbol'].dropna().unique().tolist()
        status.update("[bold cyan]Fetching live market data securely...[/bold cyan]")
        metadata = market_data.fetch_ticker_metadata(symbols)
        
        df['Expense Ratio'] = df['Symbol'].map(lambda x: metadata.get(x, {}).get('expense_ratio_pct', 0.0))
        total_value = df['Current Value'].sum()
        df['Weighted_ER'] = df['Expense Ratio'] * (df['Current Value'] / total_value)
        portfolio_weighted_er = df['Weighted_ER'].sum()

    console.print("\n[bold cyan]--- 1. PORTFOLIO HEALTH ---[/bold cyan]")
    er_color = "green" if portfolio_weighted_er <= 0.40 else "red"
    console.print(f"Weighted Average Expense Ratio: [{er_color}]{portfolio_weighted_er:.3f}%[/{er_color}]")
    if portfolio_weighted_er > 0.40:
        console.print("[red]⚠️ Warning: Aggregate fee bloat detected. Consider replacing high ER funds.[/red]")
    else:
        console.print("[green]✅ Excellent: Your portfolio fees are highly optimized.[/green]")

    console.print("\n[bold cyan]--- 2. TAX-LOSS HARVESTING OPPORTUNITIES ---[/bold cyan]")
    tlh_lots = lots_df[lots_df['Unrealized Gain'] < 0]
    if tlh_lots.empty:
        console.print("[green]No lots are currently underwater. No TLH opportunities exist.[/green]")
    else:
        harvestable = tlh_lots.groupby(['Symbol', 'Description']).size().reset_index(name='Lot Count')
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Symbol", style="cyan")
        table.add_column("Description")
        table.add_column("Underwater Lots", justify="right", style="red")
        
        for _, row in harvestable.iterrows():
            table.add_row(str(row['Symbol']), str(row['Description']), str(row['Lot Count']))
            
        console.print(table)
        console.print("[italic yellow]Recommendation: Consider selling these lots to harvest losses against capital gains.\nRe-buy a highly correlated (but not substantially identical) fund to avoid wash sales.[/italic yellow]")

    console.print("\n[bold cyan]--- 3. CAPITAL GAINS SCREENER ---[/bold cyan]")
    prof_lots = lots_df[lots_df['Unrealized Gain'] > 0]
    if not prof_lots.empty:
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Symbol", style="cyan")
        table.add_column("STCG (<365 Days)", style="red", justify="right")
        table.add_column("LTCG (>365 Days)", style="green", justify="right")
        
        for sym in prof_lots['Symbol'].dropna().unique():
            sym_lots = prof_lots[prof_lots['Symbol'] == sym]
            stcg = len(sym_lots[sym_lots['Tax_Category'] == 'STCG (<1yr)'])
            ltcg = len(sym_lots[sym_lots['Tax_Category'] == 'LTCG (>1yr)'])
            if stcg > 0 or ltcg > 0:
                table.add_row(str(sym), f"{stcg} pending", f"{ltcg} safe")
                
        console.print(table)
        console.print("[italic yellow]Recommendation: Only sell LTCG lots when taking profits to minimize tax burden.[/italic yellow]")
    
    console.print("\n[bold green]Report generation complete. Check Portfolio_Analysis_Report.md for full details.[/bold green]")

if __name__ == "__main__":
    run_terminal_ui()
