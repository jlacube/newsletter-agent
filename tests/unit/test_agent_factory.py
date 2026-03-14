"""Unit tests for the dynamic research phase agent factory.

Spec refs: Section 11.1, FR-010, Section 9.4 Decision 1.
"""

import pytest
from google.adk.agents import LlmAgent, ParallelAgent, SequentialAgent
from google.adk.tools import google_search

from newsletter_agent.agent import (
    _RESEARCH_MODEL,
    _ROOT_AGENT_NAME,
    _SYNTHESIS_MODEL,
    build_pipeline,
    build_research_phase,
    build_synthesis_agent,
)
from newsletter_agent.config.schema import (
    AppSettings,
    NewsletterConfig,
    NewsletterSettings,
    TopicConfig,
)
from newsletter_agent.tools.perplexity_search import perplexity_search_tool


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


class TestBuildResearchPhase:

    def test_single_topic_both_sources(self):
        config = _make_config([{"name": "AI", "query": "AI news"}])
        phase = build_research_phase(config)

        assert isinstance(phase, ParallelAgent)
        assert phase.name == "ResearchPhase"
        assert len(phase.sub_agents) == 1

        topic_agent = phase.sub_agents[0]
        assert isinstance(topic_agent, SequentialAgent)
        assert len(topic_agent.sub_agents) == 2

    def test_single_topic_google_only(self):
        config = _make_config([
            {"name": "AI", "query": "AI news", "sources": ["google_search"]}
        ])
        phase = build_research_phase(config)

        topic_agent = phase.sub_agents[0]
        assert len(topic_agent.sub_agents) == 1
        assert "Google" in topic_agent.sub_agents[0].name

    def test_single_topic_perplexity_only(self):
        config = _make_config([
            {"name": "AI", "query": "AI news", "sources": ["perplexity"]}
        ])
        phase = build_research_phase(config)

        topic_agent = phase.sub_agents[0]
        assert len(topic_agent.sub_agents) == 1
        assert "Perplexity" in topic_agent.sub_agents[0].name

    def test_five_topics_creates_five_parallel_agents(self):
        config = _make_config([
            {"name": f"Topic {i}", "query": f"Q{i}"} for i in range(5)
        ])
        phase = build_research_phase(config)
        assert len(phase.sub_agents) == 5

    def test_twenty_topics_max(self):
        config = _make_config([
            {"name": f"T{i}", "query": f"Q{i}"} for i in range(20)
        ])
        phase = build_research_phase(config)
        assert len(phase.sub_agents) == 20

    def test_agent_names_are_unique(self):
        config = _make_config([
            {"name": f"T{i}", "query": f"Q{i}"} for i in range(5)
        ])
        phase = build_research_phase(config)

        all_names = set()
        for topic_agent in phase.sub_agents:
            all_names.add(topic_agent.name)
            for sub in topic_agent.sub_agents:
                all_names.add(sub.name)

        assert len(all_names) == 15  # 5 topic + 10 sub (2 each)

    def test_output_keys_follow_naming_convention(self):
        config = _make_config([
            {"name": "AI", "query": "AI news"},
            {"name": "Cloud", "query": "Cloud news"},
        ])
        phase = build_research_phase(config)

        expected_keys = {
            "research_0_google",
            "research_0_perplexity",
            "research_1_google",
            "research_1_perplexity",
        }
        actual_keys = set()
        for topic_agent in phase.sub_agents:
            for sub in topic_agent.sub_agents:
                actual_keys.add(sub.output_key)

        assert actual_keys == expected_keys

    def test_deep_search_depth_reflected_in_instruction(self):
        config = _make_config([
            {"name": "AI", "query": "AI news", "search_depth": "deep"}
        ])
        phase = build_research_phase(config)

        topic_agent = phase.sub_agents[0]
        google_agent = topic_agent.sub_agents[0]
        instruction_lower = google_agent.instruction.lower()
        assert "comprehensive" in instruction_lower or "deep" in instruction_lower

    def test_mixed_sources_across_topics(self):
        config = _make_config([
            {"name": "A", "query": "Q1", "sources": ["google_search"]},
            {"name": "B", "query": "Q2", "sources": ["perplexity"]},
            {"name": "C", "query": "Q3", "sources": ["google_search", "perplexity"]},
        ])
        phase = build_research_phase(config)

        assert len(phase.sub_agents) == 3
        assert len(phase.sub_agents[0].sub_agents) == 1  # google only
        assert len(phase.sub_agents[1].sub_agents) == 1  # perplexity only
        assert len(phase.sub_agents[2].sub_agents) == 2  # both


