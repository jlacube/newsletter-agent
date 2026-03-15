"""Unit tests for the query expansion prompt template.

Spec refs: FR-MRR-003, FR-MRR-004, Section 4.3.
"""

from newsletter_agent.prompts.query_expansion import get_query_expansion_instruction


class TestQueryExpansionPrompt:

    def test_returns_string(self):
        result = get_query_expansion_instruction("AI news", "Artificial Intelligence", 3)
        assert isinstance(result, str)

    def test_contains_original_query(self):
        result = get_query_expansion_instruction("AI news", "AI Topic", 2)
        assert "AI news" in result

    def test_contains_topic_name(self):
        result = get_query_expansion_instruction("query", "My Topic", 2)
        assert "My Topic" in result

    def test_contains_variant_count(self):
        result = get_query_expansion_instruction("query", "topic", 4)
        assert "4" in result

    def test_specifies_json_array_output(self):
        result = get_query_expansion_instruction("q", "t", 2)
        assert "JSON array" in result

    def test_mentions_different_angles(self):
        result = get_query_expansion_instruction("q", "t", 2)
        lower = result.lower()
        assert "trends" in lower
        assert "expert" in lower
        assert "statistics" in lower or "data" in lower
