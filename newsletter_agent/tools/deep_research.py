"""DeepResearchOrchestrator - multi-round deep research via custom BaseAgent.

For deep-mode topics, generates query variants via an LLM, executes multiple
search rounds per provider, tracks URL accumulation with early exit, and
merges all round results into the standard research state key.

Spec refs: FR-MRR-001 through FR-MRR-011, Section 4.3, Section 8.3,
           Section 9.4 Decision 1.
"""

import json
import logging
import re
from collections.abc import AsyncGenerator

from google.adk.agents import BaseAgent, LlmAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types

from newsletter_agent.prompts.query_expansion import get_query_expansion_instruction

logger = logging.getLogger(__name__)

_MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\((https?://[^\)]+)\)")
_BARE_URL_RE = re.compile(r"(?<!\()(https?://[^\s\)\]>\"]+)")
_MIN_URLS_THRESHOLD = 15

_FALLBACK_SUFFIXES = [
    "trends and developments",
    "expert analysis and opinions",
    "data statistics and benchmarks",
    "implications and predictions",
]


class DeepResearchOrchestrator(BaseAgent):
    """Custom BaseAgent that orchestrates multi-round deep research.

    Creates and invokes LlmAgent sub-agents for query expansion and
    per-round searching. Manages round accumulation, URL tracking,
    early exit, and result merging.

    Spec refs: FR-MRR-001, Section 8.3 (DeepResearchOrchestrator contract).
    """

    model_config = {"arbitrary_types_allowed": True}

    topic_idx: int = 0
    provider: str = ""
    query: str = ""
    topic_name: str = ""
    max_rounds: int = 3
    search_depth: str = "deep"
    model: str = "gemini-2.5-flash"
    tools: list = []

    async def _run_async_impl(
        self,
        ctx: InvocationContext,
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        idx = self.topic_idx
        prov = self.provider

        # --- Step 1-3: Query expansion (skip when max_rounds == 1) ---
        variants: list[str] = []
        if self.max_rounds > 1:
            variants, expander_events = await self._expand_queries(ctx)
            for ev in expander_events:
                yield ev

        # --- Step 4-5: Multi-round search loop ---
        accumulated_urls: set[str] = set()
        round_count = 0

        for round_idx in range(self.max_rounds):
            # Determine query for this round
            if round_idx == 0:
                current_query = self.query
            elif round_idx - 1 < len(variants):
                current_query = variants[round_idx - 1]
            else:
                current_query = self.query

            # Set state key for instruction interpolation
            state[f"deep_query_current_{idx}_{prov}"] = current_query

            # Create and invoke a search round LlmAgent
            search_agent = self._make_search_agent(round_idx, current_query)
            async for event in search_agent.run_async(ctx):
                yield event

            # Read round output from state
            latest_key = f"deep_research_latest_{idx}_{prov}"
            round_output = state.get(latest_key, "")
            round_key = f"research_{idx}_{prov}_round_{round_idx}"
            state[round_key] = round_output
            round_count += 1

            # Extract URLs and track accumulation
            new_urls = self._extract_urls(round_output)
            prev_total = len(accumulated_urls)
            accumulated_urls.update(new_urls)

            logger.info(
                "[DeepResearch] Topic %s/%s round %d: %d new URLs, %d total accumulated",
                self.topic_name,
                prov,
                round_idx,
                len(accumulated_urls) - prev_total,
                len(accumulated_urls),
            )

            yield Event(
                author=self.name,
                content=types.Content(
                    parts=[
                        types.Part(
                            text=(
                                f"[DeepResearch] Topic {self.topic_name}/{prov} "
                                f"round {round_idx}: "
                                f"{len(accumulated_urls) - prev_total} new URLs, "
                                f"{len(accumulated_urls)} total accumulated"
                            )
                        )
                    ]
                ),
            )

            # Early exit check
            if len(accumulated_urls) >= _MIN_URLS_THRESHOLD:
                logger.info(
                    "[DeepResearch] Topic %s/%s: early exit at round %d with %d URLs (threshold: %d)",
                    self.topic_name,
                    prov,
                    round_idx,
                    len(accumulated_urls),
                    _MIN_URLS_THRESHOLD,
                )
                break

        # Store accumulated URLs in state
        state[f"deep_urls_accumulated_{idx}_{prov}"] = list(accumulated_urls)

        # --- Step 6: Merge all rounds ---
        merged = self._merge_rounds(state, round_count)
        state[f"research_{idx}_{prov}"] = merged

        # --- Step 7: Cleanup intermediate keys ---
        self._cleanup_state(state, round_count)

        yield Event(
            author=self.name,
            content=types.Content(
                parts=[
                    types.Part(
                        text=(
                            f"[DeepResearch] Topic {self.topic_name}/{prov}: "
                            f"completed {round_count} rounds, "
                            f"{len(accumulated_urls)} unique URLs"
                        )
                    )
                ]
            ),
        )

    async def _expand_queries(
        self, ctx: InvocationContext
    ) -> tuple[list[str], list[Event]]:
        """Invoke QueryExpanderAgent and return parsed query variants and events."""
        idx = self.topic_idx
        prov = self.provider
        variant_count = self.max_rounds - 1

        expander = LlmAgent(
            name=f"QueryExpander_{idx}_{prov}",
            model=self.model,
            instruction=get_query_expansion_instruction(
                self.query, self.topic_name, variant_count
            ),
            output_key=f"deep_queries_{idx}_{prov}",
        )

        events: list[Event] = []
        async for event in expander.run_async(ctx):
            events.append(event)

        raw = ctx.session.state.get(f"deep_queries_{idx}_{prov}", "[]")
        return self._parse_variants(raw, variant_count), events

    def _parse_variants(self, raw: str, variant_count: int) -> list[str]:
        """Parse JSON array of query variants with fallback."""
        if not isinstance(raw, str):
            raw = str(raw)

        # Strip markdown code fences if present
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)
        cleaned = cleaned.strip()

        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, list) and all(isinstance(v, str) for v in parsed):
                return parsed[:variant_count]
        except (json.JSONDecodeError, TypeError):
            pass

        logger.warning(
            "[DeepResearch] Failed to parse query variants, using fallback suffixes"
        )
        return [
            f"{self.query} {suffix}"
            for suffix in _FALLBACK_SUFFIXES[:variant_count]
        ]

    def _make_search_agent(self, round_idx: int, query: str) -> LlmAgent:
        """Create a LlmAgent for a single search round."""
        idx = self.topic_idx
        prov = self.provider

        from newsletter_agent.prompts.research_google import (
            get_google_search_instruction,
        )
        from newsletter_agent.prompts.research_perplexity import (
            get_perplexity_search_instruction,
        )

        if prov == "google":
            instruction = get_google_search_instruction(
                self.topic_name, query, self.search_depth
            )
        else:
            instruction = get_perplexity_search_instruction(
                self.topic_name, query, self.search_depth
            )

        return LlmAgent(
            name=f"DeepSearchRound_{idx}_{prov}_r{round_idx}",
            model=self.model,
            instruction=instruction,
            tools=list(self.tools),
            output_key=f"deep_research_latest_{idx}_{prov}",
        )

    @staticmethod
    def _extract_urls(text: str) -> set[str]:
        """Extract unique URLs from markdown links and bare URLs in text."""
        if not text:
            return set()
        # Markdown links: [title](url)
        urls = {match.group(2) for match in _MARKDOWN_LINK_RE.finditer(text)}
        # Bare URLs on their own (not already inside a markdown link)
        urls.update(_BARE_URL_RE.findall(text))
        return urls

    def _merge_rounds(self, state: dict, round_count: int) -> str:
        """Merge all round outputs into a single research result."""
        idx = self.topic_idx
        prov = self.provider

        summaries: list[str] = []
        seen_urls: dict[str, str] = {}  # url -> title (first occurrence)

        for r in range(round_count):
            round_key = f"research_{idx}_{prov}_round_{r}"
            content = state.get(round_key, "")
            if not content:
                continue

            # Parse SUMMARY and SOURCES sections
            summary_part, sources_part = self._split_sections(content)

            if summary_part.strip():
                if len(summaries) > 0:
                    summaries.append(f"\n\n--- Round {r} ---\n\n{summary_part}")
                else:
                    summaries.append(summary_part)

            # Collect unique sources from markdown links
            for match in _MARKDOWN_LINK_RE.finditer(sources_part or content):
                title, url = match.group(1), match.group(2)
                if url not in seen_urls:
                    seen_urls[url] = title

            # Collect bare URLs not already captured via markdown links
            self._collect_bare_urls(sources_part or content, seen_urls)

        if not summaries:
            return ""

        merged_summary = "".join(summaries)
        sources_lines = [f"- [{title}]({url})" for url, title in seen_urls.items()]
        sources_section = "\n".join(sources_lines)

        return f"SUMMARY:\n{merged_summary}\n\nSOURCES:\n{sources_section}"

    @staticmethod
    def _collect_bare_urls(text: str, seen_urls: dict[str, str]) -> None:
        """Extract bare URLs from text and infer titles from preceding lines.

        Handles output formats like:
            - Title of the article
              https://example.com/article
        """
        # Get all URLs already captured from markdown links
        md_urls = {m.group(2) for m in _MARKDOWN_LINK_RE.finditer(text)}

        lines = text.split("\n")
        for i, line in enumerate(lines):
            bare_match = _BARE_URL_RE.search(line.strip())
            if not bare_match:
                continue
            url = bare_match.group(1)
            if url in seen_urls or url in md_urls:
                continue
            # Check if this URL is inside a markdown link on the same line
            if f"]({url})" in line:
                continue
            # Try to use the previous line as the title
            title = url
            if i > 0:
                prev = lines[i - 1].strip().lstrip("-*").strip()
                if prev and not prev.startswith("http"):
                    title = prev
            seen_urls[url] = title

    @staticmethod
    def _split_sections(content: str) -> tuple[str, str]:
        """Split content into SUMMARY and SOURCES sections."""
        summary = ""
        sources = ""
        if "SOURCES:" in content:
            parts = content.split("SOURCES:", 1)
            raw_summary = parts[0]
            sources = parts[1]
        else:
            raw_summary = content

        if "SUMMARY:" in raw_summary:
            summary = raw_summary.split("SUMMARY:", 1)[1]
        else:
            summary = raw_summary

        return summary.strip(), sources.strip()

    def _cleanup_state(self, state: dict, round_count: int) -> None:
        """Remove all intermediate state keys for this topic/provider."""
        idx = self.topic_idx
        prov = self.provider

        keys_to_delete = [
            f"deep_queries_{idx}_{prov}",
            f"deep_research_latest_{idx}_{prov}",
            f"deep_urls_accumulated_{idx}_{prov}",
            f"deep_query_current_{idx}_{prov}",
        ]
        for r in range(round_count):
            keys_to_delete.append(f"research_{idx}_{prov}_round_{r}")

        for key in keys_to_delete:
            state.pop(key, None)
