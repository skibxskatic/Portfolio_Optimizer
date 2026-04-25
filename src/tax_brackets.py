"""
tax_brackets.py — High-precision tax bracket logic for the 2026 tax year.

Replaces simplified static assumptions in tax_rates.py with bracket-aware
marginal rate lookups and LTCG straddle calculations.

NOTE: Bracket data is sourced from 2025 IRS tables (Rev. Proc. 2024-61),
which is the most recent available at implementation time. Update the
_ORDINARY_BRACKETS and _LTCG_THRESHOLDS tables when the IRS publishes
official 2026 figures (typically October of the prior year).
"""


class TaxBrackets:
    """
    Bracket-aware federal tax rate engine.

    Supports ordinary income marginal rate lookup and LTCG effective rate
    calculation with full straddle logic (gain spanning multiple rate bands).

    Args:
        year:           Tax year. Falls back to 2025 data if year not in tables.
        filing_status:  One of 'Single', 'Married-Joint', 'Head-of-Household'.
    """

    # Each entry: (ceiling_inclusive, rate). Final entry ceiling = inf (top bracket).
    # Source: IRS Rev. Proc. 2024-61 (tax year 2025).
    _ORDINARY_BRACKETS: dict = {
        2025: {
            "Single": [
                (11_925, 0.10),
                (48_475, 0.12),
                (103_350, 0.22),
                (197_300, 0.24),
                (250_525, 0.32),
                (626_350, 0.35),
                (float("inf"), 0.37),
            ],
            "Married-Joint": [
                (23_850, 0.10),
                (96_950, 0.12),
                (206_700, 0.22),
                (394_600, 0.24),
                (501_050, 0.32),
                (751_600, 0.35),
                (float("inf"), 0.37),
            ],
            "Head-of-Household": [
                (17_000, 0.10),
                (64_850, 0.12),
                (103_350, 0.22),
                (197_300, 0.24),
                (250_500, 0.32),
                (626_350, 0.35),
                (float("inf"), 0.37),
            ],
        },
        2026: {
            "Single": [
                (12_400, 0.10),
                (50_400, 0.12),
                (105_700, 0.22),
                (201_775, 0.24),
                (256_225, 0.32),
                (640_600, 0.35),
                (float("inf"), 0.37),
            ],
            "Married-Joint": [
                (24_800, 0.10),
                (100_800, 0.12),
                (211_400, 0.22),
                (403_550, 0.24),
                (512_450, 0.32),
                (768_700, 0.35),
                (float("inf"), 0.37),
            ],
            "Head-of-Household": [
                (17_700, 0.10),
                (67_450, 0.12),
                (105_700, 0.22),
                (201_775, 0.24),
                (256_225, 0.32),
                (640_600, 0.35),
                (float("inf"), 0.37),
            ],
        },
    }

    # LTCG thresholds: (ceiling_inclusive, rate).
    # Gains are taxed at 0 / 15 / 20 % based on total taxable income.
    # Source: IRS Rev. Proc. 2024-61 (tax year 2025).
    _LTCG_THRESHOLDS: dict = {
        2025: {
            "Single": [(48_350, 0.00), (533_400, 0.15), (float("inf"), 0.20)],
            "Married-Joint": [(96_700, 0.00), (600_050, 0.15), (float("inf"), 0.20)],
            "Head-of-Household": [(64_750, 0.00), (566_700, 0.15), (float("inf"), 0.20)],
        },
        2026: {
            "Single": [(49_450, 0.00), (545_500, 0.15), (float("inf"), 0.20)],
            "Married-Joint": [(98_900, 0.00), (613_700, 0.15), (float("inf"), 0.20)],
            "Head-of-Household": [(66_200, 0.00), (579_350, 0.15), (float("inf"), 0.20)],
        },
    }

    _VALID_STATUSES = ("Single", "Married-Joint", "Head-of-Household")

    def __init__(self, year: int = 2026, filing_status: str = "Single") -> None:
        if filing_status not in self._VALID_STATUSES:
            raise ValueError(f"Invalid filing_status '{filing_status}'. Must be one of: {self._VALID_STATUSES}")
        self.year = year
        self.filing_status = filing_status
        self.brackets = self._load_brackets()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_marginal_rate(self, income: float) -> float:
        """
        Return the marginal ordinary-income tax rate for *income*.

        Performs a linear scan of the bracket table — O(n) on 7 brackets,
        which is fast enough and avoids the complexity of bisect with tuples.

        Args:
            income: Taxable ordinary income (before any capital gains).

        Returns:
            Marginal rate as a decimal (e.g. 0.24 for 24 %).
        """
        if income < 0:
            return 0.0
        for ceiling, rate in self.brackets["ordinary"]:
            if income <= ceiling:
                return rate
        return self.brackets["ordinary"][-1][1]  # shouldn't reach here (inf ceiling)

    def get_capital_gains_rate(self, total_income: float, gain_amount: float) -> float:
        """
        Return the effective LTCG rate for *gain_amount* stacked on *total_income*.

        Handles straddle: if a gain crosses a LTCG threshold boundary, each
        portion is taxed at its own rate and an income-weighted average is
        returned, giving a precise effective rate for this specific lot.

        Args:
            total_income: Taxable income BEFORE the gain (ordinary income only).
            gain_amount:  Size of the long-term capital gain lot.

        Returns:
            Effective LTCG rate for this lot as a decimal (e.g. 0.15).
        """
        if gain_amount <= 0:
            return 0.0

        # Build contiguous bands: [(band_lower, band_upper, rate), ...]
        bands = []
        lower = 0.0
        for ceiling, rate in self.brackets["ltcg"]:
            bands.append((lower, ceiling, rate))
            lower = ceiling

        gain_start = max(total_income, 0.0)
        gain_end = gain_start + gain_amount
        weighted_tax = 0.0

        for band_lower, band_upper, rate in bands:
            overlap_start = max(gain_start, band_lower)
            overlap_end = min(gain_end, band_upper)
            if overlap_end > overlap_start:
                weighted_tax += (overlap_end - overlap_start) * rate

        return weighted_tax / gain_amount

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_brackets(self) -> dict:
        """Load bracket tables for the configured year and filing status."""
        data_year = self.year if self.year in self._ORDINARY_BRACKETS else 2025
        return {
            "ordinary": self._ORDINARY_BRACKETS[data_year][self.filing_status],
            "ltcg": self._LTCG_THRESHOLDS[data_year][self.filing_status],
            "data_year": data_year,
        }

    def __repr__(self) -> str:
        data_year = self.brackets["data_year"]
        note = f" [using {data_year} data]" if data_year != self.year else ""
        return f"<TaxBrackets year={self.year} status='{self.filing_status}'{note}>"
