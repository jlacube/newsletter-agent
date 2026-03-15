"""Integration test: CLI runner end-to-end with mocks.

Verifies that the CLI main() function executes the full pipeline,
returns correct exit codes, and produces valid JSON summary output.

Spec refs: FR-CLI-002, FR-CLI-004, FR-CLI-005, Section 11.3 (WP14 T14-03).
"""

import json
import pytest
from io import StringIO
from unittest.mock import patch, MagicMock

from newsletter_agent.__main__ import main


class TestCLIRunnerIntegration:
    """Integration test: CLI main() with mocked pipeline."""

    def test_main_returns_0_on_success(self):
        """main() returns exit code 0 when pipeline succeeds."""
        mock_state = {
            "delivery_status": {"status": "dry_run", "output_file": "output/test.html"},
            "newsletter_metadata": {"topic_count": 2},
        }

        with patch("newsletter_agent.__main__.run_pipeline", return_value=mock_state):
            with patch("newsletter_agent.__main__.setup_logging"):
                with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
                    exit_code = main()

        assert exit_code == 0
        output = mock_stdout.getvalue().strip()
        summary = json.loads(output)
        assert summary["status"] == "success"

    def test_main_returns_1_on_failure(self):
        """main() returns exit code 1 when pipeline raises an exception."""
        with patch(
            "newsletter_agent.__main__.run_pipeline",
            side_effect=RuntimeError("Pipeline exploded"),
        ):
            with patch("newsletter_agent.__main__.setup_logging"):
                with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
                    exit_code = main()

        assert exit_code == 1
        output = mock_stdout.getvalue().strip()
        summary = json.loads(output)
        assert summary["status"] == "error"
        assert "Pipeline exploded" in summary["message"]

    def test_success_summary_has_required_fields(self):
        """JSON summary contains all required fields (FR-CLI-004)."""
        mock_state = {
            "delivery_status": {"status": "dry_run", "output_file": "output/newsletter.html"},
            "newsletter_metadata": {"topic_count": 3},
        }

        with patch("newsletter_agent.__main__.run_pipeline", return_value=mock_state):
            with patch("newsletter_agent.__main__.setup_logging"):
                with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
                    main()

        summary = json.loads(mock_stdout.getvalue().strip())
        assert "status" in summary
        assert "newsletter_date" in summary
        assert "topics_processed" in summary
        assert "email_sent" in summary
        assert "output_file" in summary

    def test_dry_run_includes_output_file(self):
        """dry_run mode includes output_file in JSON summary (FR-CLI-005)."""
        mock_state = {
            "delivery_status": {"status": "dry_run", "output_file": "output/test.html"},
            "newsletter_metadata": {"topic_count": 1},
        }

        with patch("newsletter_agent.__main__.run_pipeline", return_value=mock_state):
            with patch("newsletter_agent.__main__.setup_logging"):
                with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
                    main()

        summary = json.loads(mock_stdout.getvalue().strip())
        assert summary["output_file"] == "output/test.html"
        assert summary["email_sent"] is False

    def test_email_sent_true_when_delivered(self):
        """email_sent is True when delivery status is 'sent'."""
        mock_state = {
            "delivery_status": {"status": "sent"},
            "newsletter_metadata": {"topic_count": 2},
        }

        with patch("newsletter_agent.__main__.run_pipeline", return_value=mock_state):
            with patch("newsletter_agent.__main__.setup_logging"):
                with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
                    main()

        summary = json.loads(mock_stdout.getvalue().strip())
        assert summary["email_sent"] is True
        assert "output_file" not in summary

    def test_topics_processed_from_metadata(self):
        """topics_processed reflects the actual topic count from state."""
        mock_state = {
            "delivery_status": {"status": "dry_run", "output_file": "output/test.html"},
            "newsletter_metadata": {"topic_count": 5},
        }

        with patch("newsletter_agent.__main__.run_pipeline", return_value=mock_state):
            with patch("newsletter_agent.__main__.setup_logging"):
                with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
                    main()

        summary = json.loads(mock_stdout.getvalue().strip())
        assert summary["topics_processed"] == 5
