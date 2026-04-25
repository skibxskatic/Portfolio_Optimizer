# Design: Rewrite `classify_asset_class()` with Data-First Classification

**Date:** 2026-03-21
**Status:** Approved (rev 2 — post spec review)
**Scope:** `src/metrics.py`

## Problem

`classify_asset_class()` relies on `info['category']` which is often `None` for mutual funds. The fallback fund-name heuristics cause misclassification — e.g., CDDYX ("Columbia Dividend Income Fund", a Large Value equity fund) is classified as Bond because "income fund" matches the Bond keyword list. This corrupts 401k allocation percentages in Section 5e.

## Solution

Replace the current heuristic-heavy approach with a data-first classification using yfinance's `funds_data` API, which provides:

1. `funds_data.fund_overview['categoryName']` — the category shown on Yahoo Finance (e.g., "Large Value")
2. `funds_data.asset_classes` — quantitative allocation breakdown (stockPosition, bondPosition, cashPosition)

When data is insufficient, return `"UNCLASSIFIED"` + stderr warning instead of guessing.

## Data Source Priority Chain

```
1. funds_data.fund_overview['categoryName']  →  keyword match
2. funds_data.asset_classes                  →  quantitative thresholds
3. info['category']                          →  fallback for ETFs (funds_data unavailable)
4. FAIL → return "UNCLASSIFIED" + stderr warning
```

## Classification Logic

### Step 1 — categoryName keyword matching

Applied to whichever category string is available (`fund_overview['categoryName']` or `info['category']`).

**IMPORTANT: Order matters.** Must check in this order since keywords overlap (e.g., "Foreign Large Value" contains "value" which is a US Equity keyword, but "foreign" is checked first):

1. **Stable Value / Money Market:** `money market`, `stable value`, `ultra-short`, `ultrashort`
2. **Bond:** `bond`, `fixed income`, `intermediate`, `government`, `treasury`, `inflation`, `high yield`
3. **Intl Equity:** `foreign`, `international`, `world`, `global`, `emerging`, `europe`, `pacific`, `intl`
4. **US Equity:** `large`, `mid`, `small`, `s&p`, `nasdaq`, `technology`, `growth`, `value`, `blend`

Changes from current implementation:
- `"income"` removed from Bond keywords — root cause of CDDYX misclassification
- `"intl"` added to Intl Equity keywords — Yahoo Finance abbreviates "International" as "Intl" in some categories

### Step 2 — asset_classes quantitative fallback

When categoryName doesn't match any keywords (or is absent):

- `bondPosition >= 0.6` → `"Bond"`
- `stockPosition >= 0.6` → check categoryName for foreign/intl keywords → `"Intl Equity"` or `"US Equity"`
- `cashPosition >= 0.6` → `"Stable Value"`
- Nothing dominant → `"UNCLASSIFIED"`

Note: Actual bond/income funds that lack a category string will still be correctly classified here via their quantitative allocation (bondPosition). No coverage lost from removing heuristics.

### Step 3 — info['category'] fallback

For ETFs where `funds_data` throws an exception, apply the same keyword matching from Step 1 against `info['category']`.

### Step 4 — Fail with visibility

- `sys.stderr.write()` warning with ticker, available categoryName, and asset_classes data
- Return `"UNCLASSIFIED"`

## Caching

- New `_funds_data_cache: dict` alongside existing `_info_cache`
- New `_get_funds_data(ticker) -> Optional[FundsData]` helper with try/except returning `None`
- **`clear_cache()` must be updated** to also clear `_funds_data_cache`

## Error Handling

- `funds_data` access wrapped in try/except (money-market funds like SPAXX throw "No Fund data found")
- `fund_overview` or `asset_classes` may be missing/empty — each step guards with `if` checks
- All failures funnel to the UNCLASSIFIED + warning path

## Parallel Fix: `detect_benchmark()`

`detect_benchmark()` (metrics.py line 227) has the same `"income"` keyword bug — a Large Value fund like CDDYX would be benchmarked against AGG (bond index) instead of SPY. Fix in same pass:
- Remove bare `"income"` from Bond keyword list in `detect_benchmark()`
- Add `funds_data.fund_overview['categoryName']` as primary category source (same pattern as `classify_asset_class`)

## Downstream Impact

All `asset_class` consumers in `portfolio_analyzer.py` use `.get('asset_class', 'US Equity')`:

| Line | Context | Impact of UNCLASSIFIED |
|------|---------|----------------------|
| 327 | `_get_age_flag_text()` — checks Bond/Stable Value | Defaults to US Equity — acceptable (age flag skipped) |
| 375 | Verdict table "Why" column | Defaults to US Equity — acceptable (display) |
| 620 | Section 1 Risk Profile — equity vs bond split | **Miscount risk** — but UNCLASSIFIED is rare; stderr warning makes it debuggable |
| 659 | Section 2 age-inappropriate flagging | Defaults to US Equity — acceptable |
| 910 | Section 4 Roth IRA age penalty | Defaults to US Equity — acceptable |
| 1194 | Section 5e allocation | Excluded — `class_funds` dict only has 4 keys |
| 1267 | Section 5e "Remove" rows | Defaults to US Equity — display only |
| 1279 | Section 5e equity/bond split | **Miscount risk** — same as line 620 |

**Decision:** No changes to portfolio_analyzer.py. The UNCLASSIFIED case should be extremely rare (only triggers when ALL of: `fund_overview`, `asset_classes`, and `info.category` are missing/unrecognized). The stderr warning makes it immediately visible for troubleshooting. If it becomes common, we add explicit handling in a follow-up.

## Files Changed

| File | Change |
|---|---|
| `src/metrics.py` | Rewrite `classify_asset_class()`, add `_get_funds_data()` helper + `_funds_data_cache`, update `clear_cache()`, fix `detect_benchmark()` `"income"` bug |

## What Gets Removed

- All fund name heuristic matching (lines 269-279)
- The `return "US Equity"` silent default (line 281)
- Bare `"income"` keyword from `detect_benchmark()` Bond check (line 227)

## Validation Test Matrix

| Ticker | Expected Class | Tests |
|---|---|---|
| CDDYX | US Equity | Was misclassified as Bond — primary motivator |
| VBTLX | Bond | Bond fund via fund_overview + asset_classes |
| VTIAX | Intl Equity | Foreign Large Blend category |
| SPAXX | Stable Value | funds_data throws — falls to info/UNCLASSIFIED |
| SPY | US Equity | ETF — uses info['category'] fallback |
| AGG | Bond | ETF bond fund |
