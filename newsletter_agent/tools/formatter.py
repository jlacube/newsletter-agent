"""
Newsletter formatter agent - renders HTML from synthesis state data.

Spec refs: FR-021, FR-022, FR-026, Section 9.1.
"""

import logging
import os
from collections.abc import AsyncGenerator
from datetime import date, datetime, timezone

import jinja2
from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types

from newsletter_agent.tools.sanitizer import sanitize_synthesis_html

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")

_jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(_TEMPLATE_DIR),
    autoescape=True,
)


def render_newsletter(template_data: dict) -> str:
    """Render the newsletter HTML template with the given data.

    Args:
        template_data: Dict with newsletter_title, newsletter_date,
            executive_summary, sections, all_sources, generation_time_seconds.

    Returns:
        Rendered HTML string.
    """
    template = _jinja_env.get_template("newsletter.html.j2")
    return template.render(**template_data)


class FormatterAgent(BaseAgent):
    """Custom BaseAgent that renders the newsletter HTML from synthesis state."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        config_title = state.get("config_newsletter_title", "Newsletter")
        today = date.today().isoformat()

        # Collect synthesis sections
        sections = []
        all_sources: list[dict] = []
        topic_count = state.get("config_topic_count", 0)

        # Use known topic count to iterate; insert placeholders for missing sections
        if topic_count > 0:
            for topic_index in range(topic_count):
                key = f"synthesis_{topic_index}"
                section_data = state.get(key)
                if section_data is None:
                    sections.append({
                        "title": f"Topic {topic_index + 1}",
                        "body_html": "<p>Research unavailable for this topic.</p>",
                        "sources": [],
                    })
                    continue

                body_html = sanitize_synthesis_html(
                    section_data.get("body_markdown", "")
                )

                section = {
                    "title": section_data.get("title", f"Topic {topic_index + 1}"),
                    "body_html": body_html,
                    "sources": section_data.get("sources", []),
                }
                sections.append(section)
                all_sources.extend(section["sources"])
        else:
            # Fallback: iterate until missing key (legacy behavior)
            topic_index = 0
            while True:
                key = f"synthesis_{topic_index}"
                section_data = state.get(key)
                if section_data is None:
                    break

                body_html = sanitize_synthesis_html(
                    section_data.get("body_markdown", "")
                )

                section = {
                    "title": section_data.get("title", f"Topic {topic_index}"),
                    "body_html": body_html,
                    "sources": section_data.get("sources", []),
                }
                sections.append(section)
                all_sources.extend(section["sources"])
                topic_index += 1

        # Deduplicate all sources
        seen_urls: set[str] = set()
        unique_sources = []
        for src in all_sources:
            url = src.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_sources.append(src)

        # Get executive summary
        executive_summary = state.get("executive_summary", [])

        # Calculate generation time
        start_time = state.get("pipeline_start_time")
        gen_time = 0.0
        if start_time:
            try:
                gen_time = (
                    datetime.now(timezone.utc)
                    - datetime.fromisoformat(start_time)
                ).total_seconds()
            except (ValueError, TypeError):
                gen_time = 0.0

        # Build template context
        template_data = {
            "newsletter_title": config_title,
            "newsletter_date": today,
            "executive_summary": executive_summary,
            "sections": sections,
            "all_sources": unique_sources,
            "generation_time_seconds": gen_time,
        }

        newsletter_html = render_newsletter(template_data)

        # Store in state
        state["newsletter_html"] = newsletter_html
        state["newsletter_metadata"] = {
            "title": config_title,
            "date": today,
            "topic_count": len(sections),
            "generation_time_seconds": gen_time,
        }

        logger.info(
            "Newsletter formatted: %d sections, %d sources, %d chars HTML",
            len(sections),
            len(unique_sources),
            len(newsletter_html),
        )

        yield Event(
            author=self.name,
            content=types.Content(
                parts=[types.Part(text=f"Newsletter formatted: {len(sections)} sections")]
            ),
        )
