"""
Unit tests for synthesis post-processing.

Tests parse_synthesis_output() with various JSON formats and failure modes.
Spec refs: Section 11.1, FR-019, FR-018, Section 7.5.
"""

import json

import pytest

from newsletter_agent.tools.synthesis_utils import (
    parse_synthesis_output,
    _relink_orphaned_brackets,
    _fix_nested_links,
    _fix_split_links,
    _fix_bare_close_brackets,
)


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

    def test_synthetic_google_search_sources_are_removed(self):
        sections = [
            {
                "title": "T",
                "body_markdown": (
                    'Analysis with '
                    '[GOOGLE research for "T"](https://www.google.com/search?q=T+trends) '
                    'and '
                    '[Real Source](https://example.com/article).'
                ),
                "sources": [
                    {
                        "url": "https://www.google.com/search?q=T+trends",
                        "title": 'GOOGLE research for "T"',
                    },
                    {
                        "url": "https://example.com/article",
                        "title": "Real Source",
                    },
                ],
            }
        ]
        raw = json.dumps({"executive_summary": [], "sections": sections})
        result = parse_synthesis_output(raw, ["T"])
        section = result["synthesis_0"]
        assert section["sources"] == [{"url": "https://example.com/article", "title": "Real Source"}]
        assert "https://www.google.com/search?q=T+trends" not in section["body_markdown"]
        assert 'GOOGLE research for "T"' in section["body_markdown"]

    def test_round_placeholder_sources_are_removed(self):
        sections = [
            {
                "title": "T",
                "body_markdown": "Benchmark summary [Round 1](https://www.google.com/search?q=T+Round+1)",
                "sources": [
                    {
                        "url": "https://www.google.com/search?q=T+Round+1",
                        "title": "Round 1",
                    }
                ],
            }
        ]
        raw = json.dumps({"executive_summary": [], "sections": sections})
        result = parse_synthesis_output(raw, ["T"])
        section = result["synthesis_0"]
        assert section["sources"] == []
        assert "https://www.google.com/search?q=T+Round+1" not in section["body_markdown"]
        assert "Round 1" in section["body_markdown"]


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


class TestRelinkOrphanedBrackets:
    """Tests for _relink_orphaned_brackets post-processing."""

    def test_relinks_exact_title_match(self):
        body = "Analysis shows growth [AI Market Report]. More details follow."
        sources = [{"url": "https://example.com/report", "title": "AI Market Report"}]
        result = _relink_orphaned_brackets(body, sources)
        assert "[AI Market Report](https://example.com/report)" in result

    def test_relinks_multiple_orphans(self):
        body = (
            "First finding [Source Alpha]. "
            "Second finding [Source Beta]."
        )
        sources = [
            {"url": "https://a.com", "title": "Source Alpha"},
            {"url": "https://b.com", "title": "Source Beta"},
        ]
        result = _relink_orphaned_brackets(body, sources)
        assert "[Source Alpha](https://a.com)" in result
        assert "[Source Beta](https://b.com)" in result

    def test_preserves_existing_markdown_links(self):
        body = "Existing [Title](https://existing.com) stays intact."
        sources = [{"url": "https://other.com", "title": "Title"}]
        result = _relink_orphaned_brackets(body, sources)
        assert "[Title](https://existing.com)" in result

    def test_prefix_match_truncated_title(self):
        body = "Analysis [Advanced RAG Techniques for High-Performance LLM Appli]."
        sources = [
            {
                "url": "https://neo4j.com/rag",
                "title": "Advanced RAG Techniques for High-Performance LLM Applications - Neo4j",
            }
        ]
        result = _relink_orphaned_brackets(body, sources)
        assert "(https://neo4j.com/rag)" in result

    def test_ignores_short_brackets(self):
        body = "Version [v2.0] released. See [AI Market Report in 2026]."
        sources = [
            {"url": "https://example.com/report", "title": "AI Market Report in 2026"}
        ]
        result = _relink_orphaned_brackets(body, sources)
        # Short bracket [v2.0] should remain unchanged
        assert "[v2.0]" in result
        assert "[AI Market Report in 2026](https://example.com/report)" in result

    def test_no_sources_returns_unchanged(self):
        body = "Analysis [Some Title Reference]."
        result = _relink_orphaned_brackets(body, [])
        assert result == body

    def test_empty_body_returns_empty(self):
        sources = [{"url": "https://a.com", "title": "A"}]
        assert _relink_orphaned_brackets("", sources) == ""

    def test_no_match_returns_unchanged(self):
        body = "Reference [Completely Unknown Title Here]."
        sources = [{"url": "https://a.com", "title": "Totally Different Source"}]
        result = _relink_orphaned_brackets(body, sources)
        assert result == body

    def test_case_insensitive_matching(self):
        body = "See [ai market report] for details."
        sources = [{"url": "https://example.com", "title": "AI Market Report"}]
        result = _relink_orphaned_brackets(body, sources)
        assert "[ai market report](https://example.com)" in result

    def test_integration_with_normalize_section(self):
        """Orphaned brackets should be relinked during normalization."""
        section_data = {
            "title": "Topic",
            "body_markdown": "Finding [Real Source Title]. More text here.",
            "sources": [
                {"url": "https://real.com/article", "title": "Real Source Title"},
            ],
        }
        raw = json.dumps(
            {
                "executive_summary": [{"topic": "Topic", "summary": "S"}],
                "sections": [section_data],
            }
        )
        result = parse_synthesis_output(raw, ["Topic"])
        body = result["synthesis_0"]["body_markdown"]
        assert "[Real Source Title](https://real.com/article)" in body


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


