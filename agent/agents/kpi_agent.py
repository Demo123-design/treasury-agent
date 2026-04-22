"""Headline KPI builder.

Produces 15 treasury KPIs across five categories (Liquidity, FX, Debt,
Compliance, Counterparty) with RAG status and narratives. Inputs come from:
  • services.doc_parser.parse_all_documents() — 10 existing internal docs
  • utils.db.get_latest_spot("USDINR")       — live Frankfurter spot
  • 4 optional Excel drops (Bank_Balances, Debt_Schedule, Compliance_Log,
    Hedge_Effectiveness). Absent files → status NA with "awaiting input".

Recomputed every request (no DB persistence) — same pattern as /api/market/latest.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

from services.doc_parser import DOCS_DIR, _open_xlsx, _sheet_records, _sf, _ss, _col, parse_all_documents
from utils import db

log = logging.getLogger(__name__)


# ── categories ────────────────────────────────────────────────────────────

CAT_LIQUIDITY = "Liquidity & Cash"
CAT_FX = "FX & Hedging"
CAT_DEBT = "Debt & Borrowing"
CAT_COMPLIANCE = "Compliance & Regulatory"
CAT_COUNTERPARTY = "Counterparty & Credit Risk"

CATEGORY_ORDER = [CAT_LIQUIDITY, CAT_FX, CAT_DEBT, CAT_COMPLIANCE, CAT_COUNTERPARTY]


# ── helpers ───────────────────────────────────────────────────────────────

def _kpi(
    id: str, name: str, category: str,
    value: float | None, value_display: str,
    target: str, status: str, narrative: str,
    sources: list[str] | None = None,
) -> dict:
    return {
        "id": id,
        "name": name,
        "category": category,
        "value": value,
        "value_display": value_display,
        "target": target,
        "status": status,
        "narrative": narrative,
        "sources": sources or [],
    }


def _na(id: str, name: str, category: str, target: str, reason: str, sources: list[str] | None = None) -> dict:
    return _kpi(id, name, category, None, "n/a", target, "NA", f"Awaiting input: {reason}", sources or [])


def _fmt_mn(v: float) -> str:
    return f"{v:,.2f}"


def _fmt_pct(v: float) -> str:
    return f"{v:.1f}%"


# ── per-customer USD forecast (Doc3 re-aggregation) ───────────────────────

def _customer_usd_forecast() -> tuple[dict[str, float], float]:
    """Aggregate Doc3 receivables forecast by customer (USD section only, 12M sum).

    Doc3 layout: first a USD section (rows of customer → monthly), then a
    "SECTION B: EUR RECEIVABLES" header, then EUR customers. We stop at the
    EUR header so EUR customers don't pollute the USD denominator.
    """
    wb = _open_xlsx("Doc3_Export_Receivables_Forecast.xlsx")
    if wb is None:
        return {}, 0.0

    customer_total: dict[str, float] = {}
    try:
        sn = next((n for n in wb.sheetnames if "forecast" in n.lower() and "confidence" not in n.lower()), wb.sheetnames[0])
        headers, rows = _sheet_records(wb[sn])

        month_cols = [
            i for i, h in enumerate(headers)
            if re.match(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)", h, re.I)
        ]
        cust_match = _col(headers, "customer")
        seg_match = _col(headers, "segment")
        customer_col = cust_match if cust_match is not None else (seg_match if seg_match is not None else 0)

        in_usd_section = True
        for row in rows:
            cust = _ss(row[customer_col]) if customer_col < len(row) else ""
            cust_lower = cust.lower()

            # Section transitions: a row whose first cell signals the EUR block
            # or an "EUR RECEIVABLES" heading. Stop counting at that point.
            if ("eur" in cust_lower and "receivables" in cust_lower) or cust_lower.startswith("section b"):
                in_usd_section = False
                continue
            if "usd receivables" in cust_lower and "total" not in cust_lower:
                in_usd_section = True
                continue

            if not in_usd_section:
                continue
            if not cust or "total" in cust_lower or "grand" in cust_lower:
                continue
            # Skip the duplicate sub-header row that Doc3 places at the EUR section
            if cust_lower == "customer / segment":
                continue

            row_sum = sum(_sf(row[i]) for i in month_cols if i < len(row))
            if row_sum > 0:
                customer_total[cust] = customer_total.get(cust, 0) + row_sum
    except Exception as e:
        log.error("Error aggregating Doc3 by customer: %s", e)
    finally:
        wb.close()

    grand_total = sum(customer_total.values())
    return customer_total, grand_total


# ── KPI computations ──────────────────────────────────────────────────────

def _compute_liquidity(docs: dict) -> list[dict]:
    bb = docs.get("bank_balances", {})
    records = bb.get("records", [])

    if not records:
        return [
            _na("L01", "Total Cash Position (INR mn)", CAT_LIQUIDITY,
                "≥ INR 800 mn (operating floor)",
                "Bank_Balances.xlsx (see template in Internal Document folder)"),
            _na("L02", "INR Operating Cash (mn)", CAT_LIQUIDITY,
                "≥ INR 75 mn (policy min)", "Bank_Balances.xlsx"),
            _na("L03", "Cash Concentration — Top Bank Share", CAT_LIQUIDITY,
                "≤ 40% (internal trigger)", "Bank_Balances.xlsx"),
        ]

    sources = [bb.get("source") or "Bank_Balances.xlsx"]
    total = sum(r["balance_inr_mn"] for r in records)
    inr_operating = sum(r["balance_inr_mn"] for r in records if r["currency"].upper() == "INR")

    by_bank: dict[str, float] = {}
    for r in records:
        by_bank[r["bank"]] = by_bank.get(r["bank"], 0) + r["balance_inr_mn"]
    top_bank = max(by_bank, key=by_bank.get) if by_bank else ""
    top_share = (by_bank[top_bank] / total * 100) if total > 0 else 0

    # L01
    l01_status = "GREEN" if total >= 800 else "AMBER" if total >= 600 else "RED"
    l01_narr = (f"Healthy cushion above operating floor" if l01_status == "GREEN"
                else f"Below operating floor — review liquidity")

    # L02
    l02_status = "GREEN" if inr_operating >= 75 else "RED"
    l02_narr = ("Comfortably above policy minimum" if l02_status == "GREEN"
                else "Below INR 75 mn policy minimum")

    # L03
    l03_status = "RED" if top_share > 40 else "AMBER" if top_share > 35 else "GREEN"
    l03_narr = (f"{top_bank} concentration above 40% trigger; diversification plan in motion"
                if l03_status == "RED"
                else f"{top_bank} at {top_share:.1f}% — within policy band")

    return [
        _kpi("L01", "Total Cash Position (INR mn)", CAT_LIQUIDITY,
             total, _fmt_mn(total), "≥ INR 800 mn (operating floor)",
             l01_status, l01_narr, sources),
        _kpi("L02", "INR Operating Cash (mn)", CAT_LIQUIDITY,
             inr_operating, _fmt_mn(inr_operating), "≥ INR 75 mn (policy min)",
             l02_status, l02_narr, sources),
        _kpi("L03", "Cash Concentration — Top Bank Share", CAT_LIQUIDITY,
             top_share, _fmt_pct(top_share), "≤ 40% (internal trigger)",
             l03_status, l03_narr, sources),
    ]


def _compute_fx(docs: dict, spot: float | None) -> list[dict]:
    fc = docs.get("forward_contracts", {})
    contracts = fc.get("active_contracts", [])
    hedge_sum = fc.get("hedge_summary", {})
    rcv = docs.get("receivables_forecast", {})
    usd_monthly = rcv.get("usd_monthly", {})
    fwd_source = ["Doc2_Forward_Contract_Register.xlsx"]
    rcv_source = ["Doc3_Export_Receivables_Forecast.xlsx"]
    rt_source = ["Doc4_Export_Realization_Tracker.xlsx"]
    rc_source = ["Doc7_Risk_Committee_Minutes.docx"]

    # F01: Net Open USD Exposure = total USD receivables - total USD hedges (in USD mn)
    usd_contracts = [c for c in contracts if "usd" in c["pair"].lower()]
    usd_hedge_mn = sum(c["notional"] for c in usd_contracts) / 1_000_000
    usd_receivables_mn = sum(usd_monthly.values()) / 1_000_000 if usd_monthly else 0
    if usd_receivables_mn == 0:
        f01 = _na("F01", "Net Open USD Exposure (USD mn)", CAT_FX,
                  "Monitored (no hard limit)",
                  "Doc3 receivables forecast or Doc2 hedges", fwd_source + rcv_source)
    else:
        net_open = usd_receivables_mn - usd_hedge_mn
        f01_status = "AMBER" if net_open > 0 else "GREEN"
        f01 = _kpi("F01", "Net Open USD Exposure (USD mn)", CAT_FX,
                   net_open, f"{net_open:,.2f}", "Monitored (no hard limit)",
                   f01_status,
                   f"Receivables {usd_receivables_mn:.1f}M less hedge {usd_hedge_mn:.2f}M (Doc3 + Doc2)",
                   fwd_source + rcv_source)

    # F02: Hedge Ratio 0-3M (%)
    hedge_0_3m = sum(c["notional"] for c in usd_contracts if c["days_to_maturity"] <= 90)
    # Receivables: first 3 months from usd_monthly (order preserved in dict)
    first_3 = list(usd_monthly.values())[:3] if usd_monthly else []
    exposure_0_3m = sum(first_3)
    if exposure_0_3m <= 0:
        f02 = _na("F02", "Hedge Ratio 0-3M (%)", CAT_FX,
                  "60% — 90% (policy band)", "Doc3 forecast (0-3M bucket)", fwd_source + rcv_source)
    else:
        ratio = hedge_0_3m / exposure_0_3m * 100
        f02_status = "GREEN" if 60 <= ratio <= 90 else "AMBER" if 40 <= ratio <= 95 else "RED"
        f02 = _kpi("F02", "Hedge Ratio 0-3M (%)", CAT_FX,
                   ratio, _fmt_pct(ratio), "60% — 90% (policy band)",
                   f02_status,
                   "Within policy band; target 75% per Doc8 strategy memo" if f02_status == "GREEN"
                   else f"{ratio:.1f}% — outside 60-90% policy band",
                   fwd_source + rcv_source)

    # F03: WAR vs Spot (diff) — derived from Doc2's book MTM so this KPI is
    # internally consistent with F04. For sell-forwards (exporter hedging USD
    # receivables): total_MTM_INR = (WAR − spot) × total_USD_notional.
    # Therefore (WAR − spot) = total_MTM_INR / total_USD_notional, which is the
    # favourable/unfavourable spread per USD. Avoids the mismatch that occurs
    # when live spot diverges from the spot Doc2 was marked against.
    if usd_contracts:
        total_notional = sum(c["notional"] for c in usd_contracts)
        war = sum(c["notional"] * c["forward_rate"] for c in usd_contracts) / total_notional if total_notional else 0
        total_mtm_inr = hedge_sum.get("total_mtm_inr", 0)
        if total_notional > 0:
            diff = total_mtm_inr / total_notional
            implied_spot = war - diff
            f03_status = "GREEN" if diff >= 0 else "AMBER" if diff > -0.5 else "RED"
            sign = "+" if diff >= 0 else ""
            f03 = _kpi("F03", "Weighted-Avg USD Hedge Rate vs Spot", CAT_FX,
                       diff, f"{sign}{diff:.4f}",
                       "Hedge rate ≥ Spot (favourable)",
                       f03_status,
                       f"Hedge book WAR {war:.3f} vs book-implied spot {implied_spot:.2f} "
                       f"→ {sign}{diff:.3f} {'favourable' if diff >= 0 else 'unfavourable'}"
                       + (f" (live spot {spot:.2f})" if spot else ""),
                       fwd_source)
        else:
            f03 = _na("F03", "Weighted-Avg USD Hedge Rate vs Spot", CAT_FX,
                      "Hedge rate ≥ Spot (favourable)",
                      "active USD forward contracts", fwd_source)
    else:
        f03 = _na("F03", "Weighted-Avg USD Hedge Rate vs Spot", CAT_FX,
                  "Hedge rate ≥ Spot (favourable)",
                  "active USD forward contracts", fwd_source)

    # F04: Hedge Book MTM (INR Cr) — total_mtm_inr already computed by Doc2 parser; convert to Cr
    mtm_inr = hedge_sum.get("total_mtm_inr", 0)
    if contracts:
        mtm_cr = mtm_inr / 10_000_000  # INR to Cr
        f04_status = ("GREEN" if -5 <= mtm_cr else "AMBER" if -15 <= mtm_cr else "RED")
        f04 = _kpi("F04", "Hedge Book MTM (INR Cr)", CAT_FX,
                   mtm_cr, f"{mtm_cr:,.2f}",
                   "Stop-loss: ≤INR 5 Cr weekly / ≤INR 15 Cr monthly",
                   f04_status,
                   "Net MTM positive; well within stop-loss limits" if mtm_cr >= 0
                   else f"MTM loss {abs(mtm_cr):.2f} Cr — monitor against weekly cap",
                   fwd_source)
    else:
        f04 = _na("F04", "Hedge Book MTM (INR Cr)", CAT_FX,
                  "Stop-loss: ≤INR 5 Cr weekly / ≤INR 15 Cr monthly",
                  "Doc2 forward contracts", fwd_source)

    # F05: Realised FX Gain vs Budget — from FX_Budget.xlsx (current quarter row)
    fb = docs.get("fx_budget", {})
    fb_records = fb.get("records", [])
    current_q = next((r for r in fb_records if r["is_current"]), None) or (
        fb_records[-1] if fb_records else None
    )
    if current_q and current_q["budget_inr_cr"] > 0:
        ratio = current_q["realised_inr_cr"] / current_q["budget_inr_cr"]
        f05_status = "GREEN" if ratio >= 1.0 else "AMBER" if ratio >= 0.9 else "RED"
        f05 = _kpi("F05", "Realised Forex Gain vs Budget (x)", CAT_FX,
                   ratio, f"{ratio:.2f}x", "≥ 1.00x (at or above budget)",
                   f05_status,
                   f"{current_q['quarter']} realised INR {current_q['realised_inr_cr']:.1f} Cr "
                   f"vs budget INR {current_q['budget_inr_cr']:.1f} Cr",
                   [fb.get("source") or "FX_Budget.xlsx"])
    else:
        f05 = _na("F05", "Realised Forex Gain vs Budget (x)", CAT_FX,
                  "≥ 1.00x (at or above budget)",
                  "FX_Budget.xlsx (see template)",
                  ["FX_Budget.xlsx"])

    return [f01, f02, f03, f04, f05]


def _compute_debt(docs: dict) -> list[dict]:
    ds = docs.get("debt_schedule", {})
    records = ds.get("records", [])
    sources = [ds.get("source") or "Debt_Schedule.xlsx"]

    if not records:
        return [
            _na("D01", "Net Debt / EBITDA (x)", CAT_DEBT,
                "≤ 2.50x (ECB covenant)",
                "Debt_Schedule.xlsx (see template)"),
            _na("D02", "Working Capital Utilisation (%)", CAT_DEBT,
                "≤ 80% (internal trigger)",
                "Debt_Schedule.xlsx"),
        ]

    # D01 = long-term debt / EBITDA (ECB covenant definition, excludes WC)
    term_rows = [r for r in records if "term" in r["type"].lower()]
    total_debt = (sum(r["outstanding_inr_mn"] for r in term_rows)
                  if term_rows
                  else sum(r["outstanding_inr_mn"] for r in records))
    ebitda = max((r["ebitda_ttm_inr_mn"] for r in records), default=0)

    # D01
    if ebitda > 0:
        ratio = total_debt / ebitda
        d01_status = "GREEN" if ratio <= 2.5 else "AMBER" if ratio <= 3.0 else "RED"
        d01_narr = (f"Significant covenant headroom ({max(0, 2.5 - ratio):.2f}x of cushion)"
                    if d01_status == "GREEN"
                    else f"Ratio {ratio:.2f}x above 2.50x covenant")
        d01 = _kpi("D01", "Net Debt / EBITDA (x)", CAT_DEBT,
                   ratio, f"{ratio:.2f}x", "≤ 2.50x (ECB covenant)",
                   d01_status, d01_narr, sources)
    else:
        d01 = _na("D01", "Net Debt / EBITDA (x)", CAT_DEBT,
                  "≤ 2.50x (ECB covenant)", "EBITDA TTM value in Debt_Schedule", sources)

    # D02 — working capital utilisation = outstanding / sanctioned across all WC facilities
    wc = [r for r in records if "term" not in r["type"].lower()]  # exclude pure term loans
    sanctioned = sum(r["sanctioned_inr_mn"] for r in wc)
    outstanding = sum(r["outstanding_inr_mn"] for r in wc)
    if sanctioned > 0:
        util = outstanding / sanctioned * 100
        d02_status = "GREEN" if util <= 80 else "AMBER" if util <= 95 else "RED"
        d02 = _kpi("D02", "Working Capital Utilisation (%)", CAT_DEBT,
                   util, _fmt_pct(util), "≤ 80% (internal trigger)",
                   d02_status,
                   "Total fund-based + non-fund-based at ~%d%% of sanctioned" % int(round(util))
                   if d02_status == "GREEN" else f"Utilisation {util:.1f}% above 80% trigger",
                   sources)
    else:
        d02 = _na("D02", "Working Capital Utilisation (%)", CAT_DEBT,
                  "≤ 80% (internal trigger)", "WC facility sanctioned amounts", sources)

    return [d01, d02]


def _compute_compliance(docs: dict) -> list[dict]:
    cl = docs.get("compliance_log", {})
    records = cl.get("records", [])
    rt = docs.get("realization_tracker", {}).get("records", [])
    he = docs.get("hedge_effectiveness", {})
    he_records = he.get("records", [])

    # C01
    if records:
        total = len(records)
        on_time = sum(1 for r in records if r["on_time"])
        pct = on_time / total * 100
        c01_status = "GREEN" if pct >= 95 else "AMBER" if pct >= 90 else "RED"
        late_recent = next((r for r in records if not r["on_time"]), None)
        c01_narr = (f"{total - on_time} filing(s) late; {on_time} of {total} on-time"
                    if late_recent
                    else f"All {total} filings on-time")
        c01 = _kpi("C01", "Reg Filings On-Time % (last 12 months)", CAT_COMPLIANCE,
                   pct, _fmt_pct(pct), "≥ 95% (policy)",
                   c01_status, c01_narr, [cl.get("source") or "Compliance_Log.xlsx"])
    else:
        c01 = _na("C01", "Reg Filings On-Time % (last 12 months)", CAT_COMPLIANCE,
                  "≥ 95% (policy)",
                  "Compliance_Log.xlsx (see template)")

    # C02 — EDPMS SBs > 240 days since export = days_remaining < 30 (FEMA 270d cap)
    if rt:
        over_240 = [r for r in rt if r.get("days_remaining") is not None and r["days_remaining"] < 30]
        count = len(over_240)
        c02_status = "GREEN" if count == 0 else "AMBER" if count <= 2 else "RED"
        if count == 0:
            c02_narr = "All export proceeds within 240-day comfort window"
        else:
            sb = over_240[0]
            c02_narr = f"{sb['shipping_bill']} at >240 days ({sb['customer']}); claim/escalation in process"
        c02 = _kpi("C02", "EDPMS SBs > 240 Days (count)", CAT_COMPLIANCE,
                   count, str(count), "Target = 0 (FEMA escalation)",
                   c02_status, c02_narr, ["Doc4_Export_Realization_Tracker.xlsx"])
    else:
        c02 = _na("C02", "EDPMS SBs > 240 Days (count)", CAT_COMPLIANCE,
                  "Target = 0 (FEMA escalation)",
                  "Doc4 realization tracker records")

    # C03
    if he_records:
        total = len(he_records)
        passed = sum(1 for r in he_records if r["passed"])
        pct = passed / total * 100
        c03_status = "GREEN" if pct >= 100 else "AMBER" if pct >= 90 else "RED"
        c03 = _kpi("C03", "Hedge Effectiveness Test Pass Rate (%)", CAT_COMPLIANCE,
                   pct, _fmt_pct(pct), "Target = 100% (Ind AS 109)",
                   c03_status,
                   f"All {total} CFH designations within 80-125% dollar-offset band"
                   if c03_status == "GREEN"
                   else f"{total - passed} of {total} designations outside effectiveness band",
                   [he.get("source") or "Hedge_Effectiveness.xlsx"])
    else:
        c03 = _na("C03", "Hedge Effectiveness Test Pass Rate (%)", CAT_COMPLIANCE,
                  "Target = 100% (Ind AS 109)",
                  "Hedge_Effectiveness.xlsx (see template)")

    return [c01, c02, c03]


def _compute_counterparty(docs: dict) -> list[dict]:
    fc = docs.get("forward_contracts", {})
    bank_breakdown = fc.get("hedge_summary", {}).get("bank_breakdown", {})
    contracts = fc.get("active_contracts", [])

    # R01 — Single-bank forward concentration. Doc5 §7 is a hard cap, so any
    # breach is RED (no amber band); AMBER only for near-cap (≥27%).
    if bank_breakdown:
        total = sum(bank_breakdown.values())
        top_bank = max(bank_breakdown, key=bank_breakdown.get)
        share = bank_breakdown[top_bank] / total * 100 if total > 0 else 0
        r01_status = "RED" if share > 30 else "AMBER" if share >= 27 else "GREEN"
        r01 = _kpi("R01", "Single-Bank Concentration — Forward Book (%)", CAT_COUNTERPARTY,
                   share, _fmt_pct(share), "≤ 30% (Doc5 §7 cap)",
                   r01_status,
                   f"{top_bank} forward share at {share:.1f}%, within 30% policy cap"
                   if r01_status == "GREEN"
                   else f"{top_bank} at {share:.1f}% — "
                        + ("breaches 30% cap; redistribute new deals" if r01_status == "RED"
                           else "approaching 30% cap"),
                   ["Doc2_Forward_Contract_Register.xlsx"])
    else:
        r01 = _na("R01", "Single-Bank Concentration — Forward Book (%)", CAT_COUNTERPARTY,
                  "≤ 30% (Doc5 §7 cap)", "Doc2 active forward contracts")

    # R02 — Top-1 customer USD forecast share. 18% is a hard internal trigger,
    # so breach = RED; AMBER only for near-trigger (≥16%).
    customer_totals, grand = _customer_usd_forecast()
    if customer_totals and grand > 0:
        top_customer = max(customer_totals, key=customer_totals.get)
        share = customer_totals[top_customer] / grand * 100
        r02_status = "RED" if share > 18 else "AMBER" if share >= 16 else "GREEN"
        r02 = _kpi("R02", "Top-1 Customer Share — USD Forecast (%)", CAT_COUNTERPARTY,
                   share, _fmt_pct(share), "≤ 18% (internal trigger)",
                   r02_status,
                   f"{top_customer} at {share:.1f}% of USD 12M forecast" + (
                       "; diversification plan with Sales" if r02_status == "RED"
                       else "; approaching trigger" if r02_status == "AMBER"
                       else " — within policy band"
                   ),
                   ["Doc3_Export_Receivables_Forecast.xlsx"])
    else:
        r02 = _na("R02", "Top-1 Customer Share — USD Forecast (%)", CAT_COUNTERPARTY,
                  "≤ 18% (internal trigger)",
                  "Doc3 per-customer USD forecast rows")

    return [r01, r02]


# ── public entrypoint ─────────────────────────────────────────────────────

def build_kpi_snapshot() -> dict[str, Any]:
    """Compute all 15 KPIs fresh. Safe on missing docs — each KPI falls back to NA."""
    docs = parse_all_documents()

    spot_row = db.get_latest_spot("USDINR")
    spot = spot_row.spot_rate if spot_row else None

    kpis: list[dict] = []
    kpis.extend(_compute_liquidity(docs))
    kpis.extend(_compute_fx(docs, spot))
    kpis.extend(_compute_debt(docs))
    kpis.extend(_compute_compliance(docs))
    kpis.extend(_compute_counterparty(docs))

    by_status = {"GREEN": 0, "AMBER": 0, "RED": 0, "NA": 0}
    for k in kpis:
        by_status[k["status"]] = by_status.get(k["status"], 0) + 1

    total = len(kpis)
    computed = total - by_status["NA"]

    # Briefing one-liner
    one_liner = _one_liner(kpis, by_status, total)

    as_of = _derive_as_of(docs)

    return {
        "as_of": as_of,
        "total": total,
        "computed": computed,
        "missing_inputs": by_status["NA"],
        "by_status": by_status,
        "one_liner": one_liner,
        "categories": CATEGORY_ORDER,
        "kpis": kpis,
        "spot_used": spot,
    }


def _derive_as_of(docs: dict) -> str:
    bb = docs.get("bank_balances", {})
    if bb.get("as_of_date"):
        return bb["as_of_date"]
    return date.today().isoformat()


def _one_liner(kpis: list[dict], by_status: dict, total: int) -> str:
    reds = [k for k in kpis if k["status"] == "RED"]
    ambers = [k for k in kpis if k["status"] == "AMBER"]

    parts = []
    if by_status["GREEN"] >= total * 0.6:
        parts.append("Cash & FX healthy")
    if reds:
        red_names = ", ".join(r["name"].split("(")[0].strip() for r in reds[:2])
        parts.append(f"{red_names} require attention")
    if ambers and not reds:
        parts.append(f"{len(ambers)} amber flag{'s' if len(ambers) != 1 else ''} to monitor")

    summary = "; ".join(parts) if parts else "Status unavailable"
    tally = (
        f"{by_status['GREEN']} of {total} KPIs Green, "
        f"{by_status['AMBER']} Amber, {by_status['RED']} Red"
    )
    if by_status["NA"]:
        tally += f", {by_status['NA']} awaiting input"
    return f"{summary}. {tally}."
