"""Entry point for the PI Treasury Intelligence Agent.

Run modes:

  python main.py               - scheduler mode (blocks, runs 6:00 + 7:30 IST daily)
  python main.py --now         - run the full pipeline once and attempt live send
  python main.py --dry-run     - run the full pipeline once, save HTML preview, no send
  python main.py --date YYYY-MM-DD  - override the date for --dry-run or --now
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal

from config import CONFIG, configure_logging
from utils.db import init_db

log = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PI Treasury Intelligence Agent")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--now", action="store_true",
                      help="Run full pipeline immediately and attempt live email send")
    mode.add_argument("--dry-run", action="store_true",
                      help="Run full pipeline once, save HTML preview, do not send")
    parser.add_argument("--date", help="ISO date override (YYYY-MM-DD) for --dry-run/--now")
    return parser.parse_args()


async def _run_pipeline(run_date: str | None, dry_run: bool) -> dict:
    from agents.briefing_agent import run_briefing_agent
    from agents.forex_agent import run_forex_agent
    from agents.news_agent import run_news_agent

    forex = await run_forex_agent(run_date=run_date, persist=True)
    news = await run_news_agent(run_date=run_date, persist=True)
    briefing = await run_briefing_agent(forex, news, dry_run=dry_run, persist=True)
    return {"forex": forex, "news": news, "briefing": briefing}


async def _run_once(run_date: str | None, dry_run: bool) -> None:
    result = await _run_pipeline(run_date, dry_run=dry_run)
    briefing = result["briefing"]
    print("\n=== BRIEFING SECTIONS ===")
    print(json.dumps(briefing["briefing"], indent=2, default=str))
    print("\n=== DELIVERY ===")
    print(json.dumps(briefing["delivery"], indent=2, default=str))
    print(f"\nHTML preview: {briefing['html_path']}")


async def _run_scheduler() -> None:
    from scheduler import build_scheduler

    scheduler = build_scheduler()
    scheduler.start()

    log.info("Scheduler running. Press Ctrl+C to stop.")
    jobs_info = [(j.id, str(j.next_run_time)) for j in scheduler.get_jobs()]
    for jid, next_run in jobs_info:
        log.info("  next %s -> %s", jid, next_run)

    stop_event = asyncio.Event()

    def _handle_signal() -> None:
        log.info("Shutdown signal received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            # Windows asyncio loop does not support add_signal_handler.
            pass

    try:
        await stop_event.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        scheduler.shutdown(wait=False)
        log.info("Scheduler stopped")


def main() -> None:
    configure_logging(CONFIG)
    init_db()
    args = _parse_args()

    if args.dry_run:
        asyncio.run(_run_once(args.date, dry_run=True))
        return

    if args.now:
        try:
            CONFIG.require_live_keys()
        except Exception as exc:
            log.error("%s", exc)
            raise SystemExit(1)
        asyncio.run(_run_once(args.date, dry_run=False))
        return

    try:
        asyncio.run(_run_scheduler())
    except KeyboardInterrupt:
        log.info("Interrupted by user")


if __name__ == "__main__":
    main()
