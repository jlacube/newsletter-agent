"""Unit tests for the structured logging configuration.

Spec refs: FR-042, FR-043, FR-044, FR-045, Section 10.5.
"""

import json
import logging
import os

import pytest

import newsletter_agent.logging_config as lc
from newsletter_agent.logging_config import setup_logging


@pytest.fixture(autouse=True)
def _reset_logging():
    """Reset logging state before each test."""
    lc._configured = False
    logger = logging.getLogger("newsletter_agent")
    logger.handlers.clear()
    logger.setLevel(logging.NOTSET)
    yield


class TestSetupLogging:

    def test_configures_newsletter_agent_logger(self):
        setup_logging()
        logger = logging.getLogger("newsletter_agent")
        assert logger.handlers, "Expected at least one handler"

    def test_default_level_is_info(self):
        env = os.environ.copy()
        env.pop("LOG_LEVEL", None)
        with pytest.MonkeyPatch.context() as mp:
            mp.delenv("LOG_LEVEL", raising=False)
            setup_logging()
        logger = logging.getLogger("newsletter_agent")
        assert logger.level == logging.INFO

    def test_log_level_from_env(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        setup_logging()
        logger = logging.getLogger("newsletter_agent")
        assert logger.level == logging.DEBUG

    def test_warning_level_from_env(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "WARNING")
        setup_logging()
        logger = logging.getLogger("newsletter_agent")
        assert logger.level == logging.WARNING

    def test_idempotent_no_duplicate_handlers(self):
        setup_logging()
        count = len(logging.getLogger("newsletter_agent").handlers)
        setup_logging()
        assert len(logging.getLogger("newsletter_agent").handlers) == count

    def test_log_format_includes_required_fields(self):
        setup_logging()
        logger = logging.getLogger("newsletter_agent")
        handler = logger.handlers[0]
        record = logging.LogRecord(
            name="newsletter_agent.test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=None,
            exc_info=None,
        )
        formatted = handler.formatter.format(record)
        assert "INFO" in formatted
        assert "newsletter_agent.test" in formatted
        assert "Test message" in formatted

    def test_third_party_loggers_suppressed(self):
        setup_logging()
        for name in ("googleapiclient", "google.auth", "httplib2", "urllib3"):
            assert logging.getLogger(name).level == logging.WARNING

    def test_stdout_handler_filters_errors(self):
        """stdout handler should NOT emit ERROR-level records."""
        setup_logging()
        logger = logging.getLogger("newsletter_agent")
        stdout_handler = logger.handlers[0]
        error_record = logging.LogRecord(
            name="newsletter_agent.test",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg="err",
            args=None,
            exc_info=None,
        )
        assert stdout_handler.filter(error_record) == 0

    def test_stderr_handler_emits_errors(self):
        """stderr handler should emit ERROR-level records."""
        setup_logging()
        logger = logging.getLogger("newsletter_agent")
        stderr_handler = logger.handlers[1]
        error_record = logging.LogRecord(
            name="newsletter_agent.test",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg="err",
            args=None,
            exc_info=None,
        )
        assert stderr_handler.filter(error_record) != 0


class TestJsonLogging:
    """Tests for JSON-structured logging (Cloud Run mode)."""

    def test_json_mode_via_env(self, monkeypatch):
        monkeypatch.setenv("LOG_FORMAT_JSON", "true")
        setup_logging()
        logger = logging.getLogger("newsletter_agent")
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0].formatter, lc._CloudJsonFormatter)

    def test_json_mode_auto_detect_cloud_run(self, monkeypatch):
        monkeypatch.setenv("K_SERVICE", "newsletter-agent")
        setup_logging()
        logger = logging.getLogger("newsletter_agent")
        assert isinstance(logger.handlers[0].formatter, lc._CloudJsonFormatter)

    def test_json_output_structure(self, monkeypatch):
        monkeypatch.setenv("LOG_FORMAT_JSON", "true")
        setup_logging()
        logger = logging.getLogger("newsletter_agent")
        formatter = logger.handlers[0].formatter
        record = logging.LogRecord(
            name="newsletter_agent.test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=None,
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["severity"] == "INFO"
        assert parsed["message"] == "Test message"
        assert parsed["logger"] == "newsletter_agent.test"
        assert "timestamp" in parsed

    def test_json_error_includes_severity(self, monkeypatch):
        monkeypatch.setenv("LOG_FORMAT_JSON", "true")
        setup_logging()
        logger = logging.getLogger("newsletter_agent")
        formatter = logger.handlers[0].formatter
        record = logging.LogRecord(
            name="newsletter_agent.test",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg="Something failed",
            args=None,
            exc_info=None,
        )
        parsed = json.loads(formatter.format(record))
        assert parsed["severity"] == "ERROR"

    def test_json_with_exception(self, monkeypatch):
        monkeypatch.setenv("LOG_FORMAT_JSON", "true")
        setup_logging()
        logger = logging.getLogger("newsletter_agent")
        formatter = logger.handlers[0].formatter
        try:
            raise ValueError("test error")
        except ValueError:
            import sys
            exc_info = sys.exc_info()
        record = logging.LogRecord(
            name="newsletter_agent.test",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg="Error occurred",
            args=None,
            exc_info=exc_info,
        )
        parsed = json.loads(formatter.format(record))
        assert "exception" in parsed
        assert "ValueError" in parsed["exception"]
