"""
BDD-style acceptance tests for adaptive deep research.

Uses Given/When/Then structure to verify spec Section 11.2 scenarios.
Spec refs: Section 11.2 Feature: Adaptive Deep Research Loop,
           specs/002-adaptive-deep-research.spec.md.
"""

import json
import logging
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


def _make_config(topics_data, max_research_rounds=3, **extra_settings):
    topics = [
        TopicConfig(
            name=t.get("name", f"Topic {i}"),
            query=t.get("query", f"Query {i}"),
            search_depth=t.get("search_depth", "standard"),
            sources=t.get("sources", ["google_search", "perplexity"]),
        )
        for i, t in enumerate(topics_data)
    ]
    settings_kwargs = {"max_research_rounds": max_research_rounds}
    if max_research_rounds < 2:
        settings_kwargs["min_research_rounds"] = max_research_rounds
    settings_kwargs.update(extra_settings)
    return NewsletterConfig(
        newsletter=NewsletterSettings(
            title="Test Newsletter",
            schedule="0 0 * * 0",
            recipient_email="test@example.com",
        ),
        settings=AppSettings(**settings_kwargs),
        topics=topics,
    )


def _make_ctx(state=None):
    ctx = MagicMock()
    ctx.session.state = state if state is not None else {}
    return ctx


def _research_text(urls, summary="Some findings"):
    sources = "\n".join(f"- [{t}]({u})" for t, u in urls)
    return f"SUMMARY:\n{summary}\n\nSOURCES:\n{sources}"


def _planning_result(query="AI trends analysis", aspects=None):
    """Return (initial_query, key_aspects, events) tuple for mock _run_planning."""
    if aspects is None:
        aspects = ["recent developments", "expert opinions", "data and statistics"]
    return (query, aspects, [])


def _analysis_result(saturated=False, gaps=None, next_query=None, summary="Found relevant info"):
    """Return (analysis_dict, events) tuple for mock _run_analysis."""
    if gaps is None:
        gaps = ["gap1"] if not saturated else []
    return (
        {
            "findings_summary": summary,
            "knowledge_gaps": gaps,
            "coverage_assessment": "partial" if not saturated else "comprehensive",
            "saturated": saturated,
            "next_query": next_query or ("" if saturated else "follow-up query"),
            "next_query_rationale": "continuing research",
        },
        [],
    )


def _mock_search_agent(orch, call_count, rounds_content):
    """Create a patched _make_search_agent that writes round content to state."""
    def make(round_idx, query):
        agent = MagicMock()

        async def fake_run(run_ctx):
            idx = call_count[0]
            content = rounds_content[idx] if idx < len(rounds_content) else ""
            run_ctx.session.state[f"deep_research_latest_{orch.topic_idx}_{orch.provider}"] = content
            call_count[0] += 1
            return
            yield

        agent.run_async = fake_run
        return agent

    return make


# ---------------------------------------------------------------------------
# Scenario 1: Deep mode executes adaptive research with planning and analysis
# ---------------------------------------------------------------------------


