"""Unit tests for Google Search prompt source count requirements.

Verifies FR-PSV-007 (standard mode >= 5 sources) and FR-PSV-008
(deep mode >= 8 sources) by counting [Source Title N](URLN) entries
in the generated prompt templates.

Spec refs: FR-PSV-007, FR-PSV-008, Section 5.
"""

import re

from newsletter_agent.prompts.research_google import get_google_search_instruction

# Matches source list entries like "- [Source Title 1](URL1)"
_SOURCE_SLOT_RE = re.compile(r"-\s*\[Source Title \d+\]\(URL\d+\)")


class TestStandardModeSourceCount:
    """FR-PSV-007: Standard mode requests at least 5 sources."""

    def test_standard_prompt_has_at_least_5_source_slots(self):
        prompt = get_google_search_instruction(
            topic_name="AI", query="AI news", search_depth="standard",
        )
        slots = _SOURCE_SLOT_RE.findall(prompt)
        assert len(slots) >= 5, (
            f"Standard prompt should have >= 5 source slots, found {len(slots)}"
        )

    def test_standard_prompt_mentions_5_diverse_sources(self):
        prompt = get_google_search_instruction(
            topic_name="AI", query="AI news", search_depth="standard",
        )
        assert "at least 5 diverse sources" in prompt


class TestDeepModeSourceCount:
    """FR-PSV-008: Deep mode requests at least 8 sources."""

    def test_deep_prompt_has_at_least_8_source_slots(self):
        prompt = get_google_search_instruction(
            topic_name="AI", query="AI news", search_depth="deep",
        )
        slots = _SOURCE_SLOT_RE.findall(prompt)
        assert len(slots) >= 8, (
            f"Deep prompt should have >= 8 source slots, found {len(slots)}"
        )

    def test_deep_prompt_mentions_8_diverse_sources(self):
        prompt = get_google_search_instruction(
            topic_name="AI", query="AI news", search_depth="deep",
        )
        assert "at least 8 diverse sources" in prompt
