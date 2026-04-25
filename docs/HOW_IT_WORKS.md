# How the Portfolio Optimizer Works (A Guide for Non-Technical Users)

> [!INFO] Rules
> See [[CONSTRAINTS]] for the technical and architectural guardrails.

Welcome! If you're wondering what exactly is happening behind the scenes when you double-click the `Portfolio_Optimizer.ps1` file, this guide is for you. 

We've designed this tool to act like a mathematically rigorous, entirely private, and incredibly fast financial advisor. It runs on both **Windows** (`Portfolio_Optimizer.ps1`) and **macOS** (`Portfolio_Optimizer_Mac.app`).

For quick data maintenance without running a full analysis, you can use the **`Check_History_Health.ps1`** tool in the project folder.

---

## 1. Absolute Privacy First

The very first thing the Optimizer does is read the CSV and PDF files you dropped into the `Drop_Financial_Info_Here` folder. 

**This happens entirely on your local computer.** The Optimizer never uploads your account balances, the number of shares you own, or your account numbers to the internet. The only information it requests from the internet (specifically from Yahoo Finance) is public, generalized data—like "What is the current price of SPY?" or "What is the expense ratio of FXAIX?".

## 1a. Automatic Repo Hygiene

To keep your workspace clean, the Optimizer automatically **consolidates your transaction history**. If you drop multiple `Accounts_History` CSV files into the folder, the engine will merge them into a single, deduplicated master file named with the date range of your data (e.g., `Accounts_History_CONSOLIDATED_2020_to_2026.csv`). The individual files are then moved to an `archived/` folder automatically.

## 1b. Pre-Flight History Range Check

Before the heavy processing begins, the Optimizer scans your consolidated history and reports the **exact date range** it covers (e.g., *2020-05-14 to 2026-03-12*). 
- It tells you exactly how far back you need to go to cover your oldest purchases.
- It calculates the **percentage of your portfolio missing history** and flags it in the report summary.
- It provides an interactive pause, allowing you to stop and collect more data if you see a gap.

## 2. Pre-Flight "Reality Checks"

Before the Optimizer gives you any advice, it runs a series of **Quality Assurance (QA) checks** to make sure the data it pulled from the internet isn't broken or corrupted. 
* It checks known, stable funds (like the S&P 500) to ensure their fees and yields look exactly like they should.
* If Yahoo Finance is glitching and accidentally reports that a fund went up 1,000,000% today, the Optimizer will detect the impossibly broken data and instantly shut itself down rather than giving you bad advice based on a glitch.

## 3. The 4-Bucket "Smart Routing" Strategy

Not all investment accounts are taxed the same way. The Optimizer uses a **5-Tier Stable Routing Strategy** to decide which funds belong in which accounts. This hierarchy ensures that your core investments (like the S&P 500) don't jump between accounts just because the market was volatile last week:

1. **Golden Whitelist:** Your most foundational funds (like VTI, VOO, or QQQ) are permanently "locked" to their most tax-efficient accounts.
2. **High-Yield Anchors:** Certain types of investments that pay high dividends (like REITs or BDCs) are automatically routed to your 401k to avoid huge tax bills.
3. **Category Anchoring:** The Optimizer looks at the *long-term category* of a fund (e.g., "Technology" vs. "Bonds") to decide where it belongs.
4. **3-Year Volatility Check:** For all other funds, it looks at 3 full years of data to ensure its routing decision is based on long-term behavior, not a short-term market spike.
5. **Default Taxable:** Anything it doesn't recognize defaults to your taxable account for safety.

**The result is a "Fluctuation-Proof" strategy:**

- **Roth IRA (Maximum Growth):** Your highest-growth, most aggressive funds belong here. All growth is permanently tax-free.
- **Employer 401k (Income & Dividends):** High-yield funds that pay dividends belong here so those dividends aren't taxed every year.
- **HSA (Triple-Tax Growth):** Since all growth is tax-free and you can invest in anything, the Optimizer treats your HSA like a second Roth IRA — focusing on maximum long-term growth.
- **Taxable Brokerage (Tax-Efficient Growth):** Only funds that grow steadily with very low dividends belong here, minimizing your annual tax drag.

## 4. Grading Your Current Funds

The report now organizes your data by **Account Analysis**. Each sub-section (e.g., *Joint Brokerage*, *Roth IRA*) contains its own dedicated holdings table. For each fund, the Optimizer asks two questions:
1. **Are you overpaying for this?** It flags any fund that charges you more than 0.40% a year in fees (the "Expense Ratio").
2. **Is it worth the fee?** It calculates the **Net-of-Fees Return** over the last 5 years. If you are paying a high fee, but the fund is actually making you *more* money than the cheaper alternatives even after the fee is subtracted, the Optimizer will happily tell you to "Keep" it. It only tells you to "Evaluate" or "Replace" a fund if it is mathematically underperforming cheaper options.

