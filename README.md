# PI Industries - Treasury Intelligence Agent

Automated daily treasury briefing for PI Industries. Fetches spot rates, computes
IRP forward curves, pulls live news and policy updates, and emails a structured
morning briefing to the treasury team at 7:30 AM IST.

No ERP/TMS integration. No Bloomberg. No paid data feeds.

## Layout

```
pi-treasury-agent/
  agent/          Python backend (this PRD)
  web/            React + Vite scaffold (future dashboard)
```

## Stack

| Layer          | Tool                              |
|----------------|-----------------------------------|
| Runtime        | Python 3.11+                      |
| Spot rates     | Frankfurter.dev (free, ECB)       |
| Forward rates  | Computed via Interest Rate Parity |
| News & policy  | OpenAI `gpt-4o-search-preview`    |
| Briefing       | OpenAI `gpt-4o` (JSON mode)       |
| Email          | SendGrid                          |
| Scheduling     | APScheduler (`Asia/Kolkata`)      |
| Storage        | SQLite                            |

## Setup

```bash
cd agent
python -m pip install -r requirements.txt
cp .env.example .env
# Edit .env and fill:
#   OPENAI_API_KEY     (required)
#   SENDGRID_API_KEY   (required for live send)
#   FROM_EMAIL, TO_EMAILS
```

## Run modes

```bash
# Dry run - full pipeline, saves HTML preview, no email sent
python main.py --dry-run

# Dry run for a specific date
python main.py --dry-run --date 2026-04-10

# Live one-shot - runs pipeline now and sends email
python main.py --now

# Scheduler - daemonizes, runs 6:00 AM data fetch and 7:30 AM briefing daily
python main.py
```

## Where things land

- `agent/data/treasury.db` - SQLite with spot rates, forward curves, news, briefings, alerts
- `agent/logs/agent.log` - rotating application log
- `agent/logs/briefing_YYYY-MM-DD.html` - HTML preview for each run

## Cost per run

Roughly `$0.03 - $0.05` (OpenAI web search + GPT-4o briefing). Frankfurter and
SendGrid (under 100/day) are free.

## Tuning alerts

In `.env`:

```
USDINR_UPPER=94.00
USDINR_LOWER=90.00
FORWARD_PREMIUM_ALERT_BPS=10
CRUDE_UPPER=90.0
```

An alert fires if spot breaches upper/lower, the 6M premium moves more than N
basis points vs yesterday, or crude crosses the upper threshold.
