"""
Structured logging configuration for the Newsletter Agent.

Configures log format, handlers, and levels for the newsletter_agent
namespace. Cloud Run compatible (stdout/stderr for Cloud Logging).

When LOG_FORMAT_JSON=true (recommended on Cloud Run), emits JSON-structured
log entries that Cloud Logging parses natively, giving severity filtering,
trace correlation, and full-text search in the Logs Explorer.

Spec refs: FR-042, FR-043, FR-044, FR-045, Section 10.5.
"""

import json
import logging
import os
import sys

_TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"

_configured = False

# Cloud Logging severity mapping
_SEVERITY_MAP = {
    "DEBUG": "DEBUG",
    "INFO": "INFO",
    "WARNING": "WARNING",
    "ERROR": "ERROR",
    "CRITICAL": "CRITICAL",
}


class _CloudJsonFormatter(logging.Formatter):
    """Emit one JSON object per log line for Cloud Logging structured ingestion."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "severity": _SEVERITY_MAP.get(record.levelname, record.levelname),
            "message": record.getMessage(),
            "logger": record.name,
            "timestamp": self.formatTime(record, _DATE_FORMAT),
        }
        if record.exc_info and record.exc_info[0] is not None:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def setup_logging() -> None:
    """Configure structured logging for the newsletter_agent namespace.

    Idempotent - safe to call multiple times. Only configures on the first call.

    Environment variables:
      LOG_LEVEL        - DEBUG, INFO (default), WARNING, ERROR, CRITICAL
      LOG_FORMAT_JSON  - "true" to emit JSON (auto-enabled on Cloud Run via K_SERVICE)
    """
    global _configured
    if _configured:
        return

    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    # Auto-detect Cloud Run: K_SERVICE is set by the Cloud Run runtime
    use_json = (
        os.environ.get("LOG_FORMAT_JSON", "").lower() == "true"
        or os.environ.get("K_SERVICE", "") != ""
    )

    logger = logging.getLogger("newsletter_agent")
    logger.setLevel(level)

    if use_json:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_CloudJsonFormatter())
        logger.addHandler(handler)
    else:
        formatter = logging.Formatter(_TEXT_FORMAT, datefmt=_DATE_FORMAT)

        # stdout handler for DEBUG..WARNING
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setLevel(logging.DEBUG)
        stdout_handler.setFormatter(formatter)
        stdout_handler.addFilter(lambda record: record.levelno < logging.ERROR)

        # stderr handler for ERROR and above
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setLevel(logging.ERROR)
        stderr_handler.setFormatter(formatter)

        logger.addHandler(stdout_handler)
        logger.addHandler(stderr_handler)

    # Suppress noisy third-party loggers
    for noisy in (
        "googleapiclient",
        "google.auth",
        "httplib2",
        "urllib3",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True
