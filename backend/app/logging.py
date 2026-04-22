"""Structured JSON logging with secret redaction.

Log output is always JSON (stdout). A processor walks every event dict and
masks values whose keys look like secrets before they reach the renderer.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Mapping
from typing import Any

import structlog
from structlog.types import EventDict, Processor

from app.config import get_settings

SENSITIVE_KEY_FRAGMENTS = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "auth",
    "cookie",
    "session",
    "private",
)
REDACTED = "***REDACTED***"


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(fragment in lowered for fragment in SENSITIVE_KEY_FRAGMENTS)


def _scrub(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: (REDACTED if _is_sensitive_key(k) else _scrub(v)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        scrubbed = [_scrub(item) for item in value]
        return type(value)(scrubbed)
    return value


def redact_secrets(_logger: Any, _method: str, event_dict: EventDict) -> EventDict:
    return {k: (REDACTED if _is_sensitive_key(k) else _scrub(v)) for k, v in event_dict.items()}


def configure_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.log_level)

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redact_secrets,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[*shared_processors, structlog.processors.JSONRenderer()],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    for noisy in ("uvicorn.access",):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
