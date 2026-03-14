"""
Utilities for parsing synthesis agent output into structured state entries.

Spec refs: FR-019, FR-018, Section 7.5, Section 7.6.
"""

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


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
            state[f"synthesis_{i}"] = {
                "title": section.get("title", topic_name),
                "body_markdown": section.get("body_markdown", ""),
                "sources": _normalize_sources(section.get("sources", [])),
            }
        else:
            state[f"synthesis_{i}"] = {
                "title": topic_name,
                "body_markdown": "Research data was insufficient for full analysis.",
                "sources": [],
            }

    return state


def _normalize_sources(raw_sources: list) -> list[dict]:
    """Normalize and deduplicate source references."""
    seen: set[str] = set()
    result = []
    for src in raw_sources:
        if isinstance(src, dict) and "url" in src:
            url = str(src["url"])
            if url not in seen:
                seen.add(url)
                result.append({"url": url, "title": str(src.get("title", url))})
    return result


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
