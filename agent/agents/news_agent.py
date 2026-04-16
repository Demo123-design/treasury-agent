"""News agent - runs Perplexity queries, parses, persists to DB."""
from __future__ import annotations

import logging
from datetime import date as _date

from models.schema import InterestRate, NewsItem
from services import openai_search
from utils import db

log = logging.getLogger(__name__)


async def run_news_agent(run_date: str | None = None, persist: bool = True) -> dict:
    today = run_date or _date.today().isoformat()
    log.info("news_agent: starting run for %s", today)

    try:
        news = await openai_search.fetch_all_news(today)
    except Exception as exc:
        log.error("news_agent: fetch_all_news failed entirely: %s", exc)
        news = {}

    if persist:
        for key, payload in news.items():
            try:
                citation_url = None
                citations = payload.get("citations") or []
                if citations:
                    first = citations[0]
                    if isinstance(first, dict):
                        citation_url = first.get("url")
                    elif isinstance(first, str):
                        citation_url = first
                db.insert_news_item(NewsItem(
                    date=today,
                    category=payload["category"],
                    headline=payload.get("headline"),
                    summary=payload.get("content"),
                    relevance=payload.get("relevance"),
                    source_url=citation_url,
                ))
            except Exception as exc:
                log.error("news_agent: DB persist failed for %s: %s", key, exc)

    log.info("news_agent: done - %d queries completed", len(news))
    return {"date": today, "news": news}


async def refresh_interest_rates(run_date: str | None = None, persist: bool = True) -> dict:
    """Fetch latest policy rates from Perplexity and upsert to DB."""
    today = run_date or _date.today().isoformat()
    log.info("news_agent: refreshing interest rates for %s", today)
    try:
        rates = await openai_search.fetch_interest_rates(today)
    except Exception as exc:
        log.error("news_agent: interest rate refresh failed: %s", exc)
        return {}

    if persist:
        for rate_type in ("RBI_REPO", "FED_FUNDS", "ECB_DEPOSIT"):
            if rate_type in rates:
                try:
                    db.upsert_interest_rate(InterestRate(
                        rate_type=rate_type,
                        rate_value=float(rates[rate_type]),
                        effective_date=today,
                        source="perplexity",
                    ))
                except Exception as exc:
                    log.error("news_agent: upsert %s failed: %s", rate_type, exc)

    log.info("news_agent: interest rates refreshed: %s",
             {k: v for k, v in rates.items() if k != "raw"})
    return rates
