"""E2E test: Full pipeline with both new features (timeframe + link verification).

Runs the formatter and delivery agents with pre-populated session state
that includes timeframe configuration and link verification results,
verifying the complete output path produces correct HTML.

Spec refs: Section 11.4 bullet 1, SC-001, SC-002.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from newsletter_agent.agent import build_pipeline, build_research_phase
from newsletter_agent.config.schema import (
    AppSettings,
    NewsletterConfig,
    NewsletterSettings,
    TopicConfig,
    load_config,
)
from newsletter_agent.tools.formatter import FormatterAgent, render_newsletter
from newsletter_agent.tools.delivery import DeliveryAgent
from newsletter_agent.tools.link_verifier import LinkCheckResult
from newsletter_agent.tools.link_verifier_agent import LinkVerifierAgent


TEST_CONFIG_WITH_FEATURES_YAML = """\
newsletter:
  title: "Feature Test Newsletter"
  schedule: "0 8 * * 0"
  recipient_email: "test@example.com"

settings:
  dry_run: true
  output_dir: "{output_dir}"
  timeframe: "last_week"
  verify_links: true

topics:
  - name: "AI Frameworks"
    query: "Latest developments in AI agent frameworks"
  - name: "Cloud Native"
    query: "Cloud native technology updates"
    timeframe: "last_month"
