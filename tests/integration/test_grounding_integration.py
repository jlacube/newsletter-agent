"""Integration tests for grounding metadata extraction pipeline.

IT-001: End-to-end pipeline run with Google search produces SOURCES from grounding metadata.
IT-002: Pipeline run with both Google and Perplexity produces correct sources for each.
IT-003: Pipeline run with link verification correctly verifies grounding chunk URLs.

Spec refs: specs/004-grounding-metadata-extraction.spec.md Section 11.3.
"""

import json
import pytest
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

from newsletter_agent.agent import build_research_phase
from newsletter_agent.config.schema import (
    AppSettings,
    NewsletterConfig,
    NewsletterSettings,
    TopicConfig,
)
from newsletter_agent.tools.deep_research import DeepResearchOrchestrator
from newsletter_agent.tools.link_verifier import LinkCheckResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(state=None):
    ctx = MagicMock()
    ctx.session.state = state if state is not None else {}
    return ctx


def _grounding_raw(chunks, supports=None, queries=None):
    """Build raw grounding dict as the callback would produce."""
    return {
        "grounding_chunks": [
            {"web": {"uri": c[0], "title": c[1]}} for c in chunks
        ],
        "grounding_supports": supports or [],
        "web_search_queries": queries or ["test query"],
    }


def _research_text(urls, summary="Findings"):
    """Build SUMMARY/SOURCES text output."""
    sources = "\n".join(f"- [{t}]({u})" for t, u in urls)
    return f"SUMMARY:\n{summary}\n\nSOURCES:\n{sources}"


def _planning_result(query="AI deep dive", aspects=None):
    if aspects is None:
        aspects = ["developments", "opinions", "data"]
    return (query, aspects, [])


def _analysis_result(saturated=False, gaps=None, next_query=None, summary="Findings"):
    if gaps is None:
        gaps = ["gap1"] if not saturated else []
    return (
        {
            "findings_summary": summary,
            "knowledge_gaps": gaps,
            "coverage_assessment": "partial" if not saturated else "comprehensive",
            "saturated": saturated,
            "next_query": next_query or ("" if saturated else "follow-up"),
            "next_query_rationale": "continuing",
        },
        [],
    )


def _config_single_google(tmp_path, max_rounds=1, verify_links=False):
    """Config with a single-topic Google-only setup."""
    return NewsletterConfig(
        newsletter=NewsletterSettings(
            title="Grounding Integration Test",
            schedule="0 8 * * 0",
            recipient_email="test@example.com",
        ),
        settings=AppSettings(
            dry_run=True,
            output_dir=str(tmp_path),
            max_research_rounds=max_rounds,
            min_research_rounds=max_rounds,
            verify_links=verify_links,
        ),
        topics=[
            TopicConfig(
                name="AI News",
                query="latest AI news 2026",
                search_depth="deep",
                sources=["google_search"],
            ),
        ],
    )


def _config_dual_provider(tmp_path, max_rounds=1):
    """Config with a single topic using both Google and Perplexity."""
    return NewsletterConfig(
        newsletter=NewsletterSettings(
            title="Dual Provider Integration Test",
            schedule="0 8 * * 0",
            recipient_email="test@example.com",
        ),
        settings=AppSettings(
            dry_run=True,
            output_dir=str(tmp_path),
            max_research_rounds=max_rounds,
            min_research_rounds=max_rounds,
        ),
        topics=[
            TopicConfig(
                name="AI News",
                query="latest AI news 2026",
                search_depth="deep",
                sources=["google_search", "perplexity"],
            ),
        ],
    )


# ---------------------------------------------------------------------------
# IT-001: End-to-end Google pipeline produces SOURCES from grounding metadata
# ---------------------------------------------------------------------------


