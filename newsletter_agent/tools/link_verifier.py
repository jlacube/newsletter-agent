"""Link verification utilities: URL checking, SSRF protection, and markdown cleaning.

Provides verify_urls() for concurrent HTTP liveness checks with page title
extraction and soft-404 detection. clean_broken_links_from_markdown() removes
broken citations from markdown text.

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

_USER_AGENT = (
    "Mozilla/5.0 (compatible; NewsletterAgent/1.0; +https://github.com/newsletter-agent)"
)
_ALLOWED_SCHEMES = {"http", "https"}

# Regex for markdown links, excluding image links (negative lookbehind for !)
_MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)]+)\)")

# Max bytes to read from response body for title extraction (8 KB)
_MAX_BODY_BYTES = 8192

# Regex to extract <title> from HTML head
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

# Patterns in page titles that indicate a soft-404 or error page
_SOFT_404_TITLE_PATTERNS = re.compile(
    r"\b("
    r"404|not\s*found|page\s*not\s*found|does\s*not\s*exist"
    r"|removed|deleted|expired|unavailable|no\s*longer\s*available"
    r"|access\s*denied|forbidden|unauthorized"
    r"|error\s*page|server\s*error|internal\s*error"
    r"|page\s*missing|content\s*removed|article\s*not\s*found"
    r"|sign\s*in|log\s*in\s*required"
    r"|captcha|verify\s*you\s*are\s*human|are\s*you\s*a\s*robot"
    r"|just\s*a\s*moment|attention\s*required"
    r")\b",
    re.IGNORECASE,
)

# Patterns checked against body content (heading text + visible text on short pages)
_SOFT_404_BODY_PATTERNS = re.compile(
    r"(?:"
    r"404\s*[-:]?\s*(?:not\s*found|error|page)"
    r"|page\s*(?:not\s*found|does\s*not\s*exist|has\s*been\s*removed)"
    r"|(?:this|the)\s*(?:page|link|content|article|url)\s*(?:is\s*no\s*longer|was\s*not|could\s*not\s*be|cannot\s*be|isn.t)\s*(?:available|found|reached|accessed)"
    r"|(?:content|resource|article|page)\s*(?:not\s*found|unavailable|removed|expired|deleted)"
    r"|(?:error|err)\s*(?:404|not\s*found)"
    r"|(?:we\s*)?(?:couldn.t|could\s*not|can.t|cannot)\s*find\s*(?:the|this|that)\s*(?:page|content|article|url)"
    r"|no\s*(?:results|content|page)\s*(?:found|available)"
    r"|(?:sorry|oops)[,.]?\s*(?:this|the|that|we)\s*(?:page|link|content|couldn)"
    r"|(?:the\s*)?requested\s*(?:page|url|content|resource)\s*(?:was|is|has)\s*(?:not|no\s*longer)"
    r")",
    re.IGNORECASE,
)

# Regex to extract text from HTML heading tags
_HEADING_RE = re.compile(r"<h[1-3][^>]*>(.*?)</h[1-3]>", re.IGNORECASE | re.DOTALL)

# Regex to strip all HTML tags
_TAG_RE = re.compile(r"<[^>]+>")

_GOOGLE_GROUNDING_HOST = "vertexaisearch.cloud.google.com"
_GOOGLE_GROUNDING_PATH_PREFIX = "/grounding-api-redirect/"


@dataclass(frozen=True)
class LinkCheckResult:
    """Result of checking a single URL's liveness."""

    url: str
    status: str  # "valid" or "broken"
    http_status: int | None = None
    error: str | None = None
    page_title: str | None = None


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


