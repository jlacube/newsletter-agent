"""
Unit tests for HTML sanitizer.

Tests XSS payloads, markdown conversion, and tag filtering.
Spec refs: Section 11.6, Section 10.2.
"""

import pytest

from newsletter_agent.tools.sanitizer import sanitize_synthesis_html


class TestMarkdownConversion:
    def test_inline_link_conversion(self):
        result = sanitize_synthesis_html("[Example](https://example.com)")
        assert 'href="https://example.com"' in result
        assert ">Example</a>" in result

    def test_bold_conversion(self):
        result = sanitize_synthesis_html("**bold text**")
        assert "<strong>bold text</strong>" in result

    def test_italic_conversion(self):
        result = sanitize_synthesis_html("*italic text*")
        assert "<em>italic text</em>" in result

    def test_paragraph_conversion(self):
        result = sanitize_synthesis_html("First paragraph.\n\nSecond paragraph.")
        assert "<p>" in result

    def test_empty_input(self):
        assert sanitize_synthesis_html("") == ""

    def test_none_like_empty(self):
        assert sanitize_synthesis_html("") == ""


class TestAllowedTags:
    def test_a_tag_preserved(self):
        html = '<a href="https://example.com">link</a>'
        result = sanitize_synthesis_html(html)
        assert "https://example.com" in result
        assert "link" in result

    def test_p_tag_preserved(self):
        result = sanitize_synthesis_html("Some text in a paragraph.")
        assert "<p>" in result

    def test_strong_preserved(self):
        result = sanitize_synthesis_html("**bold**")
        assert "<strong>" in result

    def test_em_preserved(self):
        result = sanitize_synthesis_html("*italic*")
        assert "<em>" in result

    def test_list_tags_preserved(self):
        md = "- item 1\n- item 2"
        result = sanitize_synthesis_html(md)
        assert "<li>" in result


class TestXssPayloads:
    def test_script_tag_stripped(self):
        result = sanitize_synthesis_html('<script>alert("xss")</script>')
        assert "<script>" not in result
        assert "alert" not in result.lower() or "script" not in result.lower()

    def test_javascript_url_stripped(self):
        result = sanitize_synthesis_html('<a href="javascript:alert(\'xss\')">click</a>')
        assert "javascript:" not in result

    def test_img_onerror_stripped(self):
        result = sanitize_synthesis_html('<img src=x onerror=alert("xss")>')
        assert "onerror" not in result
        # img tag itself is not allowed
        assert "<img" not in result

    def test_div_onmouseover_stripped(self):
        result = sanitize_synthesis_html('<div onmouseover="alert(\'xss\')">hover</div>')
        assert "onmouseover" not in result

    def test_data_uri_stripped(self):
        result = sanitize_synthesis_html(
            '<a href="data:text/html,<script>alert(1)</script>">data</a>'
        )
        assert "data:" not in result

    def test_svg_onload_stripped(self):
        result = sanitize_synthesis_html('<svg onload=alert("xss")>')
        assert "<svg" not in result
        assert "onload" not in result

    def test_iframe_stripped(self):
        result = sanitize_synthesis_html('<iframe src="https://evil.com"></iframe>')
        assert "<iframe" not in result

    def test_form_stripped(self):
        result = sanitize_synthesis_html('<form action="https://evil.com"><input></form>')
        assert "<form" not in result

    def test_object_stripped(self):
        result = sanitize_synthesis_html('<object data="evil.swf"></object>')
        assert "<object" not in result

    def test_embed_stripped(self):
        result = sanitize_synthesis_html('<embed src="evil.swf">')
        assert "<embed" not in result

    def test_nested_script_in_markdown(self):
        result = sanitize_synthesis_html(
            'Normal text <script>document.cookie</script> more text'
        )
        assert "<script>" not in result


class TestUrlSchemes:
    def test_https_allowed(self):
        result = sanitize_synthesis_html('[Link](https://example.com)')
        assert "https://example.com" in result

    def test_http_allowed(self):
        result = sanitize_synthesis_html('[Link](http://example.com)')
        assert "http://example.com" in result

    def test_javascript_scheme_blocked(self):
        result = sanitize_synthesis_html('<a href="javascript:void(0)">x</a>')
        assert "javascript:" not in result

    def test_data_scheme_blocked(self):
        result = sanitize_synthesis_html('<a href="data:text/html,test">x</a>')
        assert "data:" not in result
