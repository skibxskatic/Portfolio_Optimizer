"""
tax_rates.py — Federal and state tax rate lookup for capital gains estimation.

When income and filing_status are provided, get_combined_tax_rate() uses
TaxBrackets for precise bracket-aware rates. Falls back to simplified
static assumptions when income context is unavailable.
"""

from tax_brackets import TaxBrackets

# Static fallbacks — used when no income context is available.
DEFAULT_INCOME_ASSUMPTION = 100000.0  # Assumed income for tax estimates if not provided
FEDERAL_LTCG_RATE = 0.15  # Long-term capital gains median assumption
FEDERAL_STCG_RATE = 0.24  # Short-term = ordinary income median bracket assumption

# State top marginal income tax rates applied to capital gains
# Sources: Tax Foundation, state revenue department publications
STATE_TAX_RATES = {
    "AL": 0.050,
    "AK": 0.000,
    "AZ": 0.025,
    "AR": 0.044,
    "CA": 0.133,
    "CO": 0.044,
    "CT": 0.069,
    "DE": 0.066,
    "FL": 0.000,
    "GA": 0.055,
    "HI": 0.110,
    "ID": 0.058,
    "IL": 0.049,
    "IN": 0.031,
    "IA": 0.060,
    "KS": 0.057,
    "KY": 0.040,
    "LA": 0.044,
    "ME": 0.075,
    "MD": 0.058,
    "MA": 0.050,
    "MI": 0.043,
    "MN": 0.099,
    "MS": 0.050,
    "MO": 0.048,
    "MT": 0.059,
    "NE": 0.064,
    "NV": 0.000,
    "NH": 0.000,
    "NJ": 0.109,
    "NM": 0.059,
    "NY": 0.109,
    "NC": 0.045,
    "ND": 0.025,
    "OH": 0.035,
    "OK": 0.048,
    "OR": 0.099,
    "PA": 0.031,
    "RI": 0.060,
    "SC": 0.064,
    "SD": 0.000,
    "TN": 0.000,
    "TX": 0.000,
    "UT": 0.047,
    "VT": 0.088,
    "VA": 0.058,
    "WA": 0.000,
    "WV": 0.055,
    "WI": 0.076,
    "WY": 0.000,
    "DC": 0.105,
}

# States with no income tax (capital gains taxed at 0%)
NO_STATE_TAX = {"AK", "FL", "NV", "NH", "SD", "TN", "TX", "WA", "WY"}


def get_combined_tax_rate(
    state: str = None,
    gain_type: str = "LTCG",
    income: float = None,
    gain_amount: float = 0.0,
    filing_status: str = "Single",
    year: int = 2026,
) -> tuple:
    """
    Returns (federal_rate, state_rate, combined_rate) for a given gain type.

    When *income* is provided, the federal rate is computed via TaxBrackets
    for bracket-aware precision. For LTCG, *gain_amount* enables straddle
    calculation (gain spanning multiple LTCG bands). Without *income*, the
    function falls back to the simplified static rates.

    Args:
        state:          2-letter state code (e.g., "CA", "TX"). None = federal only.
        gain_type:      "LTCG" or "STCG".
        income:         Taxable ordinary income before the gain. Enables precise rates.
        gain_amount:    Size of the capital gain lot. Used only for LTCG straddle.
        filing_status:  "Single", "Married-Joint", or "Head-of-Household".
        year:           Tax year for bracket lookup (default 2026).

    Returns:
        Tuple of (federal_rate, state_rate, combined_rate) as floats.
    """
    if income is None:
        income = DEFAULT_INCOME_ASSUMPTION

    tb = TaxBrackets(year=year, filing_status=filing_status)
    if gain_type == "LTCG":
        federal = tb.get_capital_gains_rate(income, gain_amount)
    else:
        federal = tb.get_marginal_rate(income)

    state_rate = 0.0
    if state:
        state_upper = state.strip().upper()
        state_rate = STATE_TAX_RATES.get(state_upper, 0.0)
    return (federal, state_rate, federal + state_rate)


def format_tax_rate_description(state: str = None, gain_type: str = "LTCG") -> str:
    """Returns a human-readable description like '15% fed + 9.3% CA' or '15% fed'."""
    federal, state_rate, _ = get_combined_tax_rate(state, gain_type)
    fed_str = f"{federal * 100:.0f}% fed"
    if state and state_rate > 0:
        return f"{fed_str} + {state_rate * 100:.1f}% {state.upper()}"
    elif state and state.strip().upper() in NO_STATE_TAX:
        return f"{fed_str}, no state tax"
    return fed_str
