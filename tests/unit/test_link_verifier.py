"""Unit tests for newsletter_agent.tools.link_verifier.

Covers LinkCheckResult, verify_urls(), SSRF protection, streaming GET with
title extraction, soft-404 detection, and clean_broken_links_from_markdown().

Spec refs: Section 11.1, Section 11.5, Section 11.6.
"""

import asyncio
import ssl
from dataclasses import FrozenInstanceError
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from newsletter_agent.tools.link_verifier import (
    LinkCheckResult,
    _check_one_url,
    _is_private_ip,
    _is_google_grounding_redirect,
    _check_scheme,
    _extract_title,
    _is_soft_404,
    _is_soft_404_body,
    clean_broken_links_from_markdown,
    verify_urls,
)


def _html(title: str = "Test Article", body: str = "content") -> str:
    """Build a minimal HTML page with the given title."""
    return f"<html><head><title>{title}</title></head><body>{body}</body></html>"


# ---------------------------------------------------------------------------
# LinkCheckResult dataclass tests
# ---------------------------------------------------------------------------
class TestLinkCheckResult:
    def test_valid_result(self):
        r = LinkCheckResult(url="https://example.com", status="valid", http_status=200)
        assert r.url == "https://example.com"
        assert r.status == "valid"
        assert r.http_status == 200
        assert r.error is None
        assert r.page_title is None

    def test_broken_result(self):
        r = LinkCheckResult(
            url="https://broken.com", status="broken", http_status=404, error="status_404"
        )
        assert r.status == "broken"
        assert r.http_status == 404
        assert r.error == "status_404"

    def test_frozen_immutability(self):
        r = LinkCheckResult(url="https://example.com", status="valid")
        with pytest.raises(FrozenInstanceError):
            r.status = "broken"

    def test_defaults(self):
        r = LinkCheckResult(url="https://x.com", status="broken")
        assert r.http_status is None
        assert r.error is None
        assert r.page_title is None

    def test_page_title_field(self):
        r = LinkCheckResult(
            url="https://x.com", status="valid", http_status=200,
            page_title="My Article",
        )
        assert r.page_title == "My Article"


# ---------------------------------------------------------------------------
# Title extraction tests
# ---------------------------------------------------------------------------
class TestTitleExtraction:
    def test_basic_title(self):
        assert _extract_title("<title>Hello World</title>") == "Hello World"

    def test_title_with_whitespace(self):
        assert _extract_title("<title>  Hello   World  </title>") == "Hello World"

    def test_title_with_newlines(self):
        assert _extract_title("<title>\n  My\n  Page\n</title>") == "My Page"

    def test_title_with_entities(self):
        assert _extract_title("<title>A &amp; B</title>") == "A & B"

    def test_title_case_insensitive(self):
        assert _extract_title("<TITLE>Test</TITLE>") == "Test"

    def test_no_title(self):
        assert _extract_title("<html><body>No title</body></html>") is None

    def test_empty_title(self):
        assert _extract_title("<title></title>") is None

    def test_title_with_attributes(self):
        assert _extract_title('<title lang="en">Page</title>') == "Page"


class TestSoft404Detection:
    def test_not_found_title(self):
        assert _is_soft_404("Page Not Found") is True

    def test_404_in_title(self):
        assert _is_soft_404("404 - Page does not exist") is True

    def test_removed(self):
        assert _is_soft_404("Article has been removed") is True

    def test_access_denied(self):
        assert _is_soft_404("Access Denied") is True

    def test_captcha(self):
        assert _is_soft_404("Attention Required | Cloudflare") is True

    def test_just_a_moment(self):
        assert _is_soft_404("Just a moment...") is True

    def test_normal_title(self):
        assert _is_soft_404("AI Revolutionizes Healthcare - TechNews") is False

    def test_none_title(self):
        assert _is_soft_404(None) is False

    def test_empty_title(self):
        assert _is_soft_404("") is False

    def test_sign_in(self):
        assert _is_soft_404("Sign In Required") is True

    def test_server_error(self):
        assert _is_soft_404("Internal Server Error") is True


