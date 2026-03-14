"""
Perplexity Sonar API search tool for Newsletter Agent.

Wraps the Perplexity API (OpenAI-compatible) as an ADK FunctionTool.
Spec refs: FR-009, FR-014, FR-015, Section 8.2.
"""

import logging
import os
from typing import Any
from urllib.parse import urlparse

from google.adk.tools import FunctionTool
from openai import OpenAI

logger = logging.getLogger(__name__)

# Hardcoded API endpoint - no user-controlled URLs (SSRF mitigation)
_PERPLEXITY_BASE_URL = "https://api.perplexity.ai"

# Model mapping: search depth -> Perplexity model name
_MODEL_MAP = {
    "standard": "sonar",
    "deep": "sonar-pro",
}


def search_perplexity(query: str, search_depth: str = "standard", search_recency_filter: str | None = None) -> dict[str, Any]:
    """Search Perplexity Sonar API for information on a topic.

    Args:
        query: Natural language search query describing what to research.
        search_depth: "standard" uses sonar model, "deep" uses sonar-pro model.
        search_recency_filter: Optional Perplexity recency filter ("day", "week", "month").

    Returns:
        dict with keys:
            - text (str): Synthesized research response
            - sources (list[dict]): List of {url, title} source references
            - provider (str): Always "perplexity"
        OR on failure:
            - error (bool): True
            - message (str): Error description
            - provider (str): Always "perplexity"
    """
    try:
        api_key = os.environ.get("PERPLEXITY_API_KEY")
        if not api_key:
            logger.error("PERPLEXITY_API_KEY environment variable not set")
            return {
                "error": True,
                "message": "PERPLEXITY_API_KEY environment variable not set",
                "provider": "perplexity",
            }

        model = _MODEL_MAP.get(search_depth, "sonar")
        logger.info("Perplexity search: query='%s', model='%s'", query[:100], model)

        client = OpenAI(api_key=api_key, base_url=_PERPLEXITY_BASE_URL)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a research assistant. Provide detailed, factual "
                        "information with specific data points, dates, and context. "
                        "Focus on recent developments and cite your sources."
                    ),
                },
                {"role": "user", "content": query},
            ],
        }
        if search_recency_filter is not None:
            kwargs["extra_body"] = {"search_recency_filter": search_recency_filter}
            logger.info("Perplexity search_recency_filter: %s", search_recency_filter)

        try:
            response = client.chat.completions.create(**kwargs)
        except Exception as filter_err:
            if search_recency_filter is not None:
                logger.warning(
                    "Perplexity rejected search_recency_filter='%s': %s. Retrying without filter.",
                    search_recency_filter,
                    filter_err,
                )
                kwargs.pop("extra_body", None)
                response = client.chat.completions.create(**kwargs)
            else:
                raise

        # Extract text content
        text = ""
        if response.choices and response.choices[0].message:
            text = response.choices[0].message.content or ""

        # Extract citations - Perplexity adds these as a top-level field
        raw_citations = getattr(response, "citations", []) or []

        sources = []
        for url in raw_citations:
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                parsed = urlparse(url)
                domain = parsed.netloc.replace("www.", "")
                path_part = (
                    parsed.path.strip("/").split("/")[-1]
                    if parsed.path.strip("/")
                    else ""
                )
                title = domain + (f" - {path_part}" if path_part else "")
                sources.append({"url": url, "title": title})

        logger.info(
            "Perplexity search complete: %d chars, %d sources",
            len(text),
            len(sources),
        )

        return {"text": text, "sources": sources, "provider": "perplexity"}

    except Exception as e:
        error_type = type(e).__name__
        error_msg = f"{error_type}: {e}"
        logger.error("Perplexity search failed: %s", error_msg)
        return {"error": True, "message": error_msg, "provider": "perplexity"}


perplexity_search_tool = FunctionTool(func=search_perplexity)
