"""BDD-style acceptance tests for search timeframe configuration.

Uses Given/When/Then structure per spec Section 11.2.
Covers: global timeframe, per-topic override, custom days, absolute range,
invalid timeframe rejection, no timeframe configured.

Spec refs: Section 11.2 Feature: Search Timeframe Configuration, US-01, US-02.
"""

import textwrap
import pytest
import yaml

from newsletter_agent.config.schema import (
    ConfigValidationError,
    NewsletterConfig,
    load_config,
)
from newsletter_agent.config.timeframe import resolve_timeframe


def _write_yaml(tmp_path, data: dict) -> str:
    """Write a topics.yaml and return its path."""
    path = tmp_path / "topics.yaml"
    path.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")
    return str(path)


def _base_config(**settings_overrides) -> dict:
    """Return a minimal valid config dict with optional settings overrides."""
    cfg = {
        "newsletter": {
            "title": "Test Newsletter",
            "schedule": "weekly",
            "recipient_email": "test@example.com",
        },
        "settings": {"dry_run": True, **settings_overrides},
    }
    return cfg


class TestGlobalTimeframeFiltersAllTopics:
    """Scenario: Global timeframe filters all topics

    Given a topics.yaml with settings.timeframe set to "last_week"
    And 3 topics with no individual timeframe
    When the config is loaded
    Then all 3 topics resolve to perplexity_recency_filter "week"
    And all 3 topics have prompt instruction containing "last week"
    """

    def test_global_timeframe_applied_to_all_topics(self, tmp_path):
        # Given settings.timeframe = "last_week" and 3 topics without timeframe
        data = _base_config(timeframe="last_week")
        data["topics"] = [
            {"name": "AI", "query": "AI news"},
            {"name": "ML", "query": "ML news"},
            {"name": "LLM", "query": "LLM news"},
        ]
        cfg = NewsletterConfig(**data)

        # When we resolve each topic's effective timeframe
        # (topics without override inherit global)
        for topic in cfg.topics:
            effective = topic.timeframe or cfg.settings.timeframe
            resolved = resolve_timeframe(effective)

            # Then perplexity_recency_filter is "week"
            assert resolved.perplexity_recency_filter == "week"
            # And prompt instruction contains "last week"
            assert "last week" in resolved.prompt_date_instruction


class TestPerTopicTimeframeOverridesGlobal:
    """Scenario: Per-topic timeframe overrides global

    Given a topics.yaml with settings.timeframe set to "last_week"
    And topic "AI" has timeframe "last_month"
    When the config is loaded
    Then topic "AI" resolves to perplexity_recency_filter "month"
    And other topics resolve to perplexity_recency_filter "week"
    """

    def test_topic_override_takes_precedence(self, tmp_path):
        # Given global = "last_week", topic "AI" overrides to "last_month"
        data = _base_config(timeframe="last_week")
        data["topics"] = [
            {"name": "AI", "query": "AI news", "timeframe": "last_month"},
            {"name": "ML", "query": "ML news"},
        ]
        cfg = NewsletterConfig(**data)

        # When resolving AI's timeframe
        ai_topic = cfg.topics[0]
        ai_effective = ai_topic.timeframe or cfg.settings.timeframe
        ai_resolved = resolve_timeframe(ai_effective)

        # Then AI resolves to "month"
        assert ai_resolved.perplexity_recency_filter == "month"

        # And ML (no override) resolves to global "week"
        ml_topic = cfg.topics[1]
        ml_effective = ml_topic.timeframe or cfg.settings.timeframe
        ml_resolved = resolve_timeframe(ml_effective)
        assert ml_resolved.perplexity_recency_filter == "week"


class TestCustomDaysTimeframe:
    """Scenario: Custom days timeframe

    Given a topics.yaml with topic timeframe "last_30_days"
    When the config is loaded
    Then the topic resolves to perplexity_recency_filter "month"
    And prompt instruction contains "last 30 days"
    """

    def test_custom_days_resolved_correctly(self, tmp_path):
        # Given topic timeframe = "last_30_days"
        data = _base_config()
        data["topics"] = [
            {"name": "AI", "query": "AI news", "timeframe": "last_30_days"},
        ]
        cfg = NewsletterConfig(**data)

        # When resolving the topic's timeframe
        resolved = resolve_timeframe(cfg.topics[0].timeframe)

        # Then perplexity_recency_filter is "month"
        assert resolved.perplexity_recency_filter == "month"
        # And prompt instruction contains "last 30 days"
        assert "last 30 days" in resolved.prompt_date_instruction


class TestAbsoluteDateRangeTimeframe:
    """Scenario: Absolute date range timeframe

    Given a topics.yaml with topic timeframe "between 2025-01-01 and 2025-06-30"
    When the config is loaded
    Then the topic resolves to perplexity_recency_filter None
    And prompt instruction contains "between 2025-01-01 and 2025-06-30"
    """

    def test_absolute_range_resolved(self, tmp_path):
        # Given absolute range timeframe
        data = _base_config()
        data["topics"] = [
            {
                "name": "AI",
                "query": "AI news",
                "timeframe": "between 2025-01-01 and 2025-06-30",
            },
        ]
        cfg = NewsletterConfig(**data)

        # When resolving the topic's timeframe
        resolved = resolve_timeframe(cfg.topics[0].timeframe)

        # Then perplexity_recency_filter is None (no preset mapping)
        assert resolved.perplexity_recency_filter is None
        # And prompt instruction contains the date range
        assert "between 2025-01-01 and 2025-06-30" in resolved.prompt_date_instruction


class TestInvalidTimeframeRejectedAtConfigLoad:
    """Scenario: Invalid timeframe rejected at config load

    Given a topics.yaml with settings.timeframe set to "last_forever"
    When the config is loaded
    Then a ConfigValidationError is raised
    And the error message lists valid timeframe formats
    """

    def test_invalid_timeframe_raises_validation_error(self, tmp_path):
        # Given invalid timeframe value
        data = _base_config(timeframe="last_forever")
        data["topics"] = [{"name": "AI", "query": "AI news"}]
        path = _write_yaml(tmp_path, data)

        # When the config is loaded
        with pytest.raises(ConfigValidationError) as exc_info:
            load_config(path)

        # Then a ConfigValidationError is raised with format guidance
        assert "last_forever" in str(exc_info.value) or "Valid formats" in str(exc_info.value)

    def test_invalid_timeframe_in_model_constructor(self):
        # Given invalid timeframe directly in model
        data = _base_config(timeframe="last_forever")
        data["topics"] = [{"name": "AI", "query": "AI news"}]

        # When constructing the model
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            NewsletterConfig(**data)

        # Then validation fails with informative message
        errors = exc_info.value.errors()
        assert any("last_forever" in str(e) or "Valid formats" in str(e) for e in errors)


class TestNoTimeframeConfigured:
    """Scenario: No timeframe configured

    Given a topics.yaml with no timeframe fields
    When the config is loaded
    Then all topics resolve to perplexity_recency_filter None
    And no date instructions are added to prompts
    """

    def test_no_timeframe_resolves_to_none(self, tmp_path):
        # Given no timeframe fields
        data = _base_config()
        data["topics"] = [
            {"name": "AI", "query": "AI news"},
            {"name": "ML", "query": "ML news"},
        ]
        cfg = NewsletterConfig(**data)

        # When resolving timeframes
        for topic in cfg.topics:
            effective = topic.timeframe or cfg.settings.timeframe
            resolved = resolve_timeframe(effective)

            # Then perplexity_recency_filter is None
            assert resolved.perplexity_recency_filter is None
            # And no date instructions
            assert resolved.prompt_date_instruction is None
