"""
BDD-style acceptance tests for autonomous CLI execution.

Uses Given/When/Then structure to verify spec Section 11.2 scenarios.
Spec refs: Section 11.2 Feature: Autonomous CLI Execution, US-01.
"""

import json
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_main():
    """Import and call main(), returning (exit_code, stdout)."""
    from newsletter_agent.__main__ import main
    return main()


def _success_state(dry_run=False, output_file=None, topic_count=3):
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
# Scenario: Successful pipeline run via CLI
#
#   Given valid config with dry_run true
#   And all environment variables are set
#   When python -m newsletter_agent is executed
#   Then the pipeline runs to completion
#   And an HTML file is saved to output/
#   And a JSON summary is printed with status "success"
#   And the process exits with code 0
# ---------------------------------------------------------------------------


class TestSuccessfulPipelineRun:
    """BDD Scenario: Successful pipeline run via CLI."""

    @patch("newsletter_agent.__main__.asyncio.run")
    @patch("newsletter_agent.__main__.setup_logging")
    def test_given_valid_config_when_executed_then_exits_zero(
        self, mock_logging, mock_run, capsys
    ):
        # Given valid config with dry_run true
        mock_run.return_value = _success_state(
            dry_run=True,
            output_file="output/2025-03-15-newsletter.html",
        )

        # When python -m newsletter_agent is executed
        exit_code = _run_main()

        # Then the process exits with code 0
        assert exit_code == 0

    @patch("newsletter_agent.__main__.asyncio.run")
    @patch("newsletter_agent.__main__.setup_logging")
    def test_given_dry_run_when_executed_then_json_summary_has_output_file(
        self, mock_logging, mock_run, capsys
    ):
        # Given valid config with dry_run true
        mock_run.return_value = _success_state(
            dry_run=True,
            output_file="output/2025-03-15-newsletter.html",
        )

        # When python -m newsletter_agent is executed
        _run_main()

        # Then an HTML file is saved to output/ (reported in summary)
        captured = capsys.readouterr()
        summary = json.loads(captured.out.strip())
        assert summary["output_file"] == "output/2025-03-15-newsletter.html"

    @patch("newsletter_agent.__main__.asyncio.run")
    @patch("newsletter_agent.__main__.setup_logging")
    def test_given_valid_config_when_executed_then_json_summary_status_success(
        self, mock_logging, mock_run, capsys
    ):
        # Given valid config with dry_run true
        mock_run.return_value = _success_state(dry_run=True, output_file="output/x.html")

        # When python -m newsletter_agent is executed
        _run_main()

        # Then a JSON summary is printed with status "success"
        captured = capsys.readouterr()
        summary = json.loads(captured.out.strip())
        assert summary["status"] == "success"
        assert "newsletter_date" in summary
        assert "topics_processed" in summary


# ---------------------------------------------------------------------------
# Scenario: CLI handles config error
#
#   Given config with missing required field
#   When python -m newsletter_agent is executed
#   Then a config error is logged
#   And the process exits with code 1
# ---------------------------------------------------------------------------


class TestConfigError:
    """BDD Scenario: CLI handles config error."""

    @patch("newsletter_agent.__main__.asyncio.run")
    @patch("newsletter_agent.__main__.setup_logging")
    def test_given_bad_config_when_executed_then_exits_one(
        self, mock_logging, mock_run, capsys
    ):
        # Given config with missing required field (raises at pipeline startup)
        mock_run.side_effect = FileNotFoundError("Config file not found: config/topics.yaml")

        # When python -m newsletter_agent is executed
        exit_code = _run_main()

        # Then the process exits with code 1
        assert exit_code == 1

    @patch("newsletter_agent.__main__.asyncio.run")
    @patch("newsletter_agent.__main__.setup_logging")
    def test_given_bad_config_when_executed_then_error_logged(
        self, mock_logging, mock_run, capsys
    ):
        # Given config with missing required field
        mock_run.side_effect = FileNotFoundError("Config file not found")

        # When python -m newsletter_agent is executed
        _run_main()

        # Then a config error is logged (visible in JSON summary)
        captured = capsys.readouterr()
        summary = json.loads(captured.out.strip())
        assert summary["status"] == "error"
        assert "FileNotFoundError" in summary["message"]


# ---------------------------------------------------------------------------
# Scenario: CLI handles pipeline failure
#
#   Given valid config
#   And all research providers are mocked to fail
#   When python -m newsletter_agent is executed
#   Then a pipeline error is logged
#   And the process exits with code 1
# ---------------------------------------------------------------------------


class TestPipelineFailure:
    """BDD Scenario: CLI handles pipeline failure."""

    @patch("newsletter_agent.__main__.asyncio.run")
    @patch("newsletter_agent.__main__.setup_logging")
    def test_given_pipeline_failure_when_executed_then_exits_one(
        self, mock_logging, mock_run, capsys
    ):
        # Given valid config and all research providers fail
        mock_run.side_effect = RuntimeError("All search providers failed")

        # When python -m newsletter_agent is executed
        exit_code = _run_main()

        # Then the process exits with code 1
        assert exit_code == 1

    @patch("newsletter_agent.__main__.asyncio.run")
    @patch("newsletter_agent.__main__.setup_logging")
    def test_given_pipeline_failure_when_executed_then_error_logged(
        self, mock_logging, mock_run, capsys
    ):
        # Given valid config and all research providers fail
        mock_run.side_effect = RuntimeError("All search providers failed")

        # When python -m newsletter_agent is executed
        _run_main()

        # Then a pipeline error is logged
        captured = capsys.readouterr()
        summary = json.loads(captured.out.strip())
        assert summary["status"] == "error"
        assert "RuntimeError" in summary["message"]
        assert "search providers failed" in summary["message"]