class TestSoft404BodyDetection:
    """Tests for _is_soft_404_body which scans heading/body content for hidden 404s."""

    def test_heading_page_not_found(self):
        html = "<html><body><h1>Page not found</h1></body></html>"
        assert _is_soft_404_body(html) is True

    def test_heading_404_error(self):
        html = "<html><body><h1>404: Not Found</h1><p>lorem ipsum</p></body></html>"
        assert _is_soft_404_body(html) is True

    def test_heading_content_unavailable(self):
        html = "<html><body><h2>This page is no longer available</h2></body></html>"
        assert _is_soft_404_body(html) is True

    def test_heading_could_not_find(self):
        html = "<html><body><h1>We couldn't find this page</h1></body></html>"
        assert _is_soft_404_body(html) is True

    def test_heading_requested_page_not_found(self):
        html = "<html><body><h1>The requested page was not found</h1></body></html>"
        assert _is_soft_404_body(html) is True

    def test_short_body_error_text(self):
        html = "<html><body>Sorry, this content is no longer available.</body></html>"
        assert _is_soft_404_body(html) is True

    def test_short_body_google_grounding_style(self):
        """Simulates a Google Grounding redirect that returns 200 with error body."""
        html = (
            "<html><head><title>Google</title></head>"
            "<body><p>The requested URL was not found on this server.</p>"
            "<p>That's all we know.</p></body></html>"
        )
        # Title is "Google" (passes title check), but body reveals the 404
        assert _is_soft_404(_extract_title(html)) is False
        assert _is_soft_404_body(html) is True

    def test_normal_page_not_flagged(self):
        html = (
            "<html><head><title>AI News</title></head>"
            "<body><h1>AI Transforms Healthcare</h1>"
            "<p>Artificial intelligence is revolutionizing the healthcare industry...</p>"
            "</body></html>"
        )
        assert _is_soft_404_body(html) is False

    def test_long_page_with_404_mention_not_flagged(self):
        """A long article that mentions '404' casually should not be flagged."""
        filler = "Lorem ipsum dolor sit amet. " * 100
        html = (
            f"<html><body><h1>Web Development Tips</h1>"
            f"<p>{filler}</p>"
            f"<p>Make sure your site returns a proper 404 page for missing URLs.</p>"
            f"<p>{filler}</p></body></html>"
        )
        assert _is_soft_404_body(html) is False

    def test_empty_body(self):
        assert _is_soft_404_body("") is False

    def test_none_body(self):
        assert _is_soft_404_body(None) is False

    def test_h3_heading_error(self):
        html = "<html><body><h3>Error 404 - page not found</h3></body></html>"
        assert _is_soft_404_body(html) is True

    def test_h4_heading_not_checked(self):
        """Only h1-h3 are checked - h4 error heading should not trigger."""
        html = "<html><body><h4>Page not found</h4>" + ("x " * 1000) + "</body></html>"
        assert _is_soft_404_body(html) is False
class TestSSRFProtection:
    def test_loopback_ipv4(self):
        assert _is_private_ip("127.0.0.1") is True

    def test_private_10_range(self):
        assert _is_private_ip("10.0.0.1") is True

    def test_private_172_range(self):
        assert _is_private_ip("172.16.0.1") is True

    def test_private_192_range(self):
        assert _is_private_ip("192.168.1.1") is True

    def test_ipv6_loopback(self):
        assert _is_private_ip("::1") is True

    def test_ipv6_private(self):
        assert _is_private_ip("fc00::1") is True

    def test_public_ip(self):
        assert _is_private_ip("8.8.8.8") is False

    def test_empty_host(self):
        assert _is_private_ip("") is False

    def test_scheme_http(self):
        assert _check_scheme("http://example.com") is True

    def test_scheme_https(self):
        assert _check_scheme("https://example.com") is True

    def test_scheme_ftp(self):
        assert _check_scheme("ftp://example.com") is False

    def test_scheme_javascript(self):
        assert _check_scheme("javascript:alert(1)") is False

    def test_scheme_file(self):
        assert _check_scheme("file:///etc/passwd") is False


