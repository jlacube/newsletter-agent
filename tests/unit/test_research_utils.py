"""Unit tests for research result parsing utilities.

Spec refs: Section 11.1, FR-012, Section 7.3, Section 7.4.
"""

import json

import pytest

from newsletter_agent.tools.research_utils import parse_research_result


class TestParseResearchResultJson:

    def test_valid_json_result(self):
        raw = json.dumps({
            "text": "AI is evolving",
            "sources": [{"url": "https://example.com", "title": "Example"}],
            "provider": "perplexity",
        })
        result = parse_research_result(raw, "perplexity")
        assert result["text"] == "AI is evolving"
        assert len(result["sources"]) == 1
        assert result["provider"] == "perplexity"

    def test_json_error_result(self):
        raw = json.dumps({
            "error": True,
            "message": "Rate limited",
            "provider": "perplexity",
        })
        result = parse_research_result(raw, "perplexity")
        assert result["error"] is True
        assert result["message"] == "Rate limited"

    def test_json_sources_as_url_strings(self):
        raw = json.dumps({
            "text": "Content",
            "sources": ["https://example.com", "https://other.com"],
        })
        result = parse_research_result(raw, "google")
        assert len(result["sources"]) == 2
        assert result["sources"][0]["url"] == "https://example.com"


class TestParseResearchResultStructured:

    def test_summary_and_sources_format(self):
        raw = """SUMMARY:
Recent developments in AI frameworks show significant progress.
LangChain has released version 0.3 with major improvements.

SOURCES:
- [LangChain v0.3 Release](https://langchain.com/blog/v03)
- [ADK Documentation](https://google.github.io/adk-docs/)
"""
        result = parse_research_result(raw, "google")
        assert "LangChain" in result["text"]
        assert len(result["sources"]) == 2
        assert result["sources"][0]["url"] == "https://langchain.com/blog/v03"
        assert result["provider"] == "google"

    def test_findings_header_also_parsed(self):
        raw = """FINDINGS:
Some research findings here.

SOURCES:
- [Source](https://example.com)
"""
        result = parse_research_result(raw, "google")
        assert "findings" in result["text"].lower()


class TestParseResearchResultFallback:

    def test_plain_text_with_markdown_links(self):
        raw = "AI is great. See [Example](https://example.com) for details."
        result = parse_research_result(raw, "google")
        assert result["text"] == raw.strip()
        assert len(result["sources"]) == 1
        assert result["sources"][0]["url"] == "https://example.com"

    def test_plain_text_no_links(self):
        raw = "Just plain text about AI with no links."
        result = parse_research_result(raw, "google")
        assert result["text"] == raw
        assert result["sources"] == []

    def test_empty_output(self):
        result = parse_research_result("", "google")
        assert result["error"] is True
        assert result["provider"] == "google"

    def test_none_output(self):
        result = parse_research_result(None, "perplexity")
        assert result["error"] is True

    def test_whitespace_only_output(self):
        result = parse_research_result("   \n  ", "google")
        assert result["error"] is True

    def test_duplicate_sources_deduplicated(self):
        raw = json.dumps({
            "text": "Content",
            "sources": [
                {"url": "https://example.com", "title": "A"},
                {"url": "https://example.com", "title": "B"},
                {"url": "https://other.com", "title": "C"},
            ],
        })
        result = parse_research_result(raw, "google")
        assert len(result["sources"]) == 2

    def test_provider_always_set(self):
        result = parse_research_result("some text", "custom_provider")
        assert result["provider"] == "custom_provider"


class TestParseResearchResultEdgeCases:

    def test_invalid_urls_filtered_from_sources(self):
        raw = json.dumps({
            "text": "Content",
            "sources": [
                {"url": "ftp://invalid.com", "title": "FTP"},
                {"url": "javascript:alert(1)", "title": "XSS"},
                {"url": "not-a-url", "title": "Bad"},
                {"url": "https://valid.com", "title": "Good"},
            ],
        })
        result = parse_research_result(raw, "google")
        assert len(result["sources"]) == 1
        assert result["sources"][0]["url"] == "https://valid.com"

    def test_very_long_text_preserved(self):
        long_text = "A" * 50000
        raw = json.dumps({"text": long_text, "sources": []})
        result = parse_research_result(raw, "perplexity")
        assert len(result["text"]) == 50000
        assert "error" not in result

    def test_special_characters_in_source_titles(self):
        raw = json.dumps({
            "text": "Content",
            "sources": [
                {"url": "https://example.com", "title": "O'Reilly & Sons <2024>"},
                {"url": "https://other.com", "title": 'Title with "quotes"'},
            ],
        })
        result = parse_research_result(raw, "google")
        assert len(result["sources"]) == 2
        assert result["sources"][0]["title"] == "O'Reilly & Sons <2024>"
        assert result["sources"][1]["title"] == 'Title with "quotes"'
