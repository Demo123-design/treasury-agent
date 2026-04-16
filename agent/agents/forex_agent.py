"""Forex agent — orchestrates spot fetch, forward curve computation, alerts, DB persist."""
from __future__ import annotations

import logging
from datetime import date as _date
from statistics import mean

from config import CONFIG
from models.schema import Alert, ForwardRate, SpotRate
from services import frankfurter
from utils import db, irp

log = logging.getLogger(__name__)

PAIRS = ["USDINR", "EURINR"]
TENORS = [1, 3, 6, 12]


def _get_interest_rate(rate_type: str, default: float) -> float:
    row = db.get_latest_interest_rate(rate_type)
    if row is not None:
        return float(row.rate_value)
    return default


def _foreign_rate_for(pair: str) -> float:
    if pair == "USDINR":
        return _get_interest_rate("FED_FUNDS", CONFIG.default_fed_funds)
    if pair == "EURINR":
        return _get_interest_rate("ECB_DEPOSIT", CONFIG.default_ecb_deposit)
    raise ValueError(f"Unknown pair: {pair}")


async def _fetch_spots_with_fallback() -> dict:
    """Try Frankfurter; on failure, fall back to latest DB rows."""
    try:
        return await frankfurter.get_all_required_rates()
    except Exception as exc:
        log.error("Frankfurter spot fetch failed: %s — using cached values", exc)
        out = {}
        for pair in PAIRS:
            cached = db.get_latest_spot(pair)
            if cached is None:
                raise RuntimeError(f"No cached spot for {pair} and live fetch failed") from exc
            base, quote = pair[:3], pair[3:]
            out[pair] = {"rate": cached.spot_rate, "date": cached.date, "base": base, "quote": quote}
        return out


async def _fetch_history_with_fallback(days: int) -> dict:
    try:
        return await frankfurter.get_all_required_history(days=days)
    except Exception as exc:
        log.warning("Frankfurter history fetch failed: %s — returning empty series", exc)
        return {"USDINR": [], "EURINR": []}


def _evaluate_alerts(
    today: str,
    pair: str,
    spot: float,
    today_6m_premium_bps: float,
) -> list[Alert]:
    alerts: list[Alert] = []
    if pair == "USDINR":
        if spot > CONFIG.usdinr_upper:
            alerts.append(Alert(
                date=today,
                alert_type="USDINR_UPPER_BREACH",
                message=f"USD/INR spot {spot:.4f} has crossed {CONFIG.usdinr_upper:.2f} — review unhedged exposure",
                threshold=f"{CONFIG.usdinr_upper:.2f}",
                actual_value=f"{spot:.4f}",
            ))
        elif spot < CONFIG.usdinr_lower:
            alerts.append(Alert(
                date=today,
                alert_type="USDINR_LOWER_BREACH",
                message=f"USD/INR spot {spot:.4f} has dropped below {CONFIG.usdinr_lower:.2f} — favourable to hedge",
                threshold=f"{CONFIG.usdinr_lower:.2f}",
                actual_value=f"{spot:.4f}",
            ))

    history = db.get_forward_premium_history(pair, "6M", days=2)
    if history:
        yesterday_6m = history[0]
        if abs(today_6m_premium_bps - yesterday_6m) > CONFIG.forward_premium_alert_bps:
            alerts.append(Alert(
                date=today,
                alert_type="FORWARD_PREMIUM_SPIKE",
                message=f"{pair} 6M forward premium moved "
                        f"{today_6m_premium_bps - yesterday_6m:+.1f}bps in a day "
                        f"(> {CONFIG.forward_premium_alert_bps:.0f}bps)",
                threshold=f"{CONFIG.forward_premium_alert_bps:.0f}bps",
                actual_value=f"{today_6m_premium_bps - yesterday_6m:+.1f}bps",
            ))
    return alerts


