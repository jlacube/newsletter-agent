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
_ORPHAN_BRACKET_RE = re.compile(r"(?<!!)\[([^\]\[]{10,})\](?!\()")
_PLACEHOLDER_TITLE_RE = re.compile(r"^(?:google\s+research\s+for\b|round\s+\d+\b)", re.IGNORECASE)

# Pattern: [[Title](URL)](URL) - nested/double-wrapped link
_NESTED_LINK_RE = re.compile(
    r"\[\[([^\]]+)\]\((https?://[^)]+)\)\]\((https?://[^)]+)\)"
)

# Pattern: ](URL) - used to find bare close-bracket links
_CLOSE_BRACKET_URL_RE = re.compile(r"\]\((https?://[^)]+)\)")

# Pattern: [Title]\n(URL) or [Title] (URL) - split across whitespace
_SPLIT_LINK_RE = re.compile(
    r"(?<!!)\[([^\]\[]{10,})\]\s+\((https?://[^)]+)\)"
)


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

    # Fix malformed citation patterns the LLM commonly produces.
    # Order matters: fix structural issues before orphan relinking.
    body_markdown = _fix_nested_links(body_markdown)
    body_markdown = _fix_split_links(body_markdown)
    body_markdown = _fix_bare_close_brackets(body_markdown, sources)
    body_markdown = _relink_orphaned_brackets(body_markdown, sources)

    return {
        "title": title,
        "body_markdown": body_markdown,
        "sources": sources,
    }


def _fix_nested_links(body_markdown: str) -> str:
    """Flatten ``[[Title](URL)](URL)`` to ``[Title](inner_URL)``.

    The LLM sometimes wraps an already-valid markdown link inside another
    link construct, producing nested brackets that markdown converters
    render with the raw inner link as display text.
    """
    if not body_markdown or "[[" not in body_markdown:
        return body_markdown

    count = 0

    def _replace(match: re.Match[str]) -> str:
        nonlocal count
        inner_title = match.group(1)
        inner_url = match.group(2)
        count += 1
        return f"[{inner_title}]({inner_url})"

    result = _NESTED_LINK_RE.sub(_replace, body_markdown)
    if count:
        logger.info("Flattened %d nested [[Title](URL)](URL) links", count)
    return result


def _fix_split_links(body_markdown: str) -> str:
    """Join ``[Title] (URL)`` or ``[Title]\\n(URL)`` into ``[Title](URL)``.

    Whitespace or newlines between ``]`` and ``(`` break markdown link
    syntax. This rejoins them.
    """
    if not body_markdown:
        return body_markdown

    count = 0

    def _replace(match: re.Match[str]) -> str:
        nonlocal count
        title = match.group(1)
        url = match.group(2)
        count += 1
        return f"[{title}]({url})"

    result = _SPLIT_LINK_RE.sub(_replace, body_markdown)
    if count:
        logger.info("Joined %d split [Title] (URL) links", count)
    return result


def _fix_bare_close_brackets(
    body_markdown: str,
    sources: list[dict] | None = None,
) -> str:
    """Fix ``Title](URL)`` by prepending the missing ``[``.

    The LLM sometimes omits the opening bracket, producing text like
    ``...claim Title](https://example.com). Next...`` which markdown
    converters cannot parse as a link.

    Uses two strategies:
    1. Match the text before ``]`` against known source titles (most accurate).
    2. Fall back to a sentence-boundary heuristic when no source title matches.
    """
    if not body_markdown or "](" not in body_markdown:
        return body_markdown

    matches = list(_CLOSE_BRACKET_URL_RE.finditer(body_markdown))
    if not matches:
        return body_markdown

    # Build sorted source title list (longest first for greedy matching)
    source_titles: list[str] = []
    if sources:
        for src in sources:
            t = src.get("title", "").strip()
            if len(t) >= 5:
                source_titles.append(t)
        source_titles.sort(key=len, reverse=True)

    count = 0
    offset = 0
    result = body_markdown

    for m in matches:
        bracket_pos = m.start() + offset  # position of ] in *result*

        # Check whether this ] already has a matching [
        depth = 0
        has_open = False
        for i in range(bracket_pos - 1, -1, -1):
            ch = result[i]
            if ch == "]":
                depth += 1
            elif ch == "[":
                if depth == 0:
                    has_open = True
                    break
                depth -= 1
        if has_open:
            continue  # Already a proper [Title](URL)

        text_before = result[:bracket_pos]
        title_start: int | None = None

        # Strategy 1: match a known source title ending right before ]
        for src_title in source_titles:
            if text_before.endswith(src_title):
                title_start = bracket_pos - len(src_title)
                break

        # Strategy 2: sentence-boundary heuristic
        if title_start is None:
            boundary_positions: list[int] = []
            for pattern in [". ", "? ", "! ", "; ", "\n", ") ", '" ']:
                pos = text_before.rfind(pattern)
                if pos >= 0:
                    boundary_positions.append(pos + len(pattern))
            if boundary_positions:
                candidate = max(boundary_positions)
                while candidate < bracket_pos and result[candidate] in " \t":
                    candidate += 1
                if bracket_pos - candidate >= 5:
                    title_start = candidate

        if title_start is None:
            continue

        result = result[:title_start] + "[" + result[title_start:]
        offset += 1
        count += 1

    if count:
        logger.info("Fixed %d bare Title](URL) links (added opening [)", count)
    return result


def _relink_orphaned_brackets(body_markdown: str, sources: list[dict]) -> str:
    """Relink [Title] bracket references that are missing their (URL) part.

    The synthesis LLM sometimes emits ``[Source Title]`` without ``(URL)``.
    This function matches those orphaned brackets against the sources list
    and rewrites them as proper ``[Title](URL)`` markdown links.
    """
    if not body_markdown or not sources:
        return body_markdown

    # Build lookup: normalized title -> url (first match wins)
    title_to_url: dict[str, str] = {}
    for src in sources:
        key = _norm_title(src.get("title", ""))
        if key and key not in title_to_url:
            title_to_url[key] = src["url"]

    if not title_to_url:
        return body_markdown

    relinked = 0

    def _replace(match: re.Match[str]) -> str:
        nonlocal relinked
        bracket_text = match.group(1)
        norm = _norm_title(bracket_text)
        # Exact match
        url = title_to_url.get(norm)
        if url:
            relinked += 1
            return f"[{bracket_text}]({url})"
        # Prefix match: the bracket text may be truncated
        for src_title, src_url in title_to_url.items():
            if src_title.startswith(norm) or norm.startswith(src_title):
                relinked += 1
                return f"[{bracket_text}]({src_url})"
        return match.group(0)

    result = _ORPHAN_BRACKET_RE.sub(_replace, body_markdown)
    if relinked:
        logger.info("Relinked %d orphaned bracket citations", relinked)
    return result


def _norm_title(title: str) -> str:
    """Normalize a title for fuzzy comparison."""
    return re.sub(r"\s+", " ", title.strip().lower())


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
