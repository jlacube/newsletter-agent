"""Unit tests for newsletter_agent.prompts.reasoning -- planning and analysis prompts.

Covers: FR-ADR-070, Section 11.1 (Prompt templates tests).
"""

import pytest

from newsletter_agent.prompts.reasoning import (
    get_analysis_instruction,
    get_planning_instruction,
)


# ---------------------------------------------------------------------------
# get_planning_instruction tests
# ---------------------------------------------------------------------------


class TestGetPlanningInstruction:

    def test_contains_query_and_topic_name(self):
        """Returned string contains the provided query and topic_name values."""
        result = get_planning_instruction(
            query="Latest AI breakthroughs", topic_name="AI Research"
        )
        assert "Latest AI breakthroughs" in result
        assert "AI Research" in result

    def test_contains_all_json_field_names(self):
        """Returned string contains all 4 required JSON field names."""
        result = get_planning_instruction(query="test query", topic_name="test topic")
        assert "query_intent" in result
        assert "key_aspects" in result
        assert "initial_search_query" in result
        assert "search_rationale" in result

    def test_contains_json_output_constraint(self):
        """Returned string ends with the JSON-only output constraint."""
        result = get_planning_instruction(query="test", topic_name="test")
        assert "Output ONLY the JSON object" in result

    def test_special_characters_interpolated(self):
        """Special characters in query/topic_name are interpolated correctly."""
        result = get_planning_instruction(
            query='AI "agents" & frameworks <2026>',
            topic_name="C++ / Rust performance",
        )
        assert 'AI "agents" & frameworks <2026>' in result
        assert "C++ / Rust performance" in result


# ---------------------------------------------------------------------------
# get_analysis_instruction tests
# ---------------------------------------------------------------------------


class TestGetAnalysisInstruction:

    def _make_result(self, **overrides):
        """Build default analysis instruction args, applying overrides."""
        defaults = {
            "topic_name": "AI Research",
            "query": "Latest AI breakthroughs",
            "key_aspects": ["model architecture", "training data", "benchmarks"],
            "prior_rounds_summary": "No prior rounds.",
            "latest_results": "Found article about GPT-5 performance.",
            "round_idx": 1,
            "current_query": "GPT-5 benchmarks 2026",
            "remaining_searches": 2,
        }
        defaults.update(overrides)
        return get_analysis_instruction(**defaults)

    def test_contains_all_parameter_values(self):
        """Returned string contains all 8 parameter values."""
        result = self._make_result()
        assert "AI Research" in result
        assert "Latest AI breakthroughs" in result
        assert "model architecture" in result
        assert "No prior rounds." in result
        assert "Found article about GPT-5 performance." in result
        assert "1" in result  # round_idx
        assert "GPT-5 benchmarks 2026" in result
        assert "2" in result  # remaining_searches

    def test_key_aspects_formatted_as_bullet_list(self):
        """key_aspects is formatted as a bulleted list."""
        result = self._make_result(
            key_aspects=["aspect1", "aspect2", "aspect3"]
        )
        assert "- aspect1\n- aspect2\n- aspect3" in result

    def test_key_aspects_single_item(self):
        """Single key_aspect formatted correctly."""
        result = self._make_result(key_aspects=["single aspect"])
        assert "- single aspect" in result

    def test_key_aspects_five_items(self):
        """Five key_aspects all appear in the output."""
        aspects = ["a1", "a2", "a3", "a4", "a5"]
        result = self._make_result(key_aspects=aspects)
        for a in aspects:
            assert f"- {a}" in result

    def test_prior_rounds_summary_zero_rounds(self):
        """Empty prior rounds summary is interpolated correctly."""
        result = self._make_result(prior_rounds_summary="No prior rounds.")
        assert "No prior rounds." in result

    def test_prior_rounds_summary_one_round(self):
        """Single prior round summary appears in output."""
        summary = "Round 0: Found 5 articles about transformer architecture."
        result = self._make_result(prior_rounds_summary=summary)
        assert summary in result

    def test_prior_rounds_summary_three_rounds(self):
        """Multi-round prior summary appears in output."""
        summary = (
            "Round 0: Found initial overview of AI landscape.\n"
            "Round 1: Discovered key benchmark comparisons.\n"
            "Round 2: Identified expert opinions on safety."
        )
        result = self._make_result(prior_rounds_summary=summary)
        assert summary in result

    def test_contains_all_json_field_names(self):
        """Returned string contains all 6 required JSON field names."""
        result = self._make_result()
        assert "findings_summary" in result
        assert "knowledge_gaps" in result
        assert "coverage_assessment" in result
        assert "saturated" in result
        assert "next_query" in result
        assert "next_query_rationale" in result

    def test_contains_saturation_guidelines(self):
        """Returned string contains saturation guidelines section."""
        result = self._make_result()
        assert "Saturation guidelines:" in result
        assert "saturated=true" in result
        assert "saturated=false" in result

    def test_contains_json_output_constraint(self):
        """Returned string ends with the JSON-only output constraint."""
        result = self._make_result()
        assert "Output ONLY the JSON object. No other text." in result
