"""
Utilities for parsing synthesis agent output into structured state entries.

Spec refs: FR-019, FR-018, Section 7.5, Section 7.6.
"""

import json
import logging
import re
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\((https?://[^)]+)\)")
_PLACEHOLDER_TITLE_RE = re.compile(r"^(?:google\s+research\s+for\b|round\s+\d+\b)", re.IGNORECASE)


def parse_synthesis_output(
    raw_output: str, expected_topics: list[str]
) -> dict[str, Any]:
    """Parse raw synthesis agent output into session state entries.

    Args:
        raw_output: Raw text output from the synthesis LlmAgent.
        expected_topics: List of expected topic names.

    Returns:
        Dict with keys: synthesis_0, synthesis_1, ..., executive_summary.
        Never raises an exception.
    """
    if not raw_output or not raw_output.strip():
        logger.warning("Empty synthesis output")
        return _fallback_output(expected_topics, "Empty synthesis output")

    # Try to extract JSON from the output
    parsed = _try_parse_json(raw_output)
    if parsed is not None:
        return _build_state_from_json(parsed, expected_topics)

    # Fallback: treat raw output as plain text for the first topic
    logger.warning("Could not parse synthesis output as JSON; using fallback")
    return _fallback_output(expected_topics, raw_output)


def _try_parse_json(text: str) -> dict | None:
    """Try to parse JSON from text, handling markdown code blocks."""
    # Strip markdown code block wrappers
    stripped = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
    stripped = re.sub(r"\n?```\s*$", "", stripped)

    # Try direct parse
    try:
        result = json.loads(stripped)
        if isinstance(result, dict):
            return result
    except (json.JSONDecodeError, TypeError):
        pass

    # Try finding JSON object in the text
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, dict):
                return result
        except (json.JSONDecodeError, TypeError):
            pass

    # Try to repair truncated JSON by closing open brackets/braces
    repaired = _try_repair_truncated_json(stripped)
    if repaired is not None:
        return repaired

    return None


def _try_repair_truncated_json(text: str) -> dict | None:
    """Attempt to repair truncated JSON by closing open structures.

    When the LLM output hits token limits, JSON is cut mid-stream.
    This tries to salvage what was produced by trimming to natural
    JSON boundaries and closing remaining open brackets/braces.
    """
    # Collect cut-point positions: after }, ], or " (natural JSON boundaries)
    cut_points = []
    for i, ch in enumerate(text):
        if ch in ('}', ']', '"'):
            cut_points.append(i + 1)

    # Try from the end backward to find the longest valid parse
    for pos in reversed(cut_points):
        candidate = text[:pos].rstrip().rstrip(",")
        open_braces = candidate.count("{") - candidate.count("}")
        open_brackets = candidate.count("[") - candidate.count("]")
        if open_braces < 0 or open_brackets < 0:
            continue
        suffix = "]" * open_brackets + "}" * open_braces
        try:
            result = json.loads(candidate + suffix)
            if isinstance(result, dict):
                logger.info(
                    "Repaired truncated JSON (trimmed %d chars from end)",
                    len(text) - pos,
                )
                return result
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def _build_state_from_json(
    data: dict, expected_topics: list[str]
) -> dict[str, Any]:
    """Convert parsed JSON into session state entries."""
    state: dict[str, Any] = {}

    # Parse executive summary
    raw_summary = data.get("executive_summary", [])
    if isinstance(raw_summary, list) and raw_summary:
        state["executive_summary"] = [
            {
                "topic": item.get("topic", f"Topic {i}"),
                "summary": item.get("summary", ""),
            }
            for i, item in enumerate(raw_summary)
            if isinstance(item, dict)
        ]
    else:
        state["executive_summary"] = [
            {"topic": name, "summary": ""} for name in expected_topics
        ]

    # Parse sections
    raw_sections = data.get("sections", [])
    for i, topic_name in enumerate(expected_topics):
        if i < len(raw_sections) and isinstance(raw_sections[i], dict):
            section = raw_sections[i]
            normalized = normalize_synthesis_section(
                title=section.get("title", topic_name),
                body_markdown=section.get("body_markdown", ""),
                raw_sources=section.get("sources", []),
            )
            state[f"synthesis_{i}"] = normalized
            logger.info(
                "[SynthesisParse] Topic %d '%s': %d sources, body=%d chars",
                i,
                normalized["title"],
                len(normalized["sources"]),
                len(normalized["body_markdown"]),
            )
        else:
            state[f"synthesis_{i}"] = {
                "title": topic_name,
                "body_markdown": "Research data was insufficient for full analysis.",
                "sources": [],
            }
            logger.warning(
                "[SynthesisParse] Topic %d '%s': no section data from synthesizer",
                i, topic_name,
            )

    return state


def _normalize_sources(raw_sources: list) -> list[dict]:
    """Normalize and deduplicate source references.

    Only http:// and https:// URLs are permitted to prevent non-web
    schemes (javascript:, data:, ftp:) from reaching the newsletter HTML.
    """
    seen: set[str] = set()
    result = []
    for src in raw_sources:
        if isinstance(src, dict) and "url" in src:
            url = str(src["url"])
            if not url.startswith(("http://", "https://")):
                continue
            if url not in seen:
                seen.add(url)
                result.append({"url": url, "title": str(src.get("title", url))})
    return result


def _is_google_search_placeholder_url(url: str) -> bool:
    """Return True for synthetic google.com search URLs fabricated as citations."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return (
        parsed.scheme.lower() in {"http", "https"}
        and host in {"www.google.com", "google.com"}
        and parsed.path == "/search"
        and "q=" in (parsed.query or "")
    )


def _is_placeholder_source(source: dict) -> bool:
    """Identify low-quality placeholder sources emitted by the synthesis model."""
    url = str(source.get("url", ""))
    title = str(source.get("title", "")).strip()
    return _is_google_search_placeholder_url(url) or bool(_PLACEHOLDER_TITLE_RE.match(title))


def _strip_removed_markdown_links(body_markdown: str, removed_urls: set[str]) -> str:
    """Replace removed markdown links with plain text labels in the body."""
    if not body_markdown or not removed_urls:
        return body_markdown

    def _replace(match: re.Match[str]) -> str:
        title, url = match.group(1), match.group(2)
        if url in removed_urls:
            return title
        return match.group(0)

    return _MARKDOWN_LINK_RE.sub(_replace, body_markdown)


def normalize_synthesis_section(
    title: str,
    body_markdown: str,
    raw_sources: list,
) -> dict[str, Any]:
    """Normalize a synthesized section and remove synthetic placeholder links."""
    sources = _normalize_sources(raw_sources)
    removed_urls = {src["url"] for src in sources if _is_placeholder_source(src)}
    if removed_urls:
        sources = [src for src in sources if src["url"] not in removed_urls]
        body_markdown = _strip_removed_markdown_links(body_markdown, removed_urls)

    return {
        "title": title,
        "body_markdown": body_markdown,
        "sources": sources,
    }


def _fallback_output(
    expected_topics: list[str], message: str
) -> dict[str, Any]:
    """Generate fallback output when parsing fails."""
    state: dict[str, Any] = {
        "executive_summary": [
            {"topic": name, "summary": "Synthesis was unable to process research data."}
            for name in expected_topics
        ],
    }
    for i, name in enumerate(expected_topics):
        state[f"synthesis_{i}"] = {
            "title": name,
            "body_markdown": f"Synthesis processing encountered an issue: {message[:500]}",
            "sources": [],
        }
    return state