def _is_google_grounding_redirect(url: str) -> bool:
    """Return True for Google grounding redirect URLs emitted by google_search."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return (
        parsed.scheme.lower() == "https"
        and host == _GOOGLE_GROUNDING_HOST
        and parsed.path.startswith(_GOOGLE_GROUNDING_PATH_PREFIX)
    )


def _extract_title(html_snippet: str) -> str | None:
    """Extract and clean the <title> text from an HTML snippet."""
    m = _TITLE_RE.search(html_snippet)
    if not m:
        return None
    raw = m.group(1).strip()
    # Collapse whitespace and decode common entities
    raw = re.sub(r"\s+", " ", raw)
    raw = raw.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    raw = raw.replace("&#39;", "'").replace("&quot;", '"')
    return raw if raw else None


def _is_soft_404(title: str | None) -> bool:
    """Return True if the page title matches common error/soft-404 patterns."""
    if not title:
        return False
    return bool(_SOFT_404_TITLE_PATTERNS.search(title))


def _is_soft_404_body(html_snippet: str) -> bool:
    """Return True if the page body content indicates a soft-404.

    Checks heading tags (h1-h3) for error patterns. Also checks the full
    visible text on very short pages (under 1500 chars of text), since genuine
    error pages tend to be small.
    """
    if not html_snippet:
        return False
    # Check heading text first - most reliable signal
    for m in _HEADING_RE.finditer(html_snippet):
        heading_text = _TAG_RE.sub("", m.group(1)).strip()
        heading_text = re.sub(r"\s+", " ", heading_text)
        if heading_text and _SOFT_404_BODY_PATTERNS.search(heading_text):
            return True
    # On short pages, also scan the visible text
    visible = _TAG_RE.sub(" ", html_snippet)
    visible = re.sub(r"\s+", " ", visible).strip()
    if len(visible) < 1500 and _SOFT_404_BODY_PATTERNS.search(visible):
        return True
    return False


async def _check_one_url(
    url: str,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
) -> LinkCheckResult:
    """Verify a single URL with streaming GET, title extraction, and soft-404 detection."""
    if _is_google_grounding_redirect(url):
        return LinkCheckResult(url=url, status="valid", http_status=200)

    # Pre-flight: scheme check
    if not _check_scheme(url):
        return LinkCheckResult(url=url, status="broken", error="invalid_scheme")

    # Pre-flight: valid domain check (catch hallucinated URLs with no hostname)
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if not hostname:
        return LinkCheckResult(url=url, status="broken", error="invalid_domain")
    # Allow IP addresses (contain colons for IPv6, or all digits/dots for IPv4)
    is_ip = ":" in hostname
    if not is_ip:
        try:
            ipaddress.ip_address(hostname)
            is_ip = True
        except ValueError:
            pass
    if not is_ip and "." not in hostname:
        return LinkCheckResult(url=url, status="broken", error="invalid_domain")

    # Pre-flight: SSRF check on original host
    if _is_private_ip(hostname):
        return LinkCheckResult(url=url, status="broken", error="ssrf_blocked")

    async with semaphore:
        try:
            # Use streaming GET to read only the head portion for title extraction
            async with client.stream("GET", url) as resp:
                status_code = resp.status_code

                # Post-redirect SSRF checks
                final_url = str(resp.url)
                if not _check_scheme(final_url):
                    return LinkCheckResult(url=url, status="broken", error="invalid_scheme")
                final_host = urlparse(final_url).hostname or ""
                if final_host != hostname and _is_private_ip(final_host):
                    return LinkCheckResult(url=url, status="broken", error="ssrf_blocked")

                # Read limited body for title extraction and soft-404 body check
                page_title = None
                body_text = ""
                content_type = resp.headers.get("content-type", "")
                if "html" in content_type or "text" in content_type or not content_type:
                    chunks = []
                    total = 0
                    async for chunk in resp.aiter_bytes():
                        chunks.append(chunk)
                        total += len(chunk)
                        if total >= _MAX_BODY_BYTES:
                            break
                    body_snippet = b"".join(chunks)[:_MAX_BODY_BYTES]
                    try:
                        body_text = body_snippet.decode("utf-8", errors="replace")
                    except Exception:
                        body_text = body_snippet.decode("latin-1", errors="replace")
                    page_title = _extract_title(body_text)

            # Hard failures: unambiguous broken
            if status_code in (404, 410):
                return LinkCheckResult(
                    url=url, status="broken", http_status=status_code,
                    error=f"status_{status_code}", page_title=page_title,
                )

            # Successful range
            if 200 <= status_code <= 399:
                # Soft-404 check: title-based
                if _is_soft_404(page_title):
                    logger.info(
                        "URL %s returned %d but title indicates error page: '%s'",
                        url, status_code, page_title,
                    )
                    return LinkCheckResult(
                        url=url, status="broken", http_status=status_code,
                        error="soft_404", page_title=page_title,
                    )
                # Soft-404 check: body content (catches hidden 404s like
                # Google Grounding redirects that return 200 with error body)
                if body_text and _is_soft_404_body(body_text):
                    logger.info(
                        "URL %s returned %d but body content indicates error page (title: '%s')",
                        url, status_code, page_title,
                    )
                    return LinkCheckResult(
                        url=url, status="broken", http_status=status_code,
                        error="soft_404_body", page_title=page_title,
                    )
                return LinkCheckResult(
                    url=url, status="valid", http_status=status_code,
                    page_title=page_title,
                )

            # Rate-limiting / temporary maintenance - likely a real page
            if status_code in (429, 503):
                logger.debug(
                    "URL %s returned %d (rate-limit/maintenance); treating as valid",
                    url, status_code,
                )
                return LinkCheckResult(
                    url=url, status="valid", http_status=status_code,
                    page_title=page_title,
                )

            # Bot protection (401, 403) - check title and body for clues
            if status_code in (401, 403):
                if page_title and _is_soft_404(page_title):
                    return LinkCheckResult(
                        url=url, status="broken", http_status=status_code,
                        error=f"status_{status_code}", page_title=page_title,
                    )
                if body_text and _is_soft_404_body(body_text):
                    logger.info(
                        "URL %s returned %d, body content indicates error page (title: '%s')",
                        url, status_code, page_title,
                    )
                    return LinkCheckResult(
                        url=url, status="broken", http_status=status_code,
                        error="soft_404_body", page_title=page_title,
                    )
                # Likely paywall or WAF - human would see the page
                logger.debug(
                    "URL %s returned %d (bot-protection); treating as valid",
                    url, status_code,
                )
                return LinkCheckResult(
                    url=url, status="valid", http_status=status_code,
                    page_title=page_title,
                )

            return LinkCheckResult(
                url=url, status="broken", http_status=status_code,
                error=f"status_{status_code}", page_title=page_title,
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
                url=url, status="broken", error="connection_error"
            )


async def verify_urls(
    urls: list[str],
    timeout: float = 15.0,
    max_concurrent: int = 10,
) -> dict[str, LinkCheckResult]:
    """Verify a list of URLs concurrently via streaming GET with title extraction.

    Each URL is checked with a streaming GET request that reads up to 8KB
    to extract the page <title>. Soft-404 detection flags pages that return
    200 but have error-indicating titles.

    Returns a dict mapping each URL to its LinkCheckResult (includes page_title).
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
