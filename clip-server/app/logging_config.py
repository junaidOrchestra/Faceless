"""Structured logging with per-request ids and a credential-redaction filter.

Two concerns live here:

* **Request id propagation** — a :class:`contextvars.ContextVar` carries a request
  id so every log line emitted while handling a request is tagged with it.
* **Redaction** — a logging filter scrubs anything that looks like an API key,
  bearer token, or credential from log records, so secrets never reach the logs
  even if a developer accidentally logs a request body.
"""

from __future__ import annotations

import logging
import re
import sys
from contextvars import ContextVar

# Carries the current request id across async boundaries within a request.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

# Patterns that, if found in a log message, get their values masked. These cover
# bearer headers and common credential-bearing JSON keys (api_key, pexels, etc.).
_REDACTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)([^\s'\"]+)"),
    re.compile(r"(?i)(\"?(?:api[_-]?key|secret|token|password|pexels)\"?\s*[:=]\s*\"?)([^\s,'\"}]+)"),
)
_REDACTED = r"\1***REDACTED***"


class RedactionFilter(logging.Filter):
    """Logging filter that masks credentials in the formatted message."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - logging API
        message = record.getMessage()
        for pattern in _REDACTION_PATTERNS:
            message = pattern.sub(_REDACTED, message)
        # Replace args so downstream formatters use the redacted text only.
        record.msg = message
        record.args = ()
        return True


class RequestIdFilter(logging.Filter):
    """Injects the current request id onto every record as ``request_id``."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - logging API
        record.request_id = request_id_var.get()
        return True


def configure_logging(level: str = "INFO") -> None:
    """Configure root logging with a structured single-line format.

    Safe to call multiple times; existing handlers are cleared first so reload
    during development does not duplicate log lines.
    """

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)s [req=%(request_id)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    handler.addFilter(RequestIdFilter())
    handler.addFilter(RedactionFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
