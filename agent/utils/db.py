"""SQLite helpers — init, connection, and CRUD for all agent tables."""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from config import CONFIG
from models.schema import (
    SCHEMA_SQL,
    Alert,
    Briefing,
    ComplianceInsight,
    ForwardRate,
    InterestRate,
    NewsItem,
    SpotRate,
)

log = logging.getLogger(__name__)


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def get_connection(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    path = db_path or CONFIG.db_path
    _ensure_parent(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> Path:
    path = db_path or CONFIG.db_path
    _ensure_parent(path)
    with get_connection(path) as conn:
        conn.executescript(SCHEMA_SQL)
        _migrate(conn)
    log.info("Initialized database at %s", path)
    return path


def _migrate(conn: sqlite3.Connection) -> None:
    """Additive migrations - run once on init. SQLite has no ADD COLUMN IF NOT EXISTS."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(briefings)").fetchall()}
    if "sections_json" not in cols:
        conn.execute("ALTER TABLE briefings ADD COLUMN sections_json TEXT")
        log.info("migrated: briefings.sections_json added")


# ---- inserts ---------------------------------------------------------------

def insert_spot_rate(rate: SpotRate) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO spot_rates(date, pair, spot_rate, source, fetched_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (rate.date, rate.pair, rate.spot_rate, rate.source, rate.fetched_at),
        )
        return int(cur.lastrowid)


def insert_forward_rate(fwd: ForwardRate) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO forward_rates(date, pair, tenor, forward_rate, "
            "forward_premium_bps, india_rate, foreign_rate, computed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                fwd.date, fwd.pair, fwd.tenor, fwd.forward_rate,
                fwd.forward_premium_bps, fwd.india_rate, fwd.foreign_rate,
                fwd.computed_at,
            ),
        )
        return int(cur.lastrowid)


def upsert_interest_rate(ir: InterestRate) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO interest_rates(rate_type, rate_value, effective_date, source, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (ir.rate_type, ir.rate_value, ir.effective_date, ir.source, ir.updated_at),
        )
        return int(cur.lastrowid)


def insert_news_item(item: NewsItem) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO news_items(date, category, headline, summary, relevance, source_url, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                item.date, item.category, item.headline, item.summary,
                item.relevance, item.source_url, item.fetched_at,
            ),
        )
        return int(cur.lastrowid)


def upsert_briefing(br: Briefing) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO briefings(date, html_content, text_content, sections_json, generated_at, delivered, delivery_error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(date) DO UPDATE SET "
            "html_content=excluded.html_content, "
            "text_content=excluded.text_content, "
            "sections_json=excluded.sections_json, "
            "generated_at=excluded.generated_at, "
            "delivered=excluded.delivered, "
            "delivery_error=excluded.delivery_error",
            (
                br.date, br.html_content, br.text_content, br.sections_json,
                br.generated_at, 1 if br.delivered else 0, br.delivery_error,
            ),
        )
        return int(cur.lastrowid)


def insert_alert(alert: Alert) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO alerts(date, alert_type, message, threshold, actual_value, triggered_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                alert.date, alert.alert_type, alert.message, alert.threshold,
                alert.actual_value, alert.triggered_at,
            ),
        )
        return int(cur.lastrowid)


def insert_compliance_insight(ci: ComplianceInsight) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO compliance_insights(date, severity, category, title, "
            "description, affected_docs, recommended_action, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ci.date, ci.severity, ci.category, ci.title,
                ci.description, ci.affected_docs, ci.recommended_action,
                ci.created_at,
            ),
        )
        return int(cur.lastrowid)


# ---- reads -----------------------------------------------------------------

def get_latest_spot(pair: str) -> SpotRate | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM spot_rates WHERE pair = ? ORDER BY date DESC, id DESC LIMIT 1",
            (pair,),
        ).fetchone()
    if row is None:
        return None
    return SpotRate(
        id=row["id"],
        date=row["date"],
        pair=row["pair"],
        spot_rate=row["spot_rate"],
        source=row["source"],
        fetched_at=row["fetched_at"],
    )


def get_latest_interest_rate(rate_type: str) -> InterestRate | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM interest_rates WHERE rate_type = ? ORDER BY updated_at DESC, id DESC LIMIT 1",
            (rate_type,),
        ).fetchone()
    if row is None:
        return None
    return InterestRate(
        id=row["id"],
        rate_type=row["rate_type"],
        rate_value=row["rate_value"],
        effective_date=row["effective_date"],
        source=row["source"],
        updated_at=row["updated_at"],
    )


def get_forward_premium_history(pair: str, tenor: str, days: int = 30) -> list[float]:
    """Return recent forward_premium_bps values for a pair/tenor, newest first."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT forward_premium_bps FROM forward_rates "
            "WHERE pair = ? AND tenor = ? AND forward_premium_bps IS NOT NULL "
            "ORDER BY date DESC, id DESC LIMIT ?",
            (pair, tenor, days),
        ).fetchall()
    return [float(r["forward_premium_bps"]) for r in rows]


def get_briefing(date: str) -> Briefing | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM briefings WHERE date = ?", (date,)).fetchone()
    if row is None:
        return None
    keys = row.keys() if hasattr(row, "keys") else []
    return Briefing(
        id=row["id"],
        date=row["date"],
        html_content=row["html_content"],
        text_content=row["text_content"],
        sections_json=row["sections_json"] if "sections_json" in keys else None,
        generated_at=row["generated_at"],
        delivered=bool(row["delivered"]),
        delivery_error=row["delivery_error"],
    )
