"""Context-aware treasury chat.

Wraps OpenAI with a system prompt that embeds the current KPI snapshot,
live market data, and short summaries of the 14 parsed documents so the
assistant can answer grounded questions without extra retrieval.
"""
from __future__ import annotations

import logging
from typing import Any

from config import CONFIG
from services.openai_client import _client, MODEL
from agents.kpi_agent import build_kpi_snapshot
from services.doc_parser import parse_all_documents
from utils import db

log = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are the Treasury Intelligence assistant.

You have real-time access to the company's treasury state via the CONTEXT \
block below: 15 headline KPIs (with RAG status), live FX spot rates, the \
active hedge book, receivables forecast, export realization tracker, and \
risk/hedging policy extracts.

Guidance:
- Ground every answer in the CONTEXT. Cite specific KPI IDs (L01, F02 etc.) \
or document names (Doc2_Forward_Contract_Register.xlsx) when relevant.
- Be concise. Treasury professionals want numbers and decisions, not prose.
- Distinguish: (a) what the data shows, (b) what policy/covenants require, \
(c) what action you'd suggest. Label these explicitly when the question \
warrants it.
- Never invent a number. If a KPI is NA or a doc isn't available, say so.
- Never recommend speculative hedging — only hedging of existing underlying \
export exposures.
- When asked about something outside the CONTEXT (general market commentary, \
explanations of terms), answer briefly but flag that it is general knowledge, \
not company data.
"""


def _format_kpi_context(snap: dict) -> str:
    lines = [
        f"## CURRENT KPI SNAPSHOT  (as of {snap['as_of']})",
        f"{snap['by_status']}  —  {snap['one_liner']}",
        "",
    ]
    current_cat = None
    for k in snap["kpis"]:
        if k["category"] != current_cat:
            current_cat = k["category"]
            lines.append(f"### {current_cat}")
        lines.append(
            f"  {k['id']}  [{k['status']}]  {k['name']} = {k['value_display']}  "
            f"(target: {k['target']})  —  {k['narrative']}"
        )
    return "\n".join(lines)


def _format_market_context() -> str:
    lines = ["## LIVE MARKET"]
    try:
        for pair in ("USDINR", "EURINR"):
            sp = db.get_latest_spot(pair)
            if sp:
                lines.append(f"  {pair} spot: {sp.spot_rate:.4f}  ({sp.date})")
        for rt in ("RBI_REPO", "FED_FUNDS", "ECB_DEPOSIT"):
            ir = db.get_latest_interest_rate(rt)
            if ir:
                lines.append(f"  {rt}: {ir.rate_value:.3f}%")
    except Exception as e:
        lines.append(f"  (market data unavailable: {e})")
    return "\n".join(lines)


def _format_doc_context(docs: dict) -> str:
    lines = ["## INTERNAL DOCUMENTS"]

    fc = docs.get("forward_contracts", {})
    hs = fc.get("hedge_summary", {})
    active = fc.get("active_contracts", [])
    if active:
        lines.append(
            f"  Hedge book (Doc2): {len(active)} active contracts, "
            f"USD ${hs.get('usd_total_notional', 0):,.0f} + "
            f"EUR €{hs.get('eur_total_notional', 0):,.0f}, "
            f"MTM INR {hs.get('total_mtm_inr', 0):,.0f}"
        )
        banks = hs.get("bank_breakdown", {})
        if banks:
            top3 = sorted(banks.items(), key=lambda x: -x[1])[:3]
            lines.append(
                "  Top forward counterparties: "
                + ", ".join(f"{b} ${n:,.0f}" for b, n in top3)
            )

    rcv = docs.get("receivables_forecast", {})
    usd = rcv.get("usd_monthly", {})
    if usd:
        total = sum(usd.values())
        lines.append(f"  USD receivables forecast (Doc3): 12M sum ${total:,.0f} across {len(usd)} months")

    rt = docs.get("realization_tracker", {}).get("records", [])
    if rt:
        high_risk = [r for r in rt if r.get("risk_level", "").upper() == "HIGH"]
        lines.append(f"  Realization tracker (Doc4): {len(rt)} open SBs, {len(high_risk)} HIGH-risk")

    rp = docs.get("risk_policy", {})
    if rp.get("hedge_bands"):
        bands = ", ".join(f"{b['tenor']} {b['min_pct']}-{b['max_pct']}%" for b in rp["hedge_bands"])
        lines.append(f"  Hedge policy bands (Doc5): {bands}")
    if rp.get("bank_concentration_limit_pct"):
        lines.append(f"  Bank concentration cap (Doc5 §7): ≤{rp['bank_concentration_limit_pct']}%")

    return "\n".join(lines)


def build_context() -> str:
    snap = build_kpi_snapshot()
    docs = parse_all_documents()
    return "\n\n".join([
        _format_kpi_context(snap),
        _format_market_context(),
        _format_doc_context(docs),
    ])


async def chat(history: list[dict[str, str]]) -> str:
    """history = [{role: user|assistant, content: ...}, ...]. Returns assistant reply text."""
    if not CONFIG.openai_api_key:
        return ("I'm not configured with an OPENAI_API_KEY on the server, "
                "so I can't respond right now. Set OPENAI_API_KEY in agent/.env.")

    context = build_context()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + "\n\n---\nCONTEXT:\n\n" + context},
        *[{"role": m["role"], "content": m["content"]} for m in history if m.get("content")],
    ]

    try:
        client = _client()
        resp = await client.chat.completions.create(
            model=MODEL,
            temperature=0.2,
            messages=messages,
            max_tokens=700,
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        log.exception("chat failed: %s", e)
        return f"Sorry — the chat service hit an error: {e}"