class TestGoogleGroundingRedirects:
    def test_detects_google_grounding_redirect(self):
        url = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/ABC123"
        assert _is_google_grounding_redirect(url) is True

    def test_non_grounding_url_not_detected(self):
        url = "https://example.com/grounding-api-redirect/ABC123"
        assert _is_google_grounding_redirect(url) is False


# ---------------------------------------------------------------------------
# verify_urls() tests
# ---------------------------------------------------------------------------
class TestVerifyUrls:
    @pytest.mark.asyncio
    async def test_empty_list(self):
        result = await verify_urls([])
        assert result == {}

    @pytest.mark.asyncio
    async def test_valid_200_with_title(self, respx_mock):
        respx_mock.get("https://example.com/page").mock(
            return_value=httpx.Response(200, html=_html("My Article"))
        )
        results = await verify_urls(["https://example.com/page"])
        r = results["https://example.com/page"]
        assert r.status == "valid"
        assert r.http_status == 200
        assert r.error is None
        assert r.page_title == "My Article"

    @pytest.mark.asyncio
    async def test_google_grounding_redirect_follows_to_destination(self, respx_mock):
        url = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/ABC123"
        # Grounding redirect follows to real article
        respx_mock.get(url).mock(
            return_value=httpx.Response(
                302,
                headers={"Location": "https://example.com/real-article"},
            )
        )
        respx_mock.get("https://example.com/real-article").mock(
            return_value=httpx.Response(200, html=_html("Real Article"))
        )
        results = await verify_urls([url])
        r = results[url]
        assert r.status == "valid"

    @pytest.mark.asyncio
    async def test_google_grounding_redirect_broken_destination(self, respx_mock):
        url = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/EXPIRED"
        respx_mock.get(url).mock(
            return_value=httpx.Response(404, html=_html("Not Found"))
        )
        results = await verify_urls([url])
        r = results[url]
        assert r.status == "broken"

    @pytest.mark.asyncio
    async def test_google_grounding_redirect_network_error_treated_valid(self, respx_mock):
        url = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/NETERR"
        respx_mock.get(url).mock(side_effect=httpx.ConnectError("connection refused"))
        results = await verify_urls([url])
        r = results[url]
        # Network errors on grounding redirects are treated as valid
        # (redirect server may be temporarily down)
        assert r.status == "valid"

    @pytest.mark.asyncio
    async def test_redirect_301_to_200(self, respx_mock):
        respx_mock.get("https://example.com/old").mock(
            return_value=httpx.Response(
                301,
                headers={"Location": "https://example.com/new"},
            )
        )
        respx_mock.get("https://example.com/new").mock(
            return_value=httpx.Response(200, html=_html("Redirected"))
        )
        results = await verify_urls(["https://example.com/old"])
        r = results["https://example.com/old"]
        assert r.status == "valid"

    @pytest.mark.asyncio
    async def test_404_broken(self, respx_mock):
        respx_mock.get("https://example.com/gone").mock(
            return_value=httpx.Response(404, html=_html("Not Found"))
        )
        results = await verify_urls(["https://example.com/gone"])
        r = results["https://example.com/gone"]
        assert r.status == "broken"
        assert r.http_status == 404
        assert r.error == "status_404"

    @pytest.mark.asyncio
    async def test_410_gone_broken(self, respx_mock):
        respx_mock.get("https://example.com/old").mock(
            return_value=httpx.Response(410, html=_html("Gone"))
        )
        results = await verify_urls(["https://example.com/old"])
        r = results["https://example.com/old"]
        assert r.status == "broken"
        assert r.http_status == 410
        assert r.error == "status_410"

    @pytest.mark.asyncio
    async def test_500_broken(self, respx_mock):
        respx_mock.get("https://example.com/error").mock(
            return_value=httpx.Response(500, html=_html("Server Error"))
        )
        results = await verify_urls(["https://example.com/error"])
        r = results["https://example.com/error"]
        assert r.status == "broken"
        assert r.http_status == 500
        assert r.error == "status_500"

    @pytest.mark.asyncio
    async def test_timeout(self, respx_mock):
        respx_mock.get("https://example.com/slow").mock(
            side_effect=httpx.ReadTimeout("timed out")
        )
        results = await verify_urls(["https://example.com/slow"])
        r = results["https://example.com/slow"]
        assert r.status == "broken"
        assert r.error == "timeout"
        assert r.http_status is None

    @pytest.mark.asyncio
    async def test_dns_failure(self, respx_mock):
        respx_mock.get("https://nonexistent.invalid/").mock(
            side_effect=httpx.ConnectError("Name resolution failed")
        )
        results = await verify_urls(["https://nonexistent.invalid/"])
        r = results["https://nonexistent.invalid/"]
        assert r.status == "broken"
        assert r.error == "dns_error"

    @pytest.mark.asyncio
    async def test_ssl_error(self, respx_mock):
        respx_mock.get("https://badsssl.com/").mock(
            side_effect=httpx.ConnectError("SSL: CERTIFICATE_VERIFY_FAILED")
        )
        results = await verify_urls(["https://badsssl.com/"])
        r = results["https://badsssl.com/"]
        assert r.status == "broken"
        assert r.error == "ssl_error"

    @pytest.mark.asyncio
    async def test_200_with_normal_title_valid(self, respx_mock):
        """200 response with a real article title should be valid."""
        respx_mock.get("https://example.com/article").mock(
            return_value=httpx.Response(200, html=_html("AI Trends in 2026"))
        )
        results = await verify_urls(["https://example.com/article"])
        r = results["https://example.com/article"]
        assert r.status == "valid"
        assert r.page_title == "AI Trends in 2026"

    @pytest.mark.asyncio
    async def test_soft_404_200_not_found_title(self, respx_mock):
        """200 response but title says 'Page Not Found' - soft 404."""
        respx_mock.get("https://example.com/deleted").mock(
            return_value=httpx.Response(200, html=_html("Page Not Found"))
        )
        results = await verify_urls(["https://example.com/deleted"])
        r = results["https://example.com/deleted"]
        assert r.status == "broken"
        assert r.error == "soft_404"
        assert r.page_title == "Page Not Found"

    @pytest.mark.asyncio
    async def test_soft_404_200_404_in_title(self, respx_mock):
        """200 response with '404' in title detected as soft 404."""
        respx_mock.get("https://example.com/missing").mock(
            return_value=httpx.Response(200, html=_html("404 - Content Removed"))
        )
        results = await verify_urls(["https://example.com/missing"])
        r = results["https://example.com/missing"]
        assert r.status == "broken"
        assert r.error == "soft_404"

    @pytest.mark.asyncio
    async def test_soft_404_captcha_page(self, respx_mock):
        """200 but title shows captcha/bot challenge."""
        respx_mock.get("https://example.com/blocked").mock(
            return_value=httpx.Response(
                200, html=_html("Attention Required | Cloudflare")
            )
        )
        results = await verify_urls(["https://example.com/blocked"])
        r = results["https://example.com/blocked"]
        assert r.status == "broken"
        assert r.error == "soft_404"

    @pytest.mark.asyncio
    async def test_soft_404_body_google_grounding_redirect(self, respx_mock):
        """200 with generic title but body reveals hidden 404 (Google Grounding style)."""
        error_html = (
            "<html><head><title>Google</title></head>"
            "<body><h1>Error 404 (Not Found)</h1>"
            "<p>The requested URL was not found on this server.</p>"
            "</body></html>"
        )
        respx_mock.get("https://example.com/grounding-redirect").mock(
            return_value=httpx.Response(200, html=error_html)
        )
        results = await verify_urls(["https://example.com/grounding-redirect"])
        r = results["https://example.com/grounding-redirect"]
        assert r.status == "broken"
        assert r.error == "soft_404_body"
        assert r.page_title == "Google"

    @pytest.mark.asyncio
    async def test_soft_404_body_hidden_not_found(self, respx_mock):
        """200 with OK title but body heading says content unavailable."""
        error_html = (
            "<html><head><title>Example Site</title></head>"
            "<body><h2>This content is no longer available</h2>"
            "<p>The link you followed may be outdated.</p>"
            "</body></html>"
        )
        respx_mock.get("https://example.com/expired-content").mock(
            return_value=httpx.Response(200, html=error_html)
        )
        results = await verify_urls(["https://example.com/expired-content"])
        r = results["https://example.com/expired-content"]
        assert r.status == "broken"
        assert r.error == "soft_404_body"

    @pytest.mark.asyncio
    async def test_normal_page_not_body_soft_404(self, respx_mock):
        """Normal page with real content should NOT trigger body soft-404."""
        normal_html = (
            "<html><head><title>AI News Today</title></head>"
            "<body><h1>AI Breakthrough in Quantum Computing</h1>"
            "<p>Researchers have made significant progress...</p>"
            "</body></html>"
        )
        respx_mock.get("https://example.com/real-article").mock(
            return_value=httpx.Response(200, html=normal_html)
        )
        results = await verify_urls(["https://example.com/real-article"])
        r = results["https://example.com/real-article"]
        assert r.status == "valid"
        assert r.page_title == "AI News Today"

    @pytest.mark.asyncio
    async def test_403_with_normal_title_valid(self, respx_mock):
        """403 with a real article title (paywall/WAF) treated as valid."""
        respx_mock.get("https://example.com/news").mock(
            return_value=httpx.Response(
                403, html=_html("Premium: AI Market Analysis - TechNews")
            )
        )
        results = await verify_urls(["https://example.com/news"])
        r = results["https://example.com/news"]
        assert r.status == "valid"
        assert r.http_status == 403

    @pytest.mark.asyncio
    async def test_403_with_access_denied_title_broken(self, respx_mock):
        """403 with 'Access Denied' title should be broken."""
        respx_mock.get("https://example.com/denied").mock(
            return_value=httpx.Response(403, html=_html("Access Denied"))
        )
        results = await verify_urls(["https://example.com/denied"])
        r = results["https://example.com/denied"]
        assert r.status == "broken"
        assert r.http_status == 403

    @pytest.mark.asyncio
    async def test_401_with_normal_title_valid(self, respx_mock):
        """401 with a normal page title (paywall) treated as valid."""
        respx_mock.get("https://example.com/premium").mock(
            return_value=httpx.Response(
                401, html=_html("Subscribe to Read - WSJ")
            )
        )
        results = await verify_urls(["https://example.com/premium"])
        r = results["https://example.com/premium"]
        assert r.status == "valid"
        assert r.http_status == 401

    @pytest.mark.asyncio
    async def test_401_with_signin_title_broken(self, respx_mock):
        """401 with 'Sign In Required' title should be broken."""
        respx_mock.get("https://example.com/locked").mock(
            return_value=httpx.Response(401, html=_html("Sign In Required"))
        )
        results = await verify_urls(["https://example.com/locked"])
        r = results["https://example.com/locked"]
        assert r.status == "broken"

    @pytest.mark.asyncio
    async def test_429_rate_limited_valid(self, respx_mock):
        """429 Too Many Requests treated as valid (rate limiter, not broken)."""
        respx_mock.get("https://example.com/rate").mock(
            return_value=httpx.Response(429, html=_html("Rate Limited"))
        )
        results = await verify_urls(["https://example.com/rate"])
        r = results["https://example.com/rate"]
        assert r.status == "valid"
        assert r.http_status == 429

    @pytest.mark.asyncio
    async def test_503_service_unavailable_valid(self, respx_mock):
        """503 Service Unavailable treated as valid (temporary, not dead)."""
        respx_mock.get("https://example.com/maint").mock(
            return_value=httpx.Response(503, html=_html("Maintenance"))
        )
        results = await verify_urls(["https://example.com/maint"])
        r = results["https://example.com/maint"]
        assert r.status == "valid"
        assert r.http_status == 503

    @pytest.mark.asyncio
    async def test_too_many_redirects(self, respx_mock):
        respx_mock.get("https://example.com/loop").mock(
            side_effect=httpx.TooManyRedirects(
                "Exceeded max redirects",
                request=httpx.Request("GET", "https://example.com/loop"),
            )
        )
        results = await verify_urls(["https://example.com/loop"])
        r = results["https://example.com/loop"]
        assert r.status == "broken"
        assert r.error == "redirect_limit"

    @pytest.mark.asyncio
    async def test_private_ip_blocked(self):
        """URLs with private IP hosts are blocked pre-request."""
        results = await verify_urls(["http://127.0.0.1/admin"])
        r = results["http://127.0.0.1/admin"]
        assert r.status == "broken"
        assert r.error == "ssrf_blocked"

    @pytest.mark.asyncio
    async def test_private_10_blocked(self):
        results = await verify_urls(["http://10.0.0.1/internal"])
        r = results["http://10.0.0.1/internal"]
        assert r.status == "broken"
        assert r.error == "ssrf_blocked"

    @pytest.mark.asyncio
    async def test_private_172_blocked(self):
        results = await verify_urls(["http://172.16.0.1/"])
        r = results["http://172.16.0.1/"]
        assert r.status == "broken"
        assert r.error == "ssrf_blocked"

    @pytest.mark.asyncio
    async def test_private_192_blocked(self):
        results = await verify_urls(["http://192.168.1.1/"])
        r = results["http://192.168.1.1/"]
        assert r.status == "broken"
        assert r.error == "ssrf_blocked"

    @pytest.mark.asyncio
    async def test_ipv6_loopback_blocked(self):
        results = await verify_urls(["http://[::1]/"])
        r = results["http://[::1]/"]
        assert r.status == "broken"
        assert r.error == "ssrf_blocked"

    @pytest.mark.asyncio
    async def test_invalid_scheme_blocked(self):
        results = await verify_urls(["ftp://example.com/file"])
        r = results["ftp://example.com/file"]
        assert r.status == "broken"
        assert r.error == "invalid_scheme"

    @pytest.mark.asyncio
    async def test_javascript_scheme_blocked(self):
        results = await verify_urls(["javascript:alert(1)"])
        r = results["javascript:alert(1)"]
        assert r.status == "broken"
        assert r.error == "invalid_scheme"

    @pytest.mark.asyncio
    async def test_invalid_domain_no_dot(self):
        """URLs with no valid domain (hallucinated by LLM) should be blocked."""
        results = await verify_urls(["https://best-frameworks-in-2026/"])
        r = results["https://best-frameworks-in-2026/"]
        assert r.status == "broken"
        assert r.error == "invalid_domain"

    @pytest.mark.asyncio
    async def test_invalid_domain_empty_host(self):
        results = await verify_urls(["https:///no-domain-path"])
        r = results["https:///no-domain-path"]
        assert r.status == "broken"
        assert r.error == "invalid_domain"

    @pytest.mark.asyncio
    async def test_user_agent_header(self, respx_mock):
        route = respx_mock.get("https://example.com/ua").mock(
            return_value=httpx.Response(200, html=_html())
        )
        await verify_urls(["https://example.com/ua"])
        request = route.calls[0].request
        assert "NewsletterAgent" in request.headers["user-agent"]

    @pytest.mark.asyncio
    async def test_no_cookies(self, respx_mock):
        route = respx_mock.get("https://example.com/clean").mock(
            return_value=httpx.Response(200, html=_html())
        )
        await verify_urls(["https://example.com/clean"])
        request = route.calls[0].request
        assert "cookie" not in request.headers
        assert "authorization" not in request.headers

    @pytest.mark.asyncio
    async def test_multiple_urls(self, respx_mock):
        respx_mock.get("https://a.com/").mock(
            return_value=httpx.Response(200, html=_html("A"))
        )
        respx_mock.get("https://b.com/").mock(
            return_value=httpx.Response(404, html=_html("Not Found"))
        )
        respx_mock.get("https://c.com/").mock(
            return_value=httpx.Response(200, html=_html("C"))
        )
        results = await verify_urls(
            ["https://a.com/", "https://b.com/", "https://c.com/"]
        )
        assert results["https://a.com/"].status == "valid"
        assert results["https://b.com/"].status == "broken"
        assert results["https://c.com/"].status == "valid"

    @pytest.mark.asyncio
    async def test_never_raises(self, respx_mock):
        """verify_urls never raises - all errors captured in results."""
        respx_mock.get("https://explode.com/").mock(
            side_effect=RuntimeError("unexpected")
        )
        results = await verify_urls(["https://explode.com/"])
        r = results["https://explode.com/"]
        assert r.status == "broken"
        assert "connection_error" in r.error

    @pytest.mark.asyncio
    async def test_non_html_content_no_title(self, respx_mock):
        """JSON/binary responses should not fail title extraction."""
        respx_mock.get("https://example.com/api.json").mock(
            return_value=httpx.Response(
                200, content=b'{"data": "value"}',
                headers={"content-type": "application/json"},
            )
        )
        results = await verify_urls(["https://example.com/api.json"])
        r = results["https://example.com/api.json"]
        assert r.status == "valid"
        assert r.page_title is None

    @pytest.mark.asyncio
    async def test_200_no_title_valid(self, respx_mock):
        """200 response without <title> tag should still be valid."""
        respx_mock.get("https://example.com/plain").mock(
            return_value=httpx.Response(
                200, text="<html><body>No title here</body></html>",
                headers={"content-type": "text/html"},
            )
        )
        results = await verify_urls(["https://example.com/plain"])
        r = results["https://example.com/plain"]
        assert r.status == "valid"
        assert r.page_title is None


