"""E2E smoke test for the observability-enabled CLI path.

Runs `python -m newsletter_agent` in dry-run mode through the real module
entry point while a `sitecustomize` shim injects a mocked pipeline path that
still emits spans and a cost summary.

Spec refs: Section 11.4, SC-002, SC-003, SC-005.
"""

import json
import os
import subprocess
import sys
import textwrap

import pytest


_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


@pytest.mark.e2e
def test_cli_dry_run_outputs_console_spans_and_cost_summary(tmp_path):
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()

    sitecustomize = shim_dir / "sitecustomize.py"
    sitecustomize.write_text(
        textwrap.dedent(
            """\
            import sys
            import types as pytypes
            from types import SimpleNamespace

            fake_agent_module = pytypes.ModuleType("newsletter_agent.agent")
            fake_agent_module.root_agent = object()
            sys.modules["newsletter_agent.agent"] = fake_agent_module

            from google.adk.runners import Runner as _RealRunner
            from google.adk.sessions import InMemorySessionService as _RealSessionService

            class FakeSession:
                def __init__(self):
                    self.id = "smoke-session"
                    self.state = {}


            class FakeSessionService:
                def __init__(self):
                    self._session = FakeSession()

                async def create_session(self, app_name, user_id):
                    return self._session

                async def get_session(self, app_name, user_id, session_id):
                    return self._session


            class FakeRunner:
                def __init__(self, agent, app_name, session_service):
                    self.session_service = session_service

                async def run_async(self, session_id, user_id, new_message):
                    from newsletter_agent.cost_tracker import ModelPricing, init_cost_tracker
                    from newsletter_agent.timing import before_agent_callback, after_agent_callback

                    state = self.session_service._session.state
                    state.update(
                        {
                            "config_topic_count": 1,
                            "config_topics": ["AI Observability"],
                            "config_dry_run": True,
                            "delivery_status": {
                                "status": "dry_run",
                                "output_file": "output/test-observability.html",
                            },
                            "newsletter_metadata": {"topic_count": 1},
                        }
                    )

                    init_cost_tracker(
                        {"gemini-2.5-pro": ModelPricing(1.25, 10.00)}
                    )

                    callback_ctx = lambda name: SimpleNamespace(
                        agent_name=name,
                        invocation_id="smoke-invocation",
                        state=state,
                    )

                    root_ctx = callback_ctx("NewsletterPipeline")
                    synth_ctx = callback_ctx("PerTopicSynthesizer_0")

                    before_agent_callback(root_ctx)
                    before_agent_callback(synth_ctx)

                    from newsletter_agent.cost_tracker import get_cost_tracker

                    get_cost_tracker().record_llm_call(
                        model="gemini-2.5-pro",
                        agent_name="PerTopicSynthesizer_0",
                        phase="synthesis",
                        topic_name="AI Observability",
                        topic_index=0,
                        prompt_tokens=1000,
                        completion_tokens=500,
                        thinking_tokens=200,
                    )

                    after_agent_callback(synth_ctx)
                    after_agent_callback(root_ctx)

                    yield SimpleNamespace(author="FakeRunner", content=object())


            import google.adk.runners
            import google.adk.sessions

            google.adk.runners.Runner = FakeRunner
            google.adk.sessions.InMemorySessionService = FakeSessionService
            """
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(shim_dir), _PROJECT_ROOT, env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    env["OTEL_ENABLED"] = "true"
    env.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
    env.pop("K_SERVICE", None)
    env["LOG_FORMAT_JSON"] = "false"

    result = subprocess.run(
        [sys.executable, "-m", "newsletter_agent"],
        cwd=_PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert '"name": "NewsletterPipeline"' in result.stdout
    assert '"name": "PerTopicSynthesizer_0"' in result.stdout
    assert "pipeline_cost_summary" in result.stdout
    assert 'trace=' in result.stdout

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    summary_line = next(
        line for line in reversed(lines) if line.startswith('{"status"')
    )
    summary = json.loads(summary_line)
    assert summary["status"] == "success"
    assert summary["email_sent"] is False
    assert summary["output_file"] == "output/test-observability.html"