class TestFixNestedLinks:
    """Tests for _fix_nested_links: [[Title](URL)](URL) flattening."""

    def test_flattens_nested_link(self):
        md = "text [[Title Here](https://inner.com)](https://outer.com). more"
        result = _fix_nested_links(md)
        assert result == "text [Title Here](https://inner.com). more"

    def test_multiple_nested_links(self):
        md = (
            "[[Alpha Source](https://a.com)](https://a.com) and "
            "[[Beta Source](https://b.com)](https://b.com)."
        )
        result = _fix_nested_links(md)
        assert "[[" not in result
        assert "[Alpha Source](https://a.com)" in result
        assert "[Beta Source](https://b.com)" in result

    def test_no_nested_links_unchanged(self):
        md = "Normal [link](https://example.com) text."
        assert _fix_nested_links(md) == md

    def test_empty_input(self):
        assert _fix_nested_links("") == ""
        assert _fix_nested_links(None) is None


class TestFixSplitLinks:
    """Tests for _fix_split_links: [Title]\\n(URL) joining."""

    def test_joins_newline_split(self):
        md = "[Advanced RAG Techniques]\n(https://example.com). Next."
        result = _fix_split_links(md)
        assert result == "[Advanced RAG Techniques](https://example.com). Next."

    def test_joins_space_split(self):
        md = "[Advanced RAG Techniques] (https://example.com). Next."
        result = _fix_split_links(md)
        assert result == "[Advanced RAG Techniques](https://example.com). Next."

    def test_no_split_links_unchanged(self):
        md = "[Title](https://example.com) normal link."
        assert _fix_split_links(md) == md

    def test_short_titles_not_matched(self):
        md = "[Short]\n(https://example.com)"
        assert _fix_split_links(md) == md

    def test_empty_input(self):
        assert _fix_split_links("") == ""


class TestFixBareCloseBrackets:
    """Tests for _fix_bare_close_brackets: Title](URL) repair."""

    def test_fixes_with_source_title_match(self):
        sources = [
            {"url": "https://example.com/article",
             "title": "Why GenAI Pilots Fail: Enterprise RAG Challenges"},
        ]
        md = (
            'data "AI-ready" '
            "Why GenAI Pilots Fail: Enterprise RAG Challenges]"
            "(https://example.com/article). More text."
        )
        result = _fix_bare_close_brackets(md, sources)
        assert "[Why GenAI Pilots Fail: Enterprise RAG Challenges]" in result

    def test_fixes_with_boundary_heuristic(self):
        md = (
            "First sentence ends. "
            "Forbes AI Newsletter Weekly Roundup]"
            "(https://example.com). Next."
        )
        result = _fix_bare_close_brackets(md)
        assert "[Forbes AI Newsletter Weekly Roundup]" in result

    def test_preserves_proper_links(self):
        md = "Normal [Title Here](https://example.com) stays intact."
        assert _fix_bare_close_brackets(md) == md

    def test_no_bare_brackets_unchanged(self):
        md = "Plain text without any brackets or URLs."
        assert _fix_bare_close_brackets(md) == md

    def test_empty_input(self):
        assert _fix_bare_close_brackets("") == ""

    def test_multiple_bare_brackets(self):
        sources = [
            {"url": "https://a.com", "title": "Source Alpha Reference Guide"},
            {"url": "https://b.com", "title": "Source Beta Technical Review"},
        ]
        md = (
            "Finding Source Alpha Reference Guide](https://a.com). "
            "Also Source Beta Technical Review](https://b.com)."
        )
        result = _fix_bare_close_brackets(md, sources)
        assert "[Source Alpha Reference Guide](https://a.com)" in result
        assert "[Source Beta Technical Review](https://b.com)" in result


class TestNormalizeSectionAllFixes:
    """Integration test: all fix functions applied via normalize_synthesis_section."""

    def test_all_fix_patterns_in_one_section(self):
        section = {
            "title": "Test Topic",
            "body_markdown": (
                "Nested [[Title A - Machine Learning Advances](https://a.com)](https://a.com). "
                "Bare Title B - Enterprise RAG Solutions](https://b.com). "
                "Split [Title C - Generative AI Research]\n(https://c.com). "
                "Orphan [Title D - Autonomous Agent Frameworks]. "
                "Good [Title E - Small Language Models](https://e.com)."
            ),
            "sources": [
                {"url": "https://a.com", "title": "Title A - Machine Learning Advances"},
                {"url": "https://b.com", "title": "Title B - Enterprise RAG Solutions"},
                {"url": "https://c.com", "title": "Title C - Generative AI Research"},
                {"url": "https://d.com", "title": "Title D - Autonomous Agent Frameworks"},
                {"url": "https://e.com", "title": "Title E - Small Language Models"},
            ],
        }
        raw = json.dumps({
            "executive_summary": [{"topic": "Test Topic", "summary": "S"}],
            "sections": [section],
        })
        result = parse_synthesis_output(raw, ["Test Topic"])
        body = result["synthesis_0"]["body_markdown"]

        # All patterns should produce valid [Title](URL) markdown
        assert "[[" not in body, "Nested links not flattened"
        assert "[Title A - Machine Learning Advances](https://a.com)" in body
        assert "[Title B - Enterprise RAG Solutions](https://b.com)" in body
        assert "[Title C - Generative AI Research](https://c.com)" in body
        assert "[Title D - Autonomous Agent Frameworks](https://d.com)" in body
        assert "[Title E - Small Language Models](https://e.com)" in body
