"""
HTML sanitization for LLM-generated content.

Converts markdown to safe HTML and strips dangerous tags/attributes.
Spec refs: Section 10.2, OWASP A03.
"""

import re

import markdown
import nh3

ALLOWED_TAGS = {"a", "p", "strong", "em", "ul", "ol", "li", "h3", "h4", "br"}
ALLOWED_ATTRIBUTES = {"a": {"href"}}
ALLOWED_URL_SCHEMES = {"http", "https"}


def sanitize_synthesis_html(markdown_text: str) -> str:
    """Convert markdown text to sanitized HTML safe for email embedding.

    Args:
        markdown_text: Raw markdown text from the synthesis agent.

    Returns:
        Sanitized HTML string with only allowed tags and attributes.
    """
    if not markdown_text:
        return ""

    # Convert markdown to HTML using the markdown library
    html = markdown.markdown(
        markdown_text,
        extensions=["extra"],
        output_format="html",
    )

    # Sanitize with nh3
    return nh3.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes=ALLOWED_URL_SCHEMES,
    )
