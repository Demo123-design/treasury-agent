"""SQLite table DDL and matching dataclasses.

Kept deliberately lean — no ORM. Dataclasses exist so agent code can pass
typed objects around; the db layer converts to/from rows.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS spot_rates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    pair TEXT NOT NULL,
    spot_rate REAL NOT NULL,
    source TEXT DEFAULT 'frankfurter',
    fetched_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_spot_rates_date_pair ON spot_rates(date, pair);

CREATE TABLE IF NOT EXISTS forward_rates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    pair TEXT NOT NULL,
    tenor TEXT NOT NULL,
    forward_rate REAL NOT NULL,
    forward_premium_bps REAL,
    india_rate REAL,
    foreign_rate REAL,
    computed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_forward_rates_date_pair ON forward_rates(date, pair);

CREATE TABLE IF NOT EXISTS interest_rates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rate_type TEXT NOT NULL,
    rate_value REAL NOT NULL,
    effective_date TEXT,
    source TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_interest_rates_type ON interest_rates(rate_type);

CREATE TABLE IF NOT EXISTS news_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    category TEXT NOT NULL,
    headline TEXT,
    summary TEXT,
    relevance TEXT,
    source_url TEXT,
    fetched_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_news_items_date_category ON news_items(date, category);

CREATE TABLE IF NOT EXISTS briefings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    html_content TEXT,
    text_content TEXT,
    sections_json TEXT,
    generated_at TEXT NOT NULL,
    delivered INTEGER DEFAULT 0,
    delivery_error TEXT
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    message TEXT,
    threshold TEXT,
    actual_value TEXT,
    triggered_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_alerts_date ON alerts(date);

CREATE TABLE IF NOT EXISTS compliance_insights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    severity TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    affected_docs TEXT,
    recommended_action TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_compliance_date ON compliance_insights(date);
CREATE INDEX IF NOT EXISTS idx_compliance_severity ON compliance_insights(date, severity);
"""


@dataclass
class SpotRate:
    date: str
    pair: str
    spot_rate: float
    source: str = "frankfurter"
    fetched_at: str = field(default_factory=now_iso)
    id: int | None = None


@dataclass
class ForwardRate:
    date: str
    pair: str
    tenor: str
    forward_rate: float
    forward_premium_bps: float | None
    india_rate: float | None
    foreign_rate: float | None
    computed_at: str = field(default_factory=now_iso)
    id: int | None = None


@dataclass
class InterestRate:
    rate_type: str
    rate_value: float
    effective_date: str | None = None
    source: str | None = None
    updated_at: str = field(default_factory=now_iso)
    id: int | None = None


@dataclass
class NewsItem:
    date: str
    category: str
    headline: str | None
    summary: str | None
    relevance: str | None
    source_url: str | None = None
    fetched_at: str = field(default_factory=now_iso)
    id: int | None = None


@dataclass
class Briefing:
    date: str
    html_content: str | None
    text_content: str | None
    sections_json: str | None = None
    generated_at: str = field(default_factory=now_iso)
    delivered: bool = False
    delivery_error: str | None = None
    id: int | None = None


@dataclass
class Alert:
    date: str
    alert_type: str
    message: str
    threshold: str
    actual_value: str
    triggered_at: str = field(default_factory=now_iso)
    id: int | None = None


@dataclass
class ComplianceInsight:
    date: str
    severity: str
    category: str
    title: str
    description: str | None = None
    affected_docs: str | None = None
    recommended_action: str | None = None
    created_at: str = field(default_factory=now_iso)
    id: int | None = None