"""


def _make_session_state_with_features(output_dir: str) -> dict:
    """Session state with both features enabled, including broken URLs in research data."""
    return {
        "config_newsletter_title": "Feature Test Newsletter",
        "config_recipient_email": "test@example.com",
        "config_dry_run": True,
        "config_output_dir": output_dir,
        "config_verify_links": True,
        "config_topic_count": 2,
        "config_timeframes": {
            0: {"perplexity_recency_filter": "week", "instruction_text": "Focus on content from the past 7 days."},
            1: {"perplexity_recency_filter": "month", "instruction_text": "Focus on content from the past 30 days."},
        },
        "pipeline_start_time": "2025-01-01T08:00:00+00:00",
        # Research keys contain broken links (pre-verification)
        "research_0_google": (
            "## AI Frameworks\n\n"
            "The AI framework landscape evolves. "
            "[ADK Docs](https://example.com/adk) show updates.\n\n"
            "[Dead Link](https://broken.example.com/gone) was removed."
        ),
        "research_1_google": (
            "## Cloud Native\n\n"
            "Cloud tech is maturing. "
            "[CNCF Report](https://example.com/cncf) highlights trends."
        ),
        # Synthesis keys represent post-synthesis output (before link verification)
        "synthesis_0": {
            "title": "AI Frameworks",
            "body_markdown": (
                "## AI Frameworks\n\n"
                "The AI framework landscape evolves. "
                "[ADK Docs](https://example.com/adk) show updates.\n\n"
                "[Dead Link](https://broken.example.com/gone) was removed."
            ),
            "sources": [
                {"url": "https://example.com/adk", "title": "ADK Docs"},
                {"url": "https://broken.example.com/gone", "title": "Dead Link"},
            ],
        },
        "synthesis_1": {
            "title": "Cloud Native",
            "body_markdown": (
                "## Cloud Native\n\n"
                "Cloud tech is maturing. "
                "[CNCF Report](https://example.com/cncf) highlights trends."
            ),
            "sources": [
                {"url": "https://example.com/cncf", "title": "CNCF Report"},
            ],
        },
        "executive_summary": [
            "AI frameworks evolving with multi-agent support.",
            "Cloud native technologies maturing rapidly.",
        ],
    }


@pytest.fixture()
def test_config_with_features_file(tmp_path):
    """Create a config file with both new features enabled."""
    output_dir = str(tmp_path / "output")
    content = TEST_CONFIG_WITH_FEATURES_YAML.format(
        output_dir=output_dir.replace("\\", "/")
    )
    config_path = tmp_path / "topics.yaml"
    config_path.write_text(content)
    return str(config_path), output_dir


class TestPipelineBuildWithFeatures:
    """Pipeline builds correctly with both features."""

    def test_config_loads_with_features(self, test_config_with_features_file):
        config_path, _ = test_config_with_features_file
        config = load_config(config_path)
        assert config.settings.timeframe == "last_week"
        assert config.settings.verify_links is True
        assert config.topics[1].timeframe == "last_month"

    def test_pipeline_includes_link_verifier(self, test_config_with_features_file):
        config_path, _ = test_config_with_features_file
        config = load_config(config_path)
        pipeline = build_pipeline(config)
        agent_names = [a.name for a in pipeline.sub_agents]
        assert "LinkVerifier" in agent_names

    def test_research_phase_has_timeframe(self, test_config_with_features_file):
        config_path, _ = test_config_with_features_file
        config = load_config(config_path)
        phase = build_research_phase(config)
        from tests.conftest import get_instruction_text
        # Topic 0 inherits global "last_week"
        for sub in phase.sub_agents[0].sub_agents:
            assert "week" in get_instruction_text(sub).lower()
        # Topic 1 overrides to "last_month"
        for sub in phase.sub_agents[1].sub_agents:
            assert "month" in get_instruction_text(sub).lower()


class TestFormatterWithVerifiedLinks:
    """Formatter produces correct HTML after link verification removes broken links from research."""

    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_link_verifier_cleans_research_keys(self, mock_verify, tmp_path):
        """Link verification cleans broken URLs from research state keys."""
        output_dir = str(tmp_path / "output")
        state = _make_session_state_with_features(output_dir)

        mock_verify.return_value = {
            "https://example.com/adk": LinkCheckResult(
                url="https://example.com/adk", status="valid", http_status=200
            ),
            "https://broken.example.com/gone": LinkCheckResult(
                url="https://broken.example.com/gone",
                status="broken",
                http_status=404,
                error="status_404",
            ),
            "https://example.com/cncf": LinkCheckResult(
                url="https://example.com/cncf", status="valid", http_status=200
            ),
        }

        # Link verification on research data (pre-synthesis)
        verifier = LinkVerifierAgent(
            name="LinkVerifier", topic_count=2, providers=["google"],
        )
        ctx = MagicMock()
        ctx.session.state = state
        async for _ in verifier._run_async_impl(ctx):
            pass

        # Broken link should be removed from research entry
        assert "https://broken.example.com/gone" not in state["research_0_google"]
        # Valid link should remain in research entry
        assert "https://example.com/adk" in state["research_0_google"]

    @pytest.mark.asyncio
    async def test_formatter_produces_clean_html(self, tmp_path):
        """Formatter produces correct HTML from clean synthesis data."""
        output_dir = str(tmp_path / "output")
        state = _make_session_state_with_features(output_dir)
        # Simulate post-verification: research is clean, synthesis was generated from clean research
        # Remove the broken link from synthesis (as would happen in real pipeline)
        state["synthesis_0"]["body_markdown"] = (
            "## AI Frameworks\n\n"
            "The AI framework landscape evolves. "
            "[ADK Docs](https://example.com/adk) show updates."
        )
        state["synthesis_0"]["sources"] = [
            {"url": "https://example.com/adk", "title": "ADK Docs"},
        ]

        ctx = MagicMock()
        ctx.session.state = state

        formatter = FormatterAgent(name="FormatterAgent")
        async for _ in formatter._run_async_impl(ctx):
            pass

        html = state.get("newsletter_html", "")
        assert "Feature Test Newsletter" in html
        assert "AI Frameworks" in html
        assert "Cloud Native" in html
        assert "broken.example.com/gone" not in html

    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_delivery_saves_clean_html(self, mock_verify, tmp_path):
        """Full pipeline output file contains no broken link markup."""
        output_dir = str(tmp_path / "output")
        state = _make_session_state_with_features(output_dir)

        mock_verify.return_value = {
            "https://example.com/adk": LinkCheckResult(
                url="https://example.com/adk", status="valid", http_status=200
            ),
            "https://broken.example.com/gone": LinkCheckResult(
                url="https://broken.example.com/gone",
                status="broken",
                http_status=404,
                error="status_404",
            ),
            "https://example.com/cncf": LinkCheckResult(
                url="https://example.com/cncf", status="valid", http_status=200
            ),
        }

        ctx = MagicMock()
        ctx.session.state = state

        # Link verify on research data (pre-synthesis)
        verifier = LinkVerifierAgent(
            name="LinkVerifier", topic_count=2, providers=["google"],
        )
        async for _ in verifier._run_async_impl(ctx):
            pass

        # Simulate clean synthesis (broken link removed by synthesizer processing clean research)
        state["synthesis_0"]["body_markdown"] = (
            "## AI Frameworks\n\n"
            "The AI framework landscape evolves. "
            "[ADK Docs](https://example.com/adk) show updates."
        )
        state["synthesis_0"]["sources"] = [
            {"url": "https://example.com/adk", "title": "ADK Docs"},
        ]

        # Format
        formatter = FormatterAgent(name="FormatterAgent")
        async for _ in formatter._run_async_impl(ctx):
            pass

        # Deliver
        delivery = DeliveryAgent(name="DeliveryAgent")
        async for _ in delivery._run_async_impl(ctx):
            pass

        delivery_status = state.get("delivery_status", {})
        assert delivery_status["status"] == "dry_run"

        output_file = Path(delivery_status["output_file"])
        assert output_file.exists()

        content = output_file.read_text(encoding="utf-8")
        assert "Feature Test Newsletter" in content
        assert "broken.example.com/gone" not in content
        assert content.startswith("<!DOCTYPE html>")
