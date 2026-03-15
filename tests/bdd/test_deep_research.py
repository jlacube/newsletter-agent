"""
BDD-style acceptance tests for multi-round deep research.

Uses Given/When/Then structure to verify spec Section 11.2 scenarios.
Spec refs: Section 11.2 Feature: Multi-Round Deep Research, US-02.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from newsletter_agent.tools.deep_research import DeepResearchOrchestrator
from newsletter_agent.agent import build_research_phase
from newsletter_agent.config.schema import (
    AppSettings,
    NewsletterConfig,
    NewsletterSettings,
    TopicConfig,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(topics_data, max_research_rounds=3):
    topics = [
        TopicConfig(
            name=t.get("name", f"Topic {i}"),
            query=t.get("query", f"Query {i}"),
            search_depth=t.get("search_depth", "standard"),
            sources=t.get("sources", ["google_search", "perplexity"]),
        )
        for i, t in enumerate(topics_data)
    ]
    return NewsletterConfig(
        newsletter=NewsletterSettings(
            title="Test Newsletter",
            schedule="0 0 * * 0",
            recipient_email="test@example.com",
        ),
        settings=AppSettings(max_research_rounds=max_research_rounds),
        topics=topics,
    )


def _make_ctx(state=None):
    ctx = MagicMock()
    ctx.session.state = state if state is not None else {}
    return ctx


def _research_text(urls, summary="Some findings"):
    sources = "\n".join(f"- [{t}]({u})" for t, u in urls)
    return f"SUMMARY:\n{summary}\n\nSOURCES:\n{sources}"


# ---------------------------------------------------------------------------
# Feature: Multi-Round Deep Research
#
# Scenario: Deep mode executes multiple research rounds
#
#   Given a topic with search_depth "deep"
#   And max_research_rounds is 3
#   When the research phase runs
#   Then 3 search rounds are executed per provider
#   And each round uses a different query angle
#   And results are combined into the standard research state key
# ---------------------------------------------------------------------------


class TestDeepModeExecutesMultipleRounds:
    """BDD Scenario: Deep mode executes multiple research rounds."""

    def test_given_deep_topic_when_built_then_orchestrator_created(self):
        """Given a topic with search_depth 'deep' and max_research_rounds 3,
        When the research pipeline is built,
        Then a DeepResearchOrchestrator is created per provider."""
        config = _make_config(
            [{"name": "AI", "query": "AI news", "search_depth": "deep"}],
            max_research_rounds=3,
        )
        phase = build_research_phase(config)
        topic_agent = phase.sub_agents[0]

        for sub in topic_agent.sub_agents:
            assert isinstance(sub, DeepResearchOrchestrator)
            assert sub.max_rounds == 3

    @pytest.mark.asyncio
    async def test_given_deep_3_rounds_when_runs_then_3_rounds_executed(self):
        """Given a topic with search_depth 'deep' and max_research_rounds 3,
        When the orchestrator runs,
        Then 3 search rounds are executed."""
        orch = DeepResearchOrchestrator(
            name="DeepResearch_0_google",
            topic_idx=0,
            provider="google",
            query="AI trends",
            topic_name="AI",
            max_rounds=3,
            search_depth="deep",
            model="gemini-2.5-flash",
            tools=[],
        )
        ctx = _make_ctx()
        rounds_content = [
            _research_text([(f"S{i}", f"https://r{r}.com") for i in range(3)], f"Round {r}")
            for r in range(3)
        ]
        call_count = [0]

        with patch.object(orch, "_expand_queries", new_callable=AsyncMock) as mock_expand, \
             patch.object(orch, "_make_search_agent") as mock_make:

            mock_expand.return_value = (["AI expert opinions", "AI data analytics"], [])

            mock_agent = MagicMock()

            async def fake_run(run_ctx):
                idx = call_count[0]
                run_ctx.session.state["deep_research_latest_0_google"] = rounds_content[idx]
                call_count[0] += 1
                return
                yield

            mock_agent.run_async = fake_run
            mock_make.return_value = mock_agent

            async for _ in orch._run_async_impl(ctx):
                pass

        # Then 3 search rounds are executed
        assert call_count[0] == 3

    @pytest.mark.asyncio
    async def test_given_deep_3_rounds_when_runs_then_each_round_different_query(self):
        """Given a deep-mode topic, when the orchestrator runs,
        Then each round uses a different query angle."""
        orch = DeepResearchOrchestrator(
            name="DeepResearch_0_google",
            topic_idx=0,
            provider="google",
            query="AI trends",
            topic_name="AI",
            max_rounds=3,
            search_depth="deep",
            model="gemini-2.5-flash",
            tools=[],
        )
        ctx = _make_ctx()
        captured_queries = []

        with patch.object(orch, "_expand_queries", new_callable=AsyncMock) as mock_expand, \
             patch.object(orch, "_make_search_agent") as mock_make:

            mock_expand.return_value = (["AI expert opinions", "AI data analytics"], [])

            def capture_make(round_idx, query):
                captured_queries.append(query)
                mock_agent = MagicMock()

                async def fake_run(run_ctx):
                    run_ctx.session.state["deep_research_latest_0_google"] = _research_text(
                        [("S", "https://example.com")], "text"
                    )
                    return
                    yield

                mock_agent.run_async = fake_run
                return mock_agent

            mock_make.side_effect = capture_make

            async for _ in orch._run_async_impl(ctx):
                pass

        # Then each round uses a different query angle
        assert len(captured_queries) == 3
        assert captured_queries[0] == "AI trends"  # original
        assert captured_queries[1] == "AI expert opinions"  # variant 1
        assert captured_queries[2] == "AI data analytics"  # variant 2
        assert len(set(captured_queries)) == 3  # all unique

    @pytest.mark.asyncio
    async def test_given_deep_3_rounds_when_runs_then_results_combined(self):
        """Given a deep-mode topic, when all rounds complete,
        Then results are combined into the standard research state key."""
        orch = DeepResearchOrchestrator(
            name="DeepResearch_0_google",
            topic_idx=0,
            provider="google",
            query="AI trends",
            topic_name="AI",
            max_rounds=3,
            search_depth="deep",
            model="gemini-2.5-flash",
            tools=[],
        )
        ctx = _make_ctx()
        rounds_content = [
            _research_text([(f"R{r}S{i}", f"https://r{r}s{i}.com") for i in range(2)], f"Round {r}")
            for r in range(3)
        ]
        call_count = [0]

        with patch.object(orch, "_expand_queries", new_callable=AsyncMock) as mock_expand, \
             patch.object(orch, "_make_search_agent") as mock_make:

            mock_expand.return_value = (["v1", "v2"], [])
            mock_agent = MagicMock()

            async def fake_run(run_ctx):
                idx = call_count[0]
                run_ctx.session.state["deep_research_latest_0_google"] = rounds_content[idx]
                call_count[0] += 1
                return
                yield

            mock_agent.run_async = fake_run
            mock_make.return_value = mock_agent

            async for _ in orch._run_async_impl(ctx):
                pass

        # Then results are combined into the standard research state key
        merged = ctx.session.state.get("research_0_google", "")
        assert "SUMMARY:" in merged
        assert "SOURCES:" in merged
        assert "Round 0" in merged
        assert "Round 1" in merged
        assert "Round 2" in merged
        # Sources from all rounds present
        assert "https://r0s0.com" in merged
        assert "https://r1s0.com" in merged
        assert "https://r2s0.com" in merged


# ---------------------------------------------------------------------------
# Feature: Multi-Round Deep Research
#
# Scenario: Early exit when enough URLs collected
#
#   Given a topic with search_depth "deep"
#   And max_research_rounds is 3
#   And round 2 accumulates 15+ unique URLs
#   When the research phase runs
#   Then only 2 search rounds execute
#   And the loop exits early via escalation
# ---------------------------------------------------------------------------


class TestEarlyExitWhenEnoughURLs:
    """BDD Scenario: Early exit when enough URLs collected."""

    @pytest.mark.asyncio
    async def test_given_15_urls_at_round_2_when_runs_then_only_2_rounds(self):
        """Given a deep topic with max_research_rounds 3,
        And round 2 (index 1) accumulates 15+ unique URLs,
        When the orchestrator runs,
        Then only 2 search rounds execute."""
        orch = DeepResearchOrchestrator(
            name="DeepResearch_0_google",
            topic_idx=0,
            provider="google",
            query="AI news",
            topic_name="AI",
            max_rounds=3,
            search_depth="deep",
            model="gemini-2.5-flash",
            tools=[],
        )
        ctx = _make_ctx()

        # Round 0: 8 unique URLs
        round0_urls = [(f"S{i}", f"https://round0-{i}.com") for i in range(8)]
        # Round 1: 8 new unique URLs -> total 16 >= 15 threshold
        round1_urls = [(f"S{i}", f"https://round1-{i}.com") for i in range(8)]
        # Round 2: should never execute
        round2_urls = [(f"S{i}", f"https://round2-{i}.com") for i in range(5)]

        rounds_content = [
            _research_text(round0_urls, "Round 0"),
            _research_text(round1_urls, "Round 1"),
            _research_text(round2_urls, "Round 2 - should not run"),
        ]
        call_count = [0]

        with patch.object(orch, "_expand_queries", new_callable=AsyncMock) as mock_expand, \
             patch.object(orch, "_make_search_agent") as mock_make:

            mock_expand.return_value = (["v1", "v2"], [])
            mock_agent = MagicMock()

            async def fake_run(run_ctx):
                idx = call_count[0]
                run_ctx.session.state["deep_research_latest_0_google"] = rounds_content[idx]
                call_count[0] += 1
                return
                yield

            mock_agent.run_async = fake_run
            mock_make.return_value = mock_agent

            events = []
            async for event in orch._run_async_impl(ctx):
                events.append(event)

        # Then only 2 search rounds execute (round 0 and round 1)
        assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_given_early_exit_then_results_still_merged(self):
        """When early exit occurs, the completed rounds are still merged
        into the standard state key."""
        orch = DeepResearchOrchestrator(
            name="DeepResearch_0_google",
            topic_idx=0,
            provider="google",
            query="AI news",
            topic_name="AI",
            max_rounds=3,
            search_depth="deep",
            model="gemini-2.5-flash",
            tools=[],
        )
        ctx = _make_ctx()

        round0_urls = [(f"S{i}", f"https://round0-{i}.com") for i in range(8)]
        round1_urls = [(f"S{i}", f"https://round1-{i}.com") for i in range(8)]

        rounds_content = [
            _research_text(round0_urls, "Round 0 findings"),
            _research_text(round1_urls, "Round 1 findings"),
        ]
        call_count = [0]

        with patch.object(orch, "_expand_queries", new_callable=AsyncMock) as mock_expand, \
             patch.object(orch, "_make_search_agent") as mock_make:

            mock_expand.return_value = (["v1", "v2"], [])
            mock_agent = MagicMock()

            async def fake_run(run_ctx):
                idx = call_count[0]
                run_ctx.session.state["deep_research_latest_0_google"] = rounds_content[idx]
                call_count[0] += 1
                return
                yield

            mock_agent.run_async = fake_run
            mock_make.return_value = mock_agent

            async for _ in orch._run_async_impl(ctx):
                pass

        # Results from completed rounds are merged
        merged = ctx.session.state.get("research_0_google", "")
        assert "Round 0 findings" in merged
        assert "Round 1 findings" in merged
        assert "round0-0.com" in merged
        assert "round1-0.com" in merged


# ---------------------------------------------------------------------------
# Feature: Multi-Round Deep Research
#
# Scenario: Standard mode is unaffected
#
#   Given a topic with search_depth "standard"
#   And max_research_rounds is 3
#   When the research phase runs
#   Then exactly 1 search round executes per provider
#   And no query expansion occurs
# ---------------------------------------------------------------------------


class TestStandardModeUnaffected:
    """BDD Scenario: Standard mode is unaffected."""

    def test_given_standard_topic_when_built_then_llm_agent_created(self):
        """Given a topic with search_depth 'standard' and max_research_rounds 3,
        When the research pipeline is built,
        Then a standard LlmAgent is created per provider (not DeepResearchOrchestrator)."""
        from google.adk.agents import LlmAgent

        config = _make_config(
            [{"name": "AI", "query": "AI news", "search_depth": "standard"}],
            max_research_rounds=3,
        )
        phase = build_research_phase(config)
        topic_agent = phase.sub_agents[0]

        # Standard mode uses LlmAgent, not DeepResearchOrchestrator
        for sub in topic_agent.sub_agents:
            assert isinstance(sub, LlmAgent)
            assert not isinstance(sub, DeepResearchOrchestrator)

    def test_given_standard_topic_then_no_deep_orchestrator_in_tree(self):
        """Given a standard topic, the agent tree contains no DeepResearchOrchestrator."""
        config = _make_config(
            [
                {"name": "Cloud", "query": "cloud computing", "search_depth": "standard"},
                {"name": "Security", "query": "cybersecurity", "search_depth": "standard"},
            ],
            max_research_rounds=3,
        )
        phase = build_research_phase(config)

        for topic_agent in phase.sub_agents:
            for sub in topic_agent.sub_agents:
                assert not isinstance(sub, DeepResearchOrchestrator)

    def test_given_standard_topic_then_single_output_key_per_provider(self):
        """Standard-mode topics produce a single output_key per provider
        (no round-specific keys, no query expansion)."""
        from google.adk.agents import LlmAgent

        config = _make_config(
            [{"name": "AI", "query": "AI news", "search_depth": "standard",
              "sources": ["google_search", "perplexity"]}],
            max_research_rounds=3,
        )
        phase = build_research_phase(config)
        topic_agent = phase.sub_agents[0]

        google_agent = topic_agent.sub_agents[0]
        perplexity_agent = topic_agent.sub_agents[1]

        assert isinstance(google_agent, LlmAgent)
        assert isinstance(perplexity_agent, LlmAgent)
        assert google_agent.output_key == "research_0_google"
        assert perplexity_agent.output_key == "research_0_perplexity"


# ---------------------------------------------------------------------------
# Feature: Multi-Round Deep Research
#
# Scenario: max_research_rounds of 1 is single-round
#
#   Given a topic with search_depth "deep"
#   And max_research_rounds is 1
#   When the research phase runs
#   Then exactly 1 search round executes per provider
#   And no query expansion occurs
# ---------------------------------------------------------------------------


class TestMaxRounds1IsSingleRound:
    """BDD Scenario: max_research_rounds of 1 is single-round."""

    def test_given_deep_with_1_round_when_built_then_orchestrator_with_1_round(self):
        """Given a topic with search_depth 'deep' and max_research_rounds 1,
        When the research pipeline is built,
        Then a DeepResearchOrchestrator is created with max_rounds=1."""
        config = _make_config(
            [{"name": "AI", "query": "AI news", "search_depth": "deep"}],
            max_research_rounds=1,
        )
        phase = build_research_phase(config)
        topic_agent = phase.sub_agents[0]

        for sub in topic_agent.sub_agents:
            assert isinstance(sub, DeepResearchOrchestrator)
            assert sub.max_rounds == 1

    @pytest.mark.asyncio
    async def test_given_max_rounds_1_when_runs_then_exactly_1_round(self):
        """Given max_research_rounds 1, when the orchestrator runs,
        Then exactly 1 search round executes."""
        orch = DeepResearchOrchestrator(
            name="DeepResearch_0_google",
            topic_idx=0,
            provider="google",
            query="AI news",
            topic_name="AI",
            max_rounds=1,
            search_depth="deep",
            model="gemini-2.5-flash",
            tools=[],
        )
        ctx = _make_ctx()
        call_count = [0]

        with patch.object(orch, "_make_search_agent") as mock_make:
            mock_agent = MagicMock()

            async def fake_run(run_ctx):
                run_ctx.session.state["deep_research_latest_0_google"] = _research_text(
                    [("A", "https://a.com")], "Single round"
                )
                call_count[0] += 1
                return
                yield

            mock_agent.run_async = fake_run
            mock_make.return_value = mock_agent

            async for _ in orch._run_async_impl(ctx):
                pass

        # Then exactly 1 search round executes
        assert call_count[0] == 1

    @pytest.mark.asyncio
    async def test_given_max_rounds_1_when_runs_then_no_query_expansion(self):
        """Given max_research_rounds 1, when the orchestrator runs,
        Then no query expansion occurs (expansion is skipped)."""
        orch = DeepResearchOrchestrator(
            name="DeepResearch_0_google",
            topic_idx=0,
            provider="google",
            query="AI news",
            topic_name="AI",
            max_rounds=1,
            search_depth="deep",
            model="gemini-2.5-flash",
            tools=[],
        )
        ctx = _make_ctx()

        with patch.object(orch, "_expand_queries", new_callable=AsyncMock) as mock_expand, \
             patch.object(orch, "_make_search_agent") as mock_make:

            mock_agent = MagicMock()

            async def fake_run(run_ctx):
                run_ctx.session.state["deep_research_latest_0_google"] = _research_text(
                    [("A", "https://a.com")], "Single round"
                )
                return
                yield

            mock_agent.run_async = fake_run
            mock_make.return_value = mock_agent

            async for _ in orch._run_async_impl(ctx):
                pass

        # Then no query expansion occurs
        mock_expand.assert_not_called()

    @pytest.mark.asyncio
    async def test_given_max_rounds_1_when_runs_then_result_in_standard_key(self):
        """Given max_research_rounds 1, the result is written to the standard
        research state key (same as standard mode)."""
        orch = DeepResearchOrchestrator(
            name="DeepResearch_0_google",
            topic_idx=0,
            provider="google",
            query="AI news",
            topic_name="AI",
            max_rounds=1,
            search_depth="deep",
            model="gemini-2.5-flash",
            tools=[],
        )
        ctx = _make_ctx()

        with patch.object(orch, "_make_search_agent") as mock_make:
            mock_agent = MagicMock()

            async def fake_run(run_ctx):
                run_ctx.session.state["deep_research_latest_0_google"] = _research_text(
                    [("A", "https://a.com")], "Single round findings"
                )
                return
                yield

            mock_agent.run_async = fake_run
            mock_make.return_value = mock_agent

            async for _ in orch._run_async_impl(ctx):
                pass

        # Result is in the standard key
        assert "research_0_google" in ctx.session.state
        assert "Single round findings" in ctx.session.state["research_0_google"]
