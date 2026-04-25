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
    pip install -r "$SCRIPT_DIR/requirements.txt" --quiet 2>/dev/null
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

# --- Investor Profile Setup ---
PROFILE_PATH="$SCRIPT_DIR/Drop_Financial_Info_Here/investor_profile.txt"

read_field() {
    local prompt="$1" default="$2" input
    printf "%s [%s]: " "$prompt" "$default"
    read -r input
    echo "${input:-$default}"
}

show_profile() {
    echo ""
    echo "--- Investor Profile ---"
    local birth="" retire="" risk="" state="" roth="" taxable="" hsa="" k401=""
    while IFS='=' read -r key val; do
        key=$(echo "$key" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')
        val=$(echo "$val" | tr -d '[:space:]')
        case "$key" in
            birth_year) birth="$val" ;;
            retirement_year) retire="$val" ;;
            risk_tolerance) risk="$val" ;;
            state) state="$val" ;;
            roth_ira_contribution) roth="$val" ;;
            taxable_contribution) taxable="$val" ;;
            hsa_contribution) hsa="$val" ;;
            401k_contribution) k401="$val" ;;
        esac
    done < <(grep -v '^\s*#' "$PROFILE_PATH" 2>/dev/null | grep '=')
    echo "  Birth Year:        ${birth:-not set}"
    echo "  Retirement Year:   ${retire:-not set}"
    echo "  Risk Tolerance:    ${risk:-auto (from age)}"
    echo "  State:             ${state:-not set (federal rates only)}"
    echo "  Roth IRA Contrib:  ${roth:+\$${roth}}${roth:-auto-detect}"
    echo "  Taxable Contrib:   ${taxable:+\$${taxable}}${taxable:-auto-detect}"
    echo "  HSA Contrib:       ${hsa:+\$${hsa}}${hsa:-auto-detect}"
    echo "  401k Contrib:      ${k401:+\$${k401}}${k401:-auto-detect}"
    echo "------------------------"
}

build_profile() {
    echo ""
    echo "--- Investor Profile Setup ---"
    local birth retire risk_input risk_val state_input
    birth=$(read_field "Birth year" "1990")
    retire=$(read_field "Retirement year" "2057")

    # Auto-recommend risk tolerance
    local current_year years_out auto_risk auto_num
    current_year=$(date +%Y)
    years_out=$((retire - current_year))
    if [ "$years_out" -ge 30 ]; then auto_risk="very_aggressive"; auto_num="5"
    elif [ "$years_out" -ge 20 ]; then auto_risk="aggressive"; auto_num="4"
    elif [ "$years_out" -ge 10 ]; then auto_risk="moderate"; auto_num="3"
    elif [ "$years_out" -ge 3 ]; then auto_risk="conservative"; auto_num="2"
    else auto_risk="very_conservative"; auto_num="1"; fi

    echo ""
    echo "Risk Tolerance (auto-recommendation: $auto_risk based on $years_out yrs to retirement):"
    echo "  1. Very Conservative - Capital preservation priority"
    echo "  2. Conservative - Stability-focused"
    echo "  3. Moderate - Balanced growth and stability"
    echo "  4. Aggressive - Growth-focused"
    echo "  5. Very Aggressive - Maximum growth"
    risk_input=$(read_field "Choose 1-5 or press Enter for auto" "$auto_num")
    case "$risk_input" in
        1) risk_val="very_conservative" ;; 2) risk_val="conservative" ;;
        3) risk_val="moderate" ;; 4) risk_val="aggressive" ;;
        5) risk_val="very_aggressive" ;; *) risk_val="$auto_risk" ;;
    esac

    echo ""
    echo "State (2-letter code for tax estimates)."
    echo "If skipped, tax estimates will use federal rates only (no state tax applied)."
    printf "State code [skip]: "
    read -r state_input

    echo ""
    echo "Contribution amounts - how much cash to deploy per account."
    echo "Press Enter to auto-detect from core/money-market positions in your CSV (recommended)."
    printf "Roth IRA \$ [auto-detect from CSV]: "; read -r roth_c
    printf "Taxable \$ [auto-detect from CSV]: "; read -r tax_c
    printf "HSA \$ [auto-detect from CSV]: "; read -r hsa_c
    printf "401k \$ [auto-detect from CSV]: "; read -r k401_c

    # Write profile
    {
        echo "# Investor Profile for Portfolio Optimizer"
        echo "birth_year = $birth"
        echo "retirement_year = $retire"
        echo "risk_tolerance = $risk_val"
        [ -n "$state_input" ] && [ ${#state_input} -eq 2 ] && echo "state = $(echo "$state_input" | tr '[:lower:]' '[:upper:]')"
        [ -n "$roth_c" ] && echo "roth_ira_contribution = $roth_c"
        [ -n "$tax_c" ] && echo "taxable_contribution = $tax_c"
        [ -n "$hsa_c" ] && echo "hsa_contribution = $hsa_c"
        [ -n "$k401_c" ] && echo "401k_contribution = $k401_c"
    } > "$PROFILE_PATH"
    echo ""
    echo "Profile saved."
}

if [ -f "$PROFILE_PATH" ]; then
    show_profile
    printf "Press Enter to continue, or type 'edit' to modify: "
    read -r edit_choice
    [ "$edit_choice" = "edit" ] && build_profile
else
    echo ""
    echo "[!] No investor profile found. Let's set one up."
    build_profile
fi

echo ""
read -rp "Press Enter to confirm your data is fresh and begin analysis, or Ctrl+C to cancel..."

echo ""
echo "Generating full portfolio analysis report..."
python3 src/portfolio_analyzer.py

echo ""
echo "Execution complete."
read -rp "Press Enter to close..."
