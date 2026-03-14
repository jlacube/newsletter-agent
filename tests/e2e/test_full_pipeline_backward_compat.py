"""E2E test: Full pipeline backward compatibility.

Verifies that the full pipeline works correctly with an old-format
topics.yaml (no timeframe, no verify_links fields). Proves no link
verification occurs and no timeframe filtering is applied.

Spec refs: Section 11.4 bullet 2, SC-004.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from newsletter_agent.agent import build_pipeline, build_research_phase, ConfigLoaderAgent
from newsletter_agent.config.schema import load_config
from newsletter_agent.tools.formatter import FormatterAgent
from newsletter_agent.tools.delivery import DeliveryAgent
from newsletter_agent.tools.link_verifier_agent import LinkVerifierAgent


# Exact same format as the original test_full_pipeline.py config
TEST_CONFIG_OLD_FORMAT_YAML = """\
newsletter:
  title: "Backward Compat Newsletter"
  schedule: "0 8 * * 0"
  recipient_email: "test@example.com"

settings:
  dry_run: true
  output_dir: "{output_dir}"

topics:
  - name: "General Tech"
    query: "Technology news and updates"
"""


def _make_old_format_state(output_dir: str) -> dict:
    """Session state matching the old pipeline format (no new features)."""
    return {
        "config_newsletter_title": "Backward Compat Newsletter",
        "config_recipient_email": "test@example.com",
        "config_dry_run": True,
        "config_output_dir": output_dir,
        "config_verify_links": False,
        "config_topic_count": 1,
        "config_timeframes": None,
        "pipeline_start_time": "2025-01-01T08:00:00+00:00",
        "synthesis_0": {
            "title": "General Tech",
            "body_markdown": (
                "## General Tech\n\n"
                "Technology trends are shifting. "
                "[Tech Report](https://example.com/tech) provides insights.\n\n"
                "See also [Another Source](https://example.com/source2)."
            ),
            "sources": [
                {"url": "https://example.com/tech", "title": "Tech Report"},
                {"url": "https://example.com/source2", "title": "Another Source"},
            ],
        },
        "executive_summary": [
            "Technology trends continue evolving rapidly.",
        ],
    }


@pytest.fixture()
def old_config_file(tmp_path):
    """Write old-format config and return (path, output_dir)."""
    output_dir = str(tmp_path / "output")
    content = TEST_CONFIG_OLD_FORMAT_YAML.format(
        output_dir=output_dir.replace("\\", "/")
    )
    config_path = tmp_path / "topics.yaml"
    config_path.write_text(content)
    return str(config_path), output_dir


class TestOldFormatConfigLoads:
    """Old-format config loads with new fields defaulting correctly."""

    def test_config_defaults(self, old_config_file):
        config_path, _ = old_config_file
        config = load_config(config_path)
        assert config.settings.timeframe is None
        assert config.settings.verify_links is False
        assert config.topics[0].timeframe is None

    def test_research_no_date_clause(self, old_config_file):
        config_path, _ = old_config_file
        config = load_config(config_path)
        phase = build_research_phase(config)
        for topic_agent in phase.sub_agents:
            for sub in topic_agent.sub_agents:
                assert "time constraint" not in sub.instruction.lower()


class TestBackwardCompatPipeline:
    """Full pipeline with old config produces correct output."""

    @pytest.mark.asyncio
    async def test_link_verifier_noop_no_http_calls(self, tmp_path):
        """LinkVerifierAgent does not make verification requests with old config."""
        output_dir = str(tmp_path / "output")
        state = _make_old_format_state(output_dir)

        ctx = MagicMock()
        ctx.session.state = state

        # Link verifier should no-op
        with patch(
            "newsletter_agent.tools.link_verifier_agent.verify_urls"
        ) as mock_verify:
            verifier = LinkVerifierAgent(name="LinkVerifier")
            async for _ in verifier._run_async_impl(ctx):
                pass

            # Should NOT have been called
            mock_verify.assert_not_called()

        # Sources should be unchanged
        assert len(state["synthesis_0"]["sources"]) == 2

    @pytest.mark.asyncio
    async def test_old_format_full_output_path(self, tmp_path):
        """Old-format config: format -> delivery produces valid HTML."""
        output_dir = str(tmp_path / "output")
        state = _make_old_format_state(output_dir)

        ctx = MagicMock()
        ctx.session.state = state

        # Link verifier (should no-op)
        verifier = LinkVerifierAgent(name="LinkVerifier")
        async for _ in verifier._run_async_impl(ctx):
            pass

        # Format
        formatter = FormatterAgent(name="FormatterAgent")
        async for _ in formatter._run_async_impl(ctx):
            pass

        html = state.get("newsletter_html", "")
        assert "Backward Compat Newsletter" in html
        assert "General Tech" in html
        # All source links should be preserved (no verification)
        assert "example.com/tech" in html
        assert "example.com/source2" in html

    @pytest.mark.asyncio
    async def test_old_format_delivery(self, tmp_path):
        """Old-format pipeline delivery produces valid file."""
        output_dir = str(tmp_path / "output")
        state = _make_old_format_state(output_dir)

        ctx = MagicMock()
        ctx.session.state = state

        # Full path
        verifier = LinkVerifierAgent(name="LinkVerifier")
        async for _ in verifier._run_async_impl(ctx):
            pass

        formatter = FormatterAgent(name="FormatterAgent")
        async for _ in formatter._run_async_impl(ctx):
            pass

        delivery = DeliveryAgent(name="DeliveryAgent")
        async for _ in delivery._run_async_impl(ctx):
            pass

        delivery_status = state.get("delivery_status", {})
        assert delivery_status["status"] == "dry_run"

        output_file = Path(delivery_status["output_file"])
        assert output_file.exists()

        content = output_file.read_text(encoding="utf-8")
        assert content.startswith("<!DOCTYPE html>")
        assert "Backward Compat Newsletter" in content
        # All links preserved
        assert "example.com/tech" in content
        assert "example.com/source2" in content

    @pytest.mark.asyncio
    async def test_session_state_no_timeframe_keys(self, old_config_file):
        """ConfigLoaderAgent with old config sets timeframes to None."""
        config_path, _ = old_config_file
        config = load_config(config_path)

        agent = ConfigLoaderAgent(name="ConfigLoader", config=config)
        ctx = MagicMock()
        ctx.session.state = {}
        async for _ in agent._run_async_impl(ctx):
            pass

        state = ctx.session.state
        assert state["config_timeframes"] is None
        assert state["config_verify_links"] is False
