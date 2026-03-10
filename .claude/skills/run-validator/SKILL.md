---
name: run-validator
description: Run the Portfolio Optimizer pre-flight validator standalone. Executes all 6 QA reality checks — API sanity (SPY/SCHD), dynamic screener filter, 4-bucket asset routing, metrics computation (Sharpe/Sortino/MaxDD), wash sale cross-account logic, and ingestion checksum if a Positions CSV is present. Use this to confirm the engine is healthy before running a full analysis, or to diagnose yfinance API breakage.
disable-model-invocation: true
---

Run all pre-flight QA checks:

```powershell
cd E:\GenAI_Antigravity_Projects\02_Active_Projects\Portfolio_Optimizer
.\venv\Scripts\Activate.ps1
cd src
py validator.py
```

Exit code 0 = all checks passed, safe to run full analysis.
Exit code 1 = one or more checks failed — do not run portfolio_analyzer.py.
