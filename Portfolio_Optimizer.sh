#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "===================================================="
echo "     Portfolio Optimizer Engine"
echo "===================================================="
echo ""
echo "Initializing Portfolio Optimizer..."

# 1. Activate the virtual environment
VENV_DIR="$SCRIPT_DIR/venv"
VENV_ACTIVATE="$VENV_DIR/bin/activate"

if [ -n "$VIRTUAL_ENV" ]; then
    echo "Virtual environment already active ($VIRTUAL_ENV)."
elif [ -f "$VENV_ACTIVATE" ]; then
    source "$VENV_ACTIVATE"
    echo "Virtual environment activated."
else
    echo "Virtual environment not found. Creating one..."
    python3 -m venv "$VENV_DIR"
    source "$VENV_ACTIVATE"
    echo "Installing dependencies..."
    pip install -r "$SCRIPT_DIR/requirements.txt"
    pip install pandas numpy yfinance requests lxml openpyxl
    echo "Virtual environment created and dependencies installed."
fi

# 2. Setup Cache
CACHE_DIR="$SCRIPT_DIR/Drop_Financial_Info_Here/.cache"
mkdir -p "$CACHE_DIR"

# 3. Run the application
echo ""
echo "[!] CRITICAL REMINDER: Ensure you have JUST downloaded a fresh Portfolio_Positions.csv from your brokerage."
echo "    The engine ignores 'Sells' in History files and relies entirely on your Positions file for true current quantities."
echo ""
read -rp "Press Enter to confirm your data is fresh and begin analysis, or Ctrl+C to cancel..."

echo ""
echo "Generating full portfolio analysis report..."
python3 src/portfolio_analyzer.py

echo ""
echo "Execution complete."
read -rp "Press Enter to close..."
