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

    # Fallback: entire output as text, extract markdown links as sources
    links = _MARKDOWN_LINK_PATTERN.findall(raw_output)
    sources = _deduplicate_sources([
        {"url": url, "title": title}
        for title, url in links
        if url.startswith(("http://", "https://"))
    ])
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
        links = _MARKDOWN_LINK_PATTERN.findall(sources_match.group(1))
        sources = [
            {"url": url, "title": title}
            for title, url in links
            if url.startswith(("http://", "https://"))
        ]
    return summary, _deduplicate_sources(sources)


def _normalize_sources(raw_sources: list) -> list[dict]:
    """Normalize a list of source references into Section 7.4 format."""
    normalized = []
    for src in raw_sources:
        if isinstance(src, dict) and "url" in src:
            normalized.append({
                "url": str(src["url"]),
                "title": str(src.get("title", src["url"])),
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
