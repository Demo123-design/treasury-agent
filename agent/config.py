"""Central configuration — loads .env and exposes typed constants.

All paths are resolved relative to the agent/ directory so commands work
regardless of the shell's current working directory.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

AGENT_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = AGENT_ROOT.parent

load_dotenv(AGENT_ROOT / ".env")


def _get(key: str, default: str | None = None) -> str | None:
    value = os.getenv(key, default)
    if value is None or value == "":
        return None
    return value


def _get_float(key: str, default: float) -> float:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    return float(raw)


def _get_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    return int(raw)


def _get_list(key: str, default: list[str] | None = None) -> list[str]:
    raw = os.getenv(key, "")
    items = [item.strip() for item in raw.split(",") if item.strip()]
    return items or (default or [])


@dataclass(frozen=True)
class Config:
    perplexity_api_key: str | None
    openai_api_key: str | None
    sendgrid_api_key: str | None

    from_email: str
    from_name: str
    to_emails: list[str]

    briefing_hour_ist: int
    briefing_minute_ist: int
    data_fetch_hour_ist: int
    data_fetch_minute_ist: int

    usdinr_upper: float
    usdinr_lower: float
    forward_premium_alert_bps: float
    crude_upper: float

    log_level: str
    db_path: Path
    logs_dir: Path

    default_rbi_repo: float = 0.0650
    default_fed_funds: float = 0.04375
    default_ecb_deposit: float = 0.0250

    def require_live_keys(self) -> None:
        """Raise if any key needed for a live run is missing."""
        missing = [
            name
            for name, value in {
                "PERPLEXITY_API_KEY": self.perplexity_api_key,
                "OPENAI_API_KEY": self.openai_api_key,
                "SENDGRID_API_KEY": self.sendgrid_api_key,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError(
                f"Missing required API keys for live run: {', '.join(missing)}. "
                "Fill them in agent/.env or use --dry-run."
            )


def load_config() -> Config:
    db_rel = _get("DB_PATH", "data/treasury.db") or "data/treasury.db"
    db_path = (AGENT_ROOT / db_rel).resolve()
    logs_dir = (AGENT_ROOT / "logs").resolve()

    return Config(
        perplexity_api_key=_get("PERPLEXITY_API_KEY"),
        openai_api_key=_get("OPENAI_API_KEY"),
        sendgrid_api_key=_get("SENDGRID_API_KEY"),
        from_email=_get("FROM_EMAIL", "treasury-agent@example.com") or "treasury-agent@example.com",
        from_name=_get("FROM_NAME", "PI Treasury Intelligence Agent") or "PI Treasury Intelligence Agent",
        to_emails=_get_list("TO_EMAILS"),
        briefing_hour_ist=_get_int("BRIEFING_HOUR_IST", 7),
        briefing_minute_ist=_get_int("BRIEFING_MINUTE_IST", 30),
        data_fetch_hour_ist=_get_int("DATA_FETCH_HOUR_IST", 6),
        data_fetch_minute_ist=_get_int("DATA_FETCH_MINUTE_IST", 0),
        usdinr_upper=_get_float("USDINR_UPPER", 86.00),
        usdinr_lower=_get_float("USDINR_LOWER", 83.00),
        forward_premium_alert_bps=_get_float("FORWARD_PREMIUM_ALERT_BPS", 10.0),
        crude_upper=_get_float("CRUDE_UPPER", 90.0),
        log_level=(_get("LOG_LEVEL", "INFO") or "INFO").upper(),
        db_path=db_path,
        logs_dir=logs_dir,
    )


def configure_logging(cfg: Config) -> None:
    cfg.logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = cfg.logs_dir / "agent.log"

    from logging.handlers import RotatingFileHandler

    handler_file = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    handler_stream = logging.StreamHandler()
    try:
        handler_stream.stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    handler_file.setFormatter(fmt)
    handler_stream.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(cfg.log_level)
    root.handlers.clear()
    root.addHandler(handler_file)
    root.addHandler(handler_stream)


CONFIG = load_config()
