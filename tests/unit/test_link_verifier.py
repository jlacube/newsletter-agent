"""Unit tests for newsletter_agent.tools.link_verifier.

Covers LinkCheckResult, verify_urls(), SSRF protection, HEAD->GET fallback,
and clean_broken_links_from_markdown().

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
    _check_scheme,
    clean_broken_links_from_markdown,
    verify_urls,
)


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


# ---------------------------------------------------------------------------
# SSRF protection helpers
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# verify_urls() tests
# ---------------------------------------------------------------------------
class TestVerifyUrls:
    @pytest.mark.asyncio
    async def test_empty_list(self):
        result = await verify_urls([])
        assert result == {}

    @pytest.mark.asyncio
    async def test_valid_200(self, respx_mock):
        respx_mock.head("https://example.com/page").mock(
            return_value=httpx.Response(200)
        )
        results = await verify_urls(["https://example.com/page"])
        r = results["https://example.com/page"]
        assert r.status == "valid"
        assert r.http_status == 200
        assert r.error is None

    @pytest.mark.asyncio
    async def test_redirect_301_to_200(self, respx_mock):
        respx_mock.head("https://example.com/old").mock(
            return_value=httpx.Response(
                301,
                headers={"Location": "https://example.com/new"},
            )
        )
        respx_mock.head("https://example.com/new").mock(
            return_value=httpx.Response(200)
        )
        results = await verify_urls(["https://example.com/old"])
        r = results["https://example.com/old"]
        assert r.status == "valid"

    @pytest.mark.asyncio
    async def test_404_broken(self, respx_mock):
        respx_mock.head("https://example.com/gone").mock(
            return_value=httpx.Response(404)
        )
        results = await verify_urls(["https://example.com/gone"])
        r = results["https://example.com/gone"]
        assert r.status == "broken"
        assert r.http_status == 404
        assert r.error == "status_404"

    @pytest.mark.asyncio
    async def test_500_broken(self, respx_mock):
        respx_mock.head("https://example.com/error").mock(
            return_value=httpx.Response(500)
        )
        results = await verify_urls(["https://example.com/error"])
        r = results["https://example.com/error"]
        assert r.status == "broken"
        assert r.http_status == 500
        assert r.error == "status_500"

    @pytest.mark.asyncio
    async def test_timeout(self, respx_mock):
        respx_mock.head("https://example.com/slow").mock(
            side_effect=httpx.ReadTimeout("timed out")
        )
        results = await verify_urls(["https://example.com/slow"])
        r = results["https://example.com/slow"]
        assert r.status == "broken"
        assert r.error == "timeout"
        assert r.http_status is None

    @pytest.mark.asyncio
    async def test_dns_failure(self, respx_mock):
        respx_mock.head("https://nonexistent.invalid/").mock(
            side_effect=httpx.ConnectError("Name resolution failed")
        )
        results = await verify_urls(["https://nonexistent.invalid/"])
        r = results["https://nonexistent.invalid/"]
        assert r.status == "broken"
        assert r.error == "dns_error"

    @pytest.mark.asyncio
    async def test_ssl_error(self, respx_mock):
        respx_mock.head("https://badsssl.com/").mock(
            side_effect=httpx.ConnectError("SSL: CERTIFICATE_VERIFY_FAILED")
        )
        results = await verify_urls(["https://badsssl.com/"])
        r = results["https://badsssl.com/"]
        assert r.status == "broken"
        assert r.error == "ssl_error"

    @pytest.mark.asyncio
    async def test_head_405_get_fallback(self, respx_mock):
        respx_mock.head("https://example.com/api").mock(
            return_value=httpx.Response(405)
        )
        respx_mock.get("https://example.com/api").mock(
            return_value=httpx.Response(200)
        )
        results = await verify_urls(["https://example.com/api"])
        r = results["https://example.com/api"]
        assert r.status == "valid"
        assert r.http_status == 200

    @pytest.mark.asyncio
    async def test_too_many_redirects(self, respx_mock):
        respx_mock.head("https://example.com/loop").mock(
            side_effect=httpx.TooManyRedirects(
                "Exceeded max redirects",
                request=httpx.Request("HEAD", "https://example.com/loop"),
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
    async def test_user_agent_header(self, respx_mock):
        route = respx_mock.head("https://example.com/ua").mock(
            return_value=httpx.Response(200)
        )
        await verify_urls(["https://example.com/ua"])
        request = route.calls[0].request
        assert request.headers["user-agent"] == "NewsletterAgent/1.0 (link-check)"

    @pytest.mark.asyncio
    async def test_no_cookies(self, respx_mock):
        route = respx_mock.head("https://example.com/clean").mock(
            return_value=httpx.Response(200)
        )
        await verify_urls(["https://example.com/clean"])
        request = route.calls[0].request
        assert "cookie" not in request.headers
        assert "authorization" not in request.headers

    @pytest.mark.asyncio
    async def test_multiple_urls(self, respx_mock):
        respx_mock.head("https://a.com/").mock(return_value=httpx.Response(200))
        respx_mock.head("https://b.com/").mock(return_value=httpx.Response(404))
        respx_mock.head("https://c.com/").mock(return_value=httpx.Response(200))
        results = await verify_urls(
            ["https://a.com/", "https://b.com/", "https://c.com/"]
        )
        assert results["https://a.com/"].status == "valid"
        assert results["https://b.com/"].status == "broken"
        assert results["https://c.com/"].status == "valid"

    @pytest.mark.asyncio
    async def test_concurrency_limit(self, respx_mock):
        """Verify semaphore limits concurrent requests."""
        concurrent_count = 0
        max_concurrent_seen = 0

        original_head = httpx.AsyncClient.head

        async def _counting_head(self_client, url, **kwargs):
            nonlocal concurrent_count, max_concurrent_seen
            concurrent_count += 1
            max_concurrent_seen = max(max_concurrent_seen, concurrent_count)
            await asyncio.sleep(0.01)
            concurrent_count -= 1
            return httpx.Response(200, request=httpx.Request("HEAD", url))

        urls = [f"https://example.com/{i}" for i in range(20)]
        for url in urls:
            respx_mock.head(url).mock(side_effect=lambda req: httpx.Response(200))

        # Use max_concurrent=5 and check it's respected
        with patch.object(httpx.AsyncClient, "head", _counting_head):
            await verify_urls(urls, max_concurrent=5)

        assert max_concurrent_seen <= 5

    @pytest.mark.asyncio
    async def test_never_raises(self, respx_mock):
        """verify_urls never raises - all errors captured in results."""
        respx_mock.head("https://explode.com/").mock(
            side_effect=RuntimeError("unexpected")
        )
        results = await verify_urls(["https://explode.com/"])
        r = results["https://explode.com/"]
        assert r.status == "broken"
        assert "connection_error" in r.error


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
