"""
Structured logging setup (JSON in prod, text in dev).

JSON format is CloudWatch Insights / Datadog-friendly. The JsonFormatter
emits one JSON object per log record with:

- Required keys (always present): `ts`, `level`, `logger`, `msg`,
  `module`, `func`, `line`.
- Per-request context (set by `RequestContextMiddleware`): `request_id`
  when the current task is handling an HTTP request.
- Extras: any field passed via `logger.info(..., extra={"key": "value"})`
  appears as a top-level key in the JSON object.
- Exception: when `exc_info` is set, the formatted traceback goes into
  the `exc` key.

Text format (dev) keeps the standard `%(asctime)s [%(levelname)s] %(name)s:
%(message)s` shape for readability.

Usage examples:

    from app.core.logging import get_logger, setup_logging

    setup_logging()  # idempotent — called once at app startup
    log = get_logger(__name__)
    log.info("user signed in", extra={"user_id": "u-123", "event": "auth.login"})
    #   prod: {"ts": "...", "level": "INFO", "logger": "app.auth", "msg": "user signed in",
    #          "module": "auth", "func": "login", "line": 42, "user_id": "u-123",
    #          "event": "auth.login", "request_id": "abc..."}
    #   dev:  2026-06-24 ... [INFO] app.auth: user signed in
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import uuid
from datetime import UTC, datetime
from typing import Any

from app.config import settings

# ---- Context variables (set per-request by RequestContextMiddleware) ----
# Using contextvars so log calls deep in the call stack don't need to
# receive `request_id` as an explicit parameter.
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")


# ---- Formatters ----
class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record. Compatible with CloudWatch
    Insights, Datadog, Loki, and other structured-log backends.

    Reserved LogRecord attributes (set by the logging module itself) are
    excluded from the payload; everything else on `record.__dict__` is
    treated as an "extra" and emitted as a top-level key. This makes
    `logger.info("msg", extra={"user_id": "u-1"})` work as expected.
    """

    _RESERVED = frozenset(
        {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "taskName",
            "message",
            "asctime",
        }
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
        }

        rid = request_id_var.get()
        if rid:
            payload["request_id"] = rid

        for key, val in record.__dict__.items():
            if key in self._RESERVED or key.startswith("_"):
                continue
            payload[key] = val

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


_TEXT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


# ---- Setup ----
def setup_logging() -> None:
    """Configure the root logger. Idempotent — safe to call multiple times."""
    handler = logging.StreamHandler(sys.stdout)
    if settings.is_local:
        handler.setFormatter(logging.Formatter(_TEXT_FORMAT))
    else:
        handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.app_log_level.upper())

    # All `app.*` loggers propagate to the root (default in stdlib, but
    # explicit is better). This makes them visible to pytest's caplog
    # fixture and to the runtime handler we just installed.
    logging.getLogger("app").propagate = True

    # Quiet down noisy libs
    for lib in ("boto3", "botocore", "urllib3", "sqlalchemy.engine"):
        logging.getLogger(lib).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a logger with the given name. Thin wrapper around
    `logging.getLogger` for ergonomics and future-proofing (we may swap
    implementations later)."""
    return logging.getLogger(name)


def new_request_id() -> str:
    """Generate a short (16-hex-char) request ID for traceability."""
    return uuid.uuid4().hex[:16]
