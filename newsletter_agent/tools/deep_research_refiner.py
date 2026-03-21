"""DeepResearchRefinerAgent - LLM-based source refinement for deep-mode topics.

After multi-round research and link verification, evaluates all verified
sources for deep-mode topics and selects the 5-20 most relevant per
provider using LLM-based relevance scoring.

Spec refs: FR-REF-001 through FR-REF-007, Section 4.4, Section 8.3.
"""

import json
import logging
import re
from collections.abc import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types

from newsletter_agent.prompts.refinement import get_refinement_instruction

logger = logging.getLogger(__name__)

_MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\((https?://[^\)]+)\)")
_REFINEMENT_MODEL = "gemini-2.5-flash"
_MIN_SOURCES = 5
_MAX_SOURCES = 20


class DeepResearchRefinerAgent(BaseAgent):
    """Selects the most relevant sources per deep-mode topic after verification.

    For each deep-mode topic-provider combination with more than 20 sources,
    calls the LLM to evaluate and select the best 5-20 sources. Updates
    the research state key in-place, removing non-selected source references.

    Standard-mode topics are passed through without modification (no-op).

    Spec refs: FR-REF-001, FR-REF-006, Section 8.3.
    """

    model_config = {"arbitrary_types_allowed": True}
    topic_count: int = 0
    providers: list = []
    topic_configs: list = []

    async def _run_async_impl(
        self,
        ctx: InvocationContext,
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state

        any_refined = False
        for idx in range(self.topic_count):
            if idx >= len(self.topic_configs):
                continue
            topic = self.topic_configs[idx]

            # FR-REF-006: no-op for standard-mode topics
            if topic.search_depth != "deep":
                continue

            for provider in self.providers:
                key = f"research_{idx}_{provider}"
                research_text = state.get(key)
                if not research_text or not isinstance(research_text, str):
                    continue

                refined = await self._refine_sources(
                    topic.name, provider, key, research_text, state, idx
                )
                any_refined = any_refined or refined

        if not any_refined:
            logger.info("[Refinement] No deep-mode topics needed refinement")
            yield Event(
                author=self.name,
                content=types.Content(
                    parts=[types.Part(text="Refinement skipped for standard topics")]
                ),
            )
        else:
            yield Event(
                author=self.name,
                content=types.Content(
                    parts=[types.Part(text="Source refinement completed")]
                ),
            )

    async def _refine_sources(
        self,
        topic_name: str,
        provider: str,
        state_key: str,
        research_text: str,
        state: dict,
        topic_index: int = 0,
    ) -> bool:
        """Refine sources for a single topic-provider combination.

        Returns True if refinement was performed, False if skipped.
        """
        # Extract all source URLs
        urls = _extract_source_urls(research_text)
        source_count = len(urls)

        # FR-REF-005: keep all if fewer than 5
        if source_count < _MIN_SOURCES:
            logger.info(
                "[Refinement] Topic %s/%s: %d sources, skipping (below minimum)",
                topic_name, provider, source_count,
            )
            return False

        # Section 8.3 no-op: skip if already within target range
        if source_count <= _MAX_SOURCES:
            logger.info(
                "[Refinement] Topic %s/%s: %d sources, skipping (already in range)",
                topic_name, provider, source_count,
            )
            return False

        # FR-REF-002, FR-REF-003: LLM-based refinement needed
        logger.info(
            "[Refinement] Topic %s/%s: %d sources, refining",
            topic_name, provider, source_count,
        )

        target_count = min(_MAX_SOURCES, source_count)
        selected_urls = await self._call_refinement_llm(
            topic_name, research_text, urls, target_count, topic_index
        )

        if selected_urls is None:
            # LLM failed - keep all sources
            return False

        # FR-REF-004: update state in-place
        updated_text = _filter_sources_in_text(research_text, selected_urls)
        after_count = len(_extract_source_urls(updated_text))

        # FR-REF-007: log before/after counts
        logger.info(
            "[Refinement] Refined topic %s/%s: %d -> %d sources",
            topic_name, provider, source_count, after_count,
        )

        state[state_key] = updated_text
        return True

    async def _call_refinement_llm(
        self,
        topic_name: str,
        research_text: str,
        urls: list[str],
        target_count: int,
        topic_index: int = 0,
    ) -> list[str] | None:
        """Call the LLM for source evaluation. Returns selected URLs or None on failure."""
        summary_text, sources_text = _split_summary_sources(research_text)
        source_list = "\n".join(f"- {url}" for url in urls)

        prompt = get_refinement_instruction(
            topic_name=topic_name,
            target_count=target_count,
            research_text=summary_text or research_text,
            source_list=source_list,
        )

        try:
            from newsletter_agent.telemetry import traced_generate

            response = await traced_generate(
                model=_REFINEMENT_MODEL,
                contents=prompt,
                agent_name="DeepResearchRefiner",
                phase="refinement",
                topic_name=topic_name,
                topic_index=topic_index,
            )
            raw_text = response.text
        except Exception:
            logger.warning(
                "[Refinement] LLM call failed for topic %s, keeping all sources",
                topic_name,
                exc_info=True,
            )
            return None

        # Parse JSON response
        try:
            parsed = _parse_llm_response(raw_text)
        except (json.JSONDecodeError, KeyError, TypeError):
            logger.warning(
                "[Refinement] Invalid JSON from LLM for topic %s, keeping all sources",
                topic_name,
            )
            return None

        if not parsed:
            logger.warning(
                "[Refinement] Empty selection from LLM for topic %s, keeping all sources",
                topic_name,
            )
            return None

        # Filter to only URLs that exist in the original source list
        url_set = set(urls)
        valid_selected = [u for u in parsed if u in url_set]

        # FR-REF-005: clamp to [5, 20] range
        if len(valid_selected) < _MIN_SOURCES:
            logger.warning(
                "[Refinement] LLM selected fewer than %d valid URLs for topic %s, keeping all sources",
                _MIN_SOURCES, topic_name,
            )
            return None

        if len(valid_selected) > _MAX_SOURCES:
            valid_selected = valid_selected[:_MAX_SOURCES]

        return valid_selected


def _extract_source_urls(text: str) -> list[str]:
    """Extract unique source URLs from markdown links in text."""
    seen: set[str] = set()
    urls: list[str] = []
    for match in _MARKDOWN_LINK_RE.finditer(text):
        url = match.group(2)
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _split_summary_sources(text: str) -> tuple[str, str]:
    """Split research text into SUMMARY and SOURCES sections."""
    if "SOURCES:" in text:
        parts = text.split("SOURCES:", 1)
        raw_summary = parts[0]
        if "SUMMARY:" in raw_summary:
            raw_summary = raw_summary.split("SUMMARY:", 1)[1]
        return raw_summary.strip(), parts[1].strip()
    return text.strip(), ""


def _parse_llm_response(raw_text: str) -> list[str] | None:
    """Parse JSON response from the refinement LLM."""
    if not raw_text or not raw_text.strip():
        return None

    cleaned = raw_text.strip()
    # Strip markdown code fences if present
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()

    parsed = json.loads(cleaned)
    if isinstance(parsed, dict) and "selected_urls" in parsed:
        selected = parsed["selected_urls"]
        if isinstance(selected, list) and all(isinstance(u, str) for u in selected):
            return selected
    return None


def _filter_sources_in_text(research_text: str, selected_urls: list[str]) -> str:
    """Remove non-selected source references from research text.

    Preserves SUMMARY text and filters SOURCES section to only include
    lines whose URL is in the selected set.
    """
    selected_set = set(selected_urls)

    if "SOURCES:" not in research_text:
        # No clean SOURCES section, skip refinement for safety
        return research_text

    parts = research_text.split("SOURCES:", 1)
    summary_section = parts[0]
    sources_section = parts[1]

    # Filter source lines: keep only those with selected URLs
    filtered_lines = []
    for line in sources_section.strip().split("\n"):
        match = _MARKDOWN_LINK_RE.search(line)
        if match:
            url = match.group(2)
            if url in selected_set:
                filtered_lines.append(line)
        elif line.strip():
            # Keep non-link lines (e.g., section headers within sources)
            filtered_lines.append(line)

    filtered_sources = "\n".join(filtered_lines)
    return f"{summary_section}SOURCES:\n{filtered_sources}"
