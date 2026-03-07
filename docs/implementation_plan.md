# Architecture Plan: Portfolio Optimizer Overhaul

## 1. Rename Project to "Portfolio Optimizer"
Remove all "Fidelity"-specific branding from docs, batch files, and scripts. The project name, titles, and instructions become platform-agnostic.

**Files affected:** `README.md`, `Fidelity_Optimizer.bat` → `Portfolio_Optimizer.bat`, `docs/PRD.md`, `docs/HOW_IT_WORKS.md`, `docs/HOW_TO_USE.md`, `run_optimizer.ps1`, `run_pdf_extractor.ps1`

---

## 2. Segregate HSA and 401k Routing

#### [MODIFY] `src/portfolio_analyzer.py`
- `ACCOUNT_TYPE_MAP`: Map HSA → `"HSA"`, 401k rows → `"Employer 401k"`
- `classify_routing_bucket()`: Return `"Tax-Deferred"` (replaces `"401k / HSA"`)
- `score_candidate()`: Update branch match to `"Tax-Deferred"`
- Split `k401_hsa_candidates` → `k401_candidates` + `hsa_candidates`
- Constrain only `k401_candidates` to plan menu. HSA gets full dynamic universe.
- Output **4 replacement tables**: Roth, Taxable, Employer 401k, HSA

#### [MODIFY] `src/validator.py`
- Update SCHD expected route → `"Tax-Deferred"`

---

## 3. File Format Auto-Dispatcher

#### [NEW] `src/file_ingestor.py`
3-layer detection pipeline:
- **Layer 1 — Extension:** `.csv`→pandas, `.xlsx`→pandas, `.pdf`→inline pypdf extract, `.txt`→Layer 2
- **Layer 2 — Content Sniff:** Delimiter test (CSV?) vs ticker pattern test (extracted PDF text?)
- **Layer 3 — Column Validation:** For CSV/Excel, require ticker-like + value-like columns

Functions:
- `detect_format(path)` → `"csv" | "pdf" | "extracted_text" | "excel" | "unknown"`
- `ingest_401k_file(path)` → `(holdings_df, plan_menu_tickers)` — dispatches to correct parser
- `discover_401k_files(data_dir)` → scans drop folder for any file with "401k" in name

**Inline PDF extraction:** If a `.pdf` is found, the engine uses `pypdf` directly within the Python process to extract text — no separate batch file step needed. The `Fidelity_401k_PDF_Extractor.bat` and `run_pdf_extractor.ps1` become deprecated/removed.

#### [MODIFY] `src/401k_parser.py`
- Remove "Fidelity NetBenefits" from docstring
- Generalize noise prefixes in `extract_plan_menu()`
- Add Strategy B fallback regex in `extract_current_holdings()`
- Add `parse_401k_csv()` for structured CSV/Excel ingestion

#### [MODIFY] `src/portfolio_analyzer.py`
- Replace `k401_parser.find_401k_options_file()` call with `file_ingestor.discover_401k_files()` + `file_ingestor.ingest_401k_file()`

#### [DELETE] `Fidelity_401k_PDF_Extractor.bat`, `src/run_pdf_extractor.ps1`

---

## 4. Documentation Sync
- `PRD.md`: 4-bucket strategy, remove Fidelity branding, update routing/metric tables
- `HOW_IT_WORKS.md`: 4-bucket explanation, remove Fidelity branding
- `HOW_TO_USE.md`: Remove PDF Extractor step, explain "just drop any file", 4 recommendation tables
- `README.md`: Rename, remove PDF Extractor from Getting Started

---

## Verification
1. Syntax check all modified `.py` files
2. Run `validator.py` standalone (routing QA must pass with new bucket names)
3. Full engine run: confirm 4 separate recommendation tables, HSA unconstrained, 401k constrained
4. Drop a raw `.pdf` into `Drop_Financial_Info_Here/` and confirm inline extraction works
