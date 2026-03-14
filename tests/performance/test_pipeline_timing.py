"""Performance validation tests for the newsletter pipeline.

These tests verify that key operations meet timing requirements.
Marked with @pytest.mark.performance -- skipped in CI by default.
Run with: pytest -m performance

Spec refs: Section 10.1, Section 11.5.
"""

import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from newsletter_agent.agent import build_research_phase, build_synthesis_agent
from newsletter_agent.config.schema import (
    AppSettings,
    NewsletterConfig,
    NewsletterSettings,
    TopicConfig,
)
from newsletter_agent.tools.formatter import FormatterAgent, render_newsletter


def _make_config(n_topics: int) -> NewsletterConfig:
    topics = [
        TopicConfig(name=f"Topic {i}", query=f"Query about topic {i}")
        for i in range(n_topics)
    ]
    return NewsletterConfig(
        newsletter=NewsletterSettings(
            title="Perf Test",
            schedule="0 8 * * 0",
            recipient_email="test@example.com",
        ),
        settings=AppSettings(dry_run=True),
        topics=topics,
    )


def _make_state(n_topics: int) -> dict:
    state = {
        "config_newsletter_title": "Perf Test Newsletter",
        "config_dry_run": True,
        "config_output_dir": "output/",
        "pipeline_start_time": "2025-01-01T08:00:00+00:00",
        "executive_summary": [f"Summary point {i}" for i in range(n_topics)],
    }
    for i in range(n_topics):
        state[f"synthesis_{i}"] = {
            "title": f"Topic {i}",
            "body_markdown": f"## Topic {i}\n\nContent about topic {i}. " * 20,
            "sources": [
                {"url": f"https://example.com/src-{i}-{j}", "title": f"Source {j}"}
                for j in range(5)
            ],
        }
    return state


@pytest.mark.performance
class TestPipelineBuildPerformance:
    """Verify agent tree construction is fast."""

    def test_build_5_topics_under_1s(self):
        config = _make_config(5)
        start = time.monotonic()
        phase = build_research_phase(config)
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, f"5-topic build took {elapsed:.2f}s"
        assert len(phase.sub_agents) == 5

    def test_build_20_topics_under_2s(self):
        config = _make_config(20)
        start = time.monotonic()
        phase = build_research_phase(config)
        elapsed = time.monotonic() - start
        assert elapsed < 2.0, f"20-topic build took {elapsed:.2f}s"
        assert len(phase.sub_agents) == 20


@pytest.mark.performance
class TestHtmlRenderingPerformance:
    """Verify HTML rendering meets the 5-second requirement (Section 10.1)."""

    @pytest.mark.asyncio
    async def test_5_topics_render_under_5s(self):
        state = _make_state(5)
        ctx = MagicMock()
        ctx.session.state = state

        formatter = FormatterAgent(name="FormatterAgent")
        start = time.monotonic()
        async for _ in formatter._run_async_impl(ctx):
            pass
        elapsed = time.monotonic() - start

        assert elapsed < 5.0, f"5-topic render took {elapsed:.2f}s"
        assert "newsletter_html" in state

    @pytest.mark.asyncio
    async def test_20_topics_render_under_5s(self):
        state = _make_state(20)
        ctx = MagicMock()
        ctx.session.state = state

        formatter = FormatterAgent(name="FormatterAgent")
        start = time.monotonic()
        async for _ in formatter._run_async_impl(ctx):
            pass
        elapsed = time.monotonic() - start

        assert elapsed < 5.0, f"20-topic render took {elapsed:.2f}s"
        assert "newsletter_html" in state

    def test_template_render_alone_under_1s(self):
        """Pure template rendering should be well under 1 second."""
        template_data = {
            "newsletter_title": "Perf Test",
            "newsletter_date": "2025-01-01",
            "executive_summary": [f"Point {i}" for i in range(20)],
            "sections": [
                {
                    "title": f"Topic {i}",
                    "body_html": f"<p>Content {i}</p>" * 20,
                    "sources": [
                        {"url": f"https://example.com/{i}/{j}", "title": f"Src {j}"}
                        for j in range(5)
                    ],
                }
                for i in range(20)
            ],
            "all_sources": [
                {"url": f"https://example.com/all/{i}", "title": f"All {i}"}
                for i in range(100)
            ],
            "generation_time_seconds": 42.0,
        }
        start = time.monotonic()
        html = render_newsletter(template_data)
        elapsed = time.monotonic() - start

        assert elapsed < 1.0, f"Template render took {elapsed:.2f}s"
        assert len(html) > 0
