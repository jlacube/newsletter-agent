"""
BDD-style acceptance tests for synthesis and formatting.

Uses Given/When/Then structure to verify spec scenarios.
Spec refs: Section 11.2, US-03, US-04, US-08.
"""

import json

import pytest

from newsletter_agent.tools.synthesis_utils import parse_synthesis_output
from newsletter_agent.tools.sanitizer import sanitize_synthesis_html
from newsletter_agent.tools.formatter import render_newsletter


def _build_synthesis_json(
    topics, word_count=250, citation_count=3, include_summary=True
):
    """Build realistic synthesis JSON for testing."""
    summary = []
    sections = []
    for i, name in enumerate(topics):
        words = " ".join(["analysis"] * word_count)
        citations = " ".join(
            f"[Source{j}](https://example.com/{i}/{j})"
            for j in range(citation_count)
        )
        body = f"{words} {citations}"
        sources = [
            {"url": f"https://example.com/{i}/{j}", "title": f"Source{j}"}
            for j in range(citation_count)
        ]
        sections.append({
            "title": name,
            "body_markdown": body,
            "sources": sources,
        })
        if include_summary:
            summary.append({"topic": name, "summary": f"Key findings for {name}."})
    return json.dumps({"executive_summary": summary, "sections": sections})


class TestDeepAnalysisWithCitations:
    """Feature: Synthesis
    Scenario: Deep analysis with citations
    """

    def test_given_research_when_parsed_then_body_at_least_200_words(self):
        """
        Given completed research for a topic from both Google and Perplexity
        When the synthesis output is parsed
        Then the body_markdown is at least 200 words
        """
        raw = _build_synthesis_json(["AI Frameworks"], word_count=250)
        result = parse_synthesis_output(raw, ["AI Frameworks"])
        body = result["synthesis_0"]["body_markdown"]
        word_count = len(body.split())
        assert word_count >= 200

    def test_given_research_when_parsed_then_at_least_3_citations(self):
        """
        Given completed research for a topic
        When the synthesis output is parsed
        Then the section has at least 3 inline citations
        """
        raw = _build_synthesis_json(["AI Frameworks"], citation_count=4)
        result = parse_synthesis_output(raw, ["AI Frameworks"])
        sources = result["synthesis_0"]["sources"]
        assert len(sources) >= 3


class TestSynthesisWithPartialResearch:
    """Feature: Synthesis
    Scenario: Synthesis with partial research data
    """

    def test_given_partial_data_when_parsed_then_still_produces_output(self):
        """
        Given research from only one provider for a topic
        When the synthesis output indicates limited data
        Then output is still produced with available content
        """
        sections = [{
            "title": "AI",
            "body_markdown": "Limited analysis from single source. " + ("word " * 50),
            "sources": [{"url": "https://example.com", "title": "Single Source"}],
        }]
        raw = json.dumps({
            "executive_summary": [{"topic": "AI", "summary": "Limited data."}],
            "sections": sections,
        })
        result = parse_synthesis_output(raw, ["AI"])
        assert result["synthesis_0"]["body_markdown"]
        assert len(result["synthesis_0"]["sources"]) >= 1


class TestSynthesisWithNoResearchData:
    """Feature: Synthesis
    Scenario: Synthesis with no research data
    """

    def test_given_no_research_when_parsed_then_unavailable_message(self):
        """
        Given no research data for any topic
        When the synthesis output indicates failure
        Then fallback messages are produced
        """
        result = parse_synthesis_output("", ["AI", "Cloud"])
        assert "synthesis_0" in result
        assert "synthesis_1" in result
        # Should have fallback content, not empty
        assert result["synthesis_0"]["body_markdown"]


class TestCompleteHtmlNewsletter:
    """Feature: Newsletter Formatting
    Scenario: Complete HTML newsletter with all sections
    """

    def test_given_synthesis_when_rendered_then_all_sections_present(self):
        """
        Given valid synthesis data for 3 topics
        When the newsletter is rendered
        Then the HTML contains all required sections in correct order
        """
        topics = ["AI", "Cloud", "Security"]
        raw = _build_synthesis_json(topics)
        parsed = parse_synthesis_output(raw, topics)

        sections = []
        all_sources = []
        for i, name in enumerate(topics):
            sec = parsed[f"synthesis_{i}"]
            body_html = sanitize_synthesis_html(sec["body_markdown"])
            sections.append({
                "title": sec["title"],
                "body_html": body_html,
                "sources": sec["sources"],
            })
            all_sources.extend(sec["sources"])

        html = render_newsletter({
            "newsletter_title": "Test Newsletter",
            "newsletter_date": "2026-01-01",
            "executive_summary": parsed["executive_summary"],
            "sections": sections,
            "all_sources": all_sources,
            "generation_time_seconds": 60.0,
        })

        # Verify all sections present in order
        assert "Test Newsletter" in html
        assert "Executive Summary" in html
        assert "In This Issue" in html
        for name in topics:
            assert name in html
        assert "All Sources" in html
        assert "Generated by Newsletter Agent" in html

        # Verify order
        positions = [
            html.find("Test Newsletter"),
            html.find("Executive Summary"),
            html.find("In This Issue"),
            html.find('id="section-0"'),
            html.find("All Sources"),
            html.find("Generated by Newsletter Agent"),
        ]
        assert positions == sorted(positions)


class TestExecutiveSummaryGeneration:
    """Feature: Synthesis
    Scenario: Executive summary generation
    """

    def test_given_topics_when_parsed_then_summary_per_topic(self):
        """
        Given synthesis for 3 topics
        When parsed and rendered
        Then executive summary has one entry per topic
        """
        topics = ["AI", "Cloud", "Security"]
        raw = _build_synthesis_json(topics)
        parsed = parse_synthesis_output(raw, topics)
        summary = parsed["executive_summary"]
        assert len(summary) == 3
        for item in summary:
            assert "topic" in item
            assert "summary" in item
            assert len(item["summary"]) > 0


class TestResponsiveLayout:
    """Feature: Newsletter Formatting
    Scenario: Responsive layout verification
    """

    def test_given_rendered_html_then_max_width_600px(self):
        """
        Given a rendered newsletter
        Then the layout uses max-width 600px
        """
        topics = ["AI"]
        raw = _build_synthesis_json(topics)
        parsed = parse_synthesis_output(raw, topics)

        sec = parsed["synthesis_0"]
        html = render_newsletter({
            "newsletter_title": "Test",
            "newsletter_date": "2026-01-01",
            "executive_summary": parsed["executive_summary"],
            "sections": [{
                "title": sec["title"],
                "body_html": sanitize_synthesis_html(sec["body_markdown"]),
                "sources": sec["sources"],
            }],
            "all_sources": sec["sources"],
            "generation_time_seconds": 10.0,
        })

        assert "max-width: 600px" in html
        assert "<!DOCTYPE html>" in html
