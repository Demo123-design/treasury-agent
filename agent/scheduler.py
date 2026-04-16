"""APScheduler setup - two daily jobs in Asia/Kolkata timezone.

Job 1 (data_fetch, 6:00 AM IST): warms the DB with forex + news so alert
    tracking has fresh history by the time the briefing runs.
Job 2 (briefing_send, 7:30 AM IST): runs the full pipeline end-to-end and
    sends the email.

Both jobs are idempotent for the current date - Job 2 skips delivery if a
delivered briefing already exists for today.
"""
from __future__ import annotations

import logging
from datetime import date as _date

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import CONFIG
from utils import db

log = logging.getLogger(__name__)

IST = pytz.timezone("Asia/Kolkata")


async def _job_data_fetch() -> None:
    from agents.forex_agent import run_forex_agent
    from agents.news_agent import run_news_agent

    today = _date.today().isoformat()
    log.info("[job] data_fetch: starting for %s", today)
    try:
        await run_forex_agent(run_date=today, persist=True)
    except Exception as exc:
        log.exception("[job] data_fetch: forex_agent failed: %s", exc)
    try:
        await run_news_agent(run_date=today, persist=True)
    except Exception as exc:
        log.exception("[job] data_fetch: news_agent failed: %s", exc)
    log.info("[job] data_fetch: done")


async def _job_briefing_send() -> None:
    from agents.briefing_agent import run_briefing_agent
    from agents.forex_agent import run_forex_agent
    from agents.news_agent import run_news_agent

    today = _date.today().isoformat()
    log.info("[job] briefing_send: starting for %s", today)

    existing = db.get_briefing(today)
    if existing and existing.delivered:
        log.info("[job] briefing_send: already delivered for %s - skipping", today)
        return

    try:
        forex = await run_forex_agent(run_date=today, persist=True)
        news = await run_news_agent(run_date=today, persist=True)
        result = await run_briefing_agent(forex, news, dry_run=False, persist=True)
    except Exception as exc:
        log.exception("[job] briefing_send: pipeline failed: %s", exc)
        return

    delivery = result.get("delivery") or {}
    if delivery.get("success"):
        log.info("[job] briefing_send: delivered (status=%s)", delivery.get("status"))
    else:
        log.error("[job] briefing_send: delivery failed: %s | preview=%s",
                  delivery.get("error"), delivery.get("path"))


def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=IST)

    data_fetch_trigger = CronTrigger(
        hour=CONFIG.data_fetch_hour_ist,
        minute=CONFIG.data_fetch_minute_ist,
        timezone=IST,
    )
    briefing_trigger = CronTrigger(
        hour=CONFIG.briefing_hour_ist,
        minute=CONFIG.briefing_minute_ist,
        timezone=IST,
    )

    scheduler.add_job(
        _job_data_fetch,
        trigger=data_fetch_trigger,
        id="data_fetch",
        name="Data fetch (forex + news)",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=1800,
    )
    scheduler.add_job(
        _job_briefing_send,
        trigger=briefing_trigger,
        id="briefing_send",
        name="Briefing generation and send",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=1800,
    )

    log.info("Scheduler built: data_fetch %02d:%02d IST, briefing_send %02d:%02d IST",
             CONFIG.data_fetch_hour_ist, CONFIG.data_fetch_minute_ist,
             CONFIG.briefing_hour_ist, CONFIG.briefing_minute_ist)
    return scheduler
