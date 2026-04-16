"""Frankfurter.dev API client — free ECB-sourced FX rates, no API key.

Real endpoint differs slightly from PRD: uses /v1/latest and /v1/{from}..{to}
instead of /v2/rates. Response shape is:
    {"amount": 1.0, "base": "USD", "date": "2026-04-10", "rates": {"INR": 92.89}}
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta

import aiohttp

BASE_URL = "https://api.frankfurter.dev/v1"
USER_AGENT = "pi-treasury-agent/0.1"
DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=15)
MAX_RETRIES = 3

log = logging.getLogger(__name__)


async def _request(session: aiohttp.ClientSession, url: str) -> dict:
    """GET with exponential backoff retry (1s, 2s, 4s)."""
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            async with session.get(url, headers={"User-Agent": USER_AGENT}) as resp:
                resp.raise_for_status()
                return await resp.json()
        except Exception as exc:
            last_exc = exc
            wait = 2**attempt
            log.warning("Frankfurter GET %s failed (attempt %d/%d): %s — retrying in %ds",
                        url, attempt + 1, MAX_RETRIES, exc, wait)
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(wait)
    assert last_exc is not None
    raise last_exc


async def get_spot_rate(base: str, quote: str, session: aiohttp.ClientSession | None = None) -> dict:
    """Fetch latest spot rate for base→quote.

    Returns: {"rate": float, "date": str, "base": str, "quote": str}
    """
    url = f"{BASE_URL}/latest?base={base}&symbols={quote}"
    owns_session = session is None
    if owns_session:
        session = aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT)
    try:
        data = await _request(session, url)
        rate = float(data["rates"][quote])
        return {"rate": rate, "date": data["date"], "base": base, "quote": quote}
    finally:
        if owns_session:
            await session.close()


async def get_historical_rates(
    base: str,
    quote: str,
    days: int = 30,
    session: aiohttp.ClientSession | None = None,
) -> list[dict]:
    """Fetch daily rates for the last `days` calendar days.

    Returns: [{"date": "2026-03-12", "rate": 92.87}, ...] sorted oldest→newest.
    """
    end = date.today()
    start = end - timedelta(days=days)
    url = f"{BASE_URL}/{start.isoformat()}..{end.isoformat()}?base={base}&symbols={quote}"
    owns_session = session is None
    if owns_session:
        session = aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT)
    try:
        data = await _request(session, url)
        rates_map: dict[str, dict[str, float]] = data.get("rates", {})
        series = [
            {"date": d, "rate": float(r[quote])}
            for d, r in sorted(rates_map.items())
            if quote in r
        ]
        return series
    finally:
        if owns_session:
            await session.close()


async def get_all_required_rates() -> dict:
    """Fetches USDINR and EURINR spot in parallel on a single session."""
    async with aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT) as session:
        usd_task = get_spot_rate("USD", "INR", session=session)
        eur_task = get_spot_rate("EUR", "INR", session=session)
        usd, eur = await asyncio.gather(usd_task, eur_task)
    return {"USDINR": usd, "EURINR": eur}


async def get_all_required_history(days: int = 30) -> dict:
    """Fetches USDINR and EURINR history in parallel on a single session."""
    async with aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT) as session:
        usd_task = get_historical_rates("USD", "INR", days=days, session=session)
        eur_task = get_historical_rates("EUR", "INR", days=days, session=session)
        usd, eur = await asyncio.gather(usd_task, eur_task)
    return {"USDINR": usd, "EURINR": eur}