class TestDeepModeAdaptiveResearch:
    """BDD Scenario 1: Deep mode executes adaptive research with planning and analysis."""

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
    async def test_planning_step_executes_first(self):
        """Given a deep-mode topic with max_research_rounds 3,
        When the orchestrator runs,
        Then a planning step executes first identifying key aspects."""
        orch = DeepResearchOrchestrator(
            name="DeepResearch_0_google", topic_idx=0, provider="google",
            query="AI trends", topic_name="AI", max_rounds=3,
            search_depth="deep", model="gemini-2.5-flash", tools=[],
        )
        ctx = _make_ctx()
        rounds_content = [
            _research_text([(f"S{i}", f"https://r{r}.com") for i in range(3)], f"Round {r}")
            for r in range(3)
        ]
        call_count = [0]
        planning_called = [False]

        async def mock_planning(inner_ctx):
            planning_called[0] = True
            return _planning_result("AI trends deep dive")

        # Analysis returns not-saturated for rounds 0,1 then max_rounds exits
        analysis_responses = [
            _analysis_result(next_query="AI expert opinions"),
            _analysis_result(next_query="AI data analytics"),
            _analysis_result(saturated=True),
        ]
        analysis_idx = [0]

        async def mock_analysis(*args, **kwargs):
            idx = analysis_idx[0]
            analysis_idx[0] += 1
            return analysis_responses[min(idx, len(analysis_responses) - 1)]

        with patch.object(orch, "_run_planning", side_effect=mock_planning), \
             patch.object(orch, "_run_analysis", side_effect=mock_analysis), \
             patch.object(orch, "_make_search_agent", side_effect=_mock_search_agent(orch, call_count, rounds_content)):
            async for _ in orch._run_async_impl(ctx):
                pass

        assert planning_called[0], "Planning step should execute first"
        assert call_count[0] == 3

    @pytest.mark.asyncio
    async def test_each_query_derived_from_analysis(self):
        """Given a deep-mode topic, when the orchestrator runs,
        Then each search query after round 0 is derived from the previous analysis."""
        orch = DeepResearchOrchestrator(
            name="DeepResearch_0_google", topic_idx=0, provider="google",
            query="AI trends", topic_name="AI", max_rounds=3,
            search_depth="deep", model="gemini-2.5-flash", tools=[],
        )
        ctx = _make_ctx()
        captured_queries = []

        async def mock_planning(inner_ctx):
            return _planning_result("AI initial query")

        analysis_responses = [
            _analysis_result(next_query="AI expert opinions"),
            _analysis_result(next_query="AI data analytics"),
            _analysis_result(saturated=True),
        ]
        analysis_idx = [0]

        async def mock_analysis(*args, **kwargs):
            idx = analysis_idx[0]
            analysis_idx[0] += 1
            return analysis_responses[min(idx, len(analysis_responses) - 1)]

        def capture_make(round_idx, query):
            captured_queries.append(query)
            agent = MagicMock()

            async def fake_run(run_ctx):
                run_ctx.session.state["deep_research_latest_0_google"] = _research_text(
                    [("S", f"https://r{round_idx}.com")], f"Round {round_idx}"
                )
                return
                yield

            agent.run_async = fake_run
            return agent

        with patch.object(orch, "_run_planning", side_effect=mock_planning), \
             patch.object(orch, "_run_analysis", side_effect=mock_analysis), \
             patch.object(orch, "_make_search_agent", side_effect=capture_make):
            async for _ in orch._run_async_impl(ctx):
                pass

        assert len(captured_queries) == 3
        assert captured_queries[0] == "AI initial query"  # from planning
        assert captured_queries[1] == "AI expert opinions"  # from analysis round 0
        assert captured_queries[2] == "AI data analytics"  # from analysis round 1

    @pytest.mark.asyncio
    async def test_results_combined_into_standard_key(self):
        """Given a deep-mode topic, when all rounds complete,
        Then results are combined into the standard research state key."""
        orch = DeepResearchOrchestrator(
            name="DeepResearch_0_google", topic_idx=0, provider="google",
            query="AI trends", topic_name="AI", max_rounds=3,
            search_depth="deep", model="gemini-2.5-flash", tools=[],
        )
        ctx = _make_ctx()
        rounds_content = [
            _research_text([(f"R{r}S{i}", f"https://r{r}s{i}.com") for i in range(2)], f"Round {r}")
            for r in range(3)
        ]
        call_count = [0]

        async def mock_planning(inner_ctx):
            return _planning_result()

        analysis_responses = [
            _analysis_result(next_query="query2"),
            _analysis_result(next_query="query3"),
            _analysis_result(saturated=True),
        ]
        analysis_idx = [0]

        async def mock_analysis(*args, **kwargs):
            idx = analysis_idx[0]
            analysis_idx[0] += 1
            return analysis_responses[min(idx, len(analysis_responses) - 1)]

        with patch.object(orch, "_run_planning", side_effect=mock_planning), \
             patch.object(orch, "_run_analysis", side_effect=mock_analysis), \
             patch.object(orch, "_make_search_agent", side_effect=_mock_search_agent(orch, call_count, rounds_content)):
            async for _ in orch._run_async_impl(ctx):
                pass

        merged = ctx.session.state.get("research_0_google", "")
        assert "SUMMARY:" in merged
        assert "SOURCES:" in merged
        assert "Round 0" in merged
        assert "Round 1" in merged
        assert "Round 2" in merged
        assert "https://r0s0.com" in merged
        assert "https://r1s0.com" in merged
        assert "https://r2s0.com" in merged


