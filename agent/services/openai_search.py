"""OpenAI web search client (gpt-4o-search-preview) - replaces Perplexity.

Uses the Chat Completions API with `web_search_options` enabled. Citations
arrive via `message.annotations` as `url_citation` entries.

Runs all 5 daily queries in parallel via AsyncOpenAI.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from openai import AsyncOpenAI
from openai import APIError, AuthenticationError, RateLimitError

from config import CONFIG

MODEL = "gpt-4o-search-preview"

log = logging.getLogger(__name__)


DAILY_QUERIES: dict[str, dict[str, str]] = {
    "rbi_policy": {
        "category": "RBI",
        "user": "Reserve Bank of India circulars notifications press releases today and recent 30 days FEMA export hedging forex {date}",
        "system": (
            "You are a treasury analyst tracking Reserve Bank of India actions. "
            "Output in TWO clearly-labeled sections separated by a blank line:\n\n"
            "TODAY ({date}):\n"
            "  Any RBI circulars, notifications, or press releases issued today. "
            "  If none, write exactly: 'No new circulars today.'\n\n"
            "RECENT (last 30 days):\n"
            "  The 3 most recent RBI circulars or major policy actions from the past 30 days, "
            "  excluding anything listed under TODAY. Format each as a bullet:\n"
            "  - [Circular/Ref No. if available] | <issue date> | <one-line summary> | <RELEVANCE: HIGH|MEDIUM|LOW>\n\n"
            "Relevance is to Indian exporters hedging USD/INR or EUR/INR forwards. "
            "Be factual and cite sources for every entry."
        ),
    },
    "fed_ecb": {
        "category": "FED_ECB",
        "user": "US Federal Reserve ECB interest rate decision statement latest news {date}",
        "system": (
            "Summarize any Federal Reserve or ECB rate decisions, minutes, or forward guidance from the "
            "past 24 hours. Focus on: rate change (if any), stance shift, and impact on USD and EUR "
            "strength vs INR. Be brief and factual. End with a RELEVANCE tag (HIGH, MEDIUM, or LOW)."
        ),
    },
    "crude_oil": {
        "category": "CRUDE",
        "user": "Brent crude oil price today USD per barrel {date}",
        "system": (
            "Give the current Brent crude oil price in USD per barrel. State if it is above $90 or $100 "
            "(alert thresholds). Briefly explain any sharp move and its likely impact on INR "
            "(India imports ~85% of its crude). End with a RELEVANCE tag (HIGH, MEDIUM, or LOW)."
        ),
    },
    "india_macro": {
        "category": "INDIA_MACRO",
        "user": "India CPI inflation WPI trade balance FPI FDI flows rupee INR today {date}",
        "system": (
            "Summarize any India macro data released today or this week: CPI, WPI, trade balance, "
            "FPI/FDI flows. State the direction of impact on INR (positive/negative/neutral) for each. "
            "End with a RELEVANCE tag (HIGH, MEDIUM, or LOW)."
        ),
    },
    "global_risk": {
        "category": "GLOBAL_RISK",
        "user": "USD INR forecast market outlook geopolitical risk global markets {date}",
        "system": (
            "Summarize key global risk factors affecting INR today: US treasury yields, DXY movement, "
            "geopolitical events, China PMI, trade policy changes. Limit to top 2-3 factors with clear "
            "impact direction on INR. End with a RELEVANCE tag (HIGH, MEDIUM, or LOW)."
        ),
    },
}


RATES_QUERY = {
    "user": "Current RBI repo rate US federal funds rate ECB deposit rate {date}",
    "system": (
        "Return the current official policy rates as of today. Output in this exact format, one per line, "
        "with percentages:\n"
        "RBI_REPO: X.XX%\n"
        "FED_FUNDS_UPPER: X.XX%\n"
        "FED_FUNDS_LOWER: X.XX%\n"
        "ECB_DEPOSIT: X.XX%\n"
        "Then briefly cite the source for each. Do not speculate - only confirmed current rates."
    ),
}


class OpenAISearchError(RuntimeError):
    pass


def _client() -> AsyncOpenAI:
    if not CONFIG.openai_api_key:
        raise OpenAISearchError("OPENAI_API_KEY not set in agent/.env")
    return AsyncOpenAI(api_key=CONFIG.openai_api_key, max_retries=2)


def _first_line(text: str, maxlen: int = 200) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:maxlen]
    return text[:maxlen]


def _extract_relevance(text: str) -> str | None:
    match = re.search(r"\bRELEVANCE\s*[:=-]?\s*(HIGH|MEDIUM|LOW)\b", text, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    for level in ("HIGH", "MEDIUM", "LOW"):
        if re.search(rf"\b{level}\b", text):
            return level
    return None


def _extract_citations(message: Any) -> list[dict]:
    """Pull url_citation annotations off an assistant message."""
    out: list[dict] = []
    annotations = getattr(message, "annotations", None) or []
    for ann in annotations:
        if getattr(ann, "type", None) != "url_citation":
            continue
        url_c = getattr(ann, "url_citation", None)
        if url_c is None:
            continue
        out.append({
            "url": getattr(url_c, "url", None),
            "title": getattr(url_c, "title", None),
        })
    return out


async def _run_one(client: AsyncOpenAI, key: str, date: str) -> dict:
    spec = DAILY_QUERIES[key]
    resp = await client.chat.completions.create(
        model=MODEL,
        web_search_options={},
        messages=[
            {"role": "system", "content": spec["system"]},
            {"role": "user", "content": spec["user"].format(date=date)},
        ],
    )
    msg = resp.choices[0].message
    content = msg.content or ""
    citations = _extract_citations(msg)
    usage = resp.usage
    total_tokens = int(getattr(usage, "total_tokens", 0) or 0)
    return {
        "category": spec["category"],
        "content": content,
        "citations": citations,
        "headline": _first_line(content),
        "relevance": _extract_relevance(content),
        "tokens_used": total_tokens,
    }


async def query_once(key: str, date: str) -> dict:
    """Run a single search query."""
    client = _client()
    try:
        return await _run_one(client, key, date)
    finally:
        await client.close()


async def fetch_all_news(date: str) -> dict[str, dict]:
    """Run all 5 daily queries in parallel. Returns dict keyed by query_key."""
    client = _client()
    try:
        tasks = {k: _run_one(client, k, date) for k in DAILY_QUERIES}
        gathered = await asyncio.gather(*tasks.values(), return_exceptions=True)
        results: dict[str, dict] = {}
        for key, outcome in zip(tasks.keys(), gathered):
            if isinstance(outcome, Exception):
                level = logging.ERROR
                if isinstance(outcome, (AuthenticationError, RateLimitError)):
                    level = logging.CRITICAL
                log.log(level, "openai_search %s failed: %s", key, outcome)
                results[key] = {
                    "category": DAILY_QUERIES[key]["category"],
                    "content": f"[query failed: {outcome}]",
                    "citations": [],
                    "headline": "(unavailable)",
                    "relevance": None,
                    "tokens_used": 0,
                    "error": str(outcome),
                }
            else:
                results[key] = outcome
    finally:
        await client.close()

    total_tokens = sum(r.get("tokens_used", 0) for r in results.values())
    # gpt-4o-search-preview pricing: ~$0.0025/1K input + $0.01/1K output + search fee
    log.info("openai_search: fetched %d queries (%d total tokens)",
             len(results), total_tokens)
    return results


async def fetch_interest_rates(date: str) -> dict:
    """Fetch current policy rates. Returns decimal rates plus raw text."""
    client = _client()
    try:
        resp = await client.chat.completions.create(
            model=MODEL,
            web_search_options={},
            messages=[
                {"role": "system", "content": RATES_QUERY["system"]},
                {"role": "user", "content": RATES_QUERY["user"].format(date=date)},
            ],
        )
    finally:
        await client.close()

    content = resp.choices[0].message.content or ""
    out: dict = {"raw": content}

    def _find_pct(label: str) -> float | None:
        m = re.search(rf"{label}\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)\s*%", content, re.IGNORECASE)
        return float(m.group(1)) / 100.0 if m else None

    rbi = _find_pct("RBI_REPO")
    if rbi is not None:
        out["RBI_REPO"] = rbi

    fed_upper = _find_pct("FED_FUNDS_UPPER")
    fed_lower = _find_pct("FED_FUNDS_LOWER")
    if fed_upper is not None and fed_lower is not None:
        out["FED_FUNDS"] = (fed_upper + fed_lower) / 2.0
    else:
        single = _find_pct("FED_FUNDS")
        if single is not None:
            out["FED_FUNDS"] = single

    ecb = _find_pct("ECB_DEPOSIT")
    if ecb is not None:
        out["ECB_DEPOSIT"] = ecb

    return out