class TestAgentTools:
    """Verify each agent has the correct tools assigned (T05-07 AC)."""

    def test_google_search_agent_has_exactly_one_tool(self):
        config = _make_config([{"name": "AI", "query": "AI news"}])
        phase = build_research_phase(config)
        google_agent = phase.sub_agents[0].sub_agents[0]
        assert len(google_agent.tools) == 1
        assert google_agent.tools[0] is google_search

    def test_perplexity_agent_has_search_tool(self):
        config = _make_config([{"name": "AI", "query": "AI news"}])
        phase = build_research_phase(config)
        perplexity_agent = phase.sub_agents[0].sub_agents[1]
        assert len(perplexity_agent.tools) == 1
        assert perplexity_agent.tools[0] is perplexity_search_tool


class TestModelAssignments:
    """Verify model assignments: Flash for research, Pro for synthesis (T05-07 AC)."""

    def test_google_search_agent_uses_flash(self):
        config = _make_config([{"name": "AI", "query": "AI news"}])
        phase = build_research_phase(config)
        google_agent = phase.sub_agents[0].sub_agents[0]
        assert google_agent.model == _RESEARCH_MODEL

    def test_perplexity_agent_uses_flash(self):
        config = _make_config([{"name": "AI", "query": "AI news"}])
        phase = build_research_phase(config)
        perplexity_agent = phase.sub_agents[0].sub_agents[1]
        assert perplexity_agent.model == _RESEARCH_MODEL

    def test_synthesis_agent_uses_pro(self):
        config = _make_config([{"name": "AI", "query": "AI news"}])
        agent = build_synthesis_agent(config)
        assert agent.model == _SYNTHESIS_MODEL


class TestBuildPipeline:
    """Verify full pipeline construction via build_pipeline() (T05-07 AC)."""

    def test_root_is_sequential_agent(self):
        config = _make_config([{"name": "AI", "query": "AI news"}])
        pipeline = build_pipeline(config)
        assert isinstance(pipeline, SequentialAgent)
        assert pipeline.name == _ROOT_AGENT_NAME

    def test_root_has_three_sub_agents(self):
        config = _make_config([{"name": "AI", "query": "AI news"}])
        pipeline = build_pipeline(config)
        assert len(pipeline.sub_agents) == 3

    def test_sub_agent_order(self):
        config = _make_config([{"name": "AI", "query": "AI news"}])
        pipeline = build_pipeline(config)
        assert isinstance(pipeline.sub_agents[0], ParallelAgent)
        assert pipeline.sub_agents[0].name == "ResearchPhase"
        assert isinstance(pipeline.sub_agents[1], LlmAgent)
        assert pipeline.sub_agents[1].name == "Synthesizer"
        assert isinstance(pipeline.sub_agents[2], SequentialAgent)
        assert pipeline.sub_agents[2].name == "OutputPhase"

    def test_output_phase_wraps_formatter_and_delivery(self):
        config = _make_config([{"name": "AI", "query": "AI news"}])
        pipeline = build_pipeline(config)
        output_phase = pipeline.sub_agents[2]
        assert len(output_phase.sub_agents) == 2
        assert output_phase.sub_agents[0].name == "FormatterAgent"
        assert output_phase.sub_agents[1].name == "DeliveryAgent"
