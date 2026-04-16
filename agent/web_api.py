"""FastAPI backend for the dashboard - thin wrapper over the agent + DB.

Run:  uvicorn web_api:app --reload --port 8000
Open: http://localhost:8000/docs for interactive API explorer.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

import os

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from config import CONFIG, configure_logging
from utils import db
from utils.db import get_connection

configure_logging(CONFIG)
log = logging.getLogger(__name__)

app = FastAPI(title="PI Treasury Intelligence Agent API", version="0.1.0")

_default_origins = "http://localhost:5173,http://127.0.0.1:5173"
_cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", _default_origins).split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


# ---- job state -------------------------------------------------------------

STAGES = ["forex", "news", "briefing", "delivery"]

_run_state: dict[str, Any] = {
    "status": "idle",  # idle | running | success | error
    "stage": None,      # forex | news | briefing | delivery | complete
    "stage_status": {s: "pending" for s in STAGES},  # pending | active | done | skipped
    "started_at": None,
    "finished_at": None,
    "dry_run": None,
    "error": None,
    "html_path": None,
    "briefing_date": None,
}
_run_lock = asyncio.Lock()


def _reset_stages() -> None:
    _run_state["stage_status"] = {s: "pending" for s in STAGES}


def _stage_start(name: str) -> None:
    _run_state["stage"] = name
    _run_state["stage_status"][name] = "active"


def _stage_done(name: str) -> None:
    _run_state["stage_status"][name] = "done"


def _stage_skip(name: str) -> None:
    _run_state["stage_status"][name] = "skipped"


async def _do_run(dry_run: bool) -> None:
    from agents.briefing_agent import run_briefing_agent
    from agents.forex_agent import run_forex_agent
    from agents.news_agent import run_news_agent

    _reset_stages()
    _run_state.update({
        "status": "running",
        "stage": None,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "finished_at": None,
        "dry_run": dry_run,
        "error": None,
        "html_path": None,
        "briefing_date": None,
    })
    try:
        _stage_start("forex")
        forex = await run_forex_agent(persist=True)
        _stage_done("forex")

        _stage_start("news")
        news = await run_news_agent(persist=True)
        _stage_done("news")

        _stage_start("briefing")
        result = await run_briefing_agent(forex, news, dry_run=dry_run, persist=True)
        _stage_done("briefing")

        if dry_run:
            _stage_skip("delivery")
        else:
            _stage_start("delivery")
            # run_briefing_agent already attempted the send
            delivery = result.get("delivery") or {}
            if delivery.get("success"):
                _stage_done("delivery")
            else:
                _run_state["stage_status"]["delivery"] = "error"

        _run_state.update({
            "status": "success",
            "stage": "complete",
            "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "html_path": result.get("html_path"),
            "briefing_date": result.get("date"),
        })
    except Exception as exc:
        log.exception("web_api: pipeline run failed: %s", exc)
        if _run_state.get("stage") in STAGES:
            _run_state["stage_status"][_run_state["stage"]] = "error"
        _run_state.update({
            "status": "error",
            "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "error": str(exc),
        })


# ---- endpoints -------------------------------------------------------------

@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "has_openai_key": bool(CONFIG.openai_api_key),
            "has_sendgrid_key": bool(CONFIG.sendgrid_api_key)}


@app.get("/api/market/latest")
async def market_latest() -> dict:
    """Run forex_agent without persisting - always returns fresh spot + curves."""
    from agents.forex_agent import run_forex_agent
    try:
        return await run_forex_agent(persist=False)
    except Exception as exc:
        log.exception("web_api: market_latest failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"forex fetch failed: {exc}")


@app.get("/api/alerts")
async def get_alerts(limit: int = 20) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, date, alert_type, message, threshold, actual_value, triggered_at "
            "FROM alerts ORDER BY triggered_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/briefings")
async def list_briefings(limit: int = 50) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT b.date, b.generated_at, b.delivered, b.delivery_error, "
            "       (SELECT spot_rate FROM spot_rates s WHERE s.pair='USDINR' AND substr(s.fetched_at,1,10)=b.date ORDER BY s.id DESC LIMIT 1) AS usdinr, "
            "       (SELECT spot_rate FROM spot_rates s WHERE s.pair='EURINR' AND substr(s.fetched_at,1,10)=b.date ORDER BY s.id DESC LIMIT 1) AS eurinr, "
            "       (SELECT COUNT(*) FROM alerts a WHERE a.date=b.date) AS alerts_count "
            "FROM briefings b "
            "ORDER BY b.date DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/briefings/{date}")
async def get_briefing_detail(date: str) -> dict:
    br = db.get_briefing(date)
    if br is None:
        raise HTTPException(status_code=404, detail=f"No briefing for {date}")

    with get_connection() as conn:
        spots = conn.execute(
            "SELECT pair, spot_rate, source, fetched_at, date AS quote_date FROM spot_rates "
            "WHERE substr(fetched_at,1,10)=? ORDER BY id DESC",
            (date,),
        ).fetchall()
        forwards = conn.execute(
            "SELECT pair, tenor, forward_rate, forward_premium_bps, india_rate, foreign_rate "
            "FROM forward_rates WHERE date=? ORDER BY pair, "
            "CASE tenor WHEN '1M' THEN 1 WHEN '3M' THEN 2 WHEN '6M' THEN 3 WHEN '12M' THEN 4 ELSE 5 END",
            (date,),
        ).fetchall()
        alerts_rows = conn.execute(
            "SELECT alert_type, message, threshold, actual_value, triggered_at "
            "FROM alerts WHERE date=? ORDER BY id",
            (date,),
        ).fetchall()
        news_rows = conn.execute(
            "SELECT category, headline, summary, relevance, source_url "
            "FROM news_items WHERE id IN ("
            "  SELECT MAX(id) FROM news_items WHERE date=? GROUP BY category"
            ") ORDER BY CASE category "
            "  WHEN 'RBI' THEN 1 WHEN 'FED_ECB' THEN 2 WHEN 'CRUDE' THEN 3 "
            "  WHEN 'INDIA_MACRO' THEN 4 WHEN 'GLOBAL_RISK' THEN 5 ELSE 6 END",
            (date,),
        ).fetchall()

    sections = None
    if br.sections_json:
        try:
            sections = json.loads(br.sections_json)
        except json.JSONDecodeError:
            sections = None

    return {
        "date": br.date,
        "generated_at": br.generated_at,
        "delivered": br.delivered,
        "delivery_error": br.delivery_error,
        "sections": sections,
        "spot_rates": [dict(r) for r in spots],
        "forward_rates": [dict(r) for r in forwards],
        "alerts": [dict(r) for r in alerts_rows],
        "news": [dict(r) for r in news_rows],
    }


@app.get("/api/briefings/{date}/html", response_class=HTMLResponse)
async def get_briefing_html(date: str) -> HTMLResponse:
    br = db.get_briefing(date)
    if br is None or not br.html_content:
        raise HTTPException(status_code=404, detail=f"No briefing HTML for {date}")
    return HTMLResponse(content=br.html_content)


@app.post("/api/run")
async def trigger_run(background_tasks: BackgroundTasks, dry_run: bool = True) -> dict:
    """Kick off the pipeline in the background. Returns immediately."""
    if _run_state.get("status") == "running":
        return {"accepted": False, "reason": "already running", "state": _run_state}

    if not dry_run:
        try:
            CONFIG.require_live_keys()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    async def _runner() -> None:
        async with _run_lock:
            await _do_run(dry_run=dry_run)

    background_tasks.add_task(_runner)
    return {"accepted": True, "dry_run": dry_run}


@app.get("/api/run/status")
async def run_status() -> dict:
    return dict(_run_state)


# ---- compliance scanner ---------------------------------------------------

@app.get("/api/compliance")
async def compliance_scan() -> dict:
    """Run the compliance scanner against internal docs + market data."""
    from agents.compliance_agent import run_compliance_agent
    try:
        return await run_compliance_agent(persist=True)
    except Exception as exc:
        log.exception("web_api: compliance scan failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"compliance scan failed: {exc}")


@app.get("/api/compliance/latest")
async def compliance_latest() -> dict:
    """Return the most recent persisted compliance scan (no re-scan)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, date, severity, category, title, description, "
            "affected_docs, recommended_action, created_at "
            "FROM compliance_insights "
            "WHERE date = (SELECT MAX(date) FROM compliance_insights) "
            "ORDER BY CASE severity "
            "  WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1 "
            "  WHEN 'MEDIUM' THEN 2 WHEN 'LOW' THEN 3 ELSE 4 END, id",
        ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="No compliance scan results found")

    insights = [dict(r) for r in rows]
    by_severity: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for ins in insights:
        by_severity[ins["severity"]] = by_severity.get(ins["severity"], 0) + 1
        by_category[ins["category"]] = by_category.get(ins["category"], 0) + 1

    return {
        "scan_date": insights[0]["date"],
        "total_insights": len(insights),
        "by_severity": by_severity,
        "by_category": by_category,
        "insights": insights,
    }