class TestIT001GoogleGroundingSources:
    """IT-001: End-to-end pipeline run with Google search produces SOURCES
    from grounding metadata (verify by checking state keys after research phase)."""

    @pytest.mark.asyncio
    async def test_google_pipeline_uses_grounding_sources(self, tmp_path):
        """Google orchestrator with grounding metadata produces SOURCES
        built from grounding chunks, not regex extraction."""
        config = _config_single_google(tmp_path, max_rounds=1)
        phase = build_research_phase(config)

        topic0 = phase.sub_agents[0]
        orch = topic0.sub_agents[0]
        assert isinstance(orch, DeepResearchOrchestrator)
        assert orch.provider == "google"

        ctx = _make_ctx()

        # Grounding metadata has 4 sources
        grounding_chunks = [
            ("https://arxiv.org/abs/2026.001", "Transformer Advances 2026"),
            ("https://blog.openai.com/gpt5", "GPT-5 Technical Report"),
            ("https://deepmind.com/research/gemini3", "Gemini 3 Architecture"),
            ("https://nature.com/articles/ai-safety", "AI Safety Perspectives"),
        ]
        raw = _grounding_raw(grounding_chunks)

        # LLM text has different (fewer) URLs - would be used by regex fallback
        llm_text = _research_text(
            [("Old Source", "https://old-source.com/article")],
            "Round 0 findings about AI in 2026",
        )

        def make_mock_agent(round_idx, query):
            agent = MagicMock()

            async def fake_run(run_ctx):
                run_ctx.session.state[f"deep_research_latest_{orch.topic_idx}_{orch.provider}"] = llm_text
                run_ctx.session.state[f"_grounding_raw_{orch.topic_idx}_{orch.provider}_round_{round_idx}"] = raw
                return
                yield

            agent.run_async = fake_run
            return agent

        with patch.object(orch, "_make_search_agent", side_effect=make_mock_agent):
            async for _ in orch._run_async_impl(ctx):
                pass

        state = ctx.session.state
        merged = state[f"research_{orch.topic_idx}_{orch.provider}"]

        # SOURCES section should contain all 4 grounding URIs
        sources_section = merged.split("SOURCES:")[1]
        for uri, title in grounding_chunks:
            assert uri in sources_section, f"Grounding URI missing from SOURCES: {uri}"
            assert title in sources_section, f"Grounding title missing from SOURCES: {title}"

        # The old LLM-only URL should NOT appear in SOURCES
        # (grounding merge replaces regex extraction for Google)
        assert "https://old-source.com/article" not in sources_section

        # Intermediate grounding state keys should be cleaned up
        for key in state:
            assert not key.startswith("_grounding_raw_"), f"Raw grounding key not cleaned: {key}"
            assert not key.startswith("grounding_sources_"), f"Grounding sources key not cleaned: {key}"

    @pytest.mark.asyncio
    async def test_google_multiround_grounding_merge(self, tmp_path):
        """Multi-round Google pipeline merges grounding sources across rounds,
        deduplicating by URI with first-title-wins semantics."""
        config = _config_single_google(tmp_path, max_rounds=3)
        phase = build_research_phase(config)
        orch = phase.sub_agents[0].sub_agents[0]
        assert orch.provider == "google"

        ctx = _make_ctx()

        # 3 rounds of grounding data with some overlap
        rounds_data = [
            {
                "text": _research_text([("A", "https://a.com")], "Round 0"),
                "grounding": _grounding_raw([
                    ("https://arxiv.org/001", "Paper 1"),
                    ("https://arxiv.org/002", "Paper 2"),
                    ("https://arxiv.org/003", "Paper 3"),
                ]),
            },
            {
                "text": _research_text([("B", "https://b.com")], "Round 1"),
                "grounding": _grounding_raw([
                    ("https://arxiv.org/002", "Paper 2 (round 1)"),  # dup
                    ("https://arxiv.org/004", "Paper 4"),
                ]),
            },
            {
                "text": _research_text([("C", "https://c.com")], "Round 2"),
                "grounding": _grounding_raw([
                    ("https://arxiv.org/005", "Paper 5"),
                ]),
            },
        ]

        call_count = [0]

        async def mock_planning(inner_ctx):
            return _planning_result()

        analysis_responses = [
            _analysis_result(saturated=False, next_query="q1", gaps=["gap"]),
            _analysis_result(saturated=False, next_query="q2", gaps=["gap"]),
            _analysis_result(saturated=True, gaps=[]),
        ]
        analysis_idx = [0]

        async def mock_analysis(*args, **kwargs):
            idx = analysis_idx[0]
            analysis_idx[0] += 1
            return analysis_responses[min(idx, len(analysis_responses) - 1)]

        def make_mock_agent(round_idx, query):
            agent = MagicMock()

            async def fake_run(run_ctx):
                rd = rounds_data[call_count[0]]
                key = f"deep_research_latest_{orch.topic_idx}_{orch.provider}"
                run_ctx.session.state[key] = rd["text"]
                gkey = f"_grounding_raw_{orch.topic_idx}_{orch.provider}_round_{round_idx}"
                run_ctx.session.state[gkey] = rd["grounding"]
                call_count[0] += 1
                return
                yield

            agent.run_async = fake_run
            return agent

        with patch.object(orch, "_run_planning", side_effect=mock_planning), \
             patch.object(orch, "_run_analysis", side_effect=mock_analysis), \
             patch.object(orch, "_make_search_agent", side_effect=make_mock_agent):
            async for _ in orch._run_async_impl(ctx):
                pass

        merged = ctx.session.state[f"research_{orch.topic_idx}_{orch.provider}"]
        sources_section = merged.split("SOURCES:")[1]

        # All 5 unique URIs should be present
        for i in range(1, 6):
            assert f"https://arxiv.org/00{i}" in sources_section

        # First title wins for duplicate (Paper 2, not Paper 2 (round 1))
        assert "Paper 2]" in sources_section
        assert "Paper 2 (round 1)" not in sources_section

        # Intermediate keys cleaned up
        assert not any(k.startswith("grounding_sources_") for k in ctx.session.state)


