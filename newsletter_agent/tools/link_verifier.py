"""Link verification utilities: URL checking, SSRF protection, and markdown cleaning.

Provides verify_urls() for concurrent HTTP liveness checks and
clean_broken_links_from_markdown() for removing broken citations.

Spec refs: FR-014 through FR-024, Section 8.5, Section 10.2.
"""

import asyncio
import ipaddress
import logging
import re
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_USER_AGENT = "NewsletterAgent/1.0 (link-check)"
_ALLOWED_SCHEMES = {"http", "https"}

# Regex for markdown links, excluding image links (negative lookbehind for !)
_MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)]+)\)")


@dataclass(frozen=True)
class LinkCheckResult:
    """Result of checking a single URL's liveness."""

    url: str
    status: str  # "valid" or "broken"
    http_status: int | None = None
    error: str | None = None


def _is_private_ip(host: str) -> bool:
    """Check if a hostname or IP address is private/loopback."""
    if not host:
        return False
    # Direct IP address check
    try:
        addr = ipaddress.ip_address(host)
        return addr.is_private or addr.is_loopback
    except ValueError:
        pass
    # Hostname: resolve via DNS
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for _family, _type, _proto, _canonname, sockaddr in infos:
            ip_str = sockaddr[0]
            addr = ipaddress.ip_address(ip_str)
            if addr.is_private or addr.is_loopback:
                return True
    except (socket.gaierror, OSError):
        pass
    return False


def _check_scheme(url: str) -> bool:
    """Return True if URL uses an allowed scheme (http or https)."""
    parsed = urlparse(url)
    return parsed.scheme.lower() in _ALLOWED_SCHEMES


async def _check_one_url(
    url: str,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
) -> LinkCheckResult:
    """Verify a single URL with concurrency control."""
    # Pre-flight: scheme check
    if not _check_scheme(url):
        return LinkCheckResult(url=url, status="broken", error="invalid_scheme")

    # Pre-flight: SSRF check on original host
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if _is_private_ip(hostname):
        return LinkCheckResult(url=url, status="broken", error="ssrf_blocked")

    async with semaphore:
        try:
            resp = await client.head(url)
            status_code = resp.status_code

            # HEAD not allowed - fall back to streaming GET
            if status_code == 405:
                async with client.stream("GET", url) as stream_resp:
                    status_code = stream_resp.status_code
                    resp = stream_resp

            # Post-redirect SSRF checks
            final_url = str(resp.url)
            if not _check_scheme(final_url):
                return LinkCheckResult(url=url, status="broken", error="invalid_scheme")
            final_host = urlparse(final_url).hostname or ""
            if final_host != hostname and _is_private_ip(final_host):
                return LinkCheckResult(url=url, status="broken", error="ssrf_blocked")

            if 200 <= status_code <= 399:
                return LinkCheckResult(
                    url=url, status="valid", http_status=status_code
                )
            return LinkCheckResult(
                url=url,
                status="broken",
                http_status=status_code,
                error=f"status_{status_code}",
            )

        except httpx.TooManyRedirects:
            return LinkCheckResult(url=url, status="broken", error="redirect_limit")
        except httpx.TimeoutException:
            return LinkCheckResult(url=url, status="broken", error="timeout")
        except Exception as exc:
            err_str = f"{type(exc).__name__}: {exc}".lower()
            if "ssl" in err_str:
                return LinkCheckResult(url=url, status="broken", error="ssl_error")
            if "name resolution" in err_str or "dns" in err_str or isinstance(
                exc, httpx.ConnectError
            ):
                return LinkCheckResult(url=url, status="broken", error="dns_error")
            return LinkCheckResult(
                url=url, status="broken", error=f"connection_error"
            )


async def verify_urls(
    urls: list[str],
    timeout: float = 10.0,
    max_concurrent: int = 10,
) -> dict[str, LinkCheckResult]:
    """Verify a list of URLs concurrently via HTTP HEAD (GET fallback).

    Returns a dict mapping each URL to its LinkCheckResult.
    Never raises - all errors are captured in individual results.
    """
    if not urls:
        return {}

    semaphore = asyncio.Semaphore(max_concurrent)
    async with httpx.AsyncClient(
        follow_redirects=True,
        max_redirects=5,
        timeout=httpx.Timeout(timeout),
        headers={"User-Agent": _USER_AGENT},
    ) as client:
        tasks = [_check_one_url(url, client, semaphore) for url in urls]
        results = await asyncio.gather(*tasks)

    return {r.url: r for r in results}


def clean_broken_links_from_markdown(
    markdown: str,
    broken_urls: set[str],
) -> str:
    """Replace markdown links whose URL is broken with just the title text.

    Image links (![alt](url)) are not affected.
    """
    if not broken_urls:
        return markdown

    def _replacer(match: re.Match) -> str:
        title = match.group(1)
        url = match.group(2)
        if url in broken_urls:
            return title
        return match.group(0)

    return _MARKDOWN_LINK_RE.sub(_replacer, markdown)
