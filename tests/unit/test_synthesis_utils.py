"""
Unit tests for synthesis post-processing.

Tests parse_synthesis_output() with various JSON formats and failure modes.
Spec refs: Section 11.1, FR-019, FR-018, Section 7.5.
"""

import json

import pytest

from newsletter_agent.tools.synthesis_utils import parse_synthesis_output


TOPICS = ["AI Frameworks", "Cloud Native", "Cybersecurity"]


def _make_valid_json(sections=None, summary=None):
    """Helper to build valid synthesis JSON."""
    if sections is None:
        sections = [
            {
                "title": name,
                "body_markdown": f"Analysis of {name} " + ("word " * 50) + f"[Source](https://example.com/{i})",
                "sources": [{"url": f"https://example.com/{i}", "title": f"Source {i}"}],
            }
            for i, name in enumerate(TOPICS)
        ]
    if summary is None:
        summary = [
            {"topic": name, "summary": f"Overview of {name}."}
            for name in TOPICS
        ]
    return json.dumps({"executive_summary": summary, "sections": sections})


class TestValidJsonOutput:
    def test_parses_valid_json(self):
        raw = _make_valid_json()
        result = parse_synthesis_output(raw, TOPICS)
        assert "synthesis_0" in result
        assert "synthesis_1" in result
        assert "synthesis_2" in result
        assert "executive_summary" in result

    def test_section_structure(self):
        raw = _make_valid_json()
        result = parse_synthesis_output(raw, TOPICS)
        section = result["synthesis_0"]
        assert "title" in section
        assert "body_markdown" in section
        assert "sources" in section
        assert section["title"] == "AI Frameworks"

    def test_executive_summary_structure(self):
        raw = _make_valid_json()
        result = parse_synthesis_output(raw, TOPICS)
        summary = result["executive_summary"]
        assert len(summary) == 3
        assert summary[0]["topic"] == "AI Frameworks"
        assert "overview" in summary[0]["summary"].lower()

    def test_sources_are_normalized(self):
        sections = [
            {
                "title": "T",
                "body_markdown": "text",
                "sources": [
                    {"url": "https://a.com", "title": "A"},
                    {"url": "https://a.com", "title": "A duplicate"},
                    {"url": "https://b.com", "title": "B"},
                ],
            }
        ]
        raw = json.dumps({"executive_summary": [], "sections": sections})
        result = parse_synthesis_output(raw, ["T"])
        sources = result["synthesis_0"]["sources"]
        assert len(sources) == 2
        urls = [s["url"] for s in sources]
        assert "https://a.com" in urls
        assert "https://b.com" in urls

    def test_non_http_urls_filtered(self):
        sections = [
            {
                "title": "T",
                "body_markdown": "text",
                "sources": [
                    {"url": "https://good.com", "title": "Good"},
                    {"url": "javascript:alert(1)", "title": "XSS"},
                    {"url": "data:text/html,<h1>bad</h1>", "title": "Data"},
                    {"url": "ftp://files.example.com", "title": "FTP"},
                    {"url": "http://plain.com", "title": "HTTP"},
                    {"url": "relative/path", "title": "Relative"},
                ],
            }
        ]
        raw = json.dumps({"executive_summary": [], "sections": sections})
        result = parse_synthesis_output(raw, ["T"])
        sources = result["synthesis_0"]["sources"]
        urls = [s["url"] for s in sources]
        assert "https://good.com" in urls
        assert "http://plain.com" in urls
        assert len(sources) == 2


class TestMarkdownWrappedJson:
    def test_json_in_code_block(self):
        inner = _make_valid_json()
        raw = f"```json\n{inner}\n```"
        result = parse_synthesis_output(raw, TOPICS)
        assert "synthesis_0" in result
        assert result["synthesis_0"]["title"] == "AI Frameworks"

    def test_json_in_plain_code_block(self):
        inner = _make_valid_json()
        raw = f"```\n{inner}\n```"
        result = parse_synthesis_output(raw, TOPICS)
        assert "synthesis_0" in result


class TestMalformedInput:
    def test_completely_empty_input(self):
        result = parse_synthesis_output("", TOPICS)
        assert "synthesis_0" in result
        assert "executive_summary" in result
        # Should have fallback content
        assert result["synthesis_0"]["title"] == "AI Frameworks"

    def test_none_like_empty(self):
        result = parse_synthesis_output("   ", TOPICS)
        assert "synthesis_0" in result

    def test_plain_text_no_json(self):
        result = parse_synthesis_output("Here is some analysis about AI.", TOPICS)
        assert "synthesis_0" in result
        assert "executive_summary" in result

    def test_partial_json_missing_sections(self):
        raw = json.dumps({"executive_summary": [{"topic": "AI", "summary": "Test"}]})
        result = parse_synthesis_output(raw, TOPICS)
        # Should still have synthesis_0 etc. with fallback content
        assert "synthesis_0" in result
        assert "executive_summary" in result


