"""End-to-end test for the full newsletter pipeline in dry-run mode.

Runs the formatter and delivery agents directly with pre-populated
session state to verify the full output path without requiring LLM calls.

Spec refs: Section 11.4, US-06.
"""

import os
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from newsletter_agent.config.schema import load_config, NewsletterConfig
from newsletter_agent.agent import build_research_phase, build_synthesis_agent
from newsletter_agent.tools.per_topic_synthesizer import PerTopicSynthesizerAgent
from newsletter_agent.tools.formatter import FormatterAgent, render_newsletter
from newsletter_agent.tools.delivery import DeliveryAgent


TEST_CONFIG_YAML = """\
newsletter:
  title: "E2E Test Newsletter"
  schedule: "0 8 * * 0"
  recipient_email: "test@example.com"

settings:
  dry_run: true
  output_dir: "{output_dir}"

topics:
  - name: "AI Frameworks"
    query: "Latest developments in AI agent frameworks"
  - name: "Cloud Native"
    query: "Cloud native technology updates"
"""


def _make_session_state(output_dir: str) -> dict:
    """Build a realistic session state as if research and synthesis already ran."""
    return {
        "config_newsletter_title": "E2E Test Newsletter",
        "config_recipient_email": "test@example.com",
        "config_dry_run": True,
        "config_output_dir": output_dir,
        "pipeline_start_time": "2025-01-01T08:00:00+00:00",
        "synthesis_0": {
            "title": "AI Frameworks",
            "body_markdown": (
                "## AI Frameworks\n\n"
                "The AI framework landscape continues to evolve. "
                "[ADK Docs](https://example.com/adk) show major updates.\n\n"
                "Key developments include improved multi-agent orchestration."
            ),
            "sources": [
                {"url": "https://example.com/adk", "title": "ADK Docs"},
            ],
        },
        "synthesis_1": {
            "title": "Cloud Native",
            "body_markdown": (
                "## Cloud Native\n\n"
                "Cloud native technology is maturing rapidly. "
                "[CNCF Report](https://example.com/cncf) highlights trends.\n\n"
                "Kubernetes adoption continues to grow."
            ),
            "sources": [
                {"url": "https://example.com/cncf", "title": "CNCF Report"},
            ],
        },
        "executive_summary": [
            "AI frameworks are evolving with better multi-agent support.",
            "Cloud native technologies continue rapid maturation.",
        ],
    }


@pytest.fixture()
def test_config_file(tmp_path):
    """Create a test config file in a temporary directory."""
    output_dir = str(tmp_path / "output")
    config_content = TEST_CONFIG_YAML.format(output_dir=output_dir.replace("\\", "/"))
    config_path = tmp_path / "topics.yaml"
    config_path.write_text(config_content)
    return str(config_path), output_dir


class TestPipelineBuildsCorrectly:
    """Verify the pipeline can be built from config."""

    def test_config_loads(self, test_config_file):
        config_path, _ = test_config_file
        config = load_config(config_path)
        assert config.newsletter.title == "E2E Test Newsletter"
        assert len(config.topics) == 2

    def test_research_phase_builds(self, test_config_file):
        config_path, _ = test_config_file
        config = load_config(config_path)
        phase = build_research_phase(config)
        assert len(phase.sub_agents) == 2

    def test_synthesis_agent_builds(self, test_config_file):
        config_path, _ = test_config_file
        config = load_config(config_path)
        agent = build_synthesis_agent(config, ["google", "perplexity"])
        assert "pro" in agent.model.lower()


