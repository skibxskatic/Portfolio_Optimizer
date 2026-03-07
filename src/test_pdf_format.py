import os
import io
import pandas as pd
from pathlib import Path
from markdown_pdf import Section, MarkdownPdf

def generate_test_pdf():
    print("Generating mock markdown report...")
    
    with io.StringIO() as f:
        f.write("# Portfolio Optimization Report (TEST MODE)\n\n")

        # Add generation timestamp
        timestamp = pd.Timestamp.now().strftime("%B %d, %Y at %I:%M %p")
        f.write(f"**Generated on:** {timestamp}\n\n")
        f.write(f"> **Test Run:** This report uses mock data to test the PDF layout and CSS styling.\n\n")

        # --- Section 1: High-Level Metrics ---
        f.write("## 1. High-Level Metrics\n")
        f.write(f"- **Weighted Average Expense Ratio:** `0.080%`\n")
        f.write("  - ✅ *Excellent: Your portfolio fees are highly optimized.*\n")
        f.write(f"- **Risk-Free Rate (13-Week T-Bill):** `4.50%` *(mocked)*\n")

        # --- Section 2: Asset Holding Breakdown ---
        f.write("\n## 2. Asset Holding Breakdown\n")
        f.write("| Symbol | Account Name | Account Type | Description | Current ER | Suggested Action |\n")
        f.write("|---|---|---|---|---|---|\n")
        
        mock_holdings = [
            ("VTI", "INDIVIDUAL", "Taxable Brokerage", "Vanguard Total Stock Market ETF", 0.03, "Keep"),
            ("VXUS", "INDIVIDUAL", "Taxable Brokerage", "Vanguard Total Intl Stock Index", 0.08, "Keep"),
            ("QQQ", "ROTH IRA", "Roth IRA", "Invesco QQQ Trust", 0.20, "Keep"),
            ("BND", "Health Savings Account", "HSA", "Vanguard Total Bond Market ETF", 0.03, "Keep"),
            ("FXAIX", "401k", "Employer 401k", "Fidelity 500 Index Fund", 0.015, "Keep"),
            ("EXPENSIVE", "INDIVIDUAL", "Taxable Brokerage", "High Fee Mutual Fund", 0.85, "**Evaluate** (ER 0.85%, Net 5Y: 6.5%)")
        ]
        
        for row in mock_holdings:
            f.write(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]:.3f}% | {row[5]} |\n")

        # --- Section 3: Recommended Replacement Funds ---
        f.write("\n## 3. Recommended Replacement Funds\n")
        f.write("Mock data for layout testing.\n\n")
        
        def write_mock_table(title, description, extra_cols):
            f.write(f"### {title}\n")
            f.write(f"{description}\n\n")
            
            header = "| Ticker | Fund Name | ER | Yield | Net 5Y Ret |"
            divider = "|---|---|---|---|---|"
            for col_name in extra_cols:
                header += f" {col_name} |"
                divider += "---|"
            header += " 1Y Ret | 3Y Ret | 5Y Ret |"
            divider += "---|---|---|"
            
            f.write(header + "\n")
            f.write(divider + "\n")

            for i in range(1, 6):
                row = f"| **TEST{i}** | Mock Fund {i} | `0.0{i}%` | *1.{i}0%* | +10.{i}0% |"
                for _ in extra_cols:
                    row += f" 1.{i}5 |"
                row += f" +15.{i}0% | +10.{i}0% | +10.{i}0% |"
                f.write(row + "\n")
            f.write("\n")

        write_mock_table(
            "🚀 Roth IRA — Maximum Growth",
            "Scored by Sortino Ratio + Net-of-Fees 5Y Return + 10Y Total Return.",
            ["Sortino (5Y)", "10Y Ret"]
        )
        write_mock_table(
            "💼 Employer 401k — Income & Dividends (Plan-Constrained)",
            "High-yield funds for your employer 401k. Constrained to your plan menu. Scored by Sharpe Ratio + Net-of-Fees 5Y Return.",
            ["Sharpe (5Y)"]
        )
        write_mock_table(
            "🏥 HSA — Income & Dividends (Full Universe)",
            "High-yield funds for your Health Savings Account. HSA has no plan menu constraint — full dynamic universe. Scored by Sharpe Ratio + Net-of-Fees 5Y Return.",
            ["Sharpe (5Y)"]
        )
        write_mock_table(
            "🏦 Taxable Brokerage — Tax-Efficient Growth",
            "Scored by Sharpe Ratio + Net-of-Fees 5Y Return + low-yield bonus.",
            ["Sharpe (5Y)", "Max DD (5Y)"]
        )

        markdown_content = f.getvalue()

    # CSS for table borders in the PDF output
    table_css = (
        "table { border-collapse: collapse; width: 100%; margin-bottom: 20px; font-size: 10px; table-layout: auto; }\n"
        "th, td { border: 1px solid #000; padding: 4px 6px; text-align: left; word-wrap: break-word; }\n"
        "th { background-color: #f2f2f2; font-weight: bold; }\n"
    )

    pdf_path = Path.cwd() / "PORTFOLIO_TEST_LAYOUT.pdf"
    
    print("Converting mock report to PDF...")
    pdf = MarkdownPdf(toc_level=2)
    pdf.add_section(Section(markdown_content, paper_size=(297, 2000)), user_css=table_css)
    pdf.save(str(pdf_path))

    print(f"\n✅ Test PDF successfully generated at: {pdf_path.absolute()}")
    print("Opening your personalized report...")
    
    try:
        os.startfile(str(pdf_path.absolute()))
    except Exception as e:
        print(f"⚠️ Could not auto-open the PDF: {e}")

if __name__ == "__main__":
    generate_test_pdf()
