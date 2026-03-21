"""LinkVerifierAgent - post-research agent that verifies source URLs.

When verify_links is enabled, extracts source URLs from research state
entries (research_{idx}_{provider}), verifies them concurrently, and
removes broken links from markdown text before refinement and synthesis.

Also provides SynthesisLinkVerifierAgent which runs AFTER synthesis to
catch URLs introduced or fabricated by the LLM during the synthesis step.

For deep-mode topics, per-round verification in DeepResearchOrchestrator
handles most broken links; this agent catches any remaining issues and
handles standard-mode topics.

Spec refs: FR-016 through FR-024, Section 4.3, Section 8.6.
"""

import logging
import re
from collections.abc import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types

from newsletter_agent.tools.link_verifier import (
    clean_broken_links_from_markdown,
    verify_urls,
)

logger = logging.getLogger(__name__)

# Regex for markdown links: [title](url) - excludes image links
_MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)]+)\)")


def _remove_broken_source_lines(text: str, broken_urls: set[str]) -> str:
    """Remove lines from SOURCES sections that reference broken URLs."""
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        if any(url in line for url in broken_urls):
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


class LinkVerifierAgent(BaseAgent):
    """Post-research agent that verifies source URLs in research output.

    Reads config_verify_links from session state. If false, no-ops.
    If true, collects URLs from research_{idx}_{provider} state entries,
    verifies them concurrently, and removes broken links so downstream
    agents (refiner, synthesizer) only see verified sources.

    Spec refs: FR-016 through FR-024, Section 4.3, Section 8.6.
    """

    model_config = {"arbitrary_types_allowed": True}
    topic_count: int = 0
    providers: list = []

    async def _run_async_impl(
        self,
        ctx: InvocationContext,
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state

        if not state.get("config_verify_links", False):
            logger.info("Link verification skipped (verify_links=false)")
            yield Event(
                author=self.name,
                content=types.Content(
                    parts=[types.Part(text="Link verification skipped")]
                ),
            )
            return

        # Collect all unique URLs from research state entries
        all_urls: set[str] = set()
        research_entries: dict[str, str] = {}

        for idx in range(self.topic_count):
            for provider in self.providers:
                key = f"research_{idx}_{provider}"
                text = state.get(key)
                if not text or not isinstance(text, str):
                    continue
                research_entries[key] = text

                for match in _MARKDOWN_LINK_RE.finditer(text):
                    url = match.group(2)
                    if url.startswith(("http://", "https://")):
                        all_urls.add(url)

        if not all_urls:
            logger.info("Link verification: no source URLs to verify")
            yield Event(
                author=self.name,
                content=types.Content(
                    parts=[types.Part(text="No URLs to verify")]
                ),
            )
            return

        # Verify all URLs concurrently
        try:
            results = await verify_urls(list(all_urls))
        except Exception as exc:
            logger.warning(
                "Link verification failed entirely, proceeding with "
                "unverified links: %s",
                exc,
            )
            yield Event(
                author=self.name,
                content=types.Content(
                    parts=[
                        types.Part(
                            text="Link verification failed, proceeding unverified"
                        )
                    ]
                ),
            )
            return

        broken_urls = {
            url for url, result in results.items() if result.status == "broken"
        }
        valid_count = len(results) - len(broken_urls)

        logger.info(
            "Link verification: %d/%d URLs verified, %d broken",
            valid_count,
            len(results),
            len(broken_urls),
        )

        for url in sorted(broken_urls):
            result = results[url]
            title_info = f", title='{result.page_title}'" if result.page_title else ""
            logger.info(
                "Broken link removed: %s - reason: %s%s", url, result.error, title_info
            )

        if not broken_urls:
            yield Event(
                author=self.name,
                content=types.Content(
                    parts=[
                        types.Part(
                            text=f"All {len(results)} source links verified"
                        )
                    ]
                ),
            )
            return

        # Clean broken links from each research entry
        for key, text in research_entries.items():
            cleaned = clean_broken_links_from_markdown(text, broken_urls)
            cleaned = _remove_broken_source_lines(cleaned, broken_urls)

            if cleaned != text:
                before_urls = len(_MARKDOWN_LINK_RE.findall(text))
                after_urls = len(_MARKDOWN_LINK_RE.findall(cleaned))
                logger.info(
                    "[LinkVerifier] %s: %d -> %d source links after cleaning",
                    key, before_urls, after_urls,
                )
                state[key] = cleaned

        yield Event(
            author=self.name,
            content=types.Content(
                parts=[
                    types.Part(
                        text=(
                            f"Link verification complete: {valid_count}/{len(results)} "
                            f"valid, {len(broken_urls)} removed"
                        )
                    )
                ]
            ),
        )


class SynthesisLinkVerifierAgent(BaseAgent):
    """Post-synthesis agent that verifies URLs in the final synthesis output.

    The synthesis LLM can introduce or fabricate URLs that were not in the
    original research data. This agent runs AFTER SynthesisPostProcessor
    and BEFORE the output phase to remove any broken links from the final
    synthesis content (synthesis_N state keys).

    Reads config_verify_links from session state. If false, no-ops.
    """

    model_config = {"arbitrary_types_allowed": True}
    topic_count: int = 0

    async def _run_async_impl(
        self,
        ctx: InvocationContext,
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state

        if not state.get("config_verify_links", False):
            logger.info("Post-synthesis link verification skipped (verify_links=false)")
            yield Event(
                author=self.name,
                content=types.Content(
                    parts=[types.Part(text="Post-synthesis link verification skipped")]
                ),
            )
            return

        # Collect all unique URLs from synthesis state entries
        all_urls: set[str] = set()
        synthesis_entries: dict[str, dict] = {}

        for idx in range(self.topic_count):
            key = f"synthesis_{idx}"
            section = state.get(key)
            if not section or not isinstance(section, dict):
                continue
            synthesis_entries[key] = section

            # URLs from body_markdown
            body = section.get("body_markdown", "")
            if body:
                for match in _MARKDOWN_LINK_RE.finditer(body):
                    url = match.group(2)
                    if url.startswith(("http://", "https://")):
                        all_urls.add(url)

            # URLs from sources list
            for src in section.get("sources", []):
                url = src.get("url", "")
                if url.startswith(("http://", "https://")):
                    all_urls.add(url)

        if not all_urls:
            logger.info("Post-synthesis link verification: no URLs to verify")
            yield Event(
                author=self.name,
                content=types.Content(
                    parts=[types.Part(text="No synthesis URLs to verify")]
                ),
            )
            return

        logger.info(
            "Post-synthesis link verification: checking %d unique URLs",
            len(all_urls),
        )

        # Verify all URLs concurrently
        try:
            results = await verify_urls(list(all_urls))
        except Exception as exc:
            logger.warning(
                "Post-synthesis link verification failed, proceeding unverified: %s",
                exc,
            )
            yield Event(
                author=self.name,
                content=types.Content(
                    parts=[
                        types.Part(
                            text="Post-synthesis verification failed, proceeding unverified"
                        )
                    ]
                ),
            )
            return

        broken_urls = {
            url for url, result in results.items() if result.status == "broken"
        }
        valid_count = len(results) - len(broken_urls)

        logger.info(
            "Post-synthesis link verification: %d/%d valid, %d broken",
            valid_count,
            len(results),
            len(broken_urls),
        )

        for url in sorted(broken_urls):
            result = results[url]
            title_info = f", title='{result.page_title}'" if result.page_title else ""
            logger.info(
                "Post-synthesis broken link: %s - reason: %s%s",
                url, result.error, title_info,
            )

        if not broken_urls:
            yield Event(
                author=self.name,
                content=types.Content(
                    parts=[
                        types.Part(
                            text=f"All {len(results)} synthesis links verified"
                        )
                    ]
                ),
            )
            return

        # Clean broken links from each synthesis entry
        for key, section in synthesis_entries.items():
            body = section.get("body_markdown", "")
            if body:
                cleaned_body = clean_broken_links_from_markdown(body, broken_urls)
                if cleaned_body != body:
                    before_urls = len(_MARKDOWN_LINK_RE.findall(body))
                    after_urls = len(_MARKDOWN_LINK_RE.findall(cleaned_body))
                    logger.info(
                        "[SynthesisLinkVerifier] %s body: %d -> %d inline links",
                        key, before_urls, after_urls,
                    )
                    section["body_markdown"] = cleaned_body

            # Remove broken URLs from sources list
            sources = section.get("sources", [])
            if sources:
                cleaned_sources = [
                    s for s in sources
                    if s.get("url", "") not in broken_urls
                ]
                if len(cleaned_sources) != len(sources):
                    logger.info(
                        "[SynthesisLinkVerifier] %s sources: %d -> %d",
                        key, len(sources), len(cleaned_sources),
                    )
                    section["sources"] = cleaned_sources

            state[key] = section

        yield Event(
            author=self.name,
            content=types.Content(
                parts=[
                    types.Part(
                        text=(
                            f"Post-synthesis verification: {valid_count}/{len(results)} "
                            f"valid, {len(broken_urls)} broken links removed"
                        )
                    )
                ]
            ),
        )
