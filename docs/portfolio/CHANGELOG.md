# Changelog

All notable changes to the **Portfolio Optimizer** project will be documented in this file.

## [v2.1.0] - 2026-04-23
### Added
- **Dual HTML/PDF Reports**: Generation of both high-fidelity HTML and portable PDF reports for analysis results.
- **Age-Aware Scoring Engine**: Implementation of a glide-path model that adjusts risk tolerance and allocation based on the user's age and years to retirement.
- **WMI Monkeypatch**: Critical fix for Python 3.13 on Windows to prevent startup hangs during hardware identification.
- **macOS/Linux Launcher**: Added `.command` and `.sh` scripts with auto-initialization for virtual environments.

## [v2.0.0] - 2026-04-21
### Added
- **6-Tier Stable Routing Engine**: Enhanced asset routing logic with account-specific anchors, category whitelists, and 3-year beta fallbacks to ensure tax efficiency.
- **Stock Split Normalization**: Authoritative split adjustment using `yfinance` historical data to prevent "phantom losses" in tax-loss harvesting (TLH) reports.
- **Account-Level Isolation**: Logic to ensure historical lots are only matched to positions within the same brokerage account, preventing multi-account unrolling errors.
- **Unified Ingestion Layer**: Consistently routes all Fidelity and generic data through `file_ingestor.py`, removing legacy 401k-specific parsing code.

## [v1.5.0] - 2026-04-10
### Added
- **Multi-Broker Data Ingestion**: Modular adapter layer to support Fidelity, generic CSVs, and initial 401k parsers.
- **Dynamic Fund Screener**: Live-scraped ETF universe analysis with pure ETF/Mutual Fund filtering.
- **Tax Location Strategies**: Implementation of the 4-bucket tax location model (Taxable, Roth, Tax-Deferred, HSA).

## [v1.0.0] - 2026-03-15
### Added
- **Initial Core Engine**: Basic portfolio parsing and analysis for Fidelity 401k exports.
- **Market Data Integration**: First implementation of `yfinance` wrapper with concurrent fetching.
- **Pre-flight Validator**: Initial safety checks for API sanity and ingestion integrity.

## [v0.1.0] - 2026-03-01
### Added
- **Proof of Concept**: Simple script to parse CSV files and calculate total portfolio value.
- **Project Scaffold**: Basic directory structure and initial documentation.
