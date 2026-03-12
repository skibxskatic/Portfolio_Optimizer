# Portfolio Optimizer — Architectural Constraints
# Source: Claude structural audit of Portfolio_Analysis_Report, PRD.md, HOW_TO_USE.md, HOW_IT_WORKS.md
# Drop this file into: .gemini/antigravity/brain/CONSTRAINTS.md
# Priority order: CRITICAL → CORRECTNESS → OUTPUT

---

## ~~[CRITICAL-1] HSA Scoring Bucket — Wrong Objective Function~~ — ✅ COMPLETE

**Implemented:**
- HSA candidate pool now sourced from `Roth IRA` routing bucket (growth-tier: low yield, high beta)
- `score_candidate` Roth IRA branch (Sortino + 5Y + 10Y) applies to HSA candidates
- HSA table header updated to `🏥 HSA — Maximum Growth (Full Universe)` with Sortino/10Y columns
- Comment in candidate routing loop documents the rationale

**No further action required.**

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

## ~~[CORRECTNESS-1] Validator Label Mismatch — 3-Bucket Test Reporting as 4-Bucket~~ — ✅ COMPLETE

**Implemented:**
- Added `VGT` as 4th benchmark to `verify_asset_routing_logic()` in `validator.py`
- `VGT` confirms HSA growth-tier routing: low yield + high beta → `"Roth IRA"` bucket (which also feeds HSA)
- Updated docstring to document all 4 buckets including HSA relationship
- Pass message updated to: `"4-Bucket routing (Taxable, Roth IRA, 401k/Tax-Deferred, HSA growth-tier) validated."`

**No further action required.**

---

## ~~[CORRECTNESS-2] SPYM Expense Ratio — Data Fidelity Error~~ — ✅ COMPLETE

**Implemented:**
- Added `MONEY_MARKET_TICKERS = {"FDRXX", "SPAXX", "FDLXX", "VMFXX", "SWVXX"}` constant to `src/market_data.py`.
- ER guard: if `er_pct == 0.0` and ticker not in `MONEY_MARKET_TICKERS`, ER is set to `None` (fetch error), not silently left as 0.0.
- Exception handler also sets `expense_ratio_pct = None` on full fetch failure.
- `src/portfolio_analyzer.py` weighted-average ER now filters via `df[df['Expense Ratio'].notna()]` with proper weight renormalization over non-null positions only.
- `src/validator.py` SPY/SCHD ER checks updated to handle `None` (flags as fetch error and fails the check).

**No further action required.**

---

## ~~[CORRECTNESS-3] IBIT Recommendation Guard — Insufficient History~~ — ✅ COMPLETE

**Implemented:**
- Added `metrics.get_history_days(ticker)` public function to `src/metrics.py` (uses internal price cache — no extra API calls).
- After `score_candidate()`, the engine sets `cand["insufficient_history"] = True` for any fund where available history < 1095 days (3 years).
- Each bucket list is split into `*_main` (≥ 3Y) and `*_emerging` (< 3Y) before rendering.
- `write_fund_table()` refactored: row-writing extracted to `_write_fund_rows()` helper; accepts optional `emerging` list.
- Main table shows only established funds (top 5). If `emerging` is non-empty, a sub-section renders below:
  `#### Emerging Funds (Limited Track Record)` with `⚠️ < 3Y History` appended inline to each fund name.

**No further action required.**

---

## ~~[OUTPUT-1] Dollar-Weighted TLH Output — Lot Count Alone Is Not Actionable~~ — ✅ COMPLETE

**Implemented:**
- TLH candidates are now grouped by `(Symbol, Account Name)` with `Est_Loss = -sum(Unrealized Gain)`.
- Sorted by `Est_Loss` descending → `Priority` rank assigned (1 = largest harvestable loss).
- New table schema: `| Priority | Account | Symbol | Description | Tax Category | Est. Loss ($) | Underwater Lots | Wash Sale Risk |`
- `Est. Loss ($)` formatted as `($X,XXX)` using `(${est_loss:,.0f})`.
- Implements [ADVISORY-1] partial fix simultaneously: `Account Name` column now visible, separating Melissa Investments TLH from primary user's TLH by row.

**No further action required.**

---

## [ADVISORY-1] "Melissa Investments" — Managed Advisory Account Partitioning (⚠️ PARTIALLY COMPLETE)

> **TLH Account Name column:** ✅ Done — `Account Name` is now a visible column in the TLH table, so Melissa Investments' TLH rows appear separately from the primary user's rows. Wash sale cross-account scanning already includes Melissa Investments (CRITICAL-2 ✅).
>
> **Remaining open items:** Full account partitioning (separate report section, isolated metrics, separate Cap Gains screener, `accounts.config`, `managed_advisory` header label) is not yet implemented. See requirements below.

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