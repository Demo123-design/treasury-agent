"""OpenAI GPT-4o client - generates the structured morning briefing.

Takes the assembled context dict (forex + news) and returns a dict with
the briefing sections per PRD section 6.4.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from config import CONFIG

MODEL = "gpt-4o"
TEMPERATURE = 0.2

log = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are the PI Industries Treasury Intelligence Agent. PI Industries is a leading \
Indian agrochemical company with significant USD and EUR export receivables.

Generate a structured daily treasury briefing for the treasury team. Be concise, \
factual, and actionable. Distinguish clearly between confirmed facts and analyst \
forecasts. Always cite sources when you mention specific data points. Never recommend \
speculative hedging positions - only recommend hedging of genuine underlying export exposures.

Output format: return a JSON object with these EXACT keys:
- overnight_highlights: array of exactly 3 short strings (top 3 developments, one sentence each)
- rbi_update: string formatted in TWO sections separated by a blank line:
    "TODAY: <today's RBI circulars/actions, or 'No new circulars today.'>

    RECENT: <3 most recent RBI circulars from the past 30 days, one per line, each prefixed with a hyphen and including circular/ref number, date, one-line summary, and relevance tag>"
  Preserve the line breaks using \\n in the JSON string. Do not merge into one paragraph.
- forward_premium_analysis: string (3-4 sentences on the USD/INR and EUR/INR forward curves, whether hedging is cheap/fair/expensive vs 30d average, and recommended tenor)
- macro_watch: string (India macro data, crude oil, global risks - 4-6 sentences)
- action_items: array of strings (specific, prioritized actions for treasury team; 2-5 items)
"""

EXPECTED_KEYS = {
    "overnight_highlights",
    "rbi_update",
    "forward_premium_analysis",
    "macro_watch",
    "action_items",
}


def _client() -> AsyncOpenAI:
    if not CONFIG.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY not set in agent/.env")
    return AsyncOpenAI(api_key=CONFIG.openai_api_key, max_retries=2)


def _compact_news(news: dict[str, Any]) -> dict[str, Any]:
    """Strip news payload to what GPT-4o needs - content, headline, relevance."""
    out: dict[str, Any] = {}
    for key, payload in news.items():
        if not isinstance(payload, dict):
            continue
        out[key] = {
            "category": payload.get("category"),
            "headline": payload.get("headline"),
            "content": payload.get("content"),
            "relevance": payload.get("relevance"),
            "citations": [c.get("url") if isinstance(c, dict) else c for c in (payload.get("citations") or [])][:3],
        }
    return out


def _build_user_prompt(context: dict) -> str:
    compact = {
        "date": context.get("date"),
        "spot_rates": context.get("spot_rates"),
        "forward_curves": context.get("forward_curves"),
        "30d_avg_spot": context.get("30d_avg_spot"),
        "hedging_assessment": context.get("hedging_assessment"),
        "interest_rates": context.get("interest_rates"),
        "alerts": context.get("alerts"),
        "news": _compact_news(context.get("news") or {}),
    }
    payload = json.dumps(compact, indent=2, default=str)
    return (
        "Here is today's market and news context. Produce the structured briefing JSON.\n\n"
        f"CONTEXT:\n{payload}"
    )


def _fallback_briefing(context: dict, error: Exception | None = None) -> dict:
    """Minimal briefing built from raw data when GPT-4o fails."""
    spot = context.get("spot_rates") or {}
    usd = (spot.get("USDINR") or {}).get("rate", "n/a")
    eur = (spot.get("EURINR") or {}).get("rate", "n/a")
    alerts = context.get("alerts") or []
    reason = f" (LLM unavailable: {error})" if error else ""
    return {
        "overnight_highlights": [
            f"USD/INR spot {usd}, EUR/INR spot {eur}.",
            f"{len(alerts)} alert(s) active." if alerts else "No threshold alerts triggered.",
            "LLM briefing synthesis unavailable - raw data only." if error else "Briefing generated from raw data only.",
        ],
        "rbi_update": "RBI update unavailable" + reason,
        "forward_premium_analysis": "Forward curve analysis unavailable" + reason + ". See market snapshot table for raw forwards.",
        "macro_watch": "Macro commentary unavailable" + reason,
        "action_items": ["Review market snapshot table manually", "Check logs for LLM error"],
        "_fallback": True,
    }


async def generate_morning_briefing(context: dict) -> dict:
    """Synthesize briefing via GPT-4o. Returns dict with EXPECTED_KEYS."""
    try:
        client = _client()
    except Exception as exc:
        log.error("openai_client: client init failed: %s", exc)
        return _fallback_briefing(context, exc)

    try:
        resp = await client.chat.completions.create(
            model=MODEL,
            temperature=TEMPERATURE,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_prompt(context)},
            ],
        )
    except Exception as exc:
        log.error("openai_client: GPT-4o call failed: %s", exc)
        await client.close()
        return _fallback_briefing(context, exc)
    finally:
        try:
            await client.close()
        except Exception:
            pass

    raw = resp.choices[0].message.content or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.error("openai_client: JSON parse failed: %s - raw=%s", exc, raw[:500])
        return _fallback_briefing(context, exc)

    missing = EXPECTED_KEYS - set(parsed.keys())
    if missing:
        log.warning("openai_client: missing keys in briefing: %s", missing)
        for k in missing:
            parsed[k] = [] if k in ("overnight_highlights", "action_items") else ""

    usage = resp.usage
    log.info("openai_client: briefing generated - tokens in=%s out=%s",
             getattr(usage, "prompt_tokens", "?"),
             getattr(usage, "completion_tokens", "?"))
    return parsed