# ---------------------------------------------------------------------------
# clean_broken_links_from_markdown() tests
# ---------------------------------------------------------------------------
class TestCleanBrokenLinks:
    def test_single_broken_link(self):
        md = "See [Article](http://broken.com) for details."
        result = clean_broken_links_from_markdown(md, {"http://broken.com"})
        assert result == "See Article for details."

    def test_working_link_unchanged(self):
        md = "See [Article](http://working.com) for details."
        result = clean_broken_links_from_markdown(md, {"http://broken.com"})
        assert result == md

    def test_multiple_broken_links(self):
        md = "Read [A](http://a.com) and [B](http://b.com) today."
        result = clean_broken_links_from_markdown(
            md, {"http://a.com", "http://b.com"}
        )
        assert result == "Read A and B today."

    def test_mixed_broken_and_working(self):
        md = "Read [A](http://a.com) and [B](http://b.com) today."
        result = clean_broken_links_from_markdown(md, {"http://a.com"})
        assert result == "Read A and [B](http://b.com) today."

    def test_title_with_parentheses(self):
        md = "See [Title (2025)](http://broken.com) here."
        result = clean_broken_links_from_markdown(md, {"http://broken.com"})
        assert result == "See Title (2025) here."

    def test_url_with_query_string(self):
        url = "http://example.com/page?id=1&foo=bar"
        md = f"See [Page]({url}) here."
        result = clean_broken_links_from_markdown(md, {url})
        assert result == "See Page here."

    def test_url_with_fragment(self):
        url = "http://example.com/page#section"
        md = f"See [Section]({url}) here."
        result = clean_broken_links_from_markdown(md, {url})
        assert result == "See Section here."

    def test_empty_broken_set(self):
        md = "See [Link](http://ok.com) here."
        result = clean_broken_links_from_markdown(md, set())
        assert result == md

    def test_no_links_in_markdown(self):
        md = "Just plain text with no links."
        result = clean_broken_links_from_markdown(md, {"http://broken.com"})
        assert result == md

    def test_image_link_not_cleaned(self):
        md = "![Alt](http://broken.com) and [Text](http://broken.com)"
        result = clean_broken_links_from_markdown(md, {"http://broken.com"})
        assert result == "![Alt](http://broken.com) and Text"

    def test_empty_title_link(self):
        md = "See [](http://broken.com) here."
        result = clean_broken_links_from_markdown(md, {"http://broken.com"})
        assert result == "See  here."

    def test_multiline_markdown(self):
        md = (
            "## Topic\n\n"
            "Read [A](http://a.com) for more.\n\n"
            "Also see [B](http://b.com) and [C](http://c.com).\n"
        )
        result = clean_broken_links_from_markdown(md, {"http://a.com", "http://c.com"})
        expected = (
            "## Topic\n\n"
            "Read A for more.\n\n"
            "Also see [B](http://b.com) and C.\n"
        )
        assert result == expected

    def test_consecutive_broken_links(self):
        md = "[A](http://a.com)[B](http://b.com)"
        result = clean_broken_links_from_markdown(
            md, {"http://a.com", "http://b.com"}
        )
        assert result == "AB"
