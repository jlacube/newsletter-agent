"""
Structured logging configuration for the Newsletter Agent.

Configures log format, handlers, and levels for the newsletter_agent
namespace. Cloud Run compatible (stdout/stderr for Cloud Logging).

Spec refs: FR-042, FR-043, FR-044, FR-045, Section 10.5.
"""

import logging
import os
import sys

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"

_configured = False


def setup_logging() -> None:
    """Configure structured logging for the newsletter_agent namespace.

    Idempotent - safe to call multiple times. Only configures on the first call.

    Reads LOG_LEVEL from the environment (default: INFO). Logs at INFO and
    below go to stdout; ERROR and above go to stderr. Third-party loggers
    are suppressed to WARNING to reduce noise.
    """
    global _configured
    if _configured:
        return

    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    logger = logging.getLogger("newsletter_agent")
    logger.setLevel(level)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

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
