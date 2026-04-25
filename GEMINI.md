# Gemini Project Instructions - Portfolio Optimizer

## Memory Imports
@../../06_Cognitive_Sync/global_preferences.md
@../../06_Cognitive_Sync/user_profile.md
@./MEMORY.md

## Agent Role
You are the Gemini assistant for the Portfolio Optimizer. Use the rules and logic in `MEMORY.md` to guide your analysis and implementation.

## Technical Context
- **Language:** Python 3.x
- **Environment:** Windows (always use `py`)
- **Main Entry:** `src/portfolio_analyzer.py`

## Commands
- Run Analysis: `py src/portfolio_analyzer.py`
- Run Validator: `cd src && py -c "import validator; validator.run_all_checks()"`
- Run Tests: `cd src && py test_multi_broker.py`