class TestMissingSections:
    def test_fewer_sections_than_topics(self):
        sections = [
            {"title": "AI Frameworks", "body_markdown": "Content", "sources": []}
        ]
        summary = [{"topic": "AI Frameworks", "summary": "S"}]
        raw = json.dumps({"executive_summary": summary, "sections": sections})
        result = parse_synthesis_output(raw, TOPICS)
        # First topic should have content
        assert result["synthesis_0"]["body_markdown"] == "Content"
        # Missing topics should have fallback
        assert "synthesis_1" in result
        assert "synthesis_2" in result

    def test_missing_executive_summary(self):
        sections = [
            {"title": name, "body_markdown": "C", "sources": []}
            for name in TOPICS
        ]
        raw = json.dumps({"sections": sections})
        result = parse_synthesis_output(raw, TOPICS)
        assert "executive_summary" in result
        summary = result["executive_summary"]
        assert len(summary) == 3

    def test_missing_sources_in_section(self):
        sections = [{"title": "AI", "body_markdown": "Content"}]
        raw = json.dumps({"executive_summary": [], "sections": sections})
        result = parse_synthesis_output(raw, ["AI"])
        assert result["synthesis_0"]["sources"] == []


class TestNeverRaises:
    @pytest.mark.parametrize(
        "raw_input",
        [
            "",
            "   ",
            "not json at all",
            "{invalid json",
            '{"sections": "not a list"}',
            '{"executive_summary": "not a list", "sections": []}',
            None,
        ],
    )
    def test_never_raises_exception(self, raw_input):
        # Should always return a dict, never raise
        if raw_input is None:
            result = parse_synthesis_output("", TOPICS)
        else:
            result = parse_synthesis_output(raw_input, TOPICS)
        assert isinstance(result, dict)
        assert "executive_summary" in result


class TestTruncatedJsonRepair:
    """Tests for truncated JSON output recovery (token limit hit)."""

    def test_truncated_after_first_summary_entry(self):
        """JSON cut mid-way through executive_summary array."""
        truncated = (
            '{"executive_summary": ['
            '{"topic": "AI Frameworks", "summary": "AI is growing."}, '
            '{"topic": "G'
        )
        result = parse_synthesis_output(truncated, TOPICS)
        # Should recover at least the first summary entry
        assert "executive_summary" in result
        summary = result["executive_summary"]
        assert len(summary) >= 1
        assert summary[0]["topic"] == "AI Frameworks"

    def test_truncated_after_first_section(self):
        """JSON cut after the first complete section."""
        truncated = json.dumps({
            "executive_summary": [
                {"topic": "AI", "summary": "AI overview."},
                {"topic": "Cloud", "summary": "Cloud overview."},
            ],
            "sections": [
                {"title": "AI", "body_markdown": "AI analysis text.", "sources": []},
            ],
        })
        # Remove the closing and add partial second section to simulate truncation
        truncated = truncated[:-2] + ', {"title": "Cloud", "body_markd'
        result = parse_synthesis_output(truncated, TOPICS)
        assert "synthesis_0" in result
        assert result["synthesis_0"]["body_markdown"] == "AI analysis text."

    def test_truncated_in_code_fences(self):
        """JSON wrapped in ```json fences and truncated."""
        inner = json.dumps({
            "executive_summary": [{"topic": "AI", "summary": "Summary."}],
            "sections": [{"title": "AI", "body_markdown": "Content.", "sources": []}],
        })
        truncated = "```json\n" + inner[:-20] + "runc"
        result = parse_synthesis_output(truncated, TOPICS)
        assert "executive_summary" in result

    def test_completely_unrecoverable_json(self):
        """Badly broken text that can't be repaired still falls back gracefully."""
        result = parse_synthesis_output('{"unclosed', TOPICS)
        assert "synthesis_0" in result
        assert "executive_summary" in result


class TestJsonWithExtraText:
    def test_json_with_prefix_text(self):
        inner = _make_valid_json()
        raw = f"Here is the synthesis:\n\n{inner}"
        result = parse_synthesis_output(raw, TOPICS)
        assert "synthesis_0" in result
        assert result["synthesis_0"]["title"] == "AI Frameworks"

    def test_json_with_suffix_text(self):
        inner = _make_valid_json()
        raw = f"{inner}\n\nI hope this helps!"
        result = parse_synthesis_output(raw, TOPICS)
        assert "synthesis_0" in result
