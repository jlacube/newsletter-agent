"""
Timeframe parsing, validation, and resolution for search date filtering.

Converts user-facing timeframe strings (e.g., "last_week", "last_30_days",
"between 2025-01-01 and 2025-06-30") into provider-specific parameters.

Spec refs: FR-001 through FR-009, Section 7.1, Section 8.4.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

# ---------------------------------------------------------------------------
# Regex patterns for timeframe value parsing
# ---------------------------------------------------------------------------

_PRESET_VALUES = {"last_week", "last_2_weeks", "last_month", "last_year"}

_CUSTOM_DAYS_RE = re.compile(r"^last_(\d+)_days$")

_ABSOLUTE_RE = re.compile(
    r"^between\s+(\d{4}-\d{2}-\d{2})\s+and\s+(\d{4}-\d{2}-\d{2})$"
)

_VALID_FORMATS_MSG = (
    "Valid formats: 'last_week', 'last_2_weeks', 'last_month', 'last_year', "
    "'last_X_days' (X=1-365), 'between YYYY-MM-DD and YYYY-MM-DD'"
)


# ---------------------------------------------------------------------------
# Pydantic validator function
# ---------------------------------------------------------------------------


def validate_timeframe(value: str | None) -> str | None:
    """Validate a timeframe string for use as a Pydantic BeforeValidator.

    Returns the value unchanged if valid, or raises ValueError with a
    descriptive message if invalid.
    """
    if value is None:
        return None

    if not isinstance(value, str):
        raise ValueError(
            f"Invalid timeframe type: expected string, got {type(value).__name__}. "
            f"{_VALID_FORMATS_MSG}"
        )

    if value in _PRESET_VALUES:
        return value

    m = _CUSTOM_DAYS_RE.match(value)
    if m:
        days = int(m.group(1))
        if days < 1 or days > 365:
            raise ValueError(
                f"Invalid timeframe '{value}': X must be between 1 and 365. "
                f"{_VALID_FORMATS_MSG}"
            )
        return value

    m = _ABSOLUTE_RE.match(value)
    if m:
        start_str, end_str = m.group(1), m.group(2)
        try:
            start_date = date.fromisoformat(start_str)
        except ValueError:
            raise ValueError(
                f"Invalid timeframe '{value}': '{start_str}' is not a valid date. "
                f"{_VALID_FORMATS_MSG}"
            )
        try:
            end_date = date.fromisoformat(end_str)
        except ValueError:
            raise ValueError(
                f"Invalid timeframe '{value}': '{end_str}' is not a valid date. "
                f"{_VALID_FORMATS_MSG}"
            )
        if start_date >= end_date:
            raise ValueError(
                f"Invalid timeframe '{value}': start date must be before end date."
            )
        if end_date > date.today():
            raise ValueError(
                f"Invalid timeframe '{value}': end date must not be in the future."
            )
        return value

    raise ValueError(
        f"Invalid timeframe '{value}'. {_VALID_FORMATS_MSG}"
    )


# ---------------------------------------------------------------------------
# Resolved timeframe dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedTimeframe:
    """Provider-specific parameters derived from a user-facing timeframe string.

    Attributes:
        perplexity_recency_filter: One of "day", "week", "month", or None.
        prompt_date_instruction: Natural-language clause for agent prompts, or None.
        original_value: The raw timeframe string from config, or None.
    """

    perplexity_recency_filter: str | None
    prompt_date_instruction: str | None
    original_value: str | None


_NONE_RESOLVED = ResolvedTimeframe(
    perplexity_recency_filter=None,
    prompt_date_instruction=None,
    original_value=None,
)


def resolve_timeframe(value: str | None) -> ResolvedTimeframe:
    """Convert a validated timeframe string to provider-specific parameters.

    Args:
        value: A validated timeframe string, or None.

    Returns:
        ResolvedTimeframe with provider-specific filter and prompt instruction.
    """
    if value is None:
        return _NONE_RESOLVED

    # Named presets
    if value == "last_week":
        return ResolvedTimeframe(
            perplexity_recency_filter="week",
            prompt_date_instruction="Focus on results from the last week.",
            original_value=value,
        )
    if value == "last_2_weeks":
        return ResolvedTimeframe(
            perplexity_recency_filter="month",
            prompt_date_instruction="Focus on results from the last 2 weeks.",
            original_value=value,
        )
    if value == "last_month":
        return ResolvedTimeframe(
            perplexity_recency_filter="month",
            prompt_date_instruction="Focus on results from the past month.",
            original_value=value,
        )
    if value == "last_year":
        return ResolvedTimeframe(
            perplexity_recency_filter=None,
            prompt_date_instruction="Focus on results from the past year.",
            original_value=value,
        )

    # Custom days: last_X_days
    m = _CUSTOM_DAYS_RE.match(value)
    if m:
        days = int(m.group(1))
        if days <= 1:
            pfilter = "day"
        elif days <= 7:
            pfilter = "week"
        elif days <= 31:
            pfilter = "month"
        else:
            pfilter = None
        return ResolvedTimeframe(
            perplexity_recency_filter=pfilter,
            prompt_date_instruction=f"Focus on results from the last {days} days.",
            original_value=value,
        )

    # Absolute range: between YYYY-MM-DD and YYYY-MM-DD
    m = _ABSOLUTE_RE.match(value)
    if m:
        start_str, end_str = m.group(1), m.group(2)
        return ResolvedTimeframe(
            perplexity_recency_filter=None,
            prompt_date_instruction=(
                f"Only include results published between {start_str} and {end_str}."
            ),
            original_value=value,
        )

    # Fallback (should not happen if validation ran first)
    return _NONE_RESOLVED
