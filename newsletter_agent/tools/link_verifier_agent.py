"""LinkVerifierAgent - pre-synthesis agent that verifies source URLs.

When verify_links is enabled, extracts source URLs from research state keys,
verifies them concurrently, and removes broken links from research text
so that only verified sources reach the synthesis agent.

Spec refs: FR-PSV-001 through FR-PSV-006, FR-014, FR-015, Section 8.6.
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


class LinkVerifierAgent(BaseAgent):
    """Pre-synthesis agent that verifies source URLs in research results.

    Reads config_verify_links from session state. If false, no-ops.
    If true, collects URLs from research_N_{provider} state keys,
    verifies them concurrently, and removes broken links from the
    research text so synthesis only sees verified sources.

    Spec refs: FR-PSV-001 through FR-PSV-006, Section 8.6.
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

        # Collect all unique URLs from research state keys
        all_urls: set[str] = set()
        research_keys: list[str] = []

        for i in range(self.topic_count):
            for provider in self.providers:
                key = f"research_{i}_{provider}"
                val = state.get(key)
                if val and isinstance(val, str):
                    research_keys.append(key)
                    for match in _MARKDOWN_LINK_RE.finditer(val):
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

        # Clean broken links from each research state key
        for key in research_keys:
            val = state.get(key)
            if val and isinstance(val, str):
                state[key] = clean_broken_links_from_markdown(val, broken_urls)

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
