"""LinkVerifierAgent - post-synthesis agent that verifies source URLs.

When verify_links is enabled, extracts source URLs from synthesis state,
verifies them concurrently, and removes broken links from sources and
inline markdown citations.

Spec refs: FR-014, FR-015, FR-020, FR-021, FR-023, FR-024, Section 8.6.
"""

import logging
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

_ALL_BROKEN_NOTICE = (
    "\n\n*Note: Sources for this topic could not be verified "
    "and have been omitted.*"
)


class LinkVerifierAgent(BaseAgent):
    """Post-synthesis agent that verifies source URLs and removes broken links.

    Reads config_verify_links from session state. If false, no-ops.
    If true, collects all source URLs across topics, verifies them
    concurrently, removes broken links from sources lists and inline
    markdown citations, and appends a notice when all sources for a
    topic are removed.

    Spec refs: Section 8.6, FR-014 through FR-024.
    """

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

        # Collect all unique URLs across topics
        topic_count = state.get("config_topic_count", 0)
        all_urls: set[str] = set()
        for i in range(topic_count):
            synth = state.get(f"synthesis_{i}")
            if synth and "sources" in synth:
                for source in synth["sources"]:
                    url = source.get("url")
                    if url:
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
            "Link verification: %d/%d URLs verified, %d removed",
            valid_count,
            len(results),
            len(broken_urls),
        )

        for url in sorted(broken_urls):
            result = results[url]
            logger.debug("Broken link removed: %s - reason: %s", url, result.error)

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

        # Clean each topic's synthesis data
        for i in range(topic_count):
            synth = state.get(f"synthesis_{i}")
            if not synth:
                continue

            original_sources = synth.get("sources", [])
            cleaned_sources = [
                s for s in original_sources if s.get("url") not in broken_urls
            ]

            body = synth.get("body_markdown", "")
            cleaned_body = clean_broken_links_from_markdown(body, broken_urls)

            # Append notice if all sources were removed
            if not cleaned_sources and original_sources:
                cleaned_body += _ALL_BROKEN_NOTICE

            state[f"synthesis_{i}"] = {
                **synth,
                "sources": cleaned_sources,
                "body_markdown": cleaned_body,
            }

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