# ---------------------------------------------------------------------------
# IT-002: Dual provider (Google + Perplexity) correct source extraction
# ---------------------------------------------------------------------------


class TestIT002DualProviderSources:
    """IT-002: Pipeline run with both Google and Perplexity providers produces
    correct sources for each (Google from metadata, Perplexity from text)."""

    @pytest.mark.asyncio
    async def test_google_uses_grounding_perplexity_uses_regex(self, tmp_path):
        """When both providers run, Google SOURCES come from grounding metadata
        while Perplexity SOURCES come from regex text extraction."""
        config = _config_dual_provider(tmp_path, max_rounds=1)
        phase = build_research_phase(config)
        topic0 = phase.sub_agents[0]

        google_orch = topic0.sub_agents[0]
        perplexity_orch = topic0.sub_agents[1]
        assert google_orch.provider == "google"
        assert perplexity_orch.provider == "perplexity"

        ctx = _make_ctx()

        # Google: grounding metadata has specific URIs
        google_grounding = _grounding_raw([
            ("https://google-grounding.com/1", "Google Source 1"),
            ("https://google-grounding.com/2", "Google Source 2"),
        ])
        google_llm_text = _research_text(
            [("LLM Only", "https://llm-only.com")],
            "Google round findings",
        )

        # Perplexity: only LLM text (no grounding)
        perplexity_text = _research_text(
            [("Perp Source 1", "https://perplexity.com/1"),
             ("Perp Source 2", "https://perplexity.com/2"),
             ("Perp Source 3", "https://perplexity.com/3")],
            "Perplexity findings",
        )

        def make_google_agent(round_idx, query):
            agent = MagicMock()

            async def fake_run(run_ctx):
                run_ctx.session.state[f"deep_research_latest_{google_orch.topic_idx}_{google_orch.provider}"] = google_llm_text
                run_ctx.session.state[f"_grounding_raw_{google_orch.topic_idx}_{google_orch.provider}_round_{round_idx}"] = google_grounding
                return
                yield

            agent.run_async = fake_run
            return agent

        def make_perplexity_agent(round_idx, query):
            agent = MagicMock()

            async def fake_run(run_ctx):
                run_ctx.session.state[f"deep_research_latest_{perplexity_orch.topic_idx}_{perplexity_orch.provider}"] = perplexity_text
                return
                yield

            agent.run_async = fake_run
            return agent

        # Run Google orchestrator
        with patch.object(google_orch, "_make_search_agent", side_effect=make_google_agent):
            async for _ in google_orch._run_async_impl(ctx):
                pass

        # Run Perplexity orchestrator
        with patch.object(perplexity_orch, "_make_search_agent", side_effect=make_perplexity_agent):
            async for _ in perplexity_orch._run_async_impl(ctx):
                pass

        state = ctx.session.state

        # Google: SOURCES from grounding metadata, not LLM text
        google_merged = state[f"research_{google_orch.topic_idx}_{google_orch.provider}"]
        google_sources = google_merged.split("SOURCES:")[1]
        assert "https://google-grounding.com/1" in google_sources
        assert "https://google-grounding.com/2" in google_sources
        assert "https://llm-only.com" not in google_sources

        # Perplexity: SOURCES from regex (no grounding attempted)
        perplexity_merged = state[f"research_{perplexity_orch.topic_idx}_{perplexity_orch.provider}"]
        perplexity_sources = perplexity_merged.split("SOURCES:")[1]
        assert "https://perplexity.com/1" in perplexity_sources
        assert "https://perplexity.com/2" in perplexity_sources
        assert "https://perplexity.com/3" in perplexity_sources


# ---------------------------------------------------------------------------
# IT-003: Link verification with grounding URLs
# ---------------------------------------------------------------------------


