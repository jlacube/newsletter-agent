"""E2E test: CLI subprocess execution.

Runs `python -m newsletter_agent` as a subprocess and verifies
exit codes and output. Uses mocked pipeline to avoid real API calls.

Spec refs: FR-CLI-001, FR-CLI-004, SC-001, Section 11.4 (WP14 T14-05).
"""

import json
import os
import subprocess
import sys
import textwrap

import pytest

# Project root directory for subprocess cwd
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run_script(script_path):
    """Run a helper script as a subprocess with the project on sys.path."""
    env = os.environ.copy()
    env["PYTHONPATH"] = _PROJECT_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, str(script_path)],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


@pytest.mark.e2e
class TestCLISubprocessExecution:
    """E2E test: CLI subprocess with real Python entry point."""

    def test_module_is_runnable(self):
        """python -m newsletter_agent is a valid entry point (FR-CLI-001)."""
        # Verify __main__.py exists and can be imported
        result = subprocess.run(
            [sys.executable, "-c", "from newsletter_agent.__main__ import main"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"Import failed: {result.stderr}"

    def test_subprocess_success_with_mocked_pipeline(self, tmp_path):
        """Subprocess returns exit 0 with JSON summary when pipeline succeeds (SC-001)."""
        script = tmp_path / "run_cli.py"
        script.write_text(textwrap.dedent("""\
            import json
            import logging
            import sys
            from unittest.mock import AsyncMock, patch

            # Suppress all logging to avoid polluting stdout
            logging.disable(logging.CRITICAL)

            mock_state = {
                "delivery_status": {"status": "dry_run", "output_file": "output/test.html"},
                "newsletter_metadata": {"topic_count": 2},
            }

            with patch("newsletter_agent.__main__.run_pipeline", new=AsyncMock(return_value=mock_state)):
                with patch("newsletter_agent.__main__.setup_logging"):
                    from newsletter_agent.__main__ import main
                    sys.exit(main())
        """), encoding="utf-8")

        result = _run_script(script)
        assert result.returncode == 0, f"Exit code {result.returncode}: {result.stderr}"

        # Parse the last line (JSON summary) from stdout
        lines = [l for l in result.stdout.strip().splitlines() if l.strip()]
        summary = json.loads(lines[-1])
        assert summary["status"] == "success"
        assert "newsletter_date" in summary
        assert "topics_processed" in summary

    def test_subprocess_failure_returns_exit_1(self, tmp_path):
        """Subprocess returns exit 1 with error JSON when pipeline fails."""
        script = tmp_path / "run_cli_fail.py"
        script.write_text(textwrap.dedent("""\
            import logging
            import sys
            from unittest.mock import AsyncMock, patch

            logging.disable(logging.CRITICAL)

            with patch(
                "newsletter_agent.__main__.run_pipeline",
                new=AsyncMock(side_effect=RuntimeError("Config error")),
            ):
                with patch("newsletter_agent.__main__.setup_logging"):
                    from newsletter_agent.__main__ import main
                    sys.exit(main())
        """), encoding="utf-8")

        result = _run_script(script)
        assert result.returncode == 1

        lines = [l for l in result.stdout.strip().splitlines() if l.strip()]
        summary = json.loads(lines[-1])
        assert summary["status"] == "error"
        assert "Config error" in summary["message"]

    def test_no_interactive_input_required(self, tmp_path):
        """CLI completes without any stdin input (SC-001)."""
        script = tmp_path / "run_cli_noinput.py"
        script.write_text(textwrap.dedent("""\
            import logging
            import sys
            from unittest.mock import AsyncMock, patch

            logging.disable(logging.CRITICAL)

            mock_state = {
                "delivery_status": {"status": "dry_run", "output_file": "output/test.html"},
                "newsletter_metadata": {"topic_count": 1},
            }

            with patch("newsletter_agent.__main__.run_pipeline", new=AsyncMock(return_value=mock_state)):
                with patch("newsletter_agent.__main__.setup_logging"):
                    from newsletter_agent.__main__ import main
                    sys.exit(main())
        """), encoding="utf-8")

        env = os.environ.copy()
        env["PYTHONPATH"] = _PROJECT_ROOT + os.pathsep + env.get("PYTHONPATH", "")
        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            timeout=30,
            input="",  # Explicitly provide empty stdin
            env=env,
        )
        assert result.returncode == 0, "CLI should complete without interactive input"
