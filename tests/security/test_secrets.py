"""Security tests for the Newsletter Agent.

Verifies secrets protection, XSS prevention, and credential safety.
Spec refs: Section 10.2, Section 11.6.
"""

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class TestSecretsNotInCode:
    """Verify no secrets are committed to version control."""

    def test_env_file_in_gitignore(self):
        gitignore = PROJECT_ROOT / ".gitignore"
        assert gitignore.exists(), ".gitignore must exist"
        content = gitignore.read_text()
        assert ".env" in content

    def test_token_json_in_gitignore(self):
        gitignore = PROJECT_ROOT / ".gitignore"
        content = gitignore.read_text()
        assert "token.json" in content

    def test_no_api_keys_in_committed_files(self):
        """Scan code files for patterns that look like real API keys."""
        suspicious_patterns = [
            r"AIza[0-9A-Za-z\-_]{35}",  # Google API key
            r"pplx-[a-z0-9]{48}",  # Perplexity API key
            r"ya29\.[0-9A-Za-z\-_]+",  # Google OAuth2 access token
            r"1//[0-9A-Za-z\-_]{20,}",  # Google refresh token
        ]
        code_files = (
            list(PROJECT_ROOT.rglob("*.py"))
            + list(PROJECT_ROOT.rglob("*.yaml"))
            + list(PROJECT_ROOT.rglob("*.yml"))
        )
        for filepath in code_files:
            rel = filepath.relative_to(PROJECT_ROOT)
            if ".env" in str(rel) or "node_modules" in str(rel):
                continue
            content = filepath.read_text(errors="ignore")
            for pattern in suspicious_patterns:
                matches = re.findall(pattern, content)
                assert not matches, (
                    f"Potential API key in {rel}: {matches[0][:10]}..."
                )

    def test_no_client_secret_in_code(self):
        # Build pattern dynamically to avoid this test file matching itself
        prefix = "GOCSPX"
        pattern = prefix + "-"
        code_files = list(PROJECT_ROOT.rglob("*.py"))
        for filepath in code_files:
            if "test_secrets" in filepath.name:
                continue
            content = filepath.read_text(errors="ignore")
            assert pattern not in content, (
                f"Potential client secret in {filepath.relative_to(PROJECT_ROOT)}"
            )


class TestXssPrevention:
    """Verify XSS prevention in HTML output."""

    def test_jinja2_environment_has_autoescape(self):
        from newsletter_agent.tools.formatter import _jinja_env

        assert _jinja_env.autoescape is True

    def test_xss_payload_in_title_is_escaped(self):
        from newsletter_agent.tools.formatter import render_newsletter

        xss_payload = "<script>alert('xss')</script>"
        html = render_newsletter(
            {
                "newsletter_title": xss_payload,
                "newsletter_date": "2025-01-01",
                "executive_summary": [],
                "sections": [],
                "all_sources": [],
                "generation_time_seconds": 0.0,
            }
        )
        assert "<script>" not in html
        assert "&lt;script&gt;" in html or "alert" not in html

    def test_xss_payload_in_section_body_is_sanitized(self):
        """Content goes through nh3 sanitizer before rendering."""
        from newsletter_agent.tools.sanitizer import sanitize_synthesis_html

        xss_input = "<script>alert('xss')</script><p>Safe content</p>"
        sanitized = sanitize_synthesis_html(xss_input)
        assert "<script>" not in sanitized
        assert "Safe content" in sanitized


class TestErrorMessageSafety:
    """Verify error messages do not leak credentials."""

    def test_gmail_auth_error_does_not_leak_creds(self):
        from newsletter_agent.tools.gmail_auth import GmailAuthError

        error = GmailAuthError("Missing GMAIL_CLIENT_ID")
        error_str = str(error)
        # Build patterns dynamically to avoid self-match
        assert "GOCSPX" + "-" not in error_str
        assert "ya29" + "." not in error_str