class TestIT003LinkVerificationGrounding:
    """IT-003: Pipeline run with link verification enabled correctly verifies
    grounding chunk URLs and removes broken ones."""

    @pytest.mark.asyncio
    async def test_link_verification_filters_broken_grounding_urls(self, tmp_path):
        """When link verification is enabled, broken grounding URLs are removed
        from the final merged SOURCES section."""
        config = _config_single_google(tmp_path, max_rounds=1, verify_links=True)
        phase = build_research_phase(config)
        orch = phase.sub_agents[0].sub_agents[0]
        assert orch.provider == "google"

        ctx = _make_ctx({"config_verify_links": True})

        # 4 grounding URLs, 1 broken
        grounding = _grounding_raw([
            ("https://valid1.com/article", "Valid Article 1"),
            ("https://valid2.com/article", "Valid Article 2"),
            ("https://broken.com/dead-link", "Dead Link Article"),
            ("https://valid3.com/article", "Valid Article 3"),
        ])

        llm_text = _research_text(
            [("LLM", "https://llm-only.com")],
            "Research findings with some broken links",
        )

        check_results = {
            "https://valid1.com/article": LinkCheckResult(
                url="https://valid1.com/article", status="valid",
            ),
            "https://valid2.com/article": LinkCheckResult(
                url="https://valid2.com/article", status="valid",
            ),
            "https://broken.com/dead-link": LinkCheckResult(
                url="https://broken.com/dead-link", status="broken", error="404 Not Found",
            ),
            "https://valid3.com/article": LinkCheckResult(
                url="https://valid3.com/article", status="valid",
            ),
        }

        def make_mock_agent(round_idx, query):
            agent = MagicMock()

            async def fake_run(run_ctx):
                run_ctx.session.state[f"deep_research_latest_{orch.topic_idx}_{orch.provider}"] = llm_text
                run_ctx.session.state[f"_grounding_raw_{orch.topic_idx}_{orch.provider}_round_{round_idx}"] = grounding
                return
                yield

            agent.run_async = fake_run
            return agent

        with patch.object(orch, "_make_search_agent", side_effect=make_mock_agent), \
             patch("newsletter_agent.tools.deep_research.verify_urls",
                   new_callable=AsyncMock, return_value=check_results):
            async for _ in orch._run_async_impl(ctx):
                pass

        merged = ctx.session.state[f"research_{orch.topic_idx}_{orch.provider}"]
        sources_section = merged.split("SOURCES:")[1]

        # Valid URLs present
        assert "https://valid1.com/article" in sources_section
        assert "https://valid2.com/article" in sources_section
        assert "https://valid3.com/article" in sources_section

        # Broken URL removed
        assert "https://broken.com/dead-link" not in sources_section

        # LLM-only URL not present (grounding replaces regex for Google)
        assert "https://llm-only.com" not in sources_section

    @pytest.mark.asyncio
    async def test_verification_uses_grounding_urls_not_regex(self, tmp_path):
        """verify_urls is called with grounding chunk URLs, not regex-extracted URLs."""
        config = _config_single_google(tmp_path, max_rounds=1, verify_links=True)
        phase = build_research_phase(config)
        orch = phase.sub_agents[0].sub_agents[0]

        ctx = _make_ctx({"config_verify_links": True})

        grounding = _grounding_raw([
            ("https://grounding1.com/a", "G1"),
            ("https://grounding2.com/b", "G2"),
        ])
        llm_text = _research_text(
            [("Regex Source", "https://regex-only.com/x")],
            "LLM output",
        )

        all_valid = {
            "https://grounding1.com/a": LinkCheckResult(url="https://grounding1.com/a", status="valid"),
            "https://grounding2.com/b": LinkCheckResult(url="https://grounding2.com/b", status="valid"),
        }

        def make_mock_agent(round_idx, query):
            agent = MagicMock()

            async def fake_run(run_ctx):
                run_ctx.session.state[f"deep_research_latest_{orch.topic_idx}_{orch.provider}"] = llm_text
                run_ctx.session.state[f"_grounding_raw_{orch.topic_idx}_{orch.provider}_round_{round_idx}"] = grounding
                return
                yield

            agent.run_async = fake_run
            return agent

        with patch.object(orch, "_make_search_agent", side_effect=make_mock_agent), \
             patch("newsletter_agent.tools.deep_research.verify_urls",
                   new_callable=AsyncMock, return_value=all_valid) as mock_verify:
            async for _ in orch._run_async_impl(ctx):
                pass

        # verify_urls was called with grounding URLs, not regex URLs
        call_args = mock_verify.call_args[0][0]
        assert "https://grounding1.com/a" in call_args
        assert "https://grounding2.com/b" in call_args
        assert "https://regex-only.com/x" not in call_args
