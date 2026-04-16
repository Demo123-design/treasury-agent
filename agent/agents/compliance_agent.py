"""Compliance Scanner — cross-references internal documents against market data.

Reads parsed internal docs (forward contracts, policies, forecasts, etc.)
and compares with live/DB market data to surface conflicts, regulatory risks,
and actionable insights.  Each insight includes document evidence excerpts
so users can see exactly what data triggered the alert.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from models.schema import ComplianceInsight, now_iso
from services.doc_parser import parse_all_documents
from utils import db
from utils.db import get_connection

log = logging.getLogger(__name__)

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}


# ── helpers ────────────────────────────────────────────────────────────────

def _insight(
    severity: str, category: str, title: str,
    description: str, docs: str, action: str,
    evidence: list[dict] | None = None,
) -> dict:
    return {
        "severity": severity,
        "category": category,
        "title": title,
        "description": description,
        "affected_docs": docs,
        "recommended_action": action,
        "evidence": evidence or [],
    }


def _ev_table(source: str, file: str, headers: list[str], rows: list[list[str]]) -> dict:
    return {"source": source, "file": file, "type": "table", "headers": headers, "rows": rows}


def _ev_text(source: str, file: str, content: str) -> dict:
    return {"source": source, "file": file, "type": "text", "content": content}


def _ev_metric(source: str, file: str, items: list[dict]) -> dict:
    return {"source": source, "file": file, "type": "metric", "items": items}


def _days_between(iso_a: str | None, iso_b: str | None) -> int | None:
    if not iso_a or not iso_b:
        return None
    try:
        a = datetime.strptime(iso_a[:10], "%Y-%m-%d").date()
        b = datetime.strptime(iso_b[:10], "%Y-%m-%d").date()
        return (b - a).days
    except Exception:
        return None


def _fmt_ccy(ccy: str, val: float) -> str:
    sym = "$" if "usd" in ccy.lower() else "\u20ac"
    return f"{sym}{val:,.0f}"


def _get_market_data() -> dict:
    market: dict[str, Any] = {"spot": {}, "interest_rates": {}, "news": []}
    try:
        usd = db.get_latest_spot("USDINR")
        eur = db.get_latest_spot("EURINR")
        if usd:
            market["spot"]["USDINR"] = usd.spot_rate
        if eur:
            market["spot"]["EURINR"] = eur.spot_rate
        for rt in ("RBI_REPO", "FED_FUNDS", "ECB_DEPOSIT"):
            ir = db.get_latest_interest_rate(rt)
            if ir:
                market["interest_rates"][rt] = ir.rate_value
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT category, headline, summary, relevance, source_url, date "
                "FROM news_items WHERE date >= date('now', '-7 days') "
                "ORDER BY date DESC, id DESC LIMIT 30",
            ).fetchall()
        market["news"] = [dict(r) for r in rows]
    except Exception as e:
        log.warning("Could not fetch market data from DB: %s", e)
    return market


# ── compliance checks ──────────────────────────────────────────────────────

def _check_fema_realization(docs: dict, today: str) -> list[dict]:
    insights = []
    records = docs.get("realization_tracker", {}).get("records", [])
    policy = docs.get("risk_policy", {})

    policy_ev = _ev_text(
        "Treasury Risk Policy \u2014 Section 8",
        "Doc5_Treasury_Risk_Policy.docx",
        "Export proceeds must be realized within 9 months (270 days) from date of export "
        "(per RBI Master Direction). Alerts at 180, 210, and 240 days. "
        "Escalate to CFO at 240 days. Initiate write-off application with AD bank for likely-breach.",
    )

    for rec in records:
        deadline = rec.get("realization_deadline")
        days_rem = rec.get("days_remaining")
        if days_rem is None and deadline:
            days_rem = _days_between(today, deadline)
        if days_rem is None:
            continue

        pending = rec.get("balance_pending", 0)
        ccy = rec.get("currency", "USD")
        customer = rec.get("customer", "Unknown")
        sb = rec.get("shipping_bill", "")
        pct = rec.get("pct_realized", 0)
        if pending <= 0:
            continue

        row_ev = _ev_table(
            "Export Realization Tracker",
            "Doc4_Export_Realization_Tracker.xlsx",
            ["Shipping Bill", "Customer", "Currency", "Pending", "Deadline", "Days Left", "Realized", "Risk"],
            [[sb, customer, ccy, _fmt_ccy(ccy, pending), deadline or "?",
              str(days_rem), f"{pct:.0f}%", rec.get("risk_level", "?")]],
        )

        if days_rem <= 0:
            insights.append(_insight(
                "CRITICAL", "FEMA",
                f"FEMA 270-Day BREACHED \u2014 {customer}",
                f"Shipping bill {sb}: {ccy} {pending:,.0f} outstanding ({pct:.0f}% realized). "
                f"Realization deadline was {deadline}. This is a direct FEMA violation.",
                "Realization Tracker, Invoice Register, Risk Policy",
                "Report to AD bank immediately. Initiate write-off / extension application with RBI.",
                evidence=[row_ev, policy_ev],
            ))
        elif days_rem <= 7:
            insights.append(_insight(
                "CRITICAL", "FEMA",
                f"FEMA Breach Imminent \u2014 {customer} ({days_rem}d left)",
                f"Shipping bill {sb}: {ccy} {pending:,.0f} outstanding ({pct:.0f}% realized). "
                f"Deadline: {deadline} \u2014 only {days_rem} days remaining.",
                "Realization Tracker, Invoice Register",
                "Escalate to CFO. Contact customer for urgent payment. Prepare RBI extension application.",
                evidence=[row_ev, policy_ev],
            ))
        elif days_rem <= 30:
            sev = "HIGH" if days_rem <= 15 else "MEDIUM"
            insights.append(_insight(
                sev, "FEMA",
                f"FEMA Deadline Approaching \u2014 {customer} ({days_rem}d left)",
                f"Shipping bill {sb}: {ccy} {pending:,.0f} outstanding ({pct:.0f}% realized). "
                f"Deadline: {deadline}.",
                "Realization Tracker",
                f"Intensify collection follow-up. {'Escalate to Sales Head.' if days_rem <= 15 else 'Monitor weekly.'}",
                evidence=[row_ev],
            ))

    return insights


def _check_bank_concentration(docs: dict) -> list[dict]:
    insights = []
    fc = docs.get("forward_contracts", {})
    policy = docs.get("risk_policy", {})
    limit_pct = policy.get("bank_concentration_limit_pct", 30)
    breakdown = fc.get("hedge_summary", {}).get("bank_breakdown", {})

    if not breakdown:
        return insights
    total = sum(breakdown.values())
    if total <= 0:
        return insights

    # Build full breakdown evidence table
    table_rows = []
    for bank, notional in sorted(breakdown.items(), key=lambda x: -x[1]):
        pct = (notional / total) * 100
        status = "BREACH" if pct > limit_pct else "OK"
        table_rows.append([bank, f"${notional:,.0f}", f"{pct:.1f}%", f"{limit_pct}%", status])

    breakdown_ev = _ev_table(
        "Forward Contract Register \u2014 Bank Breakdown",
        "Doc2_Forward_Contract_Register.xlsx",
        ["Bank", "Notional", "Share %", "Limit", "Status"],
        table_rows,
    )
    policy_ev = _ev_text(
        "Treasury Risk Policy \u2014 Section 7",
        "Doc5_Treasury_Risk_Policy.docx",
        f"No single bank may exceed {limit_pct}% of total outstanding hedge notional. "
        "Minimum 3 banks must be used at any given time.",
    )

    for bank, notional in sorted(breakdown.items(), key=lambda x: -x[1]):
        pct = (notional / total) * 100
        if pct > limit_pct:
            insights.append(_insight(
                "HIGH", "CONCENTRATION",
                f"Bank Concentration Breach \u2014 {bank} ({pct:.0f}%)",
                f"{bank} holds {pct:.1f}% of total hedge notional "
                f"(${notional:,.0f} of ${total:,.0f}). Policy limit is {limit_pct}%.",
                "Forward Contract Register, Risk Policy",
                f"Rebalance forward book. Shift new deals to other approved banks.",
                evidence=[breakdown_ev, policy_ev],
            ))
        elif pct > limit_pct * 0.85:
            insights.append(_insight(
                "MEDIUM", "CONCENTRATION",
                f"Bank Concentration Warning \u2014 {bank} ({pct:.0f}%)",
                f"{bank} at {pct:.1f}% of total notional, approaching {limit_pct}% limit.",
                "Forward Contract Register, Risk Policy",
                "Monitor. Consider diversifying future deal flow.",
                evidence=[breakdown_ev],
            ))

    # EUR-specific concentration
    eur_contracts = [c for c in fc.get("active_contracts", []) if "eur" in c.get("pair", "").lower()]
    if eur_contracts:
        eur_banks: dict[str, int] = {}
        for c in eur_contracts:
            eur_banks[c.get("bank", "")] = eur_banks.get(c.get("bank", ""), 0) + 1
        total_eur = len(eur_contracts)
        for bank, count in eur_banks.items():
            if total_eur > 2 and count / total_eur > 0.7:
                eur_rows = [
                    [c["deal_ref"], c["bank"], f"\u20ac{c['notional']:,.0f}",
                     c.get("tenor", ""), c.get("maturity_date", "")]
                    for c in eur_contracts
                ]
                insights.append(_insight(
                    "MEDIUM", "CONCENTRATION",
                    f"EUR Hedge Concentration \u2014 {bank} ({count}/{total_eur} contracts)",
                    f"{bank} holds {count} of {total_eur} EUR forward contracts. "
                    "Single-bank concentration creates counterparty risk.",
                    "Forward Contract Register",
                    "Diversify EUR forward bookings across at least 2-3 banks.",
                    evidence=[_ev_table(
                        "EUR Forward Contracts",
                        "Doc2_Forward_Contract_Register.xlsx",
                        ["Deal Ref", "Bank", "Notional", "Tenor", "Maturity"],
                        eur_rows,
                    )],
                ))
    return insights


def _check_rate_divergence(docs: dict, market: dict) -> list[dict]:
    insights = []
    outlook = docs.get("forex_outlook", {})
    live_spot = market.get("spot", {})

    internal_usd = outlook.get("internal_usdinr_spot")
    live_usd = live_spot.get("USDINR")
    if internal_usd and live_usd:
        diff = abs(live_usd - internal_usd)
        diff_pct = (diff / internal_usd) * 100
        ev = [_ev_metric(
            "Rate Comparison", "",
            [{"label": "Live USD/INR", "value": f"{live_usd:.4f}"},
             {"label": "Internal Outlook", "value": f"{internal_usd:.2f}"},
             {"label": "Divergence", "value": f"{diff:.4f} ({diff_pct:.1f}%)"}],
        )]
        if diff_pct > 1.0:
            direction = "higher" if live_usd > internal_usd else "lower"
            insights.append(_insight(
                "HIGH", "RATE_DIVERGENCE",
                f"USD/INR Spot Divergence \u2014 Market {direction} than internal view",
                f"Live USD/INR: {live_usd:.4f} vs Internal outlook: {internal_usd:.2f} "
                f"(diff: {diff:.4f}, {diff_pct:.1f}%). "
                "Hedging decisions based on stale internal view may be mis-calibrated.",
                "Internal Forex Outlook",
                "Update internal forex outlook. Review hedge execution triggers.",
                evidence=ev,
            ))
        elif diff_pct > 0.3:
            insights.append(_insight(
                "LOW", "RATE_DIVERGENCE",
                f"USD/INR Spot Drift \u2014 {diff_pct:.1f}% from internal view",
                f"Live: {live_usd:.4f} vs Internal: {internal_usd:.2f}. Minor drift, monitor.",
                "Internal Forex Outlook",
                "No immediate action. Update at next scheduled outlook revision.",
                evidence=ev,
            ))

    internal_eur = outlook.get("internal_eurinr_spot")
    live_eur = live_spot.get("EURINR")
    if internal_eur and live_eur:
        diff = abs(live_eur - internal_eur)
        diff_pct = (diff / internal_eur) * 100
        if diff_pct > 1.0:
            direction = "higher" if live_eur > internal_eur else "lower"
            insights.append(_insight(
                "HIGH", "RATE_DIVERGENCE",
                f"EUR/INR Spot Divergence \u2014 Market {direction} than internal view",
                f"Live EUR/INR: {live_eur:.4f} vs Internal: {internal_eur:.2f} "
                f"(diff: {diff:.4f}, {diff_pct:.1f}%).",
                "Internal Forex Outlook",
                "Update EUR/INR outlook. Review EUR hedging priorities.",
                evidence=[_ev_metric("Rate Comparison", "", [
                    {"label": "Live EUR/INR", "value": f"{live_eur:.4f}"},
                    {"label": "Internal Outlook", "value": f"{internal_eur:.2f}"},
                    {"label": "Divergence", "value": f"{diff:.4f} ({diff_pct:.1f}%)"},
                ])],
            ))

    live_rates = market.get("interest_rates", {})
    if live_rates.get("RBI_REPO"):
        live_rbi = live_rates["RBI_REPO"]
        internal_rbi = 6.25
        if abs(live_rbi - internal_rbi) > 0.25:
            insights.append(_insight(
                "MEDIUM", "RATE_DIVERGENCE",
                "RBI Repo Rate Changed \u2014 Forward curves may need recalibration",
                f"Live RBI repo: {live_rbi:.2f}% vs Internal assumption: {internal_rbi:.2f}%.",
                "Internal Forex Outlook, Forward Contract Register",
                "Recalculate forward curves with updated rates.",
                evidence=[_ev_metric("Interest Rate Comparison", "", [
                    {"label": "Live RBI Repo", "value": f"{live_rbi:.2f}%"},
                    {"label": "Internal Assumption", "value": f"{internal_rbi:.2f}%"},
                ])],
            ))
    return insights


def _check_policy_rc_gaps(docs: dict) -> list[dict]:
    insights = []
    policy = docs.get("risk_policy", {})
    rc = docs.get("rc_minutes", {})

    policy_quotes = policy.get("min_quotes_above_1m", 2)
    rc_quotes = rc.get("rc_min_quotes")
    if rc_quotes and rc_quotes != policy_quotes:
        insights.append(_insight(
            "MEDIUM", "POLICY_GAP",
            f"Policy vs RC Discrepancy \u2014 Quote requirement ({policy_quotes} vs {rc_quotes})",
            f"Treasury Risk Policy requires {policy_quotes} quotes for deals >USD 1M, "
            f"but Risk Committee resolved {rc_quotes} quotes for deals "
            f">{rc.get('rc_min_quotes_threshold', 'USD 3M')}.",
            "Risk Policy, Risk Committee Minutes",
            "Update Treasury Risk Policy Section 7 to incorporate RC decision.",
            evidence=[
                _ev_text("Treasury Risk Policy \u2014 Section 7",
                         "Doc5_Treasury_Risk_Policy.docx",
                         f"Minimum {policy_quotes} competitive quotes required for any deal above USD 1 million."),
                _ev_text("Risk Committee Minutes \u2014 RC/2025-26/Q4-03",
                         "Doc7_Risk_Committee_Minutes.docx",
                         f"RC Modification: For any single deal >USD 3M, minimum {rc_quotes} bank quotes required "
                         f"(stricter than policy\u2019s {policy_quotes} quotes for >USD 1M)."),
            ],
        ))
    return insights


def _check_ecb_exposure(docs: dict) -> list[dict]:
    insights = []
    cf = docs.get("cash_flow", {})
    fc = docs.get("forward_contracts", {})
    ecb = cf.get("ecb_payments", [])
    if not ecb:
        return insights

    total_ecb = sum(p.get("amount", 0) for p in ecb)
    if total_ecb <= 0:
        return insights

    ecb_hedged = any("ecb" in str(c.get("purpose", "")).lower()
                     for c in fc.get("active_contracts", []))

    if not ecb_hedged:
        ecb_rows = [[p["month"], f"${p['amount']:,.0f}K", "None"] for p in ecb]
        insights.append(_insight(
            "HIGH", "UNHEDGED_EXPOSURE",
            f"ECB Loan Repayments Unhedged \u2014 USD {total_ecb:,.0f}K in FY27",
            f"Cash flow forecast shows ECB principal repayments of USD {total_ecb:,.0f}K. "
            "No corresponding hedge found. RBI ECB guidelines require hedging.",
            "Cash Flow Forecast, Forward Contract Register, Risk Policy",
            "Arrange cross-currency swap or forward cover. Policy permits CCS for ECB with CFO approval.",
            evidence=[
                _ev_table("Cash Flow Forecast \u2014 ECB Repayments",
                          "Doc9_Cash_Flow_Forecast.xlsx",
                          ["Month", "Principal Payment", "Hedge Coverage"], ecb_rows),
                _ev_text("Treasury Risk Policy \u2014 Section 5",
                         "Doc5_Treasury_Risk_Policy.docx",
                         "Cross-currency swaps permitted only for ECB hedging, subject to CFO approval."),
            ],
        ))
    return insights


def _check_tenor_limits(docs: dict) -> list[dict]:
    """Group all 12M tenor contracts into a single insight."""
    contracts = docs.get("forward_contracts", {}).get("active_contracts", [])
    at_limit = [c for c in contracts if c.get("tenor", "").upper() == "12M"]
    if not at_limit:
        return []

    rows = [
        [c["deal_ref"], c["bank"], c["pair"], f"{c['notional']:,.0f}",
         c.get("maturity_date", "?")]
        for c in at_limit
    ]
    return [_insight(
        "LOW", "TENOR_LIMIT",
        f"{len(at_limit)} Forward Contracts at RBI 12M Limit",
        f"{len(at_limit)} active contracts are at the maximum 12-month tenor "
        "permitted for exporters under RBI guidelines. Rollover beyond 12M "
        "requires specific RBI/AD bank approval.",
        "Forward Contract Register",
        "Ensure underlying exposures are confirmed. Do not roll over without RBI approval.",
        evidence=[_ev_table(
            "Contracts at 12M Tenor",
            "Doc2_Forward_Contract_Register.xlsx",
            ["Deal Ref", "Bank", "Pair", "Notional", "Maturity"],
            rows,
        )],
    )]


def _check_mtm_stoploss(docs: dict) -> list[dict]:
    insights = []
    fc = docs.get("forward_contracts", {})
    contracts = fc.get("active_contracts", [])
    total_mtm = fc.get("hedge_summary", {}).get("total_mtm_inr", 0)

    losers = [c for c in contracts if c.get("mtm_inr", 0) < 0]
    total_loss = sum(c["mtm_inr"] for c in losers)
    total_gain = sum(c["mtm_inr"] for c in contracts if c.get("mtm_inr", 0) > 0)
    loss_cr = abs(total_loss) / 10_000_000

    loss_rows = [
        [c["deal_ref"], c["bank"], c["pair"], f"{c['notional']:,.0f}",
         f"{c['forward_rate']:.4f}", f"INR {c['mtm_inr'] / 100_000:.1f}L"]
        for c in losers
    ]
    loss_ev = _ev_table(
        "Forward Contracts \u2014 Negative MTM",
        "Doc2_Forward_Contract_Register.xlsx",
        ["Deal Ref", "Bank", "Pair", "Notional", "Fwd Rate", "MTM (INR)"],
        loss_rows,
    ) if loss_rows else None

    if loss_cr > 15:
        ev = [loss_ev] if loss_ev else []
        ev.append(_ev_text("Risk Policy \u2014 Section 10", "Doc5_Treasury_Risk_Policy.docx",
                           "MTM loss > INR 15 Cr: Emergency review required \u2014 CFO + MD."))
        insights.append(_insight(
            "CRITICAL", "MTM_STOPLOSS",
            "MTM Loss Exceeds INR 15 Cr \u2014 Emergency Review Required",
            f"Aggregate MTM loss: INR {loss_cr:.1f} Cr. Net P&L: INR {total_mtm / 10_000_000:.1f} Cr.",
            "Forward Contract Register, Risk Policy",
            "Convene emergency review with CFO and MD. Assess unwinding options.",
            evidence=ev,
        ))
    elif loss_cr > 5:
        ev = [loss_ev] if loss_ev else []
        ev.append(_ev_text("Risk Policy \u2014 Section 10", "Doc5_Treasury_Risk_Policy.docx",
                           "MTM loss > INR 5 Cr: Review hedge strategy \u2014 escalate to CFO."))
        insights.append(_insight(
            "HIGH", "MTM_STOPLOSS",
            "MTM Loss Exceeds INR 5 Cr \u2014 Strategy Review Required",
            f"Aggregate MTM loss: INR {loss_cr:.1f} Cr. Net P&L: INR {total_mtm / 10_000_000:.1f} Cr.",
            "Forward Contract Register, Risk Policy",
            "Schedule hedge strategy review with CFO.",
            evidence=ev,
        ))

    for c in losers:
        if c["mtm_inr"] < -2_000_000:
            insights.append(_insight(
                "MEDIUM", "MTM_STOPLOSS",
                f"Large MTM Loss \u2014 {c['deal_ref']} (INR {abs(c['mtm_inr']) / 100_000:.1f}L)",
                f"{c['deal_ref']} ({c['bank']}): {c['pair']} {c['notional']:,.0f} booked at "
                f"{c['forward_rate']:.4f}, MTM: INR {c['mtm_inr'] / 100_000:.1f} lakh.",
                "Forward Contract Register",
                "Monitor. Review at next hedge book reconciliation.",
                evidence=[_ev_table(
                    "Contract Detail",
                    "Doc2_Forward_Contract_Register.xlsx",
                    ["Deal Ref", "Bank", "Pair", "Notional", "Fwd Rate", "Maturity", "MTM"],
                    [[c["deal_ref"], c["bank"], c["pair"], f"{c['notional']:,.0f}",
                      f"{c['forward_rate']:.4f}", c.get("maturity_date", "?"),
                      f"INR {c['mtm_inr'] / 100_000:.1f}L"]],
                )],
            ))
    return insights


def _check_action_items(docs: dict, today: str) -> list[dict]:
    insights = []
    items = docs.get("rc_minutes", {}).get("action_items", [])
    seen_actions: set[str] = set()

    for item in items:
        deadline = item.get("deadline")
        if not deadline or "ongoing" in str(deadline).lower():
            continue
        days = _days_between(today, deadline)
        if days is None:
            continue

        action = item.get("action", "")[:120]
        owner = item.get("owner", "Unassigned")

        # Dedup by action text
        key = action[:40]
        if key in seen_actions:
            continue
        seen_actions.add(key)

        ev = [_ev_table(
            "Risk Committee Minutes \u2014 Action Items",
            "Doc7_Risk_Committee_Minutes.docx",
            ["Action", "Owner", "Deadline", "Status"],
            [[action, owner, deadline or "?",
              f"{abs(days)}d overdue" if days < 0 else f"{days}d remaining"]],
        )]

        if days < 0:
            insights.append(_insight(
                "HIGH" if abs(days) > 5 else "MEDIUM",
                "ACTION_OVERDUE",
                f"RC Action Item Overdue \u2014 {owner} ({abs(days)}d late)",
                f"Action: \u2018{action}\u2019. Deadline: {deadline}.",
                "Risk Committee Minutes",
                f"Follow up with {owner}. Escalate to RC chair if >5 days overdue.",
                evidence=ev,
            ))
        elif days <= 3:
            insights.append(_insight(
                "LOW", "ACTION_DUE",
                f"RC Action Item Due Soon \u2014 {owner} ({days}d left)",
                f"Action: \u2018{action}\u2019. Deadline: {deadline}.",
                "Risk Committee Minutes",
                f"Ensure {owner} is on track for deadline.",
                evidence=ev,
            ))
    return insights


def _check_quote_anomalies(docs: dict) -> list[dict]:
    insights = []
    quotes = docs.get("dealer_quotes", {}).get("quotes", [])

    sessions: dict[str, list[dict]] = {}
    for q in quotes:
        key = f"{q.get('date')}|{q.get('pair')}|{q.get('tenor')}"
        sessions.setdefault(key, []).append(q)

    for key, group in sessions.items():
        best = [q for q in group if q.get("is_best")]
        booked = [q for q in group if q.get("is_booked")]

        if best and booked:
            best_bank = best[0].get("bank")
            booked_bank = booked[0].get("bank")
            if best_bank and booked_bank and best_bank != booked_bank:
                parts = key.split("|")
                quote_rows = [
                    [q["bank"], f"{q.get('mid_rate', 0):.4f}", f"{q.get('spread_paise', 0):.0f}",
                     "YES" if q.get("is_best") else "", "YES" if q.get("is_booked") else ""]
                    for q in group
                ]
                insights.append(_insight(
                    "HIGH", "QUOTE_ANOMALY",
                    f"Best-Execution Violation \u2014 {parts[0]} {parts[1]} {parts[2]}",
                    f"Best quote from {best_bank} but deal booked with {booked_bank}. "
                    "Violates best-execution principles and RBI arm\u2019s-length dealing norms.",
                    "Dealer Quote Compilation",
                    "Internal audit should investigate. Document rationale if legitimate override.",
                    evidence=[_ev_table(
                        f"Dealer Quotes \u2014 {parts[0]} {parts[1]} {parts[2]}",
                        "Doc6_Dealer_Quote_Compilation.xlsx",
                        ["Bank", "Mid Rate", "Spread (p)", "Best?", "Booked?"],
                        quote_rows,
                    )],
                ))

    bank_stats: dict[str, dict] = {}
    for q in quotes:
        bank = q.get("bank", "")
        if not bank:
            continue
        if bank not in bank_stats:
            bank_stats[bank] = {"quotes": 0, "booked": 0}
        bank_stats[bank]["quotes"] += 1
        if q.get("is_booked"):
            bank_stats[bank]["booked"] += 1

    for bank, stats in bank_stats.items():
        if stats["quotes"] >= 5 and stats["booked"] == 0:
            perf_rows = [[b, str(s["quotes"]), str(s["booked"]),
                          f"{s['booked']/s['quotes']*100:.0f}%" if s['quotes'] else "0%"]
                         for b, s in sorted(bank_stats.items(), key=lambda x: -x[1]["quotes"])]
            insights.append(_insight(
                "MEDIUM", "QUOTE_ANOMALY",
                f"Zero Bookings Despite Active Quoting \u2014 {bank}",
                f"{bank} submitted {stats['quotes']} quotes but won zero deals.",
                "Dealer Quote Compilation, Risk Policy",
                "Review deal allocation process. Ensure arm\u2019s-length compliance.",
                evidence=[_ev_table(
                    "Bank Performance Summary",
                    "Doc6_Dealer_Quote_Compilation.xlsx",
                    ["Bank", "Quotes", "Booked", "Win Rate"],
                    perf_rows,
                )],
            ))
    return insights


def _check_hedge_discrepancy(docs: dict) -> list[dict]:
    fc = docs.get("forward_contracts", {})
    strat = docs.get("hedging_strategy", {})
    fc_usd = fc.get("hedge_summary", {}).get("usd_total_notional", 0)
    memo_amounts = strat.get("already_hedged_usd_m", [])

    if memo_amounts and fc_usd > 0:
        memo_total_m = sum(memo_amounts)
        fc_m = fc_usd / 1_000_000
        if abs(fc_m - memo_total_m) > 0.5:
            return [_insight(
                "MEDIUM", "DATA_DISCREPANCY",
                f"Hedge Amount Mismatch \u2014 Register (${fc_m:.1f}M) vs Memo (${memo_total_m:.1f}M)",
                f"Forward Contract Register shows USD {fc_m:.1f}M in active hedges, but "
                f"Hedging Strategy Memo references USD {memo_total_m:.1f}M as \u2018already hedged\u2019. "
                f"Gap: USD {abs(fc_m - memo_total_m):.1f}M.",
                "Forward Contract Register, Hedging Strategy Memo",
                "Reconcile the two documents. Register should be the source of truth.",
                evidence=[_ev_metric("Hedge Amount Comparison", "", [
                    {"label": "Forward Contract Register", "value": f"USD {fc_m:.1f}M"},
                    {"label": "Hedging Strategy Memo", "value": f"USD {memo_total_m:.1f}M"},
                    {"label": "Discrepancy", "value": f"USD {abs(fc_m - memo_total_m):.1f}M"},
                ])],
            )]
    return []


def _check_forecast_confidence(docs: dict) -> list[dict]:
    forecast = docs.get("receivables_forecast", {})
    confidence = forecast.get("confidence", {})

    low_conf = [(m, c.get("usd", 100), c.get("eur", 100))
                for m, c in confidence.items()
                if c.get("usd", 100) < 70 or c.get("eur", 100) < 70]
    if not low_conf:
        return []

    rows = [[m, f"{u:.0f}%", f"{e:.0f}%", "Below threshold" if u < 70 or e < 70 else "OK"]
            for m, u, e in low_conf]
    return [_insight(
        "MEDIUM", "FORECAST_RISK",
        f"Low-Confidence Forecasts \u2014 Hedge accounting risk for {len(low_conf)} months",
        "Ind AS 109 requires \u2018highly probable\u2019 exposures for hedge accounting. "
        "Forwards hedging these months may fail hedge effectiveness tests.",
        "Receivables Forecast, Hedging Strategy Memo",
        "Limit hedging to >75% confidence months. Use options for lower-confidence.",
        evidence=[_ev_table(
            "Forecast Confidence Levels",
            "Doc3_Export_Receivables_Forecast.xlsx",
            ["Month", "USD Confidence", "EUR Confidence", "Status"],
            rows,
        )],
    )]


def _check_circular_impact(docs: dict, market: dict, today: str) -> list[dict]:
    insights = []
    news = market.get("news", [])
    rbi_news = [n for n in news
                if n.get("category") == "RBI"
                and (n.get("relevance") or "").upper() == "HIGH"]

    seen_headlines: set[str] = set()
    for item in rbi_news[:3]:
        headline = item.get("headline", "") or ""
        summary = (item.get("summary", "") or "")[:200]
        if not headline or headline[:40] in seen_headlines:
            continue
        seen_headlines.add(headline[:40])

        text = (headline + " " + summary).lower()
        impact_keywords = [
            ("hedge", "hedging", "forward"),
            ("fema", "export", "realization"),
            ("repo", "rate", "interest"),
            ("ecb", "external commercial"),
        ]
        for kw_group in impact_keywords:
            if any(kw in text for kw in kw_group):
                insights.append(_insight(
                    "MEDIUM", "REGULATORY",
                    f"RBI Circular May Impact Operations",
                    f"{headline[:120]}. {summary}",
                    "Risk Policy, News/Circulars",
                    "Legal/Compliance to review against current policy.",
                    evidence=[_ev_text(
                        f"RBI Circular \u2014 {item.get('date', '')}",
                        "News Feed (OpenAI Search)",
                        f"{headline}\n\n{summary}",
                    )],
                ))
                break
    return insights


def _check_maturing_contracts(docs: dict, today: str) -> list[dict]:
    insights = []
    contracts = docs.get("forward_contracts", {}).get("active_contracts", [])

    for c in contracts:
        days = c.get("days_to_maturity", 999)
        ev = [_ev_table(
            "Forward Contract Detail",
            "Doc2_Forward_Contract_Register.xlsx",
            ["Deal Ref", "Bank", "Pair", "Notional", "Fwd Rate", "Maturity", "MTM"],
            [[c["deal_ref"], c["bank"], c["pair"], f"{c['notional']:,.0f}",
              f"{c['forward_rate']:.4f}", c.get("maturity_date", "?"),
              f"INR {c.get('mtm_inr', 0) / 100_000:.1f}L"]],
        )]
        if days <= 0:
            insights.append(_insight(
                "HIGH", "CONTRACT_MATURITY",
                f"Contract Past Maturity \u2014 {c['deal_ref']}",
                f"{c['deal_ref']} ({c['bank']}): maturity date {c.get('maturity_date')} has passed. "
                "Settlement may be pending.",
                "Forward Contract Register",
                "Verify settlement status with bank. Update register.",
                evidence=ev,
            ))
        elif days <= 5:
            insights.append(_insight(
                "MEDIUM", "CONTRACT_MATURITY",
                f"Contract Maturing in {days}d \u2014 {c['deal_ref']}",
                f"{c['deal_ref']} ({c['bank']}): {c['pair']} {c['notional']:,.0f}. "
                f"Maturity: {c.get('maturity_date')}.",
                "Forward Contract Register",
                "Confirm settlement with bank. Ensure underlying receivable is ready.",
                evidence=ev,
            ))
    return insights


# ── main entry point ───────────────────────────────────────────────────────

async def run_compliance_agent(
    run_date: str | None = None,
    persist: bool = True,
) -> dict:
    today = run_date or date.today().isoformat()
    log.info("Running compliance scan for %s", today)

    docs = parse_all_documents()
    market = _get_market_data()

    insights: list[dict] = []
    checks = [
        ("FEMA realization", lambda: _check_fema_realization(docs, today)),
        ("Bank concentration", lambda: _check_bank_concentration(docs)),
        ("Rate divergence", lambda: _check_rate_divergence(docs, market)),
        ("Policy/RC gaps", lambda: _check_policy_rc_gaps(docs)),
        ("ECB exposure", lambda: _check_ecb_exposure(docs)),
        ("Tenor limits", lambda: _check_tenor_limits(docs)),
        ("MTM stop-loss", lambda: _check_mtm_stoploss(docs)),
        ("Action items", lambda: _check_action_items(docs, today)),
        ("Quote anomalies", lambda: _check_quote_anomalies(docs)),
        ("Hedge discrepancy", lambda: _check_hedge_discrepancy(docs)),
        ("Forecast confidence", lambda: _check_forecast_confidence(docs)),
        ("Circular impact", lambda: _check_circular_impact(docs, market, today)),
        ("Maturing contracts", lambda: _check_maturing_contracts(docs, today)),
    ]

    for name, check_fn in checks:
        try:
            results = check_fn()
            insights.extend(results)
            log.info("  %s: %d insights", name, len(results))
        except Exception as e:
            log.error("  %s check failed: %s", name, e)

    insights.sort(key=lambda x: SEVERITY_ORDER.get(x["severity"], 5))

    if persist:
        try:
            with get_connection() as conn:
                conn.execute("DELETE FROM compliance_insights WHERE date = ?", (today,))
            for ins in insights:
                db.insert_compliance_insight(ComplianceInsight(
                    date=today,
                    severity=ins["severity"],
                    category=ins["category"],
                    title=ins["title"],
                    description=ins["description"],
                    affected_docs=ins["affected_docs"],
                    recommended_action=ins["recommended_action"],
                ))
        except Exception as e:
            log.error("Failed to persist compliance insights: %s", e)

    by_severity: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for ins in insights:
        by_severity[ins["severity"]] = by_severity.get(ins["severity"], 0) + 1
        by_category[ins["category"]] = by_category.get(ins["category"], 0) + 1

    log.info("Compliance scan complete: %d insights (%s)",
             len(insights), ", ".join(f"{k}:{v}" for k, v in sorted(by_severity.items())))

    return {
        "scan_date": today,
        "total_insights": len(insights),
        "by_severity": by_severity,
        "by_category": by_category,
        "insights": insights,
    }