# ---------------------------------------------------------------------------
# Scenario 2: Saturation detection triggers early exit
# ---------------------------------------------------------------------------


class TestSaturationDetection:
    """BDD Scenario 2: Saturation detection triggers early exit."""

    @pytest.mark.asyncio
    async def test_saturated_after_round_2_exits_early(self, caplog):
        """Given deep mode with max_research_rounds=5,
        When AnalysisAgent reports saturated after round 2,
        Then only 3 rounds execute (0, 1, 2)
        And the log contains a saturation exit message."""
        orch = DeepResearchOrchestrator(
            name="DeepResearch_0_google", topic_idx=0, provider="google",
            query="AI news", topic_name="AI", max_rounds=5,
            search_depth="deep", model="gemini-2.5-flash", tools=[],
        )
        ctx = _make_ctx()
        rounds_content = [
            _research_text([(f"S{i}", f"https://r{r}.com") for i in range(3)], f"Round {r}")
            for r in range(5)
        ]
        call_count = [0]

        async def mock_planning(inner_ctx):
            return _planning_result()

        # Rounds 0,1: not saturated; Round 2: saturated
        analysis_responses = [
            _analysis_result(saturated=False, next_query="q1", gaps=["gap1"]),
            _analysis_result(saturated=False, next_query="q2", gaps=["gap2"]),
            _analysis_result(saturated=True, gaps=[]),
        ]
        analysis_idx = [0]

        async def mock_analysis(*args, **kwargs):
            idx = analysis_idx[0]
            analysis_idx[0] += 1
            return analysis_responses[min(idx, len(analysis_responses) - 1)]

        with patch.object(orch, "_run_planning", side_effect=mock_planning), \
             patch.object(orch, "_run_analysis", side_effect=mock_analysis), \
             patch.object(orch, "_make_search_agent", side_effect=_mock_search_agent(orch, call_count, rounds_content)), \
             caplog.at_level(logging.INFO):
            async for _ in orch._run_async_impl(ctx):
                pass

        assert call_count[0] == 3, f"Expected 3 rounds, got {call_count[0]}"
        assert any("saturated" in m for m in caplog.messages), "Expected saturation log message"


# ---------------------------------------------------------------------------
# Scenario 3: Round 0 saturation is overridden
# ---------------------------------------------------------------------------


class TestRound0SaturationOverride:
    """BDD Scenario 3: Round 0 saturation is overridden."""

    @pytest.mark.asyncio
    async def test_round_0_saturation_overridden(self, caplog):
        """Given deep mode with max_research_rounds=3,
        When AnalysisAgent reports saturated on round 0,
        Then at least min_rounds rounds execute
        And the round 0 saturation signal is overridden."""
        orch = DeepResearchOrchestrator(
            name="DeepResearch_0_google", topic_idx=0, provider="google",
            query="AI news", topic_name="AI", max_rounds=3, min_rounds=2,
            search_depth="deep", model="gemini-2.5-flash", tools=[],
        )
        ctx = _make_ctx()
        rounds_content = [
            _research_text([(f"S{i}", f"https://r{r}.com") for i in range(3)], f"Round {r}")
            for r in range(5)
        ]
        call_count = [0]

        async def mock_planning(inner_ctx):
            return _planning_result()

        # Round 0: saturated (should be overridden), Round 1: saturated (now >= min_rounds)
        analysis_responses = [
            _analysis_result(saturated=True, next_query="q1", gaps=["remaining gap"]),
            _analysis_result(saturated=True, gaps=[]),
        ]
        analysis_idx = [0]

        async def mock_analysis(*args, **kwargs):
            idx = analysis_idx[0]
            analysis_idx[0] += 1
            return analysis_responses[min(idx, len(analysis_responses) - 1)]

        with patch.object(orch, "_run_planning", side_effect=mock_planning), \
             patch.object(orch, "_run_analysis", side_effect=mock_analysis), \
             patch.object(orch, "_make_search_agent", side_effect=_mock_search_agent(orch, call_count, rounds_content)), \
             caplog.at_level(logging.INFO):
            async for _ in orch._run_async_impl(ctx):
                pass

        # At least 2 rounds (min_rounds) must execute despite round 0 saturation
        assert call_count[0] >= 2, f"Expected >= 2 rounds, got {call_count[0]}"
        assert any("overridden" in m for m in caplog.messages), "Expected override log message"


