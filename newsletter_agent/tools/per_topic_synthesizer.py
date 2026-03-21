"""Per-topic synthesizer agent - calls the LLM once per topic to avoid truncation.

Instead of producing a single massive JSON for all topics (which gets truncated
when the combined output exceeds the model's output token limit), this agent
makes one LLM call per topic, each producing a small JSON with one section
and one executive summary entry. Results are assembled into state keys that
downstream agents (SynthesisLinkVerifier, Formatter) already expect.

Spec refs: FR-016, FR-017, FR-018, FR-019, FR-020.
"""

import asyncio
import json
import logging
import re
from collections.abc import AsyncGenerator
from typing import Any

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types

from newsletter_agent.prompts.synthesis import build_per_topic_prompt

logger = logging.getLogger(__name__)

_SYNTHESIS_MODEL = "gemini-2.5-pro"

# GenerateContentConfig shared by all per-topic calls
_GENERATE_CONFIG = types.GenerateContentConfig(
    max_output_tokens=16384,
    thinking_config=types.ThinkingConfig(
        thinking_budget=1024,
    ),
)


class PerTopicSynthesizerAgent(BaseAgent):
    """Synthesizes research into newsletter sections one topic at a time.

    For each topic, reads research data from ``research_{idx}_{provider}``
    state keys, builds a focused single-topic prompt, calls the LLM, and
    writes ``synthesis_{idx}`` and accumulates ``executive_summary``.

    Also writes ``config_topic_count`` to state for downstream consumers.
    """

    model_config = {"arbitrary_types_allowed": True}
    topic_names: list[str] = []
    providers: list[str] = []

    async def _run_async_impl(
        self,
        ctx: InvocationContext,
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        topic_count = len(self.topic_names)

        if topic_count == 0:
            logger.warning("PerTopicSynthesizer: no topics configured")
            yield Event(
                author=self.name,
                content=types.Content(
                    parts=[types.Part(text="No topics to synthesize")]
                ),
            )
            return

        # Gather research data per topic
        topic_research: list[str] = []
        for idx, name in enumerate(self.topic_names):
            parts: list[str] = []
            for prov in self.providers:
                key = f"research_{idx}_{prov}"
                data = state.get(key)
                if data and isinstance(data, str) and data.strip():
                    parts.append(
                        f"--- {prov.upper()} research for \"{name}\" ---\n{data}"
                    )
            topic_research.append("\n\n".join(parts) if parts else "")

        # Run all per-topic LLM calls concurrently
        tasks = []
        for idx, name in enumerate(self.topic_names):
            tasks.append(
                self._synthesize_topic(idx, name, topic_research[idx])
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Assemble state from results
        executive_summary: list[dict[str, str]] = []
        success_count = 0

        for idx, (name, result) in enumerate(
            zip(self.topic_names, results, strict=True)
        ):
            if isinstance(result, Exception):
                logger.error(
                    "[PerTopicSynthesizer] Topic %d '%s' failed: %s",
                    idx, name, result,
                )
                state[f"synthesis_{idx}"] = _fallback_section(name)
                executive_summary.append(
                    {"topic": name, "summary": "Synthesis failed for this topic."}
                )
                continue

            section, summary = result
            state[f"synthesis_{idx}"] = section
            executive_summary.append({"topic": name, "summary": summary})
            success_count += 1

            src_count = len(section.get("sources", []))
            body_len = len(section.get("body_markdown", ""))
            logger.info(
                "[PerTopicSynthesizer] Topic %d '%s': %d sources, body=%d chars",
                idx, name, src_count, body_len,
            )

        state["executive_summary"] = executive_summary
        state["config_topic_count"] = topic_count

        logger.info(
            "Per-topic synthesis complete: %d/%d topics succeeded",
            success_count, topic_count,
        )

        yield Event(
            author=self.name,
            content=types.Content(
                parts=[
                    types.Part(
                        text=(
                            f"Synthesized {success_count}/{topic_count} topics "
                            f"({topic_count - success_count} fallbacks)"
                        )
                    )
                ]
            ),
        )

    async def _synthesize_topic(
        self,
        idx: int,
        name: str,
        research_data: str,
    ) -> tuple[dict[str, Any], str]:
        """Call the LLM for a single topic and parse the result.

        Returns:
            Tuple of (section_dict, executive_summary_string).

        Raises:
            RuntimeError: If the LLM call or parsing fails.
        """
        if not research_data.strip():
            logger.warning(
                "[PerTopicSynthesizer] No research data for topic %d '%s'",
                idx, name,
            )
            return _fallback_section(name), "No research data was available."

        prompt = build_per_topic_prompt(name, research_data)

        try:
            from newsletter_agent.telemetry import traced_generate

            response = await traced_generate(
                model=_SYNTHESIS_MODEL,
                contents=prompt,
                config=_GENERATE_CONFIG,
                agent_name="PerTopicSynthesizer",
                phase="synthesis",
                topic_name=name,
                topic_index=idx,
            )
            raw_text = response.text
        except Exception as exc:
            raise RuntimeError(
                f"LLM call failed for topic '{name}': {exc}"
            ) from exc

        if not raw_text or not raw_text.strip():
            raise RuntimeError(f"Empty LLM response for topic '{name}'")

        logger.debug(
            "[PerTopicSynthesizer] Raw output for topic %d '%s': %d chars",
            idx, name, len(raw_text),
        )

        parsed = _try_parse_json(raw_text)
        if parsed is None:
            raise RuntimeError(
                f"Could not parse JSON for topic '{name}' "
                f"(raw length: {len(raw_text)})"
            )

        # Extract section
        raw_section = parsed.get("section", {})
        if not isinstance(raw_section, dict):
            raise RuntimeError(
                f"Missing 'section' key in response for topic '{name}'"
            )

        sources = _normalize_sources(raw_section.get("sources", []))
        body = raw_section.get("body_markdown", "")
        section = {
            "title": raw_section.get("title", name),
            "body_markdown": body,
            "sources": sources,
        }

        # Extract executive summary
        summary = parsed.get("executive_summary", "")
        if not isinstance(summary, str):
            # Sometimes returned as dict or list
            summary = str(summary)

        return section, summary


def _try_parse_json(text: str) -> dict | None:
    """Try to parse JSON from LLM output, handling code blocks."""
    stripped = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
    stripped = re.sub(r"\n?```\s*$", "", stripped)

    try:
        result = json.loads(stripped)
        if isinstance(result, dict):
            return result
    except (json.JSONDecodeError, TypeError):
        pass

    # Find JSON object in text
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, dict):
                return result
        except (json.JSONDecodeError, TypeError):
            pass

    return None


def _normalize_sources(raw_sources: list) -> list[dict]:
    """Normalize and deduplicate source references."""
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


def _fallback_section(name: str) -> dict[str, Any]:
    """Generate a fallback section for a failed topic."""
    return {
        "title": name,
        "body_markdown": "Research data was insufficient for full analysis.",
        "sources": [],
    }