## 5. Account Analysis & Action Plans

Instead of a generic list of recommendations, the report now provides a **Consolidated Target Portfolio** blueprint for every single account you own.

### 5a. Strategy-Aligned Scoring
Within each account section, the engine scores your holdings using risk mathematics tailored to that account's purpose:
*   **Taxable Accounts (Joint, Individual):** Uses the **Sharpe Ratio** (reward per unit of total risk) and rewards funds with low dividend yields to minimize annual tax drag.
*   **Tax-Free Accounts (Roth IRA, HSA):** Uses the **Sortino Ratio** (reward per unit of *downside* risk) and prioritizes aggressive growth. Since growth is tax-free, the engine ignores "good" upward volatility and focuses on maximizing your total compounding speed.

### 5b. The "🔴 Sell & Consolidate" Label
In each account section, look for the **Candidates for Consolidation** table.
- If an existing fund lags significantly behind the top-ranked alternatives, it is marked with a **🔴 Sell & Consolidate** instruction.
- The engine calculates the **"Gap vs Best"** — showing you exactly how much performance you are losing by holding that fund instead of the top recommendation.

### 5c. Target Allocation Blueprint
Each account section includes a target percentage table (e.g., 28.4%, 15.2%). 
- **Action:** Sell all funds marked "🔴 Sell" and re-distribute the entire account value according to these percentages.
- **Precision:** The target numbers are mathematically guaranteed to sum to exactly **100.0%**, making it easy to input your new elections into Fidelity.

### 5d. Account-Specific Cash Mapping
If you have uninvested cash (like SPAXX or CORE) sitting in an account, the report tells you exactly how much is available *in that specific account* and how to deploy it according to the target blueprint.

## 6. Specialized 401k Plan Scorecard

Your **Employer 401k** section is the most advanced. Because you are restricted to a small menu of funds, the Optimizer:
1. **Discovers your plan menu** — It dynamically extracts *every* fund your employer offers.
2. **Scores everything** — It ranks every fund in your plan from #1 to the bottom based on your age and retirement horizon.
3. **Identifies Gaps** — It highlights top-scoring funds you *don't* currently hold and flags your weakest holdings for removal.
4. **Age-Aware Glide Path:** It calculates exactly what percentage to put in each fund based on a piecewise linear "glide path" (e.g., 90% stocks for younger investors, 50% for those near retirement).

## 7. Age-Aware Personalization & Risk Tolerance

The Optimizer uses your **Investor Profile** (`investor_profile.txt`) to personalize everything:
- **Risk Tolerance:** Adjusts how much performance is traded for stability (Stability Score).
- **Time Horizon:** Shifts the "Lookback Zone" — younger investors get higher weight on long-term growth; near-retirement investors get higher weight on safety and drawdown protection.
- **Horizon Match:** If you hold "lazy" bonds in a growth account like a Roth IRA while you're young, the report will flag it as age-inappropriate.

## 9. Saving You Taxes (Harvesting & Capital Gains)

Finally, it looks at the exact day you bought every single share in your **taxable accounts**:
* **Tax Snapshot:** At the top of the Tax Optimization section, the report shows a one-line summary: the number of positions with harvestable losses and their total estimated value, plus the number of positions with pending short-term capital gains exposure.
* **Tax-Loss Harvesting:** If you bought shares in a taxable account that have gone down in value, the Optimizer will flag them. Selling these "underwater" shares allows you to deduct the loss from your taxes. The Optimizer **prioritizes these by dollar impact**, showing you exactly how much you can save in taxes (Estimated Tax Savings).
* **The "One-Year Wait" Screener:** If you bought shares less than a year ago that have gone *up* in value, selling them now will trigger high "Short-Term Capital Gains" taxes. The Optimizer flags these and tells you exactly how many are safely past the 1-year mark.
* **The "De Minimis" Override:** If you have a short-term gain that is incredibly tiny (less than 1% of the value of the shares), the Optimizer will flag it as "Safe to Reallocate." The tax hit is so small that it's mathematically better to just sell it now and move the money into a better fund.

## 10. The Final Report

The Optimizer takes all of this math and bundles it into two report formats:

* **Interactive HTML Report** — Opens automatically in your browser with a **sticky sidebar table of contents** that highlights your current section as you scroll, collapsible methodology sections, and professional styling. This is the primary way to read your report.
* **PDF Report** — A continuous, single-page PDF saved alongside the HTML for offline sharing or printing.

The report starts with an **Executive Summary** featuring a ⚡ **Immediate Execution Steps** table (your highest-priority actions and their tax impact), followed by detailed analysis in Sections 1-5, then closes with **Next Steps** and **Why These Recommendations**.
