"""Briefing agent - assembles context, generates briefing, delivers email."""
from __future__ import annotations

import json
import logging

from models.schema import Briefing
from services import email_service, openai_client
from utils import db
from utils.formatter import build_html_email, build_text_email

log = logging.getLogger(__name__)


def _assemble_context(forex: dict, news: dict) -> dict:
    return {
        "date": forex.get("date"),
        "spot_rates": forex.get("spot_rates"),
        "forward_curves": forex.get("forward_curves"),
        "30d_avg_spot": forex.get("30d_avg_spot"),
        "hedging_assessment": forex.get("hedging_assessment"),
        "interest_rates": forex.get("interest_rates"),
        "alerts": forex.get("alerts"),
        "news": (news or {}).get("news") or {},
    }


async def run_briefing_agent(
    forex_data: dict,
    news_data: dict,
    dry_run: bool = False,
    persist: bool = True,
) -> dict:
    date = forex_data.get("date") or (news_data or {}).get("date") or ""
    log.info("briefing_agent: starting run for %s (dry_run=%s)", date, dry_run)

    context = _assemble_context(forex_data, news_data)
    briefing = await openai_client.generate_morning_briefing(context)

    html = build_html_email(briefing, forex_data, news_data, date)
    text = build_text_email(briefing, forex_data, date)

    usd_rate = ((forex_data.get("spot_rates") or {}).get("USDINR") or {}).get("rate")
    delivery = email_service.send_briefing_email(
        html=html,
        text=text,
        date=date,
        usd_rate=usd_rate,
        dry_run=dry_run,
    )

    if persist:
        try:
            db.upsert_briefing(Briefing(
                date=date,
                html_content=html,
                text_content=text,
                sections_json=json.dumps(briefing, default=str),
                delivered=bool(delivery.get("success")) and not dry_run,
                delivery_error=None if delivery.get("success") else delivery.get("error"),
            ))
        except Exception as exc:
            log.error("briefing_agent: DB persist failed: %s", exc)

    log.info("briefing_agent: done - delivery=%s fallback=%s",
             delivery.get("success"), briefing.get("_fallback", False))
    return {
        "date": date,
        "briefing": briefing,
        "delivery": delivery,
        "html_path": delivery.get("path"),
    }
