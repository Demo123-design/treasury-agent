"""HTML email template builder for the daily briefing.

Uses inline styles throughout - most email clients (Outlook especially)
strip or ignore <style> blocks.
"""
from __future__ import annotations

import html
from typing import Any


def _esc(text: Any) -> str:
    if text is None:
        return ""
    return html.escape(str(text))


def _esc_multiline(text: Any) -> str:
    """Escape and preserve newlines as <br> tags for HTML email rendering."""
    if text is None:
        return ""
    return html.escape(str(text)).replace("\n", "<br>")


def _fmt_rate(value: Any, digits: int = 4) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_bps(value: Any) -> str:
    try:
        return f"{float(value):+.1f}bps"
    except (TypeError, ValueError):
        return "n/a"


def _snapshot_table(forex: dict) -> str:
    curves = forex.get("forward_curves") or {}
    spots = forex.get("spot_rates") or {}
    hedging = forex.get("hedging_assessment") or {}

    rows = []
    for pair in ("USDINR", "EURINR"):
        spot_payload = spots.get(pair) or {}
        spot = spot_payload.get("rate")
        curve = curves.get(pair) or []
        tenor_map = {p.get("tenor"): p for p in curve}
        pair_label = "USD/INR" if pair == "USDINR" else "EUR/INR"
        verdict = (hedging.get(pair) or {}).get("verdict", "-")

        cells = [
            f'<td style="padding:8px 10px;border:1px solid #dce1e6;font-weight:600;">{pair_label}</td>',
            f'<td style="padding:8px 10px;border:1px solid #dce1e6;">{_fmt_rate(spot, 4)}</td>',
        ]
        for tenor in ("1M", "3M", "6M", "12M"):
            row = tenor_map.get(tenor) or {}
            fwd = row.get("forward_rate")
            prem = row.get("forward_premium_bps")
            cells.append(
                f'<td style="padding:8px 10px;border:1px solid #dce1e6;">'
                f'{_fmt_rate(fwd, 4)}<br><span style="color:#6b7680;font-size:11px;">{_fmt_bps(prem)}</span>'
                f'</td>'
            )
        verdict_color = {"CHEAP": "#1f8a4b", "FAIR": "#6b7680", "EXPENSIVE": "#c0392b"}.get(verdict, "#6b7680")
        cells.append(
            f'<td style="padding:8px 10px;border:1px solid #dce1e6;color:{verdict_color};font-weight:600;">{verdict}</td>'
        )
        rows.append("<tr>" + "".join(cells) + "</tr>")

    header = (
        '<tr style="background:#f4f6f8;">'
        '<th style="padding:8px 10px;border:1px solid #dce1e6;text-align:left;">Pair</th>'
        '<th style="padding:8px 10px;border:1px solid #dce1e6;text-align:left;">Spot</th>'
        '<th style="padding:8px 10px;border:1px solid #dce1e6;text-align:left;">1M Fwd</th>'
        '<th style="padding:8px 10px;border:1px solid #dce1e6;text-align:left;">3M Fwd</th>'
        '<th style="padding:8px 10px;border:1px solid #dce1e6;text-align:left;">6M Fwd</th>'
        '<th style="padding:8px 10px;border:1px solid #dce1e6;text-align:left;">12M Fwd</th>'
        '<th style="padding:8px 10px;border:1px solid #dce1e6;text-align:left;">6M Assessment</th>'
        '</tr>'
    )
    return (
        '<table style="border-collapse:collapse;font-size:13px;width:100%;font-family:Arial,sans-serif;">'
        + header
        + "".join(rows)
        + "</table>"
    )


def _interest_rates_footer(forex: dict) -> str:
    rates = forex.get("interest_rates") or {}
    def pct(key: str) -> str:
        v = rates.get(key)
        return f"{v * 100:.2f}%" if isinstance(v, (int, float)) else "n/a"
    return (
        f'<p style="font-size:11px;color:#6b7680;margin:6px 0 0 0;">'
        f'Forward rates computed via Interest Rate Parity. '
        f'RBI Repo: {pct("RBI_REPO")} | Fed Funds: {pct("FED_FUNDS")} | ECB Deposit: {pct("ECB_DEPOSIT")}'
        f'</p>'
    )


def _alert_banner(alerts: list[dict]) -> str:
    if not alerts:
        return ""
    items = "".join(
        f'<li style="margin:3px 0;">{_esc(a.get("message", ""))}</li>' for a in alerts
    )
    return (
        '<div style="background:#c0392b;color:white;padding:14px 22px;font-family:Arial,sans-serif;">'
        '<strong style="font-size:14px;">ALERTS TRIGGERED</strong>'
        f'<ul style="margin:6px 0 0 20px;padding:0;font-size:13px;">{items}</ul>'
        '</div>'
    )


def _section(title: str, body_html: str) -> str:
    return (
        f'<h3 style="color:#1a3a5c;font-family:Arial,sans-serif;font-size:15px;'
        f'margin:24px 0 8px 0;border-bottom:2px solid #1a3a5c;padding-bottom:4px;">{_esc(title)}</h3>'
        f'<div style="font-family:Arial,sans-serif;font-size:13px;color:#2c3e50;line-height:1.6;">{body_html}</div>'
    )


def _bullets(items: list[str]) -> str:
    if not items:
        return '<p style="margin:0;color:#6b7680;">(none)</p>'
    li = "".join(f'<li style="margin:4px 0;">{_esc(item)}</li>' for item in items)
    return f'<ul style="margin:0;padding-left:22px;">{li}</ul>'


def _numbered(items: list[str]) -> str:
    if not items:
        return '<p style="margin:0;color:#6b7680;">(none)</p>'
    li = "".join(f'<li style="margin:4px 0;">{_esc(item)}</li>' for item in items)
    return f'<ol style="margin:0;padding-left:22px;">{li}</ol>'


