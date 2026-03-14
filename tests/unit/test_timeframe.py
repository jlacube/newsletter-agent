"""Unit tests for newsletter_agent.config.timeframe -- validation and resolution.

Covers: FR-001 through FR-009, Section 11.1 (Timeframe parsing and resolution).
"""

from datetime import date, timedelta

import pytest

from newsletter_agent.config.timeframe import (
    ResolvedTimeframe,
    resolve_timeframe,
    validate_timeframe,
)


# ---------------------------------------------------------------------------
# validate_timeframe -- valid inputs
# ---------------------------------------------------------------------------


class TestValidateTimeframeValid:

    @pytest.mark.parametrize("value", [
        "last_week",
        "last_2_weeks",
        "last_month",
        "last_year",
    ])
    def test_presets_accepted(self, value):
        assert validate_timeframe(value) == value

    @pytest.mark.parametrize("value", [
        "last_1_days",
        "last_7_days",
        "last_30_days",
        "last_100_days",
        "last_365_days",
    ])
    def test_custom_days_accepted(self, value):
        assert validate_timeframe(value) == value

    def test_absolute_range_accepted(self):
        result = validate_timeframe("between 2025-01-01 and 2025-06-30")
        assert result == "between 2025-01-01 and 2025-06-30"

    def test_none_accepted(self):
        assert validate_timeframe(None) is None


# ---------------------------------------------------------------------------
# validate_timeframe -- invalid inputs
# ---------------------------------------------------------------------------


class TestValidateTimeframeInvalid:

    def test_last_0_days_rejected(self):
        with pytest.raises(ValueError, match="X must be between 1 and 365"):
            validate_timeframe("last_0_days")

    def test_last_500_days_rejected(self):
        with pytest.raises(ValueError, match="X must be between 1 and 365"):
            validate_timeframe("last_500_days")

    @pytest.mark.parametrize("value", [
        "last_forever",
        "yesterday",
        "",
        "recent",
    ])
    def test_invalid_strings_rejected(self, value):
        with pytest.raises(ValueError, match="Invalid timeframe"):
            validate_timeframe(value)

    def test_absolute_range_start_after_end(self):
        with pytest.raises(ValueError, match="start date must be before end date"):
            validate_timeframe("between 2025-06-30 and 2025-01-01")

    def test_absolute_range_future_end(self):
        future = date.today() + timedelta(days=365)
        far_future = future + timedelta(days=30)
        value = f"between {future.isoformat()} and {far_future.isoformat()}"
        with pytest.raises(ValueError, match="must not be in the future"):
            validate_timeframe(value)

    def test_absolute_range_invalid_month(self):
        with pytest.raises(ValueError, match="not a valid date"):
            validate_timeframe("between 2025-13-01 and 2025-06-30")

    def test_non_string_rejected(self):
        with pytest.raises(ValueError, match="expected string"):
            validate_timeframe(42)


# ---------------------------------------------------------------------------
# resolve_timeframe -- presets
# ---------------------------------------------------------------------------


class TestResolveTimeframePresets:

    def test_last_week(self):
        r = resolve_timeframe("last_week")
        assert r.perplexity_recency_filter == "week"
        assert "last week" in r.prompt_date_instruction.lower()
        assert r.original_value == "last_week"

    def test_last_month(self):
        r = resolve_timeframe("last_month")
        assert r.perplexity_recency_filter == "month"
        assert "month" in r.prompt_date_instruction.lower()

    def test_last_2_weeks(self):
        r = resolve_timeframe("last_2_weeks")
        assert r.perplexity_recency_filter == "month"
        assert "2 weeks" in r.prompt_date_instruction.lower()

    def test_last_year(self):
        r = resolve_timeframe("last_year")
        assert r.perplexity_recency_filter is None
        assert "year" in r.prompt_date_instruction.lower()


# ---------------------------------------------------------------------------
# resolve_timeframe -- custom days
# ---------------------------------------------------------------------------


class TestResolveTimeframeCustomDays:

    def test_1_day_maps_to_day(self):
        r = resolve_timeframe("last_1_days")
        assert r.perplexity_recency_filter == "day"

    def test_7_days_maps_to_week(self):
        r = resolve_timeframe("last_7_days")
        assert r.perplexity_recency_filter == "week"

    def test_8_days_maps_to_month(self):
        r = resolve_timeframe("last_8_days")
        assert r.perplexity_recency_filter == "month"

    def test_30_days_maps_to_month(self):
        r = resolve_timeframe("last_30_days")
        assert r.perplexity_recency_filter == "month"

    def test_31_days_maps_to_month(self):
        r = resolve_timeframe("last_31_days")
        assert r.perplexity_recency_filter == "month"

    def test_32_days_maps_to_none(self):
        r = resolve_timeframe("last_32_days")
        assert r.perplexity_recency_filter is None

    def test_90_days_maps_to_none(self):
        r = resolve_timeframe("last_90_days")
        assert r.perplexity_recency_filter is None

    def test_instruction_contains_days(self):
        r = resolve_timeframe("last_14_days")
        assert "14 days" in r.prompt_date_instruction


# ---------------------------------------------------------------------------
# resolve_timeframe -- absolute ranges
# ---------------------------------------------------------------------------


class TestResolveTimeframeAbsolute:

    def test_absolute_range(self):
        r = resolve_timeframe("between 2025-01-01 and 2025-06-30")
        assert r.perplexity_recency_filter is None
        assert "2025-01-01" in r.prompt_date_instruction
        assert "2025-06-30" in r.prompt_date_instruction
        assert r.original_value == "between 2025-01-01 and 2025-06-30"


# ---------------------------------------------------------------------------
# resolve_timeframe -- None
# ---------------------------------------------------------------------------


class TestResolveTimeframeNone:

    def test_none_returns_all_none(self):
        r = resolve_timeframe(None)
        assert r.perplexity_recency_filter is None
        assert r.prompt_date_instruction is None
        assert r.original_value is None
