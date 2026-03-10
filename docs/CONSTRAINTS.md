# Portfolio Optimizer — Architectural Constraints
# Source: Claude structural audit of Portfolio_Analysis_Report, PRD.md, HOW_TO_USE.md, HOW_IT_WORKS.md
# Drop this file into: .gemini/antigravity/brain/CONSTRAINTS.md
# Priority order: CRITICAL → CORRECTNESS → OUTPUT

---

## [CRITICAL-1] HSA Scoring Bucket — Wrong Objective Function

**Problem:**
HSA is currently routed to the 401k/HSA income bucket and scored by Sharpe Ratio + yield.
HSA has a triple tax advantage (pre-tax contributions, tax-free growth, tax-free qualified withdrawals).
Income/yield optimization wastes the compounding ceiling of the most tax-privileged account in the portfolio.

**Required Fix:**
- Decouple HSA from the 401k income bucket entirely.
- Map HSA → Roth IRA scoring tier: Sortino Ratio + Net-of-Fees 5Y Return + 10Y Total Return.
- HSA recommended replacements table must be separate from 401k table and labeled:
  `🏥 HSA — Maximum Growth (Full Universe)`
- Update HOW_IT_WORKS.md Section 3 bucket description to reflect corrected rationale.

**Affected files (expected):**
- `src/portfolio_analyzer.py` — bucket routing logic
- `src/validator.py` — routing QA test (see CORRECTNESS-1)
- Report template — section label for HSA recommendations

---

## ~~[CRITICAL-2] Wash Sale Guard~~ — ✅ COMPLETE

**Implemented:**
- `SUBSTANTIALLY_IDENTICAL_MAP` constant added to `src/portfolio_analyzer.py`
- `get_substantially_identical_symbols()` and `detect_wash_sale_risk()` functions implemented
- `⚠️ YES (Cross-Account)` flag renders inline in TLH candidate table
- `verify_cross_account_wash_sale_logic()` Reality Check added to `src/validator.py`
- Synthetic test coverage: single-account, same-account identical, cross-account identical — all passing
- Melissa Investments included in cross-account scan scope

**No further action required.**

---

## [CORRECTNESS-1] Validator Label Mismatch — 3-Bucket Test Reporting as 4-Bucket

**Problem:**
`validator.py` QA output reads: `"Asset Routing QA PASSED: 4-Bucket routing logic is correct"`
Inline test description reads: `"Tests 3-Bucket routing (SCHD→401k/HSA, QQQ→Roth IRA, VTI→Taxable)"`
HSA is not independently validated as a routing target.

After CRITICAL-1 is resolved, HSA will be a fully independent bucket and MUST have its own routing test.

**Required Fix:**
- Add HSA as a fourth independent routing test case in `validator.py`.
- Use a known high-growth ETF (e.g., QQQ or VGT) as the HSA routing test target.
- Update the QA pass message to accurately reflect 4-bucket coverage.

**Affected files (expected):**
- `src/validator.py`

---

## [CORRECTNESS-2] SPYM Expense Ratio — Data Fidelity Error

**Problem:**
SPYM (SPDR Portfolio S&P 500 ETF) is reported with ER = 0.000%.
Actual ER is 0.03%. This is not a zero-fee money market fund.

If weighted average ER is computed from this field, the portfolio-level metric is contaminated.

