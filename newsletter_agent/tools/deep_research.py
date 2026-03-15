"""DeepResearchOrchestrator - adaptive deep research via custom BaseAgent.

For deep-mode topics, uses a Plan-Search-Analyze-Decide adaptive loop:
a PlanningAgent identifies key aspects and an initial search query,
each round is followed by an AnalysisAgent that evaluates findings and
suggests the next query, and the orchestrator exits when saturation is
detected or configured limits are reached.

Spec refs: FR-ADR-001 through FR-ADR-085, Section 4, Section 8.1,
           Section 9.4 (Design Decisions ADR-1 through ADR-4).
"""

import json
import logging
import re
from collections.abc import AsyncGenerator

from google.adk.agents import BaseAgent, LlmAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types

from newsletter_agent.prompts.reasoning import (
    get_analysis_instruction,
    get_planning_instruction,
)

logger = logging.getLogger(__name__)

_MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\((https?://[^\)]+)\)")
_BARE_URL_RE = re.compile(r"(?<!\()(https?://[^\s\)\]>\"]+)")

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
            initial_query, key_aspects, plan_events = await self._run_planning(ctx)
            for ev in plan_events:
                yield ev
            plan_intent = initial_query  # reuse for context
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

            # Search round
            search_agent = self._make_search_agent(round_idx, current_query)
            async for event in search_agent.run_async(ctx):
                yield event

            # Read round output
            latest_key = f"deep_research_latest_{idx}_{prov}"
            round_output = state.get(latest_key, "")
            round_key = f"research_{idx}_{prov}_round_{round_idx}"
            state[round_key] = round_output
            round_count += 1
            searches_done += 1

            # Track URLs
            new_urls = self._extract_urls(round_output)
            prev_total = len(accumulated_urls)
            accumulated_urls.update(new_urls)

            logger.info(
                "[AdaptiveResearch] Topic %s/%s round %d: %d new URLs, %d total",
                self.topic_name, prov, round_idx,
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

            # --- Analysis phase ---
            prior_summary = self._format_prior_rounds(adaptive_context["rounds"])
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
            for ev in analysis_events:
                yield ev

            # Update adaptive context
            adaptive_context["rounds"].append({
                "round_idx": round_idx,
                "query": current_query,
                "findings_summary": analysis["findings_summary"],
                "knowledge_gaps": analysis["knowledge_gaps"],
                "urls_found": len(accumulated_urls) - prev_total,
                "coverage_assessment": analysis["coverage_assessment"],
                "saturated": analysis["saturated"],
            })

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
        merged = self._merge_rounds(state, round_count)
        state[f"research_{idx}_{prov}"] = merged

        # --- Cleanup intermediate keys ---
        self._cleanup_state(state, round_count)

        yield Event(
            author=self.name,
            content=types.Content(
                parts=[types.Part(text=(
                    f"[AdaptiveResearch] Topic {self.topic_name}/{prov}: "
                    f"completed {round_count} rounds ({exit_reason}), "
                    f"{len(accumulated_urls)} unique URLs"
                ))],
            ),
        )

    async def _run_planning(
        self, ctx: InvocationContext
    ) -> tuple[str, list[str], list[Event]]:
        """Invoke PlanningAgent and return initial query, key aspects, and events."""
        idx = self.topic_idx
        prov = self.provider

        planner = LlmAgent(
            name=f"AdaptivePlanner_{idx}_{prov}",
            model=self.model,
            instruction=get_planning_instruction(self.query, self.topic_name),
            output_key=f"adaptive_plan_{idx}_{prov}",
        )

        events: list[Event] = []
        async for event in planner.run_async(ctx):
            events.append(event)

        raw = ctx.session.state.get(f"adaptive_plan_{idx}_{prov}", "")
        return self._parse_planning_output(raw) + (events,)

    def _parse_planning_output(self, raw: str) -> tuple[str, list[str]]:
        """Parse PlanningAgent JSON output with fallback."""
        cleaned = self._strip_code_fences(raw)
        try:
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

        except (json.JSONDecodeError, TypeError, ValueError):
            logger.warning(
                "[AdaptiveResearch] Planning failed for %s/%s, using fallback",
                self.topic_name, self.provider,
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

        analyzer = LlmAgent(
            name=f"AdaptiveAnalyzer_{idx}_{prov}_r{round_idx}",
            model=self.model,
            instruction=get_analysis_instruction(
                topic_name=topic_name,
                query=query,
                key_aspects=key_aspects,
                prior_rounds_summary=prior_rounds_summary,
                latest_results=latest_results,
                round_idx=round_idx,
                current_query=current_query,
                remaining_searches=remaining_searches,
            ),
            output_key=f"adaptive_analysis_{idx}_{prov}",
        )

        events: list[Event] = []
        async for event in analyzer.run_async(ctx):
            events.append(event)

        raw = ctx.session.state.get(f"adaptive_analysis_{idx}_{prov}", "")
        return self._parse_analysis_output(raw, round_idx), events

    def _parse_analysis_output(self, raw: str, round_idx: int) -> dict:
        """Parse AnalysisAgent JSON output with fallback."""
        cleaned = self._strip_code_fences(raw)
        try:
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

        except (json.JSONDecodeError, TypeError, ValueError):
            suffix_idx = round_idx % len(_FALLBACK_SUFFIXES)
            logger.warning(
                "[AdaptiveResearch] Analysis failed for %s/%s round %d, using fallback query",
                self.topic_name, self.provider, round_idx,
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

        for key in keys_to_delete:
            state.pop(key, None)