async def run_forex_agent(run_date: str | None = None, persist: bool = True) -> dict:
    """Run the full forex pipeline and return a context dict for the briefing agent."""
    today = run_date or _date.today().isoformat()
    log.info("forex_agent: starting run for %s", today)

    spots = await _fetch_spots_with_fallback()
    history = await _fetch_history_with_fallback(days=30)

    india_rate = _get_interest_rate("RBI_REPO", CONFIG.default_rbi_repo)

    result: dict = {
        "date": today,
        "spot_rates": {},
        "spot_deltas": {},
        "forward_curves": {},
        "30d_avg_spot": {},
        "hedging_assessment": {},
        "interest_rates": {
            "RBI_REPO": india_rate,
            "FED_FUNDS": _get_interest_rate("FED_FUNDS", CONFIG.default_fed_funds),
            "ECB_DEPOSIT": _get_interest_rate("ECB_DEPOSIT", CONFIG.default_ecb_deposit),
        },
        "alerts": [],
    }

    all_alerts: list[Alert] = []

    for pair in PAIRS:
        spot_payload = spots[pair]
        spot = float(spot_payload["rate"])
        spot_date = spot_payload["date"]
        result["spot_rates"][pair] = {"rate": spot, "date": spot_date}

        series = history.get(pair, [])
        if series:
            result["30d_avg_spot"][pair] = mean(item["rate"] for item in series)
        else:
            result["30d_avg_spot"][pair] = None

        prev_rate = None
        for item in reversed(series):
            if item["rate"] != spot:
                prev_rate = item["rate"]
                break
        avg_30d = result["30d_avg_spot"][pair]
        result["spot_deltas"][pair] = {
            "prev_rate": prev_rate,
            "d1_abs": (spot - prev_rate) if prev_rate is not None else None,
            "d1_pct": ((spot - prev_rate) / prev_rate * 100) if prev_rate else None,
            "d30_abs": (spot - avg_30d) if avg_30d is not None else None,
            "d30_pct": ((spot - avg_30d) / avg_30d * 100) if avg_30d else None,
        }

        foreign_rate = _foreign_rate_for(pair)
        curve = irp.compute_full_forward_curve(spot, india_rate, foreign_rate, TENORS)
        result["forward_curves"][pair] = curve

        prem_history_6m = db.get_forward_premium_history(pair, "6M", days=30)
        avg_6m_premium = mean(prem_history_6m) if prem_history_6m else None
        today_6m_premium = next((p["forward_premium_bps"] for p in curve if p["tenor"] == "6M"), 0.0)
        assessment = irp.assess_hedging_cost(today_6m_premium, avg_6m_premium)
        result["hedging_assessment"][pair] = {
            "tenor": "6M",
            "current_premium_bps": today_6m_premium,
            "avg_30d_premium_bps": avg_6m_premium,
            "verdict": assessment,
        }

        pair_alerts = _evaluate_alerts(today, pair, spot, today_6m_premium)
        all_alerts.extend(pair_alerts)

        if persist:
            try:
                db.insert_spot_rate(SpotRate(date=spot_date, pair=pair, spot_rate=spot))
                for row in curve:
                    db.insert_forward_rate(ForwardRate(
                        date=today,
                        pair=pair,
                        tenor=row["tenor"],
                        forward_rate=row["forward_rate"],
                        forward_premium_bps=row["forward_premium_bps"],
                        india_rate=india_rate,
                        foreign_rate=foreign_rate,
                    ))
            except Exception as exc:
                log.error("forex_agent: DB persist failed for %s: %s", pair, exc)

    if persist and all_alerts:
        for a in all_alerts:
            try:
                db.insert_alert(a)
            except Exception as exc:
                log.error("forex_agent: DB alert persist failed: %s", exc)

    result["alerts"] = [
        {"type": a.alert_type, "message": a.message, "threshold": a.threshold, "actual": a.actual_value}
        for a in all_alerts
    ]

    log.info("forex_agent: done - spot USDINR=%s EURINR=%s alerts=%d",
             result["spot_rates"]["USDINR"]["rate"],
             result["spot_rates"]["EURINR"]["rate"],
             len(all_alerts))
    return result