**Required Fix:**
- Audit all non-money-market positions reporting 0.000% ER.
  Money market funds (FDRXX, SPAXX, FDLXX, SPYM's cash sleeve) are the only valid 0.000% entries.
- For any non-money-market fund with 0.000% ER, fall back to a hardcoded known-good ER floor
  or flag as `ER_FETCH_ERROR` rather than silently using 0.
- Exclude `ER_FETCH_ERROR` flagged positions from the weighted average ER calculation.

**Affected files (expected):**
- `src/portfolio_analyzer.py` — ER fetch and weighted average computation
- ER validation logic in `src/validator.py` API sanity check

---

## [CORRECTNESS-3] IBIT Recommendation Guard — Insufficient History

**Problem:**
IBIT (iShares Bitcoin Trust ETF) has < 26 months of price history (inception ~Jan 2024).
It is currently ranked #2 in Roth IRA recommendations with a 5Y Sortino of 0.873,
but both 3Y Return and 5Y Return fields show 0.00% — the engine's own data confirms no history.
A Sortino score computed on 26 months is not a valid 5Y metric.

**Required Fix:**
- Any fund with < 36 months of price history must be assigned `INSUFFICIENT_HISTORY` status.
- `INSUFFICIENT_HISTORY` funds:
  - May still appear in recommendations.
  - Must display a `⚠️ < 3Y History` inline label.
  - Must NOT be ranked against funds with full 5Y history using the same Sortino/Sharpe score.
  - Must be placed in a separate sub-section: `"Emerging Funds (Limited Track Record)"` below the main table.

**Affected files (expected):**
- `src/portfolio_analyzer.py` — recommendation scoring and ranking logic
- Report template — recommendations table rendering

---

## [OUTPUT-1] Dollar-Weighted TLH Output — Lot Count Alone Is Not Actionable

**Problem:**
TLH candidates are currently listed with only symbol, description, tax category, and lot count.
Without cost basis delta and current market value per lot, there is no way to prioritize which
losses to harvest first or assess total harvestable loss against the $3,000 ordinary income cap.

**Required Fix:**
TLH candidate table must include the following additional columns:
- `Est. Loss ($)` — sum of (cost basis - current value) across all underwater lots for that symbol
- `Priority Rank` — ordered by Est. Loss descending
- `Wash Sale Risk` — flag from CRITICAL-2 guard

The positions CSV already contains share quantities and cost basis data per lot.
This is a report output change, not a data availability problem.

**Affected files (expected):**
- `src/portfolio_analyzer.py` — TLH output block
- Report template — TLH table schema

---

## [ADVISORY-1] "Melissa Investments" — Managed Advisory Account Partitioning

**Clarified Context:**
"Melissa Investments" is a third-party account managed by the primary user on behalf of the account holder.
It is NOT a joint account. The primary user manages performance but does not take personal trades from it.

**Correct behavior — this account is `managed_advisory` type:**
- It IS a separate tax entity. Her TLH losses offset HER taxes, not the primary user's $3,000 cap.
- Performance recommendations ARE wanted (user actively manages allocation).
- The account must be visually and computationally partitioned from the primary user's accounts.

**Required Fix:**

1. Add `accounts.config` with an `account_type` field. Valid values:
   - `primary` — primary user's own accounts (INDIVIDUAL, Roth IRA, HSA)
   - `managed_advisory` — third-party accounts managed by primary user
   - (Future) `joint` — shared accounts with co-equal ownership

   Example config:
   ```
   INDIVIDUAL = primary
   Roth IRA = primary
   Health Savings Account = primary
   Cash Management (Individual - TOD) = primary
   Melissa Investments = managed_advisory
   ```

2. `managed_advisory` accounts must:
   - Be included in cross-account wash sale scans (already implemented in CRITICAL-2 ✅)
   - Generate their own performance recommendations and scoring (do NOT suppress)
   - Render in a clearly separated report section: `📋 Managed Account — Melissa Investments`
   - Display a header label: `[Managed Advisory — Performance recommendations only. Execution authority belongs to account holder.]`
   - NOT be included in the primary user's weighted average ER calculation
   - NOT be included in the primary user's portfolio-level high-level metrics
   - Have their own isolated TLH candidate table with a header note:
     `[Tax impact applies to account holder's tax return, not primary user's]`
   - Have their own isolated Capital Gains screener table

3. HOW_IT_WORKS.md should document the `managed_advisory` account type in a new Section 9.

**Affected files (expected):**
- New `accounts.config`
- `src/portfolio_analyzer.py` — metrics aggregation, TLH generation, report sectioning
- Report template — Melissa section header and label rendering
- `HOW_IT_WORKS.md` — Section 9