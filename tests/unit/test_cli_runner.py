"""Unit tests for the CLI runner (__main__.py).

Spec refs: FR-CLI-001 through FR-CLI-005, Section 11.1.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Module importability (FR-CLI-001)
# ---------------------------------------------------------------------------


def test_main_module_is_importable():
    """__main__.py module exists and is importable. FR-CLI-001."""
    from newsletter_agent.__main__ import main
    assert callable(main)


def test_run_pipeline_is_importable():
    """run_pipeline async function exists and is importable."""
    from newsletter_agent.__main__ import run_pipeline
    assert callable(run_pipeline)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_success_state(topic_count=3, dry_run=False, output_file=None):
    """Build a mock session state dict for successful pipeline completion."""
    state = {
        "newsletter_metadata": {"topic_count": topic_count},
        "delivery_status": {
            "status": "dry_run" if dry_run else "sent",
        },
    }
    if dry_run and output_file:
        state["delivery_status"]["output_file"] = output_file
    return state


# ---------------------------------------------------------------------------
# main() success path (FR-CLI-002, FR-CLI-004, FR-CLI-005)
# ---------------------------------------------------------------------------


class TestMainSuccess:

    @patch("newsletter_agent.__main__.asyncio.run")
    @patch("newsletter_agent.__main__.setup_logging")
    def test_exit_code_zero_on_success(self, mock_logging, mock_asyncio_run, capsys):
        """main() returns 0 on successful pipeline completion. FR-CLI-004."""
        mock_asyncio_run.return_value = _make_success_state()

        from newsletter_agent.__main__ import main
        exit_code = main()

        assert exit_code == 0
        mock_logging.assert_called_once()

    @patch("newsletter_agent.__main__.asyncio.run")
    @patch("newsletter_agent.__main__.setup_logging")
    def test_json_summary_on_success(self, mock_logging, mock_asyncio_run, capsys):
        """main() prints JSON summary with required fields. FR-CLI-005."""
        mock_asyncio_run.return_value = _make_success_state(topic_count=5)

        from newsletter_agent.__main__ import main
        main()

        captured = capsys.readouterr()
        summary = json.loads(captured.out.strip())
        assert summary["status"] == "success"
        assert "newsletter_date" in summary
        assert summary["topics_processed"] == 5
        assert "email_sent" in summary

    @patch("newsletter_agent.__main__.asyncio.run")
    @patch("newsletter_agent.__main__.setup_logging")
    def test_email_sent_true_when_sent(self, mock_logging, mock_asyncio_run, capsys):
        """email_sent is True when delivery status is 'sent'. FR-CLI-005."""
        mock_asyncio_run.return_value = _make_success_state()

        from newsletter_agent.__main__ import main
        main()

        captured = capsys.readouterr()
        summary = json.loads(captured.out.strip())
        assert summary["email_sent"] is True

    @patch("newsletter_agent.__main__.asyncio.run")
    @patch("newsletter_agent.__main__.setup_logging")
    def test_dry_run_includes_output_file(self, mock_logging, mock_asyncio_run, capsys):
        """Dry run includes output_file in summary. FR-CLI-005."""
        mock_asyncio_run.return_value = _make_success_state(
            dry_run=True, output_file="output/2025-01-01-newsletter.html"
        )

        from newsletter_agent.__main__ import main
        main()

        captured = capsys.readouterr()
        summary = json.loads(captured.out.strip())
        assert summary["status"] == "success"
        assert summary["output_file"] == "output/2025-01-01-newsletter.html"
        assert summary["email_sent"] is False

    @patch("newsletter_agent.__main__.asyncio.run")
    @patch("newsletter_agent.__main__.setup_logging")
    def test_newsletter_date_is_iso_format(self, mock_logging, mock_asyncio_run, capsys):
        """newsletter_date is ISO YYYY-MM-DD format. FR-CLI-005."""
        mock_asyncio_run.return_value = _make_success_state()

        from newsletter_agent.__main__ import main
        main()

        captured = capsys.readouterr()
        summary = json.loads(captured.out.strip())
        assert len(summary["newsletter_date"]) == 10  # YYYY-MM-DD


# ---------------------------------------------------------------------------
# main() failure path (FR-CLI-004, FR-CLI-005)
# ---------------------------------------------------------------------------


class TestMainFailure:

    @patch("newsletter_agent.__main__.asyncio.run")
    @patch("newsletter_agent.__main__.setup_logging")
    def test_exit_code_one_on_exception(self, mock_logging, mock_asyncio_run, capsys):
        """main() returns 1 on pipeline exception. FR-CLI-004."""
        mock_asyncio_run.side_effect = RuntimeError("LLM quota exceeded")

        from newsletter_agent.__main__ import main
        exit_code = main()

        assert exit_code == 1

    @patch("newsletter_agent.__main__.asyncio.run")
    @patch("newsletter_agent.__main__.setup_logging")
    def test_error_summary_on_exception(self, mock_logging, mock_asyncio_run, capsys):
        """main() prints error JSON summary on failure. FR-CLI-005."""
        mock_asyncio_run.side_effect = RuntimeError("LLM quota exceeded")

        from newsletter_agent.__main__ import main
        main()

        captured = capsys.readouterr()
        summary = json.loads(captured.out.strip())
        assert summary["status"] == "error"
        assert "message" in summary
        assert "RuntimeError" in summary["message"]
        assert "LLM quota exceeded" in summary["message"]

    @patch("newsletter_agent.__main__.asyncio.run")
    @patch("newsletter_agent.__main__.setup_logging")
    def test_error_summary_on_config_error(self, mock_logging, mock_asyncio_run, capsys):
        """main() returns 1 on config error. FR-CLI-004."""
        mock_asyncio_run.side_effect = FileNotFoundError("Config file not found: config/topics.yaml")

        from newsletter_agent.__main__ import main
        exit_code = main()

        assert exit_code == 1
        captured = capsys.readouterr()
        summary = json.loads(captured.out.strip())
        assert summary["status"] == "error"
        assert "FileNotFoundError" in summary["message"]


# ---------------------------------------------------------------------------
# run_pipeline() integration (FR-CLI-002)
# ---------------------------------------------------------------------------


class TestRunPipeline:

    @pytest.mark.asyncio
    async def test_run_pipeline_returns_session_state(self):
        """run_pipeline uses Runner and returns session state. FR-CLI-002."""
        mock_session = MagicMock()
        mock_session.id = "test-session-id"
        mock_session.state = {"newsletter_metadata": {"topic_count": 2}}

        mock_session_service = AsyncMock()
        mock_session_service.create_session = AsyncMock(return_value=mock_session)
        mock_session_service.get_session = AsyncMock(return_value=mock_session)

        mock_runner = MagicMock()

        async def mock_run_async(**kwargs):
            return
            yield  # make it an async generator

        mock_runner.run_async = mock_run_async

        with patch("google.adk.sessions.InMemorySessionService", return_value=mock_session_service), \
             patch("google.adk.runners.Runner", return_value=mock_runner), \
             patch("newsletter_agent.agent.root_agent"):

            from newsletter_agent.__main__ import run_pipeline
            state = await run_pipeline()

        assert state == {"newsletter_metadata": {"topic_count": 2}}

    @pytest.mark.asyncio
    async def test_run_pipeline_sends_trigger_message(self):
        """run_pipeline sends 'Generate newsletter' trigger. FR-CLI-002."""
        mock_session = MagicMock()
        mock_session.id = "sess-1"
        mock_session.state = {}

        mock_session_service = AsyncMock()
        mock_session_service.create_session = AsyncMock(return_value=mock_session)
        mock_session_service.get_session = AsyncMock(return_value=mock_session)

        captured_kwargs = {}
        mock_runner = MagicMock()

        async def mock_run_async(**kwargs):
            captured_kwargs.update(kwargs)
            return
            yield

        mock_runner.run_async = mock_run_async

        with patch("google.adk.sessions.InMemorySessionService", return_value=mock_session_service), \
             patch("google.adk.runners.Runner", return_value=mock_runner), \
             patch("newsletter_agent.agent.root_agent"):

            from newsletter_agent.__main__ import run_pipeline
            await run_pipeline()

        assert captured_kwargs["user_id"] == "cli"
        assert captured_kwargs["session_id"] == "sess-1"
        parts = captured_kwargs["new_message"].parts
        assert any("Generate newsletter" in p.text for p in parts)

    @pytest.mark.asyncio
    async def test_run_pipeline_returns_empty_dict_when_no_session(self):
        """run_pipeline handles None session gracefully."""
        mock_session = MagicMock()
        mock_session.id = "sess-2"

        mock_session_service = AsyncMock()
        mock_session_service.create_session = AsyncMock(return_value=mock_session)
        mock_session_service.get_session = AsyncMock(return_value=None)

        mock_runner = MagicMock()

        async def mock_run_async(**kwargs):
            return
            yield

        mock_runner.run_async = mock_run_async

        with patch("google.adk.sessions.InMemorySessionService", return_value=mock_session_service), \
             patch("google.adk.runners.Runner", return_value=mock_runner), \
             patch("newsletter_agent.agent.root_agent"):

            from newsletter_agent.__main__ import run_pipeline
            state = await run_pipeline()

        assert state == {}


# ---------------------------------------------------------------------------
# Logging setup (FR-CLI-003)
# ---------------------------------------------------------------------------


class TestLogging:

    @patch("newsletter_agent.__main__.asyncio.run")
    @patch("newsletter_agent.__main__.setup_logging")
    def test_setup_logging_called(self, mock_logging, mock_asyncio_run):
        """main() calls setup_logging before running pipeline. FR-CLI-003."""
        mock_asyncio_run.return_value = _make_success_state()

        from newsletter_agent.__main__ import main
        main()

        mock_logging.assert_called_once()
