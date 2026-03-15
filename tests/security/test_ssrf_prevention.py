"""Security test: SSRF Prevention in Pipeline Context.

Verifies SSRF protections work in the full pipeline context, not just
in unit isolation. Tests redirect-based SSRF, private IP blocking,
scheme validation, and header leakage.

Spec refs: NFR-LINK-SEC, Section 11.6.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from newsletter_agent.tools.link_verifier import (
    LinkCheckResult,
    verify_urls,
    _check_one_url,
    _is_private_ip,
)
from newsletter_agent.tools.link_verifier_agent import LinkVerifierAgent


class TestSSRFPrivateIPBlocking:
    """Private IP ranges are rejected before any request is made."""

    @pytest.mark.asyncio
    async def test_loopback_127(self, respx_mock):
        """URL with 127.0.0.1 host is blocked."""
        results = await verify_urls(["http://127.0.0.1/admin"])
        r = results["http://127.0.0.1/admin"]
        assert r.status == "broken"
        assert r.error == "ssrf_blocked"

    @pytest.mark.asyncio
    async def test_private_10_range(self, respx_mock):
        """URL with 10.x.x.x host is blocked."""
        results = await verify_urls(["http://10.0.0.1/internal"])
        r = results["http://10.0.0.1/internal"]
        assert r.status == "broken"
        assert r.error == "ssrf_blocked"

    @pytest.mark.asyncio
    async def test_private_172_range(self, respx_mock):
        """URL with 172.16.x.x host is blocked."""
        results = await verify_urls(["http://172.16.0.1/secret"])
        r = results["http://172.16.0.1/secret"]
        assert r.status == "broken"
        assert r.error == "ssrf_blocked"

    @pytest.mark.asyncio
    async def test_private_192_range(self, respx_mock):
        """URL with 192.168.x.x host is blocked."""
        results = await verify_urls(["http://192.168.1.1/router"])
        r = results["http://192.168.1.1/router"]
        assert r.status == "broken"
        assert r.error == "ssrf_blocked"

    @pytest.mark.asyncio
    async def test_ipv6_loopback(self, respx_mock):
        """URL with ::1 host is blocked."""
        results = await verify_urls(["http://[::1]/admin"])
        r = results["http://[::1]/admin"]
        assert r.status == "broken"
        assert r.error == "ssrf_blocked"


class TestSSRFSchemeValidation:
    """Non-HTTP(S) schemes are rejected."""

    @pytest.mark.asyncio
    async def test_file_scheme_blocked(self, respx_mock):
        """file:// URLs are blocked."""
        results = await verify_urls(["file:///etc/passwd"])
        r = results["file:///etc/passwd"]
        assert r.status == "broken"
        assert r.error == "invalid_scheme"

    @pytest.mark.asyncio
    async def test_javascript_scheme_blocked(self, respx_mock):
        """javascript: URLs are blocked."""
        results = await verify_urls(["javascript:alert(1)"])
        r = results["javascript:alert(1)"]
        assert r.status == "broken"
        assert r.error == "invalid_scheme"

    @pytest.mark.asyncio
    async def test_ftp_scheme_blocked(self, respx_mock):
        """ftp:// URLs are blocked."""
        results = await verify_urls(["ftp://ftp.example.com/file.txt"])
        r = results["ftp://ftp.example.com/file.txt"]
        assert r.status == "broken"
        assert r.error == "invalid_scheme"


class TestSSRFRedirectProtection:
    """Redirects to private IPs or bad schemes are caught."""

    @pytest.mark.asyncio
    async def test_redirect_to_loopback_blocked(self):
        """A public URL that redirects to 127.0.0.1 is marked broken.

        Directly calls _check_one_url with a mock client that returns
        a response whose .url points to 127.0.0.1 (simulating redirect).
        """
        # Build a fake response whose .url is the private redirect target
        final_request = httpx.Request("HEAD", "http://127.0.0.1/admin")
        fake_response = httpx.Response(200, request=final_request)

        mock_client = MagicMock()
        mock_client.head = AsyncMock(return_value=fake_response)

        sem = asyncio.Semaphore(10)
        result = await _check_one_url(
            "https://evil.example.com/redirect", mock_client, sem
        )

        assert result.status == "broken"
        assert result.error == "ssrf_blocked"


class TestSSRFHeaderLeakage:
    """Outgoing requests must not contain sensitive headers."""

    @pytest.mark.asyncio
    async def test_no_authorization_header(self, respx_mock):
        """Verification requests have no Authorization header."""
        captured_headers = {}

        async def capture_request(request):
            captured_headers.update(dict(request.headers))
            return httpx.Response(200)

        respx_mock.head("https://check-headers.example.com/page").mock(
            side_effect=capture_request
        )

        await verify_urls(["https://check-headers.example.com/page"])

        # No Authorization header should be present
        assert "authorization" not in {k.lower() for k in captured_headers}

    @pytest.mark.asyncio
    async def test_no_cookie_header(self, respx_mock):
        """Verification requests have no Cookie header."""
        captured_headers = {}

        async def capture_request(request):
            captured_headers.update(dict(request.headers))
            return httpx.Response(200)

        respx_mock.head("https://check-cookies.example.com/page").mock(
            side_effect=capture_request
        )

        await verify_urls(["https://check-cookies.example.com/page"])

        assert "cookie" not in {k.lower() for k in captured_headers}

    @pytest.mark.asyncio
    async def test_user_agent_is_set(self, respx_mock):
        """User-Agent is set to the expected value."""
        captured_headers = {}

        async def capture_request(request):
            captured_headers.update(dict(request.headers))
            return httpx.Response(200)

        respx_mock.head("https://check-ua.example.com/page").mock(
            side_effect=capture_request
        )

        await verify_urls(["https://check-ua.example.com/page"])

        assert "user-agent" in {k.lower() for k in captured_headers}
        ua_value = captured_headers.get("user-agent", "")
        assert "NewsletterAgent" in ua_value


class TestSSRFViaLinkVerifierAgent:
    """SSRF protections work through the LinkVerifierAgent path."""

    @pytest.mark.asyncio
    @patch("newsletter_agent.tools.link_verifier_agent.verify_urls")
    async def test_agent_blocks_private_ip_urls(self, mock_verify):
        """LinkVerifierAgent removes URLs that the verifier marks as SSRF-blocked."""
        mock_verify.return_value = {
            "https://good.example.com": LinkCheckResult(
                url="https://good.example.com", status="valid", http_status=200
            ),
            "http://192.168.1.1/admin": LinkCheckResult(
                url="http://192.168.1.1/admin",
                status="broken",
                error="ssrf_blocked",
            ),
        }

        state = {
            "config_verify_links": True,
            "research_0_google": (
                "## Security\n\n"
                "See [Good](https://good.example.com) and "
                "[Internal](http://192.168.1.1/admin)."
            ),
        }

        agent = LinkVerifierAgent(
            name="LinkVerifier", topic_count=1, providers=["google"],
        )
        ctx = MagicMock()
        ctx.session.state = state

        async for _ in agent._run_async_impl(ctx):
            pass

        # SSRF URL removed from research text
        assert "[Internal](http://192.168.1.1/admin)" not in state["research_0_google"]
        assert "[Good](https://good.example.com)" in state["research_0_google"]
