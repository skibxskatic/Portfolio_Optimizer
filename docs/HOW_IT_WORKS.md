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

The report's **Asset Holding Breakdown** groups your funds by account type — Taxable Brokerage, Roth IRA, HSA, and Employer 401k — each under its own sub-header. For each non-401k fund, the Optimizer asks two questions:
1. **Are you overpaying for this?** It flags any fund that charges you more than 0.40% a year in fees (the "Expense Ratio").
2. **Is it worth the fee?** It calculates the **Net-of-Fees Return** over the last 5 years. If you are paying a high fee, but the fund is actually making you *more* money than the cheaper alternatives even after the fee is subtracted, the Optimizer will happily tell you to "Keep" it. It only tells you to "Evaluate" or "Replace" a fund if it is mathematically underperforming cheaper options.

Your 401k holdings are shown as a summary with a pointer to the dedicated **401k Plan Analysis** section, where they receive full scoring, rebalance recommendations, and underperformance flags.

## 5. Finding Replacements

If the Optimizer thinks you can do better, it goes out to the internet, scrapes a live list of the top 60-80 ETFs and Mutual Funds in the world right now, and grades them.

It **does not recommend individual stocks** (like Apple or Tesla). It only recommends diversified index funds and ETFs to ensure your portfolio remains safe and stable.

It scores these replacements using advanced risk mathematics:
* **For your Taxable Brokerage and 401k:** It uses the **Sharpe Ratio**, which measures how smooth and consistent a fund's growth is. It actively penalizes funds that are a wild rollercoaster.
* **For your Roth IRA and HSA:** It uses the **Sortino Ratio**, which is similar, but it *only* penalizes a fund if it crashes downward. It doesn't penalize a fund for unexpectedly shooting upward, which is exactly what you want in a permanently tax-free growth account.

**Note on emerging funds:** Any fund with less than 3 years of price history is flagged with `⚠️ < 3Y History` and shown in a separate "Emerging Funds" sub-section below each bucket's main ranked table. This prevents a fund's short-term Sortino score from being compared head-to-head against a fund with 10 years of data.

## 6. 401k Plan Evaluation

If you drop your 401k **Investment Options PDF** (after extracting the text) into the `Drop_Financial_Info_Here/` folder, the Optimizer will automatically:

1. **Read your current 401k holdings** — It detects the funds you currently own, their balances, and cost basis directly from your Investment Options page.
2. **Discover your plan menu** — It dynamically extracts *every* fund your employer offers in the plan. No hardcoding required — it works for any employer.
3. **Constrain recommendations to your plan** — Unlike the Roth IRA or Taxable accounts (where you can buy anything), your 401k is limited to the funds in your employer's menu. The Optimizer respects this constraint and **only recommends funds you can actually buy** in your 401k.
4. **Identify Rebalance Opportunities** — It highlights the top 5 highest-scoring funds in your plan that you *don't* currently hold, giving you exact reasons why you might want to switch to them.
5. **Flag Underperforming Holdings** — If any fund you currently hold ranks in the bottom half of your employer's menu, it flags it for a potential allocation reduction.

This means the 401k analysis section in your report gives you a complete, personalized scorecard of your specific employer plan.

## 7. Age-Aware 401k Allocation Recommendations

If you have a 401k plan, the Optimizer goes one step further: it tells you **exactly what percentage to put in each fund** based on how close you are to retirement.

**How it works:**

1. **Your Investor Profile:** The Optimizer looks for a file called `investor_profile.txt` in the `Drop_Financial_Info_Here/` folder. This simple text file contains your birth year and target retirement year. We recommend completing this file for the most accurate, personalized analysis. If it doesn't exist, the Optimizer uses default assumptions and notes it in the report.

2. **The Glide Path:** Based on how many years you have until retirement, the Optimizer uses a "glide path" — a well-established investment principle where younger investors hold more stocks (higher growth, more risk) and gradually shift toward bonds (lower growth, lower risk) as retirement approaches:
   - **40+ years out:** 90% stocks / 10% bonds
   - **25 years out:** 80% stocks / 20% bonds
   - **10 years out:** 60% stocks / 40% bonds
   - **At retirement:** 50% stocks / 50% bonds
   - **7 years past retirement:** 30% stocks / 70% bonds

3. **Fund Classification:** The Optimizer automatically categorizes every fund in your employer's plan and determines your **Plan Objective** (e.g., "Maximum Growth" for young investors vs. "Income & Stability" for those near retirement).

4. **Score-Weighted Allocation:** Within each asset class, the top-scoring funds receive a larger share of the allocation. Every recommended fund gets at least a 5% minimum allocation.

5. **The Recommendation Table:** The report shows a clear table with each recommended fund, its asset class, your current percentage, the target percentage, the change needed, and a simple action word (Add, Increase, Reduce, Hold, or Remove).

## 8. Age-Aware Personalization & Risk Tolerance

Beyond 401k allocation, the Optimizer uses your investor profile to personalize recommendations across **every** account type:

- **Risk Tolerance:** You can set your risk tolerance in your investor profile (`very_conservative` through `very_aggressive`). If you don't, the Optimizer auto-calculates it from your age and retirement year. This controls how the Optimizer balances fund *performance* against fund *stability* — conservative investors get recommendations that prioritize steadiness, while aggressive investors get maximum-growth picks.
- **Stability Score:** Every fund receives a stability score (0-100) based on how small its worst crash was and how closely it tracks the overall market. This is blended with the performance score based on your risk tolerance.
- **Risk-Calibrated Scoring:** The mathematical weights used to score replacement funds shift based on how many years you have until retirement. Young investors get higher weight on growth metrics; near-retirement investors get higher weight on risk and drawdown metrics.
- **Portfolio Risk Profile:** Section 1 of the report compares your actual equity allocation (across all accounts) to the target for your age, flagging if rebalancing is needed.
- **Holdings Flags:** If you hold conservative funds (bonds, stable value) in a growth account like Roth IRA when you're young, or aggressive high-beta funds when you're near retirement, the report flags it in the Suggested Action column.
- **Replacement Penalties:** Replacement fund candidates that are age-inappropriate for your Roth IRA (e.g., bonds for young investors, high-beta for near-retirement) receive a soft scoring penalty.
- **TLH Urgency:** Tax-loss harvesting candidates are labeled with urgency levels — "High" for near-retirement investors who have a shorter window to utilize harvested losses.

## 8a. Portfolio Rebalancing Plan (Section 5f)

The Optimizer now tells you **exactly how to allocate** your uninvested cash across recommended funds for each account:

1. **Core Position Detection:** If you have money sitting in a money-market fund (like SPAXX or FDRXX), the Optimizer automatically detects it and treats it as deployable cash.
2. **Score-Weighted Allocation:** For each account (Roth IRA, Taxable Brokerage, HSA), the Optimizer takes the top-scoring recommended funds and assigns each a target allocation percentage based on its score. Every fund gets at least 5% to maintain diversification.
3. **Existing Holdings Comparison:** If you already hold funds in the account, the report shows how each existing fund's key metric (Sortino for Roth/HSA, Sharpe for Taxable) compares against the top recommendation, so you can decide whether to keep or replace.
4. **Manual Override:** You can specify exact contribution amounts in your investor profile instead of relying on auto-detection.

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