def build_html_email(briefing: dict, forex: dict, news: dict, date: str) -> str:
    alerts = forex.get("alerts") or []
    overnight = briefing.get("overnight_highlights") or []
    if isinstance(overnight, str):
        overnight = [overnight]
    actions = briefing.get("action_items") or []
    if isinstance(actions, str):
        actions = [actions]

    parts: list[str] = []
    parts.append(
        '<div style="background:#1a3a5c;color:white;padding:22px;font-family:Arial,sans-serif;">'
        '<h1 style="margin:0;font-size:20px;">PI Industries - Treasury Intelligence Briefing</h1>'
        f'<p style="margin:6px 0 0 0;font-size:12px;opacity:0.85;">{_esc(date)} | Generated at 7:30 AM IST</p>'
        '</div>'
    )
    parts.append(_alert_banner(alerts))
    parts.append('<div style="padding:22px;background:white;">')

    parts.append(_section("Overnight Highlights", _bullets(list(overnight))))
    parts.append(_section("Market Snapshot", _snapshot_table(forex) + _interest_rates_footer(forex)))
    parts.append(_section("RBI & Policy Update",
                          f'<p style="margin:0;white-space:pre-wrap;">{_esc_multiline(briefing.get("rbi_update") or "")}</p>'))
    parts.append(_section("Forward Premium Analysis",
                          f'<p style="margin:0;white-space:pre-wrap;">{_esc_multiline(briefing.get("forward_premium_analysis") or "")}</p>'))
    parts.append(_section("Macro Watch",
                          f'<p style="margin:0;white-space:pre-wrap;">{_esc_multiline(briefing.get("macro_watch") or "")}</p>'))
    parts.append(_section("Action Items", _numbered(list(actions))))

    parts.append('</div>')

    parts.append(
        '<div style="padding:16px 22px;background:#f4f6f8;color:#6b7680;'
        'font-size:11px;font-family:Arial,sans-serif;">'
        'Sources: Frankfurter.dev (spot rates, ECB-sourced) | OpenAI web search (news) | '
        'Computed via Interest Rate Parity (forwards).<br>'
        'This briefing is for informational purposes only and does not constitute financial advice.'
        '</div>'
    )

    body = "".join(parts)
    subject_rate = ""
    usd_rate = ((forex.get("spot_rates") or {}).get("USDINR") or {}).get("rate")
    if usd_rate is not None:
        subject_rate = f"{usd_rate:.4f}"
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f'<title>PI Treasury Briefing {_esc(date)} USD/INR {subject_rate}</title></head>'
        '<body style="margin:0;padding:0;background:#eef1f4;">'
        '<div style="max-width:760px;margin:0 auto;background:white;">'
        + body +
        '</div></body></html>'
    )


def build_text_email(briefing: dict, forex: dict, date: str) -> str:
    """Plain-text version for email fallback clients."""
    lines: list[str] = []
    lines.append(f"PI INDUSTRIES - TREASURY INTELLIGENCE BRIEFING")
    lines.append(f"{date} | 7:30 AM IST")
    lines.append("=" * 60)

    alerts = forex.get("alerts") or []
    if alerts:
        lines.append("")
        lines.append("** ALERTS TRIGGERED **")
        for a in alerts:
            lines.append(f"  - {a.get('message', '')}")

    lines.append("")
    lines.append("OVERNIGHT HIGHLIGHTS")
    for h in briefing.get("overnight_highlights") or []:
        lines.append(f"  - {h}")

    lines.append("")
    lines.append("MARKET SNAPSHOT")
    spots = forex.get("spot_rates") or {}
    curves = forex.get("forward_curves") or {}
    hedging = forex.get("hedging_assessment") or {}
    for pair in ("USDINR", "EURINR"):
        spot = (spots.get(pair) or {}).get("rate")
        curve = curves.get(pair) or []
        pair_label = "USD/INR" if pair == "USDINR" else "EUR/INR"
        spot_s = f"{spot:.4f}" if isinstance(spot, (int, float)) else "n/a"
        fwds = " | ".join(
            f"{p.get('tenor')}: {p.get('forward_rate', 0):.4f} ({p.get('forward_premium_bps', 0):+.1f}bps)"
            for p in curve
        )
        verdict = (hedging.get(pair) or {}).get("verdict", "-")
        lines.append(f"  {pair_label}  Spot: {spot_s}  |  6M: {verdict}")
        lines.append(f"    {fwds}")

    rates = forex.get("interest_rates") or {}
    def _p(k: str) -> str:
        v = rates.get(k)
        return f"{v*100:.2f}%" if isinstance(v, (int, float)) else "n/a"
    lines.append(f"  (RBI: {_p('RBI_REPO')}, Fed: {_p('FED_FUNDS')}, ECB: {_p('ECB_DEPOSIT')})")

    lines.append("")
    lines.append("RBI & POLICY UPDATE")
    lines.append(f"  {briefing.get('rbi_update', '')}")

    lines.append("")
    lines.append("FORWARD PREMIUM ANALYSIS")
    lines.append(f"  {briefing.get('forward_premium_analysis', '')}")

    lines.append("")
    lines.append("MACRO WATCH")
    lines.append(f"  {briefing.get('macro_watch', '')}")

    lines.append("")
    lines.append("ACTION ITEMS")
    for i, a in enumerate(briefing.get("action_items") or [], 1):
        lines.append(f"  {i}. {a}")

    lines.append("")
    lines.append("-" * 60)
    lines.append("Sources: Frankfurter.dev | OpenAI web search | IRP forward calc")

    return "\n".join(lines)