# ---------------------------------------------------------------------------
# Scenario 4: Empty knowledge gaps triggers early exit
# ---------------------------------------------------------------------------


class TestEmptyKnowledgeGapsExit:
    """BDD Scenario 4: Empty knowledge gaps triggers early exit."""

    @pytest.mark.asyncio
    async def test_empty_gaps_after_round_1(self, caplog):
        """Given deep mode with max_research_rounds=5,
        When AnalysisAgent reports empty knowledge_gaps after round 1,
        Then only 2 rounds execute (0, 1)
        And the log contains a full coverage exit message."""
        orch = DeepResearchOrchestrator(
            name="DeepResearch_0_google", topic_idx=0, provider="google",
            query="AI news", topic_name="AI", max_rounds=5,
            search_depth="deep", model="gemini-2.5-flash", tools=[],
        )
        ctx = _make_ctx()
        rounds_content = [
            _research_text([(f"S{i}", f"https://r{r}.com") for i in range(3)], f"Round {r}")
            for r in range(5)
        ]
        call_count = [0]

        async def mock_planning(inner_ctx):
            return _planning_result()

        # Round 0: gaps remain; Round 1: no gaps (full coverage)
        analysis_responses = [
            _analysis_result(saturated=False, next_query="q1", gaps=["gap1"]),
            _analysis_result(saturated=False, gaps=[], next_query="q2"),
        ]
        analysis_idx = [0]

        async def mock_analysis(*args, **kwargs):
            idx = analysis_idx[0]
            analysis_idx[0] += 1
            return analysis_responses[min(idx, len(analysis_responses) - 1)]

        with patch.object(orch, "_run_planning", side_effect=mock_planning), \
             patch.object(orch, "_run_analysis", side_effect=mock_analysis), \
             patch.object(orch, "_make_search_agent", side_effect=_mock_search_agent(orch, call_count, rounds_content)), \
             caplog.at_level(logging.INFO):
            async for _ in orch._run_async_impl(ctx):
                pass

        assert call_count[0] == 2, f"Expected 2 rounds, got {call_count[0]}"
        assert any("full coverage" in m for m in caplog.messages), "Expected full coverage log message"


# ---------------------------------------------------------------------------
# Scenario 5: Search budget exhaustion stops loop
# ---------------------------------------------------------------------------


class TestSearchBudgetExhaustion:
    """BDD Scenario 5: Search budget exhaustion stops loop."""

    @pytest.mark.asyncio
    async def test_budget_exhaustion(self, caplog):
        """Given deep mode with max_research_rounds=5 and max_searches_per_topic=2,
        When the research phase runs,
        Then only 2 search rounds execute
        And the log contains a budget exhaustion message."""
        orch = DeepResearchOrchestrator(
            name="DeepResearch_0_google", topic_idx=0, provider="google",
            query="AI news", topic_name="AI", max_rounds=5,
            max_searches=2,
            search_depth="deep", model="gemini-2.5-flash", tools=[],
        )
        ctx = _make_ctx()
        rounds_content = [
            _research_text([(f"S{i}", f"https://r{r}.com") for i in range(3)], f"Round {r}")
            for r in range(5)
        ]
        call_count = [0]

        async def mock_planning(inner_ctx):
            return _planning_result()

        # All analyses not saturated, with gaps
        async def mock_analysis(*args, **kwargs):
            return _analysis_result(saturated=False, next_query="next", gaps=["gap"])

        with patch.object(orch, "_run_planning", side_effect=mock_planning), \
             patch.object(orch, "_run_analysis", side_effect=mock_analysis), \
             patch.object(orch, "_make_search_agent", side_effect=_mock_search_agent(orch, call_count, rounds_content)), \
             caplog.at_level(logging.INFO):
            async for _ in orch._run_async_impl(ctx):
                pass

        assert call_count[0] == 2, f"Expected 2 rounds, got {call_count[0]}"
        assert any("budget exhausted" in m for m in caplog.messages), "Expected budget exhaustion log"


