"""
BDD-style acceptance tests for the research pipeline.

Uses Given/When/Then structure to verify spec Section 11.2 scenarios.
Spec refs: Section 11.2 Feature: Research Pipeline, US-02.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from newsletter_agent.agent import (
    ResearchValidatorAgent,
    build_research_phase,
)
from newsletter_agent.config.schema import (
    AppSettings,
    NewsletterConfig,
    NewsletterSettings,
    TopicConfig,
)


def _make_config(topics_data):
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
        settings=AppSettings(),
        topics=topics,
    )


class TestSuccessfulDualSourceResearch:
    """Feature: Research Pipeline
    Scenario: Successful dual-source research

    Given a valid topic config with both google_search and perplexity sources
    When the research pipeline runs for that topic
    Then session state contains research_0_google with text and sources
    And session state contains research_0_perplexity with text and sources
    """

    def test_given_dual_source_topic_when_built_then_both_agents_created(self):
        # Given a valid topic config with both google_search and perplexity sources
        config = _make_config([
            {"name": "AI Frameworks", "query": "latest AI frameworks 2026",
             "sources": ["google_search", "perplexity"]}
        ])

        # When the research pipeline is built for that topic
        phase = build_research_phase(config)

        # Then both agents are created with correct output keys
        topic_agent = phase.sub_agents[0]
        assert len(topic_agent.sub_agents) == 2
        google_agent = topic_agent.sub_agents[0]
        perplexity_agent = topic_agent.sub_agents[1]

        assert google_agent.output_key == "research_0_google"
        assert perplexity_agent.output_key == "research_0_perplexity"
        assert "GoogleSearcher" in google_agent.name
        assert "PerplexitySearcher" in perplexity_agent.name


class TestSingleProviderFailure:
    """Feature: Research Pipeline
    Scenario: Single provider failure

    Given a valid topic config with both sources
    And the Perplexity API returns a 429 error
    When the research pipeline runs
    Then session state research_0_perplexity has error=true
    And session state research_0_google has valid research data
    And the pipeline continues without aborting
    """

    @pytest.mark.asyncio
    async def test_given_one_failure_when_validated_then_not_all_failed(self):
        # Given research results where Google succeeded but Perplexity failed
        state = {
            "research_0_google": {
                "text": "Valid AI research data",
                "sources": [{"url": "https://example.com", "title": "Source"}],
                "provider": "google",
            },
            "research_0_perplexity": {
                "error": True,
                "message": "Rate limit exceeded (429)",
                "provider": "perplexity",
            },
        }
        ctx = MagicMock()
        ctx.session.state = state

        # When the research validator runs
        validator = ResearchValidatorAgent(
            name="ResearchValidator",
            topic_count=1,
            providers=["google", "perplexity"],
        )
        events = []
        async for event in validator._run_async_impl(ctx):
            events.append(event)

        # Then research_all_failed is False (pipeline continues)
        assert state["research_all_failed"] is False

    def test_given_dual_source_when_built_then_agents_are_independent(self):
        # Given a valid topic config with both sources
        config = _make_config([
            {"name": "AI", "query": "AI news",
             "sources": ["google_search", "perplexity"]}
        ])

        # When the research pipeline is built
        phase = build_research_phase(config)
        topic_agent = phase.sub_agents[0]

        # Then each agent is independent (separate output keys, no shared state)
        assert topic_agent.sub_agents[0].output_key != topic_agent.sub_agents[1].output_key


class TestParallelExecutionMultipleTopics:
    """Feature: Research Pipeline
    Scenario: Parallel execution of multiple topics

    Given 3 valid topic configs
    When the research pipeline runs
    Then all 3 topics are researched
    """

    def test_given_three_topics_when_built_then_parallel_agent_has_three(self):
        # Given 3 valid topic configs
        config = _make_config([
            {"name": "AI", "query": "AI news"},
            {"name": "Cloud", "query": "Cloud computing"},
            {"name": "Security", "query": "Cybersecurity trends"},
        ])

        # When the research pipeline is built
        phase = build_research_phase(config)

        # Then all 3 topics are present as parallel sub-agents
        from google.adk.agents import ParallelAgent
        assert isinstance(phase, ParallelAgent)
        assert len(phase.sub_agents) == 3

        # And each topic has its own research agents
        for idx, topic_agent in enumerate(phase.sub_agents):
            assert topic_agent.name == f"Topic{idx}Research"
            assert len(topic_agent.sub_agents) == 2  # google + perplexity


class TestAllProvidersFail:
    """Feature: Research Pipeline
    Scenario: All providers fail

    Given all providers return errors for all topics
    When the research validator runs
    Then research_all_failed is True
    And a critical error is logged
    """

    @pytest.mark.asyncio
    async def test_given_all_errors_when_validated_then_all_failed_true(self):
        # Given all providers return errors for all topics
        state = {
            "research_0_google": {
                "error": True, "message": "API error", "provider": "google"
            },
            "research_0_perplexity": {
                "error": True, "message": "Rate limit", "provider": "perplexity"
            },
            "research_1_google": {
                "error": True, "message": "Timeout", "provider": "google"
            },
            "research_1_perplexity": {
                "error": True, "message": "Auth error", "provider": "perplexity"
            },
        }
        ctx = MagicMock()
        ctx.session.state = state

        # When the research validator checks
        validator = ResearchValidatorAgent(
            name="ResearchValidator",
            topic_count=2,
            providers=["google", "perplexity"],
        )
        events = []
        async for event in validator._run_async_impl(ctx):
            events.append(event)

        # Then research_all_failed is True
        assert state["research_all_failed"] is True

    @pytest.mark.asyncio
    async def test_given_missing_keys_when_validated_then_all_failed_true(self):
        # Given no research keys exist in state at all
        state = {}
        ctx = MagicMock()
        ctx.session.state = state

        # When the research validator checks
        validator = ResearchValidatorAgent(
            name="ResearchValidator",
            topic_count=1,
            providers=["google", "perplexity"],
        )
        events = []
        async for event in validator._run_async_impl(ctx):
            events.append(event)

        # Then research_all_failed is True
        assert state["research_all_failed"] is True
