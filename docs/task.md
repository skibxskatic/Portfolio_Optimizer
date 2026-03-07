# Portfolio Optimizer Overhaul

## Phase 1: Project Rename
- [x] Rename `Fidelity_Optimizer.bat` → `Portfolio_Optimizer.bat`
- [x] Update `run_optimizer.ps1` title/branding
- [x] Update all doc titles and headers (README, PRD, HOW_IT_WORKS, HOW_TO_USE)

## Phase 2: Split HSA and 401k Routing
- [x] Update `ACCOUNT_TYPE_MAP`: HSA → `"HSA"`, 401k → `"Employer 401k"`
- [x] Update `classify_routing_bucket()` → return `"Tax-Deferred"`
- [x] Update `score_candidate()` branch to match `"Tax-Deferred"`
- [x] Split `k401_hsa_candidates` into `k401_candidates` + `hsa_candidates`
- [x] Constrain only `k401_candidates` to plan menu
- [x] Output 4 replacement tables (Roth, Taxable, 401k, HSA)
- [x] Update Section 6 evaluation metrics for 4 buckets
- [x] Update `validator.py` routing QA expectation

## Phase 3: File Format Auto-Dispatcher
- [x] Create `src/file_ingestor.py` with `detect_format()`, `ingest_401k_file()`, `discover_401k_files()`
- [x] Implement inline PDF text extraction via `pypdf`
- [x] Implement CSV/Excel auto-column detection
- [x] Implement `.txt` content sniffing (delimiter vs ticker pattern)
- [x] Update `portfolio_analyzer.py` to use `file_ingestor` instead of `401k_parser.find_*`

## Phase 4: Generalize 401k Parser
- [x] Remove "Fidelity" from `401k_parser.py` docstring
- [x] Generalize noise prefix cleanup in `extract_plan_menu()`
- [x] Add Strategy B fallback regex in `extract_current_holdings()`

## Phase 5: Cleanup
- [x] Delete `Fidelity_401k_PDF_Extractor.bat`
- [x] Delete `src/run_pdf_extractor.ps1`
- [x] Add `pypdf` to `requirements.txt`

## Phase 6: Documentation Sync
- [x] `PRD.md`: 4-bucket routing tables, remove Fidelity branding, update metrics
- [x] `HOW_IT_WORKS.md`: 4-bucket explanation, remove Fidelity branding
- [x] `HOW_TO_USE.md`: Remove PDF Extractor step, explain "just drop any file"
- [x] `README.md`: Update Getting Started (no more PDF Extractor step)

## Phase 7: Verification
- [x] Syntax check all modified `.py` files
- [x] Scan for stale runtime references