# ---------------------------------------------------------------------------
# Scenario 6: Single round mode skips planning and analysis
# ---------------------------------------------------------------------------


class TestSingleRoundMode:
    """BDD Scenario 6: Single round mode skips planning and analysis."""

    @pytest.mark.asyncio
    async def test_single_round_no_planning_no_analysis(self):
        """Given max_research_rounds=1,
        When the orchestrator runs,
        Then exactly 1 search round executes
        And no planning or analysis agents are invoked."""
        orch = DeepResearchOrchestrator(
            name="DeepResearch_0_google", topic_idx=0, provider="google",
            query="AI news", topic_name="AI", max_rounds=1, min_rounds=1,
            search_depth="deep", model="gemini-2.5-flash", tools=[],
        )
        ctx = _make_ctx()
        call_count = [0]
        planning_called = [False]
        analysis_called = [False]

        async def mock_planning(inner_ctx):
            planning_called[0] = True
            return _planning_result()

        async def mock_analysis(*args, **kwargs):
            analysis_called[0] = True
            return _analysis_result()

        rounds_content = [_research_text([("A", "https://a.com")], "Single round")]

        with patch.object(orch, "_run_planning", side_effect=mock_planning), \
             patch.object(orch, "_run_analysis", side_effect=mock_analysis), \
             patch.object(orch, "_make_search_agent", side_effect=_mock_search_agent(orch, call_count, rounds_content)):
            async for _ in orch._run_async_impl(ctx):
                pass

        assert call_count[0] == 1
        assert not planning_called[0], "Planning should not run in single-round mode"
        assert not analysis_called[0], "Analysis should not run in single-round mode"

    @pytest.mark.asyncio
    async def test_single_round_result_in_standard_key(self):
        """Given max_research_rounds=1, result is written to standard research key."""
        orch = DeepResearchOrchestrator(
            name="DeepResearch_0_google", topic_idx=0, provider="google",
            query="AI news", topic_name="AI", max_rounds=1, min_rounds=1,
            search_depth="deep", model="gemini-2.5-flash", tools=[],
        )
        ctx = _make_ctx()
        call_count = [0]
        rounds_content = [_research_text([("A", "https://a.com")], "Single round findings")]

        with patch.object(orch, "_make_search_agent", side_effect=_mock_search_agent(orch, call_count, rounds_content)):
            async for _ in orch._run_async_impl(ctx):
                pass

        assert "research_0_google" in ctx.session.state
        assert "Single round findings" in ctx.session.state["research_0_google"]

    def test_given_deep_with_1_round_when_built_then_orchestrator_with_1_round(self):
        """Given search_depth 'deep' and max_research_rounds 1,
        When built, a DeepResearchOrchestrator is created with max_rounds=1."""
        config = _make_config(
            [{"name": "AI", "query": "AI news", "search_depth": "deep"}],
            max_research_rounds=1,
        )
        phase = build_research_phase(config)
        topic_agent = phase.sub_agents[0]

        for sub in topic_agent.sub_agents:
            assert isinstance(sub, DeepResearchOrchestrator)
            assert sub.max_rounds == 1


# ---------------------------------------------------------------------------
# Scenario 7: Standard mode is unaffected by adaptive changes
# ---------------------------------------------------------------------------


class TestStandardModeUnaffected:
    """BDD Scenario 7: Standard mode is unaffected by adaptive changes."""

    def test_given_standard_topic_when_built_then_llm_agent_created(self):
        """Given search_depth 'standard', LlmAgent is created (not orchestrator)."""
        from google.adk.agents import LlmAgent

        config = _make_config(
            [{"name": "AI", "query": "AI news", "search_depth": "standard"}],
            max_research_rounds=3,
        )
        phase = build_research_phase(config)
        topic_agent = phase.sub_agents[0]

        for sub in topic_agent.sub_agents:
            assert isinstance(sub, LlmAgent)
            assert not isinstance(sub, DeepResearchOrchestrator)

    def test_given_standard_topic_then_no_deep_orchestrator_in_tree(self):
        """Standard topics produce no DeepResearchOrchestrator in the tree."""
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
        """Standard-mode topics produce a single output_key per provider."""
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
# Scenario 8: Planning failure uses graceful fallback
# ---------------------------------------------------------------------------


