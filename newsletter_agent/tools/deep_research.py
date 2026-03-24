"""DeepResearchOrchestrator - adaptive deep research via custom BaseAgent.

For deep-mode topics, uses a Plan-Search-Analyze-Decide adaptive loop:
a PlanningAgent identifies key aspects and an initial search query,
each round is followed by an AnalysisAgent that evaluates findings and
suggests the next query, and the orchestrator exits when saturation is
detected or configured limits are reached.

Spec refs: FR-ADR-001 through FR-ADR-085, Section 4, Section 8.1,
           Section 9.4 (Design Decisions ADR-1 through ADR-4).
"""

import asyncio
import dataclasses
import json
import logging
import random
import re
from collections.abc import AsyncGenerator
from html import unescape
from typing import Any
from urllib.parse import urlparse

from google.adk.agents import BaseAgent, LlmAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types

from newsletter_agent.prompts.reasoning import (
    get_analysis_instruction,
    get_planning_instruction,
)
from newsletter_agent.tools.link_verifier import (
    clean_broken_links_from_markdown,
    verify_urls,
)

import httpx
import httpcore

logger = logging.getLogger(__name__)

# Transient network errors that should be retried rather than crashing the pipeline
_TRANSIENT_ERRORS = (httpx.ReadError, httpx.ConnectError, httpx.RemoteProtocolError,
                     httpcore.ReadError, httpcore.ConnectError, ConnectionError, TimeoutError)
_MAX_RETRIES = 2
_RETRY_BASE_DELAY = 3.0  # seconds

_MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\((https?://[^\)]+)\)")
_BARE_URL_RE = re.compile(r"(?<!\()(https?://[^\s\)\]>\"]+)")
_TITLED_PAREN_URL_LINE_RE = re.compile(
    r"^\s*[-*]?\s*(?P<title>.+?)\s*\((?P<url>https?://[^\s)]+)\)\s*$",
    re.MULTILINE,
)
_HTML_LINK_RE = re.compile(
    r"<a\b[^>]*\bhref=[\"'](?P<url>https?://[^\"']+)[\"'][^>]*>(?P<title>.*?)</a>",
    re.IGNORECASE,
)

_FALLBACK_SUFFIXES = [
    "trends and developments",
    "expert analysis and opinions",
    "data statistics and benchmarks",
    "implications and predictions",
]

_DEFAULT_ASPECTS = [
    "recent developments",
    "expert opinions",
    "data and statistics",
    "industry implications",
    "emerging trends",
]


_GROUNDING_REDIRECT_HOST = "vertexaisearch.cloud.google.com"
_GROUNDING_REDIRECT_PATH_PREFIX = "/grounding-api-redirect/"
_RESOLVE_TIMEOUT = 10.0
_RESOLVE_MAX_CONCURRENT = 10


def _extract_text_from_events(events: list[Event]) -> str:
    """Extract concatenated text from LlmAgent events.

    ADK may not populate output_key for LlmAgents running as sub-agents
    inside a custom BaseAgent. This helper extracts the model's text
    response directly from the emitted events as a fallback.
    """
    parts = []
    for ev in events:
        if not hasattr(ev, "content") or not ev.content:
            continue
        if not hasattr(ev.content, "parts") or not ev.content.parts:
            continue
        for part in ev.content.parts:
            if hasattr(part, "text") and part.text:
                parts.append(part.text)
    return "".join(parts)


def _is_grounding_redirect_url(url: str) -> bool:
    """Return True if the URL is a Google grounding redirect."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return (
        parsed.scheme.lower() == "https"
        and host == _GROUNDING_REDIRECT_HOST
        and parsed.path.startswith(_GROUNDING_REDIRECT_PATH_PREFIX)
    )


async def _resolve_single_redirect(url: str, client: httpx.AsyncClient, semaphore: asyncio.Semaphore) -> str:
    """Follow a grounding redirect URL and return the real destination.

    Returns the original URL on any error (network, timeout, etc.).
    """
    if not _is_grounding_redirect_url(url):
        return url
    async with semaphore:
        try:
            resp = await client.head(url, follow_redirects=True)
            final = str(resp.url)
            if final and final != url:
                return final
        except Exception:
            pass
        # Fallback: try GET if HEAD didn't redirect
        try:
            resp = await client.get(url, follow_redirects=True)
            final = str(resp.url)
            if final and final != url:
                return final
        except Exception:
            logger.warning(
                "[Grounding] Failed to resolve redirect URL: %s", url,
            )
    return url


async def resolve_grounding_redirects(
    urls: dict[str, str],
) -> tuple[dict[str, str], dict[str, str]]:
    """Resolve grounding redirect URLs to real destinations.

    Args:
        urls: Mapping of URI -> title.

    Returns:
        Tuple of (resolved_urls mapping, redirect_map from old -> new URL).
    """
    redirect_urls = {u for u in urls if _is_grounding_redirect_url(u)}
    if not redirect_urls:
        return urls, {}

    semaphore = asyncio.Semaphore(_RESOLVE_MAX_CONCURRENT)
    url_list = sorted(redirect_urls)

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(_RESOLVE_TIMEOUT),
        follow_redirects=True,
        max_redirects=5,
        headers={"User-Agent": "Mozilla/5.0 (compatible; NewsletterAgent/1.0)"},
    ) as client:
        tasks = [_resolve_single_redirect(u, client, semaphore) for u in url_list]
        resolved = await asyncio.gather(*tasks)

    redirect_map: dict[str, str] = {}
    for orig, real in zip(url_list, resolved):
        if real != orig:
            redirect_map[orig] = real

    # Build new urls dict with resolved URIs
    resolved_urls: dict[str, str] = {}
    for uri, title in urls.items():
        new_uri = redirect_map.get(uri, uri)
        if new_uri not in resolved_urls:  # dedup by resolved URI
            resolved_urls[new_uri] = title

    logger.info(
        "[Grounding] Resolved %d/%d grounding redirect URLs to real destinations",
        len(redirect_map), len(redirect_urls),
    )

    return resolved_urls, redirect_map


def _apply_redirect_map_to_text(text: str, redirect_map: dict[str, str]) -> str:
    """Replace grounding redirect URLs in text with their resolved destinations."""
    if not redirect_map:
        return text
    for old_url, new_url in redirect_map.items():
        text = text.replace(old_url, new_url)
    return text


def _remove_broken_source_lines(text: str, broken_urls: set[str]) -> str:
    """Remove lines from SOURCES sections that reference broken URLs."""
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        if any(url in line for url in broken_urls):
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


# --- Grounding metadata extraction (FR-GME-001 through FR-GME-051) ---

_MD_SPECIAL_RE = re.compile(r"([\[\]\(\)])")


@dataclasses.dataclass
class GroundingResult:
    """Structured result from grounding metadata extraction."""

    sources: list[dict[str, str]] = dataclasses.field(default_factory=list)
    supports: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    queries: list[str] = dataclasses.field(default_factory=list)
    has_metadata: bool = False


def _grounding_capture_callback(
    callback_context: Any,
    llm_response: Any,
    idx: int,
    prov: str,
    round_idx: int,
) -> None:
    """Capture grounding metadata into a raw state key for later parsing.

    Registered as after_model_callback on Google search LlmAgents.

    Checks two sources for grounding metadata (in priority order):
    1. ``llm_response.grounding_metadata`` - set by gemini_llm_connection when
       the Gemini API returns grounding data inline with GoogleSearchTool.
    2. ``temp:_adk_grounding_metadata`` in session state - set by
       GoogleSearchAgentTool (alternative search tool).

    Returns None (never modifies the LLM response). Never raises.
    """
    try:
        state = callback_context.state

        # Primary: read directly from the LLM response (GoogleSearchTool path)
        gm = getattr(llm_response, "grounding_metadata", None)

        # Fallback: read from temp state (GoogleSearchAgentTool path)
        if gm is None:
            gm = state.get("temp:_adk_grounding_metadata")

        if gm is None:
            return None

        raw: dict[str, Any] = {}

        # Extract grounding chunks
        chunks = getattr(gm, "grounding_chunks", None) or []
        serialized_chunks = []
        for chunk in chunks:
            web = getattr(chunk, "web", None)
            if web is None:
                continue
            uri = getattr(web, "uri", "") or ""
            title = getattr(web, "title", "") or ""
            if uri:
                serialized_chunks.append({"web": {"uri": uri, "title": title}})
        raw["grounding_chunks"] = serialized_chunks

        # Extract grounding supports
        supports = getattr(gm, "grounding_supports", None) or []
        serialized_supports = []
        for support in supports:
            segment = getattr(support, "segment", None)
            entry: dict[str, Any] = {
                "segment_text": getattr(segment, "text", "") if segment else "",
                "start_index": getattr(segment, "start_index", 0) if segment else 0,
                "end_index": getattr(segment, "end_index", 0) if segment else 0,
                "chunk_indices": list(
                    getattr(support, "grounding_chunk_indices", None) or []
                ),
            }
            serialized_supports.append(entry)
        raw["grounding_supports"] = serialized_supports

        # Extract web search queries
        raw["web_search_queries"] = list(
            getattr(gm, "web_search_queries", None) or []
        )

        key = f"_grounding_raw_{idx}_{prov}_round_{round_idx}"
        state[key] = raw

    except Exception:
        logger.warning(
            "[Grounding] Callback error capturing metadata for idx=%d/%s round %d",
            idx, prov, round_idx, exc_info=True,
        )
    return None


def _make_grounding_callback(
    idx: int, prov: str, round_idx: int
) -> Any:
    """Create a bound after_model_callback for grounding metadata capture."""

    def _cb(callback_context: Any, llm_response: Any) -> None:
        return _grounding_capture_callback(
            callback_context, llm_response, idx, prov, round_idx
        )

    return _cb


class DeepResearchOrchestrator(BaseAgent):
    """Custom BaseAgent that orchestrates adaptive deep research.

    Uses a Plan-Search-Analyze-Decide loop with LlmAgent sub-agents for
    planning, per-round searching, and analysis. Manages adaptive context,
    saturation detection, and result merging.

    Spec refs: FR-ADR-001, Section 8.1 (DeepResearchOrchestrator contract).
    """

    model_config = {"arbitrary_types_allowed": True}

    topic_idx: int = 0
    provider: str = ""
    query: str = ""
    topic_name: str = ""
    timeframe_instruction: str | None = None
    max_rounds: int = 3
    max_searches: int = 3
    min_rounds: int = 2
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

        # --- Phase 0: Planning (skip if single-round mode) ---
        if self.max_rounds > 1:
            for attempt in range(_MAX_RETRIES + 1):
                try:
                    initial_query, key_aspects, plan_events = await self._run_planning(ctx)
                    break
                except _TRANSIENT_ERRORS as exc:
                    if attempt < _MAX_RETRIES:
                        delay = _RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, 1)
                        logger.warning(
                            "[AdaptiveResearch] Topic %s/%s: planning failed (%s: %s), retrying in %.1fs (attempt %d/%d)",
                            self.topic_name, prov, type(exc).__name__, exc, delay, attempt + 1, _MAX_RETRIES,
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            "[AdaptiveResearch] Topic %s/%s: planning failed after %d retries (%s: %s), using fallback",
                            self.topic_name, prov, _MAX_RETRIES, type(exc).__name__, exc,
                        )
                        initial_query = self.query
                        key_aspects = list(_DEFAULT_ASPECTS)
                        plan_events = []
            for ev in plan_events:
                yield ev
            plan_intent = initial_query  # reuse for context
            logger.info(
                "[AdaptiveResearch] Topic %s/%s: Plan - intent: '%s', aspects: [%s], initial query: '%s'",
                self.topic_name, prov, plan_intent,
                ", ".join(key_aspects), initial_query,
            )
        else:
            initial_query = self.query
            key_aspects = []
            plan_intent = self.query

        # Initialize tracking
        adaptive_context = {
            "plan": {"query_intent": plan_intent, "key_aspects": key_aspects},
            "rounds": [],
        }
        accumulated_urls: set[str] = set()
        round_count = 0
        searches_done = 0
        used_queries: set[str] = set()
        next_query = initial_query
        exit_reason = None

        # --- Adaptive loop ---
        for round_idx in range(self.max_rounds):
            current_query = next_query if round_idx > 0 else initial_query

            # Duplicate query detection
            if current_query in used_queries:
                suffix_idx = len(used_queries) % len(_FALLBACK_SUFFIXES)
                current_query = f"{current_query} {_FALLBACK_SUFFIXES[suffix_idx]}"
                logger.warning(
                    "[AdaptiveResearch] Topic %s/%s round %d: duplicate query detected, adding suffix",
                    self.topic_name, prov, round_idx,
                )
            used_queries.add(current_query)

            # Search round (with retry for transient network errors)
            search_agent = self._make_search_agent(round_idx, current_query)
            search_succeeded = False
            for attempt in range(_MAX_RETRIES + 1):
                try:
                    async for event in search_agent.run_async(ctx):
                        yield event
                    search_succeeded = True
                    break
                except _TRANSIENT_ERRORS as exc:
                    if attempt < _MAX_RETRIES:
                        delay = _RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, 1)
                        logger.warning(
                            "[AdaptiveResearch] Topic %s/%s round %d: search failed (%s: %s), retrying in %.1fs (attempt %d/%d)",
                            self.topic_name, prov, round_idx, type(exc).__name__, exc, delay, attempt + 1, _MAX_RETRIES,
                        )
                        await asyncio.sleep(delay)
                        search_agent = self._make_search_agent(round_idx, current_query)
                    else:
                        logger.error(
                            "[AdaptiveResearch] Topic %s/%s round %d: search failed after %d retries (%s: %s), skipping round",
                            self.topic_name, prov, round_idx, _MAX_RETRIES, type(exc).__name__, exc,
                        )

            if not search_succeeded:
                # Skip this round but continue with next if we have prior data
                if round_count > 0:
                    break  # Exit loop, use data from prior rounds
                continue  # Try next round

            # Read round output
            latest_key = f"deep_research_latest_{idx}_{prov}"
            round_output = state.get(latest_key, "")
            round_count += 1
            searches_done += 1

            logger.info(
                "[AdaptiveResearch] Topic %s/%s round %d: output length=%d chars",
                self.topic_name, prov, round_idx, len(round_output),
            )

            # --- Parse grounding metadata for this round (FR-GME-005) ---
            # Must happen before link verification so grounding URIs are available
            grounding_for_round = GroundingResult()
            redirect_map_for_round: dict[str, str] = {}
            if prov == "google":
                grounding_for_round = self._parse_grounding_from_state(
                    state, idx, prov, round_idx,
                )
                if grounding_for_round.has_metadata:
                    # Resolve grounding redirect URLs to real destinations
                    src_map = {s["uri"]: s.get("title", "") for s in grounding_for_round.sources}
                    try:
                        resolved_map, redirect_map_for_round = await resolve_grounding_redirects(src_map)
                        # Update sources with resolved URLs
                        grounding_for_round.sources = [
                            {"uri": uri, "title": title}
                            for uri, title in resolved_map.items()
                        ]
                        # Replace redirect URLs in round output text
                        if redirect_map_for_round:
                            round_output = _apply_redirect_map_to_text(round_output, redirect_map_for_round)
                            state[f"deep_research_latest_{idx}_{prov}"] = round_output
                    except _TRANSIENT_ERRORS as exc:
                        logger.warning(
                            "[Grounding] Topic %s/%s round %d: redirect resolution failed (%s: %s), using raw grounding URIs",
                            self.topic_name, prov, round_idx, type(exc).__name__, exc,
                        )

                    state[f"grounding_sources_{idx}_{prov}_round_{round_idx}"] = grounding_for_round.sources
                    state[f"grounding_supports_{idx}_{prov}_round_{round_idx}"] = grounding_for_round.supports
                    state[f"grounding_queries_{idx}_{prov}_round_{round_idx}"] = grounding_for_round.queries
                    logger.info(
                        "[Grounding] Topic %s/%s round %d: extracted %d sources, "
                        "%d supports, %d queries",
                        self.topic_name, prov, round_idx,
                        len(grounding_for_round.sources),
                        len(grounding_for_round.supports),
                        len(grounding_for_round.queries),
                    )
                else:
                    logger.warning(
                        "[Grounding] Topic %s/%s round %d: no grounding metadata available",
                        self.topic_name, prov, round_idx,
                    )

            # --- Per-round link verification (if enabled) ---
            if state.get("config_verify_links", False) and round_output:
                # FR-GME-040: use grounding URIs for Google when available
                if prov == "google" and grounding_for_round.has_metadata:
                    round_urls = [s["uri"] for s in grounding_for_round.sources]
                else:
                    round_urls = list(self._extract_urls(round_output))

                if round_urls:
                    try:
                        check_results = await verify_urls(round_urls)
                        broken = {
                            url for url, r in check_results.items()
                            if r.status == "broken"
                        }
                        if broken:
                            logger.info(
                                "[AdaptiveResearch] Topic %s/%s round %d: %d/%d URLs broken, cleaning",
                                self.topic_name, prov, round_idx,
                                len(broken), len(round_urls),
                            )
                            for url in sorted(broken):
                                r = check_results[url]
                                title_info = f", title='{r.page_title}'" if r.page_title else ""
                                logger.info(
                                    "[AdaptiveResearch]   broken: %s (%s%s)",
                                    url, r.error, title_info,
                                )
                            round_output = clean_broken_links_from_markdown(
                                round_output, broken
                            )
                            round_output = _remove_broken_source_lines(
                                round_output, broken
                            )
                            # FR-GME-041: remove broken URIs from grounding sources state
                            gs_key = f"grounding_sources_{idx}_{prov}_round_{round_idx}"
                            gs = state.get(gs_key)
                            if gs:
                                state[gs_key] = [
                                    s for s in gs if s["uri"] not in broken
                                ]
                        else:
                            logger.info(
                                "[AdaptiveResearch] Topic %s/%s round %d: all %d URLs valid",
                                self.topic_name, prov, round_idx, len(round_urls),
                            )
                    except Exception as exc:
                        logger.warning(
                            "[AdaptiveResearch] Topic %s/%s round %d: link verification failed: %s",
                            self.topic_name, prov, round_idx, exc,
                        )

            round_key = f"research_{idx}_{prov}_round_{round_idx}"
            state[round_key] = round_output

            # Track URLs (only verified/surviving URLs reach the accumulator)
            # FR-GME-030: Google with grounding uses chunk URIs, not regex
            if prov == "google" and grounding_for_round.has_metadata:
                new_urls = {s["uri"] for s in grounding_for_round.sources}
            else:
                new_urls = self._extract_urls(round_output)
            prev_total = len(accumulated_urls)
            accumulated_urls.update(new_urls)

            logger.info(
                "[AdaptiveResearch] Topic %s/%s round %d: searched '%s', %d new URLs, %d total",
                self.topic_name, prov, round_idx, current_query,
                len(accumulated_urls) - prev_total, len(accumulated_urls),
            )

            yield Event(
                author=self.name,
                content=types.Content(
                    parts=[types.Part(text=(
                        f"[AdaptiveResearch] Topic {self.topic_name}/{prov} "
                        f"round {round_idx}: "
                        f"{len(accumulated_urls) - prev_total} new URLs, "
                        f"{len(accumulated_urls)} total"
                    ))],
                ),
            )

            # Single-round mode: skip analysis
            if self.max_rounds == 1:
                break

            # --- Analysis phase (with retry for transient network errors) ---
            prior_summary = self._format_prior_rounds(adaptive_context["rounds"])
            analysis = None
            analysis_events: list[Event] = []
            for attempt in range(_MAX_RETRIES + 1):
                try:
                    analysis, analysis_events = await self._run_analysis(
                        ctx,
                        topic_name=self.topic_name,
                        query=self.query,
                        key_aspects=key_aspects,
                        prior_rounds_summary=prior_summary,
                        latest_results=round_output,
                        round_idx=round_idx,
                        current_query=current_query,
                        remaining_searches=self.max_searches - searches_done,
                    )
                    break
                except _TRANSIENT_ERRORS as exc:
                    if attempt < _MAX_RETRIES:
                        delay = _RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, 1)
                        logger.warning(
                            "[AdaptiveResearch] Topic %s/%s round %d: analysis failed (%s: %s), retrying in %.1fs (attempt %d/%d)",
                            self.topic_name, prov, round_idx, type(exc).__name__, exc, delay, attempt + 1, _MAX_RETRIES,
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            "[AdaptiveResearch] Topic %s/%s round %d: analysis failed after %d retries (%s: %s), treating as saturated",
                            self.topic_name, prov, round_idx, _MAX_RETRIES, type(exc).__name__, exc,
                        )

            if analysis is None:
                # Analysis failed - treat as saturated with data from this round
                exit_reason = "analysis_network_error"
                break

            for ev in analysis_events:
                yield ev

            # Update adaptive context
            # FR-GME-050: include grounding_source_count
            grounding_src_count = (
                len(grounding_for_round.sources)
                if grounding_for_round.has_metadata
                else 0
            )
            adaptive_context["rounds"].append({
                "round_idx": round_idx,
                "query": current_query,
                "findings_summary": analysis["findings_summary"],
                "knowledge_gaps": analysis["knowledge_gaps"],
                "urls_found": len(accumulated_urls) - prev_total,
                "coverage_assessment": analysis["coverage_assessment"],
                "saturated": analysis["saturated"],
                "grounding_source_count": grounding_src_count,
            })

            logger.info(
                "[AdaptiveResearch] Topic %s/%s round %d: %s. Gaps: [%s]. Saturated: %s",
                self.topic_name, prov, round_idx,
                analysis["findings_summary"],
                ", ".join(analysis["knowledge_gaps"]),
                analysis["saturated"],
            )

            # Persist adaptive_context to session state (FR-ADR-050)
            state[f"adaptive_context_{idx}_{prov}"] = adaptive_context

            # --- Exit criteria ---
            if analysis["saturated"] and round_count >= self.min_rounds:
                exit_reason = "saturation"
                logger.info(
                    "[AdaptiveResearch] Topic %s/%s: saturated at round %d - %s",
                    self.topic_name, prov, round_idx, analysis["coverage_assessment"],
                )
                break
            elif analysis["saturated"] and round_count < self.min_rounds:
                logger.info(
                    "[AdaptiveResearch] Topic %s/%s: saturation overridden at round %d (min_rounds=%d)",
                    self.topic_name, prov, round_idx, self.min_rounds,
                )

            if len(analysis.get("knowledge_gaps", [])) == 0:
                exit_reason = "full_coverage"
                logger.info(
                    "[AdaptiveResearch] Topic %s/%s: full coverage at round %d",
                    self.topic_name, prov, round_idx,
                )
                break

            if searches_done >= self.max_searches:
                exit_reason = "search_budget_exhausted"
                logger.info(
                    "[AdaptiveResearch] Topic %s/%s: search budget exhausted (%d/%d searches)",
                    self.topic_name, prov, searches_done, self.max_searches,
                )
                break

            # Prepare next query
            next_query = analysis.get("next_query") or initial_query
        else:
            # Loop completed without break - max_rounds reached
            if exit_reason is None:
                exit_reason = "max_rounds_reached"
                gaps = ", ".join(
                    adaptive_context["rounds"][-1].get("knowledge_gaps", [])
                ) if adaptive_context["rounds"] else "unknown"
                logger.warning(
                    "[AdaptiveResearch] Topic %s/%s: reached max rounds (%d) without saturation. Gaps remaining: [%s]",
                    self.topic_name, prov, self.max_rounds, gaps,
                )

        # Store accumulated URLs
        state[f"deep_urls_accumulated_{idx}_{prov}"] = list(accumulated_urls)

        # --- Persist reasoning chain (before cleanup) ---
        state[f"adaptive_reasoning_chain_{idx}_{prov}"] = json.dumps(adaptive_context)

        # --- Merge all rounds ---
        if prov == "google":
            merged = self._merge_rounds_with_grounding(state, round_count)
        else:
            merged = self._merge_rounds(state, round_count)

        # Resolve any remaining grounding redirect URLs in merged text
        if prov == "google":
            try:
                remaining_redirects = {
                    m.group(2) if m.lastindex and m.lastindex >= 2 else m.group(0)
                    for m in _BARE_URL_RE.finditer(merged)
                    if _is_grounding_redirect_url(m.group(1) if m.lastindex else m.group(0))
                }
                # Simpler: find all URLs, filter grounding redirects
                all_urls_in_merged = set(_BARE_URL_RE.findall(merged))
                remaining_redirects = {u for u in all_urls_in_merged if _is_grounding_redirect_url(u)}
                if remaining_redirects:
                    rmap_extra: dict[str, str] = {}
                    url_title_map = {u: u for u in remaining_redirects}
                    _, rmap_extra = await resolve_grounding_redirects(url_title_map)
                    if rmap_extra:
                        merged = _apply_redirect_map_to_text(merged, rmap_extra)
                        logger.info(
                            "[Grounding] Topic %s/%s: resolved %d remaining redirect URLs in merged text",
                            self.topic_name, prov, len(rmap_extra),
                        )
            except _TRANSIENT_ERRORS as exc:
                logger.warning(
                    "[AdaptiveResearch] Topic %s/%s: grounding redirect resolution failed (%s: %s), using unresolved URLs",
                    self.topic_name, prov, type(exc).__name__, exc,
                )

        state[f"research_{idx}_{prov}"] = merged

        merged_source_count = len(_MARKDOWN_LINK_RE.findall(merged.split("SOURCES:", 1)[1] if "SOURCES:" in merged else ""))
        logger.info(
            "[AdaptiveResearch] Topic %s/%s: merged result: %d chars, %d sources in SOURCES section",
            self.topic_name, prov, len(merged), merged_source_count,
        )

        # --- Cleanup intermediate keys ---
        self._cleanup_state(state, round_count)

        logger.info(
            "[AdaptiveResearch] Topic %s/%s: completed %d rounds, %d unique URLs, exit reason: %s",
            self.topic_name, prov, round_count,
            len(accumulated_urls), exit_reason,
        )

        yield Event(
            author=self.name,
            content=types.Content(
                parts=[types.Part(text=(
                    f"[AdaptiveResearch] Topic {self.topic_name}/{prov}: "
                    f"completed {round_count} rounds, "
                    f"{len(accumulated_urls)} unique URLs, "
                    f"exit reason: {exit_reason}"
                ))],
            ),
        )

    async def _run_planning(
        self, ctx: InvocationContext
    ) -> tuple[str, list[str], list[Event]]:
        """Invoke PlanningAgent and return initial query, key aspects, and events."""
        idx = self.topic_idx
        prov = self.provider
        output_key = f"adaptive_plan_{idx}_{prov}"

        _planning_instr = get_planning_instruction(self.query, self.topic_name)
        planner = LlmAgent(
            name=f"AdaptivePlanner_{idx}_{prov}",
            model=self.model,
            instruction=lambda ctx, _s=_planning_instr: _s,
            output_key=output_key,
        )

        events: list[Event] = []
        async for event in planner.run_async(ctx):
            events.append(event)

        # Try output_key first; fall back to extracting text from events
        # (ADK may not populate output_key for sub-agents inside BaseAgent)
        raw = ctx.session.state.get(output_key, "")
        if not raw.strip():
            raw = _extract_text_from_events(events)
            if raw.strip():
                logger.info(
                    "[AdaptiveResearch] Topic %s/%s: planning output recovered from events (%d chars)",
                    self.topic_name, prov, len(raw),
                )

        return self._parse_planning_output(raw) + (events,)

    def _parse_planning_output(self, raw: str) -> tuple[str, list[str]]:
        """Parse PlanningAgent JSON output with fallback."""
        cleaned = self._extract_json_object(raw)
        try:
            if cleaned is None:
                raise ValueError("Missing JSON object")
            parsed = json.loads(cleaned)
            if not isinstance(parsed, dict):
                raise ValueError("Expected JSON object")

            initial_query = parsed.get("initial_search_query", "")
            key_aspects = parsed.get("key_aspects", [])

            if not initial_query or not isinstance(initial_query, str):
                raise ValueError("Missing initial_search_query")
            if not isinstance(key_aspects, list):
                raise ValueError("key_aspects must be a list")

            # Ensure key_aspects are strings
            key_aspects = [str(a) for a in key_aspects if a]

            # Pad if fewer than 3
            if len(key_aspects) < 3:
                for default in _DEFAULT_ASPECTS:
                    if len(key_aspects) >= 3:
                        break
                    if default not in key_aspects:
                        key_aspects.append(default)

            # Truncate if more than 5
            key_aspects = key_aspects[:5]

            return initial_query, key_aspects

        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning(
                "[AdaptiveResearch] Planning failed for %s/%s, using fallback. "
                "Reason: %s. Raw output length: %d, first 200 chars: %.200s",
                self.topic_name, self.provider, exc, len(raw), raw,
            )
            return self.query, list(_DEFAULT_ASPECTS)

    async def _run_analysis(
        self,
        ctx: InvocationContext,
        topic_name: str,
        query: str,
        key_aspects: list[str],
        prior_rounds_summary: str,
        latest_results: str,
        round_idx: int,
        current_query: str,
        remaining_searches: int,
    ) -> tuple[dict, list[Event]]:
        """Invoke AnalysisAgent and return analysis dict and events."""
        idx = self.topic_idx
        prov = self.provider

        _analysis_instr = get_analysis_instruction(
            topic_name=topic_name,
            query=query,
            key_aspects=key_aspects,
            prior_rounds_summary=prior_rounds_summary,
            latest_results=latest_results,
            round_idx=round_idx,
            current_query=current_query,
            remaining_searches=remaining_searches,
        )
        output_key = f"adaptive_analysis_{idx}_{prov}"
        analyzer = LlmAgent(
            name=f"AdaptiveAnalyzer_{idx}_{prov}_r{round_idx}",
            model=self.model,
            instruction=lambda ctx, _s=_analysis_instr: _s,
            output_key=output_key,
        )

        events: list[Event] = []
        async for event in analyzer.run_async(ctx):
            events.append(event)

        # Try output_key first; fall back to extracting text from events
        raw = ctx.session.state.get(output_key, "")
        if not raw.strip():
            raw = _extract_text_from_events(events)
            if raw.strip():
                logger.info(
                    "[AdaptiveResearch] Topic %s/%s round %d: analysis output recovered from events (%d chars)",
                    self.topic_name, prov, round_idx, len(raw),
                )

        return self._parse_analysis_output(raw, round_idx), events

    def _parse_analysis_output(self, raw: str, round_idx: int) -> dict:
        """Parse AnalysisAgent JSON output with fallback."""
        cleaned = self._extract_json_object(raw)
        try:
            if cleaned is None:
                raise ValueError("Missing JSON object")
            parsed = json.loads(cleaned)
            if not isinstance(parsed, dict):
                raise ValueError("Expected JSON object")

            findings = parsed.get("findings_summary", "")
            gaps = parsed.get("knowledge_gaps", [])
            coverage = parsed.get("coverage_assessment", "")
            saturated = parsed.get("saturated", False)
            next_q = parsed.get("next_query")
            next_rationale = parsed.get("next_query_rationale")

            if not isinstance(gaps, list):
                gaps = []
            gaps = [str(g) for g in gaps if g][:5]

            # If not saturated but no next_query, use fallback
            if not saturated and not next_q:
                suffix_idx = round_idx % len(_FALLBACK_SUFFIXES)
                next_q = f"{self.query} {_FALLBACK_SUFFIXES[suffix_idx]}"

            return {
                "findings_summary": str(findings) if findings else "",
                "knowledge_gaps": gaps,
                "coverage_assessment": str(coverage) if coverage else "",
                "saturated": bool(saturated),
                "next_query": next_q,
                "next_query_rationale": str(next_rationale) if next_rationale else None,
            }

        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            suffix_idx = round_idx % len(_FALLBACK_SUFFIXES)
            logger.warning(
                "[AdaptiveResearch] Analysis failed for %s/%s round %d, using fallback query. "
                "Reason: %s. Raw output length: %d, first 200 chars: %.200s",
                self.topic_name, self.provider, round_idx, exc, len(raw), raw,
            )
            return {
                "findings_summary": "",
                "knowledge_gaps": ["analysis failed"],
                "coverage_assessment": "",
                "saturated": False,
                "next_query": f"{self.query} {_FALLBACK_SUFFIXES[suffix_idx]}",
                "next_query_rationale": None,
            }

    @staticmethod
    def _strip_code_fences(raw: str) -> str:
        """Strip markdown code fences from LLM output."""
        if not isinstance(raw, str):
            raw = str(raw)
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [line for line in lines if not line.strip().startswith("```")]
            cleaned = "\n".join(lines)
        return cleaned.strip()

    @classmethod
    def _extract_json_object(cls, raw: str) -> str | None:
        """Extract a JSON object from model output, tolerating wrapper text."""
        cleaned = cls._strip_code_fences(raw)
        if not cleaned:
            return None

        if cleaned.startswith("{") and cleaned.endswith("}"):
            return cleaned

        match = re.search(r"\{[\s\S]*\}", cleaned)
        if match:
            return match.group(0).strip()

        return None

    @staticmethod
    def _format_prior_rounds(rounds: list[dict]) -> str:
        """Format prior rounds into a summary string for the AnalysisAgent."""
        if not rounds:
            return "No prior research rounds."
        lines = []
        for r in rounds:
            lines.append(f"Round {r['round_idx']} (query: \"{r['query']}\"):")
            lines.append(f"  Findings: {r['findings_summary']}")
            gaps = ", ".join(r["knowledge_gaps"]) if r["knowledge_gaps"] else "none"
            lines.append(f"  Remaining gaps: {gaps}")
            # FR-GME-051: include grounding source count for AnalysisAgent
            gs_count = r.get("grounding_source_count")
            if gs_count is not None:
                lines.append(f"  Grounding sources: {gs_count}")
        return "\n".join(lines)

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
                self.topic_name,
                query,
                self.search_depth,
                timeframe_instruction=self.timeframe_instruction,
            )
        else:
            instruction = get_perplexity_search_instruction(
                self.topic_name,
                query,
                self.search_depth,
                timeframe_instruction=self.timeframe_instruction,
            )

        # Wire grounding metadata callback for Google provider (FR-GME-004)
        after_cb = None
        if prov == "google":
            after_cb = _make_grounding_callback(idx, prov, round_idx)

        return LlmAgent(
            name=f"DeepSearchRound_{idx}_{prov}_r{round_idx}",
            model=self.model,
            instruction=lambda ctx, _s=instruction: _s,
            tools=list(self.tools),
            output_key=f"deep_research_latest_{idx}_{prov}",
            after_model_callback=after_cb,
        )

    @staticmethod
    def _extract_urls(text: str) -> set[str]:
        """Extract unique URLs from markdown links and bare URLs in text."""
        if not text:
            return set()
        # Markdown links: [title](url)
        urls = {match.group(2) for match in _MARKDOWN_LINK_RE.finditer(text)}
        # Source lines like: - Title (https://example.com/article)
        urls.update(match.group("url") for match in _TITLED_PAREN_URL_LINE_RE.finditer(text))
        # HTML anchors from Google search entrypoint payloads
        urls.update(match.group("url") for match in _HTML_LINK_RE.finditer(text))
        # Bare URLs on their own (not already inside a markdown link)
        urls.update(_BARE_URL_RE.findall(text))
        return urls

    def _parse_grounding_from_state(
        self, state: dict, idx: int, prov: str, round_idx: int,
    ) -> GroundingResult:
        """Parse raw grounding metadata from session state into GroundingResult.

        Reads _grounding_raw_{idx}_{prov}_round_{round_idx}, deduplicates URIs,
        escapes markdown-special characters in titles, and handles all edge cases.
        Never raises -- returns empty GroundingResult on any error.
        """
        try:
            key = f"_grounding_raw_{idx}_{prov}_round_{round_idx}"
            raw = state.get(key)
            if not raw:
                return GroundingResult()

            # Extract sources from grounding chunks
            seen_uris: dict[str, str] = {}  # uri -> title (first wins)
            chunks = raw.get("grounding_chunks", []) or []
            for i, chunk in enumerate(chunks):
                web = chunk.get("web") if isinstance(chunk, dict) else None
                if not web:
                    continue
                uri = web.get("uri", "") or ""
                if not uri or not uri.startswith("https://"):
                    continue
                title = web.get("title", "") or ""
                if not title:
                    # LOG-004: empty title
                    logger.warning(
                        "[Grounding] Topic %s/%s round %d: chunk %d has empty title, using URI",
                        self.topic_name, prov, round_idx, i,
                    )
                    title = uri
                else:
                    # Escape markdown-special characters in titles
                    title = _MD_SPECIAL_RE.sub(r"\\\1", title)
                if uri not in seen_uris:
                    seen_uris[uri] = title

            sources = [{"uri": uri, "title": title} for uri, title in seen_uris.items()]

            # Extract supports
            supports_raw = raw.get("grounding_supports", []) or []
            supports = []
            for s in supports_raw:
                if isinstance(s, dict):
                    supports.append({
                        "segment_text": s.get("segment_text", ""),
                        "start_index": s.get("start_index", 0),
                        "end_index": s.get("end_index", 0),
                        "chunk_indices": s.get("chunk_indices", []),
                    })

            # Extract queries
            queries = list(raw.get("web_search_queries", []) or [])

            return GroundingResult(
                sources=sources,
                supports=supports,
                queries=queries,
                has_metadata=True,
            )
        except Exception:
            logger.warning(
                "[Grounding] Error parsing grounding state for idx=%d/%s round %d",
                idx, prov, round_idx, exc_info=True,
            )
            return GroundingResult()

    def _merge_rounds_with_grounding(self, state: dict, round_count: int) -> str:
        """Merge rounds using grounding metadata for SOURCES (Google provider).

        SOURCES are built from grounding_sources state keys (deduplicated by URI).
        SUMMARY is built from LLM text output (same as _merge_rounds).
        Falls back to _merge_rounds if no grounding data exists for any round.
        """
        idx = self.topic_idx
        prov = self.provider

        # Collect grounding sources across all rounds
        all_sources: dict[str, str] = {}  # uri -> title (first wins)
        has_any_grounding = False

        for r in range(round_count):
            gs_key = f"grounding_sources_{idx}_{prov}_round_{r}"
            grounding_sources = state.get(gs_key)
            if grounding_sources:
                has_any_grounding = True
                for src in grounding_sources:
                    uri = src.get("uri", "")
                    if uri and uri not in all_sources:
                        all_sources[uri] = src.get("title", uri)

        if not has_any_grounding:
            # FR-GME-022: complete fallback
            logger.warning(
                "[Grounding] Topic %s/%s: no grounding metadata available, "
                "falling back to text extraction",
                self.topic_name, prov,
            )
            return self._merge_rounds(state, round_count)

        # Build SUMMARY from LLM text output and supplement grounding sources
        # with text URLs from rounds that LACK grounding metadata
        summaries: list[str] = []
        for r in range(round_count):
            round_key = f"research_{idx}_{prov}_round_{r}"
            content = state.get(round_key, "")
            if not content:
                continue
            summary_part, _ = self._split_sections(content)
            if summary_part.strip():
                if len(summaries) > 0:
                    summaries.append(f"\n\n--- Round {r} ---\n\n{summary_part}")
                else:
                    summaries.append(summary_part)

            # For rounds without grounding metadata, extract text URLs
            # as a supplement (grounding is authoritative when present)
            gs_key = f"grounding_sources_{idx}_{prov}_round_{r}"
            if not state.get(gs_key):
                for match in _MARKDOWN_LINK_RE.finditer(content):
                    title, url = match.group(1), match.group(2)
                    if url not in all_sources:
                        all_sources[url] = title
                self._collect_bare_urls(content, all_sources)

        if not summaries:
            return ""

        merged_summary = "".join(summaries)
        sources_lines = [
            f"- [{title}]({uri})" for uri, title in all_sources.items()
        ]
        sources_section = "\n".join(sources_lines)

        # LOG-003: merge summary
        logger.info(
            "[Grounding] Topic %s/%s: merged %d unique sources from "
            "grounding metadata + text extraction across %d rounds",
            self.topic_name, prov, len(all_sources), round_count,
        )

        return f"SUMMARY:\n{merged_summary}\n\nSOURCES:\n{sources_section}"

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

            # Collect unique sources from markdown links in the full content
            # (search both SUMMARY and SOURCES to catch inline citations)
            for match in _MARKDOWN_LINK_RE.finditer(content):
                title, url = match.group(1), match.group(2)
                if url not in seen_urls:
                    seen_urls[url] = title

            # Collect bare URLs not already captured via markdown links
            self._collect_bare_urls(content, seen_urls)

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

        for match in _HTML_LINK_RE.finditer(text):
            url = match.group("url")
            if url in seen_urls or url in md_urls:
                continue
            title = re.sub(r"<[^>]+>", "", match.group("title"))
            seen_urls[url] = unescape(title).strip() or url

        lines = text.split("\n")
        for i, line in enumerate(lines):
            titled_match = _TITLED_PAREN_URL_LINE_RE.match(line.strip())
            if titled_match:
                url = titled_match.group("url")
                if url not in seen_urls and url not in md_urls:
                    seen_urls[url] = titled_match.group("title").strip()
                continue

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
        """Remove all intermediate state keys for this topic/provider.

        Preserves: research_{idx}_{prov} (merged output),
                   adaptive_reasoning_chain_{idx}_{prov} (reasoning chain).
        """
        idx = self.topic_idx
        prov = self.provider

        keys_to_delete = [
            f"adaptive_plan_{idx}_{prov}",
            f"adaptive_analysis_{idx}_{prov}",
            f"adaptive_context_{idx}_{prov}",
            f"deep_research_latest_{idx}_{prov}",
            f"deep_urls_accumulated_{idx}_{prov}",
        ]
        for r in range(round_count):
            keys_to_delete.append(f"research_{idx}_{prov}_round_{r}")
            # Grounding metadata keys (FR-GME-013)
            keys_to_delete.append(f"_grounding_raw_{idx}_{prov}_round_{r}")
            keys_to_delete.append(f"grounding_sources_{idx}_{prov}_round_{r}")
            keys_to_delete.append(f"grounding_supports_{idx}_{prov}_round_{r}")
            keys_to_delete.append(f"grounding_queries_{idx}_{prov}_round_{r}")

        for key in keys_to_delete:
            state.pop(key, None)
