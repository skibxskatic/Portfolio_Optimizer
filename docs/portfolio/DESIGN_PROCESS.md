# Design Process

This document outlines the brainstorming, technical rationale, and evolutionary steps taken during the development of the **Portfolio Optimizer**.

## 1. Evolution of the Launcher System

### The Problem
Initial versions used simple Windows batch files (`.bat`). These were fragile, lacked robust error handling, and were platform-specific. Users on macOS and Linux had to manually set up their environments.

### The Solution: PowerShell & Native Shell Scripts
- **Transition to PowerShell (`.ps1`)**: We moved to a native PowerShell script for Windows. This allowed for:
  - Better detection of Python installations.
  - Automatic virtual environment (`venv`) initialization and dependency syncing.
  - Robust error handling and logging.
- **Platform Parity**: Created `.command` and `.sh` scripts for macOS/Linux to provide a "one-click" experience across all operating systems.
- **Zero-Config Goal**: The project now auto-initializes everything (venv, dependencies) on the first run, reducing technical friction for non-technical users.

## 2. Mathematical Rationale for Scoring

To recommend the "best" funds, the engine uses different scoring models based on the tax characteristics of the account.

### Taxable Brokerage
- **Primary Metric**: **Sharpe Ratio** (Total risk-adjusted return).
- **Secondary Metric**: 5-Year Net Return.
- **Rationale**: In taxable accounts, we optimize for the best possible return relative to overall volatility. The Sharpe ratio is the industry standard for assessing if the returns justify the "bumps" along the way.

### Roth IRA / HSA
- **Primary Metric**: **Sortino Ratio** (Downside risk-adjusted return).
- **Secondary Metrics**: 5-Year Net Return + Max Drawdown.
- **Rationale**: These are tax-free compounding engines. The biggest threat to a Roth or HSA is a permanent loss of capital during a crash. The Sortino ratio ignores "good" upside volatility and only penalizes "bad" downside volatility, making it superior for tax-free buckets where preservation of the "base" is paramount.

## 3. Age-Aware Allocation Logic

### Glide-Path Model
We implemented a dynamic "Risk Tolerance" calculator based on **Years to Retirement (YTR)**.
- **Aggressive (YTR > 20)**: Focuses 90-100% on equity scores.
- **Conservative (YTR < 5)**: Shifts focus toward stability and drawdown protection.
- **Rationale**: This mirrors institutional target-date fund logic, ensuring that as users age, the engine automatically prioritizes stability over raw growth.

## 4. Stability vs. Efficiency (v2 Engine)

### The Conflict
Early versions of the engine were "too efficient," recommending portfolio overhauls for minor tax gains. This triggered unnecessary tax events and confusion.

### The Solution: 6-Tier Stable Routing
We introduced a hierarchical routing system to provide stability:
1. **Account-Specific Anchors**: Hard-codes certain accounts (like a Joint Brokerage) to specific strategies.
2. **Whitelist**: Protects core index funds (VTI/VOO) from being "optimized" into obscure ETFs.
3. **Beta Fallback**: If market data is noisy, the engine falls back to 3-year volatility averages to prevent churn.