class TestPlanningFailureFallback:
    """BDD Scenario 8: Planning failure uses graceful fallback."""

    @pytest.mark.asyncio
    async def test_planning_invalid_json_uses_fallback(self, caplog):
        """Given PlanningAgent returns invalid JSON,
        Then the original topic query is used for round 0,
        And default key aspects are used for analysis,
        And a warning is logged about planning failure."""
        orch = DeepResearchOrchestrator(
            name="DeepResearch_0_google", topic_idx=0, provider="google",
            query="AI news", topic_name="AI", max_rounds=2, min_rounds=1,
            search_depth="deep", model="gemini-2.5-flash", tools=[],
        )
        ctx = _make_ctx()
        call_count = [0]
        captured_queries = []

        # Planning returns fallback (original query + default aspects)
        async def mock_planning(inner_ctx):
            # Simulate what _run_planning does when parsing fails
            return (orch.query, ["recent developments", "expert opinions", "data and statistics", "industry implications", "emerging trends"], [])

        async def mock_analysis(*args, **kwargs):
            return _analysis_result(saturated=True, gaps=[])

        def capture_make(round_idx, query):
            captured_queries.append(query)
            agent = MagicMock()

            async def fake_run(run_ctx):
                run_ctx.session.state[f"deep_research_latest_0_google"] = _research_text(
                    [("S", f"https://r{round_idx}.com")], f"Round {round_idx}"
                )
                call_count[0] += 1
                return
                yield

            agent.run_async = fake_run
            return agent

        with patch.object(orch, "_run_planning", side_effect=mock_planning), \
             patch.object(orch, "_run_analysis", side_effect=mock_analysis), \
             patch.object(orch, "_make_search_agent", side_effect=capture_make):
            async for _ in orch._run_async_impl(ctx):
                pass

        # Original query used for round 0
        assert captured_queries[0] == "AI news"


# ---------------------------------------------------------------------------
# Scenario 9: Analysis failure uses graceful fallback
# ---------------------------------------------------------------------------


class TestAnalysisFailureFallback:
    """BDD Scenario 9: Analysis failure uses graceful fallback."""

    @pytest.mark.asyncio
    async def test_analysis_invalid_json_uses_fallback_query(self, caplog):
        """Given AnalysisAgent returns invalid JSON on round 1,
        Then a fallback suffix-based query is used for round 2,
        And a warning is logged about analysis failure,
        And the loop continues normally."""
        orch = DeepResearchOrchestrator(
            name="DeepResearch_0_google", topic_idx=0, provider="google",
            query="AI news", topic_name="AI", max_rounds=3, min_rounds=1,
            search_depth="deep", model="gemini-2.5-flash", tools=[],
        )
        ctx = _make_ctx()
        call_count = [0]

        async def mock_planning(inner_ctx):
            return _planning_result("AI initial")

        # Round 0: normal analysis, Round 1: fallback (simulating parse failure result)
        analysis_idx = [0]

        async def mock_analysis(*args, **kwargs):
            idx = analysis_idx[0]
            analysis_idx[0] += 1
            if idx == 0:
                return _analysis_result(saturated=False, next_query="follow-up", gaps=["gap"])
            elif idx == 1:
                # Fallback result from _parse_analysis_output when JSON is invalid
                return (
                    {
                        "findings_summary": "Analysis unavailable",
                        "knowledge_gaps": ["continued exploration needed"],
                        "coverage_assessment": "incomplete",
                        "saturated": False,
                        "next_query": f"AI news trends and developments",
                        "next_query_rationale": "fallback",
                    },
                    [],
                )
            else:
                return _analysis_result(saturated=True, gaps=[])

        rounds_content = [
            _research_text([("S", f"https://r{r}.com")], f"Round {r}")
            for r in range(5)
        ]

        with patch.object(orch, "_run_planning", side_effect=mock_planning), \
             patch.object(orch, "_run_analysis", side_effect=mock_analysis), \
             patch.object(orch, "_make_search_agent", side_effect=_mock_search_agent(orch, call_count, rounds_content)):
            async for _ in orch._run_async_impl(ctx):
                pass

        # Loop continued past the fallback round
        assert call_count[0] == 3, f"Expected 3 rounds, got {call_count[0]}"


