"""
Unit tests for HTML file output.

Spec refs: Section 11.1, FR-034, FR-035.
"""

from pathlib import Path

from newsletter_agent.tools.file_output import save_newsletter_html


class TestSaveToExistingDir:
    def test_saves_file(self, tmp_path):
        result = save_newsletter_html("<h1>Test</h1>", str(tmp_path), "2026-03-14")
        assert Path(result).exists()
        assert Path(result).read_text(encoding="utf-8") == "<h1>Test</h1>"

    def test_correct_filename(self, tmp_path):
        result = save_newsletter_html("<h1>Test</h1>", str(tmp_path), "2026-03-14")
        assert result.endswith("2026-03-14-newsletter.html")


class TestAutoCreateDir:
    def test_creates_nested_dirs(self, tmp_path):
        nested = str(tmp_path / "new" / "nested" / "dir")
        result = save_newsletter_html("<h1>Test</h1>", nested, "2026-01-01")
        assert Path(result).exists()

    def test_returns_absolute_path(self, tmp_path):
        result = save_newsletter_html("<h1>Test</h1>", str(tmp_path), "2026-01-01")
        assert Path(result).is_absolute()


class TestOverwrite:
    def test_overwrites_existing_file(self, tmp_path):
        save_newsletter_html("<h1>First</h1>", str(tmp_path), "2026-03-14")
        result = save_newsletter_html("<h1>Second</h1>", str(tmp_path), "2026-03-14")
        assert Path(result).read_text(encoding="utf-8") == "<h1>Second</h1>"


class TestUtf8Encoding:
    def test_special_characters(self, tmp_path):
        html = "<p>Cafe in Munchen - 2026</p>"
        result = save_newsletter_html(html, str(tmp_path), "2026-03-14")
        assert Path(result).read_text(encoding="utf-8") == html
