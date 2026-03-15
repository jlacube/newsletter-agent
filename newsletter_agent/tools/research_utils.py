"""
Utilities for parsing raw research agent output into structured ResearchResult dicts.

Spec refs: FR-011, FR-012, FR-013, Section 7.3, Section 7.4.
"""

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\((https?://[^\)]+)\)")
_BARE_URL_RE = re.compile(r"(?<!\()(https?://[^\s\)\]>\"]+)")


def parse_research_result(raw_output: str, provider: str) -> dict[str, Any]:
    """Parse raw agent output into a structured ResearchResult dict.

    Args:
        raw_output: The raw text output from a research agent.
        provider: The provider name ("google" or "perplexity").

    Returns:
        dict with text/sources/provider on success, or error/message/provider on failure.
    """
    if not raw_output or not raw_output.strip():
        logger.warning("Empty research output from %s", provider)
        return {"error": True, "message": "Empty research output", "provider": provider}

    # Try JSON parsing first (Perplexity tool may return JSON)
    try:
        parsed = json.loads(raw_output)
        if isinstance(parsed, dict):
            if parsed.get("error"):
                return {
                    "error": True,
                    "message": parsed.get("message", "Unknown error"),
                    "provider": provider,
                }
            if "text" in parsed and "sources" in parsed:
                return {
                    "text": str(parsed["text"]),
                    "sources": _normalize_sources(parsed.get("sources", [])),
                    "provider": provider,
                }
    except (json.JSONDecodeError, TypeError):
        pass

    # Try structured SUMMARY/SOURCES format
    summary, sources = _parse_structured_output(raw_output)
    if summary:
        return {"text": summary, "sources": sources, "provider": provider}

    # Fallback: entire output as text, extract markdown links and bare URLs as sources
    links = _MARKDOWN_LINK_PATTERN.findall(raw_output)
    md_urls = set()
    sources = []
    for title, url in links:
        if url.startswith(("http://", "https://")):
            sources.append({"url": url, "title": title})
            md_urls.add(url)
    sources.extend(_extract_bare_url_sources(raw_output, md_urls))
    sources = _deduplicate_sources(sources)
    return {"text": raw_output.strip(), "sources": sources, "provider": provider}


def _parse_structured_output(text: str) -> tuple[str, list[dict]]:
    """Parse SUMMARY/SOURCES structured output format."""
    summary_match = re.search(
        r"(?:SUMMARY|FINDINGS|RESEARCH):\s*\n(.*?)(?:\n\s*SOURCES:|$)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    sources_match = re.search(
        r"SOURCES:\s*\n(.*?)$",
        text,
        re.DOTALL | re.IGNORECASE,
    )

    if not summary_match:
        return "", []

    summary = summary_match.group(1).strip()
    sources = []
    if sources_match:
        sources_text = sources_match.group(1)
        # Extract markdown links
        links = _MARKDOWN_LINK_PATTERN.findall(sources_text)
        md_urls = set()
        for title, url in links:
            if url.startswith(("http://", "https://")):
                sources.append({"url": url, "title": title})
                md_urls.add(url)
        # Extract bare URLs not already captured via markdown links
        sources.extend(_extract_bare_url_sources(sources_text, md_urls))
    return summary, _deduplicate_sources(sources)


def _extract_bare_url_sources(text: str, exclude_urls: set[str] | None = None) -> list[dict]:
    """Extract bare URLs from text, inferring titles from preceding lines.

    Handles Google grounding output like:
        - Title of the article
          https://vertexaisearch.cloud.google.com/grounding-api-redirect/...
    """
    exclude = exclude_urls or set()
    sources = []
    lines = text.split("\n")
    for i, line in enumerate(lines):
        bare_match = _BARE_URL_RE.search(line.strip())
        if not bare_match:
            continue
        url = bare_match.group(1)
        if url in exclude:
            continue
        # Skip if this URL is inside a markdown link on the same line
        if f"]({url})" in line:
            continue
        # Try to use the previous line as the title
        title = url
        if i > 0:
            prev = lines[i - 1].strip().lstrip("-*").strip()
            if prev and not prev.startswith("http"):
                title = prev
        sources.append({"url": url, "title": title})
        exclude.add(url)
    return sources


def _normalize_sources(raw_sources: list) -> list[dict]:
    """Normalize a list of source references into Section 7.4 format."""
    normalized = []
    for src in raw_sources:
        if isinstance(src, dict) and "url" in src:
            url = str(src["url"])
            if not url.startswith(("http://", "https://")):
                continue
            normalized.append({
                "url": url,
                "title": str(src.get("title", url)),
            })
        elif isinstance(src, str) and src.startswith(("http://", "https://")):
            normalized.append({"url": src, "title": src})
    return _deduplicate_sources(normalized)


def _deduplicate_sources(sources: list[dict]) -> list[dict]:
    """Remove duplicate sources by URL."""
    seen: set[str] = set()
    unique = []
    for src in sources:
        url = src.get("url", "")
        if url and url not in seen:
            seen.add(url)
            unique.append(src)
    return unique