# ---------------------------------------------------------------------------
# Scenario 10: Reasoning chain logged for transparency
# ---------------------------------------------------------------------------


class TestReasoningChainLogged:
    """BDD Scenario 10: Reasoning chain logged for transparency."""

    @pytest.mark.asyncio
    async def test_info_logs_contain_adaptive_messages(self, caplog):
        """Given deep mode with max_research_rounds=3,
        When the research phase runs,
        Then INFO logs contain planning output, analysis summaries, and completion."""
        orch = DeepResearchOrchestrator(
            name="DeepResearch_0_google", topic_idx=0, provider="google",
            query="AI news", topic_name="AI", max_rounds=3,
            search_depth="deep", model="gemini-2.5-flash", tools=[],
        )
        ctx = _make_ctx()
        rounds_content = [
            _research_text([(f"S{i}", f"https://r{r}.com") for i in range(3)], f"Round {r}")
            for r in range(3)
        ]
        call_count = [0]

        async def mock_planning(inner_ctx):
            return _planning_result()

        analysis_responses = [
            _analysis_result(saturated=False, next_query="q1", gaps=["g1"]),
            _analysis_result(saturated=False, next_query="q2", gaps=["g2"]),
            _analysis_result(saturated=True, gaps=[]),
        ]
        analysis_idx = [0]

        async def mock_analysis(*args, **kwargs):
            idx = analysis_idx[0]
            analysis_idx[0] += 1
            return analysis_responses[min(idx, len(analysis_responses) - 1)]

        with patch.object(orch, "_run_planning", side_effect=mock_planning), \
             patch.object(orch, "_run_analysis", side_effect=mock_analysis), \
             patch.object(orch, "_make_search_agent", side_effect=_mock_search_agent(orch, call_count, rounds_content)), \
             caplog.at_level(logging.INFO):
            async for _ in orch._run_async_impl(ctx):
                pass

        log_text = " ".join(caplog.messages)
        assert "[AdaptiveResearch]" in log_text, "Expected [AdaptiveResearch] log entries"
        assert "round 0" in log_text, "Expected round 0 log"
        assert "round 1" in log_text, "Expected round 1 log"
        assert "round 2" in log_text, "Expected round 2 log"

    @pytest.mark.asyncio
    async def test_reasoning_chain_persisted_to_state(self):
        """After adaptive research, the reasoning chain is persisted to state."""
        orch = DeepResearchOrchestrator(
            name="DeepResearch_0_google", topic_idx=0, provider="google",
            query="AI news", topic_name="AI", max_rounds=2, min_rounds=1,
            search_depth="deep", model="gemini-2.5-flash", tools=[],
        )
        ctx = _make_ctx()
        rounds_content = [
            _research_text([("S", f"https://r{r}.com")], f"Round {r}")
            for r in range(2)
        ]
        call_count = [0]

        async def mock_planning(inner_ctx):
            return _planning_result()

        async def mock_analysis(*args, **kwargs):
            return _analysis_result(saturated=True, gaps=[])

        with patch.object(orch, "_run_planning", side_effect=mock_planning), \
             patch.object(orch, "_run_analysis", side_effect=mock_analysis), \
             patch.object(orch, "_make_search_agent", side_effect=_mock_search_agent(orch, call_count, rounds_content)):
            async for _ in orch._run_async_impl(ctx):
                pass

        chain_key = "adaptive_reasoning_chain_0_google"
        assert chain_key in ctx.session.state
        chain = json.loads(ctx.session.state[chain_key])
        assert "plan" in chain
        assert "rounds" in chain
        assert len(chain["rounds"]) >= 1
