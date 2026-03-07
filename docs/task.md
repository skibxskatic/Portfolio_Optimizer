# Portfolio Optimizer Overhaul

## Phase 1: Project Rename
- [ ] Rename `Fidelity_Optimizer.bat` → `Portfolio_Optimizer.bat`
- [ ] Update `run_optimizer.ps1` title/branding
- [ ] Update all doc titles and headers (README, PRD, HOW_IT_WORKS, HOW_TO_USE)

## Phase 2: Split HSA and 401k Routing
- [ ] Update `ACCOUNT_TYPE_MAP`: HSA → `"HSA"`, 401k → `"Employer 401k"`
- [ ] Update `classify_routing_bucket()` → return `"Tax-Deferred"`
- [ ] Update `score_candidate()` branch to match `"Tax-Deferred"`
- [ ] Split `k401_hsa_candidates` into `k401_candidates` + `hsa_candidates`
- [ ] Constrain only `k401_candidates` to plan menu
- [ ] Output 4 replacement tables (Roth, Taxable, 401k, HSA)
- [ ] Update Section 6 evaluation metrics for 4 buckets
- [ ] Update `validator.py` routing QA expectation

## Phase 3: File Format Auto-Dispatcher
- [ ] Create `src/file_ingestor.py` with `detect_format()`, `ingest_401k_file()`, `discover_401k_files()`
- [ ] Implement inline PDF text extraction via `pypdf`
- [ ] Implement CSV/Excel auto-column detection
- [ ] Implement `.txt` content sniffing (delimiter vs ticker pattern)
- [ ] Update `portfolio_analyzer.py` to use `file_ingestor` instead of `401k_parser.find_*`

## Phase 4: Generalize 401k Parser
- [ ] Remove "Fidelity" from `401k_parser.py` docstring
- [ ] Generalize noise prefix cleanup in `extract_plan_menu()`
- [ ] Add Strategy B fallback regex in `extract_current_holdings()`
- [ ] Add `parse_401k_csv()` function

## Phase 5: Cleanup
- [ ] Delete `Fidelity_401k_PDF_Extractor.bat`
- [ ] Delete `src/run_pdf_extractor.ps1`

## Phase 6: Documentation Sync
- [ ] `PRD.md`: 4-bucket routing tables, remove Fidelity branding, update metrics
- [ ] `HOW_IT_WORKS.md`: 4-bucket explanation, remove Fidelity branding
- [ ] `HOW_TO_USE.md`: Remove PDF Extractor step, explain "just drop any file"
- [ ] `README.md`: Update Getting Started (no more PDF Extractor step)

## Phase 7: Verification
- [ ] Syntax check all modified `.py` files
- [ ] Run `validator.py` standalone
- [ ] Full engine run (4 tables, HSA unconstrained, 401k constrained)
- [ ] Drop raw `.pdf` into folder → confirm inline extraction works
