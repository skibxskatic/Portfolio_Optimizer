# Claude Project Instructions - Portfolio Optimizer

## Memory Synchronization
MANDATORY: Before proceeding, read the following files:
1. `E:\Obsidian_Vault\06_Cognitive_Sync\global_preferences.md`
2. `E:\Obsidian_Vault\06_Cognitive_Sync\user_profile.md`
3. `./MEMORY.md` (Core Logic & Architecture)

## Commands

**Run the full optimizer:**
```
py src/portfolio_analyzer.py
```

**Run validator standalone:**
```
cd src && py -c "import validator; validator.run_all_checks()"
```

**Run individual test scripts:**
```
cd src && py test_tlh_screener.py
cd src && py test_multi_broker.py
```

## Agent Role
You are the Claude assistant for the Portfolio Optimizer. Maintain technical integrity and privacy standards defined in `MEMORY.md`.
