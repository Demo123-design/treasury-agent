"""Interest Rate Parity forward rate calculator.

Formula:
    Forward = Spot × (1 + r_india × T) / (1 + r_foreign × T)
    T = tenor_months / 12
    r_* are annualized decimal rates (e.g. 0.065 for 6.5%)
"""
from __future__ import annotations

TENOR_LABELS = {1: "1M", 3: "3M", 6: "6M", 12: "12M"}


def compute_forward_rate(
    spot: float,
    india_rate: float,
    foreign_rate: float,
    tenor_months: int,
) -> dict:
    """Compute forward rate and premium for a single tenor.

    Returns:
        tenor: e.g. "3M"
        tenor_months: int
        forward_rate: float
        forward_premium_bps: (forward/spot - 1) * 10000, over the tenor
        annualized_premium_pct: premium annualized to % p.a.
    """
    t_years = tenor_months / 12.0
    forward = spot * (1.0 + india_rate * t_years) / (1.0 + foreign_rate * t_years)
    premium_ratio = (forward / spot) - 1.0
    premium_bps = premium_ratio * 10_000.0
    annualized_pct = (premium_ratio / t_years) * 100.0
    return {
        "tenor": TENOR_LABELS.get(tenor_months, f"{tenor_months}M"),
        "tenor_months": tenor_months,
        "forward_rate": forward,
        "forward_premium_bps": premium_bps,
        "annualized_premium_pct": annualized_pct,
    }


def compute_full_forward_curve(
    spot: float,
    india_rate: float,
    foreign_rate: float,
    tenors: list[int] | None = None,
) -> list[dict]:
    tenors = tenors or [1, 3, 6, 12]
    return [compute_forward_rate(spot, india_rate, foreign_rate, t) for t in tenors]


def assess_hedging_cost(
    current_premium_bps: float,
    avg_premium_bps: float | None,
    band_bps: float = 5.0,
) -> str:
    """CHEAP if premium is below (avg - band); EXPENSIVE if above (avg + band); else FAIR."""
    if avg_premium_bps is None:
        return "FAIR"
    if current_premium_bps < avg_premium_bps - band_bps:
        return "CHEAP"
    if current_premium_bps > avg_premium_bps + band_bps:
        return "EXPENSIVE"
    return "FAIR"