class TestFormatterE2E:
    """Test the formatter agent with pre-populated state."""

    @pytest.mark.asyncio
    async def test_formatter_produces_html(self, tmp_path):
        output_dir = str(tmp_path / "output")
        state = _make_session_state(output_dir)

        ctx = MagicMock()
        ctx.session.state = state

        formatter = FormatterAgent(name="FormatterAgent")
        events = []
        async for event in formatter._run_async_impl(ctx):
            events.append(event)

        assert len(events) == 1
        html = state.get("newsletter_html", "")
        assert "E2E Test Newsletter" in html
        assert "AI Frameworks" in html
        assert "Cloud Native" in html

    @pytest.mark.asyncio
    async def test_html_contains_sources(self, tmp_path):
        output_dir = str(tmp_path / "output")
        state = _make_session_state(output_dir)

        ctx = MagicMock()
        ctx.session.state = state

        formatter = FormatterAgent(name="FormatterAgent")
        async for _ in formatter._run_async_impl(ctx):
            pass

        html = state.get("newsletter_html", "")
        assert "example.com/adk" in html
        assert "example.com/cncf" in html

    @pytest.mark.asyncio
    async def test_html_contains_executive_summary(self, tmp_path):
        output_dir = str(tmp_path / "output")
        state = _make_session_state(output_dir)

        ctx = MagicMock()
        ctx.session.state = state

        formatter = FormatterAgent(name="FormatterAgent")
        async for _ in formatter._run_async_impl(ctx):
            pass

        html = state.get("newsletter_html", "")
        assert "multi-agent" in html


class TestDeliveryDryRunE2E:
    """Test the delivery agent in dry-run mode produces a file."""

    @pytest.mark.asyncio
    async def test_dry_run_saves_html_file(self, tmp_path):
        output_dir = str(tmp_path / "output")
        state = _make_session_state(output_dir)

        # First run the formatter to produce the HTML
        ctx = MagicMock()
        ctx.session.state = state
        formatter = FormatterAgent(name="FormatterAgent")
        async for _ in formatter._run_async_impl(ctx):
            pass

        # Then run delivery
        delivery = DeliveryAgent(name="DeliveryAgent")
        events = []
        async for event in delivery._run_async_impl(ctx):
            events.append(event)

        assert len(events) == 1
        delivery_status = state.get("delivery_status", {})
        assert delivery_status["status"] == "dry_run"
        assert delivery_status["output_file"]

        # Verify the file actually exists
        output_file = Path(delivery_status["output_file"])
        assert output_file.exists()
        content = output_file.read_text(encoding="utf-8")
        assert "E2E Test Newsletter" in content

    @pytest.mark.asyncio
    async def test_html_file_is_valid(self, tmp_path):
        output_dir = str(tmp_path / "output")
        state = _make_session_state(output_dir)

        ctx = MagicMock()
        ctx.session.state = state

        formatter = FormatterAgent(name="FormatterAgent")
        async for _ in formatter._run_async_impl(ctx):
            pass

        delivery = DeliveryAgent(name="DeliveryAgent")
        async for _ in delivery._run_async_impl(ctx):
            pass

        output_file = Path(state["delivery_status"]["output_file"])
        content = output_file.read_text(encoding="utf-8")
        assert content.startswith("<!DOCTYPE html>")
        assert "</html>" in content


class TestFullOutputPathE2E:
    """Test the complete output path: formatter -> delivery."""

    @pytest.mark.asyncio
    async def test_two_topics_produce_two_sections_in_html(self, tmp_path):
        output_dir = str(tmp_path / "output")
        state = _make_session_state(output_dir)

        ctx = MagicMock()
        ctx.session.state = state

        # Formatter
        formatter = FormatterAgent(name="FormatterAgent")
        async for _ in formatter._run_async_impl(ctx):
            pass

        # Delivery
        delivery = DeliveryAgent(name="DeliveryAgent")
        async for _ in delivery._run_async_impl(ctx):
            pass

        output_file = Path(state["delivery_status"]["output_file"])
        content = output_file.read_text(encoding="utf-8")
        assert "AI Frameworks" in content
        assert "Cloud Native" in content

    @pytest.mark.asyncio
    async def test_metadata_is_populated(self, tmp_path):
        output_dir = str(tmp_path / "output")
        state = _make_session_state(output_dir)

        ctx = MagicMock()
        ctx.session.state = state

        formatter = FormatterAgent(name="FormatterAgent")
        async for _ in formatter._run_async_impl(ctx):
            pass

        metadata = state.get("newsletter_metadata", {})
        assert metadata["title"] == "E2E Test Newsletter"
        assert metadata["topic_count"] == 2
