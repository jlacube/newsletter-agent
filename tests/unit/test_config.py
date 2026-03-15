"""Unit tests for newsletter_agent.config.schema -- models and loader.

Covers: FR-001 through FR-007, Section 11.1, Section 11.2 BDD scenarios.
"""

import pytest
import yaml

from newsletter_agent.config.schema import (
    ConfigValidationError,
    NewsletterConfig,
    TopicConfig,
    load_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_topic(name="Test Topic", query="Test query", **overrides):
    base = {"name": name, "query": query}
    base.update(overrides)
    return base


def make_config(topics=None, **overrides):
    data = {
        "newsletter": {
            "title": "Test Newsletter",
            "schedule": "0 8 * * 0",
            "recipient_email": "test@example.com",
        },
        "topics": [make_topic()] if topics is None else topics,
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# Happy path tests
# ---------------------------------------------------------------------------


def test_valid_config_minimal():
    """1 topic with required fields only. Maps to US-01 Scenario 1."""
    data = make_config()
    config = NewsletterConfig(**data)
    assert len(config.topics) == 1
    assert config.topics[0].name == "Test Topic"


def test_valid_config_three_topics():
    """3 topics, all with full fields. BDD: 'Valid config with 3 topics'."""
    topics = [
        make_topic(name="Topic A", query="Query A", search_depth="deep"),
        make_topic(name="Topic B", query="Query B"),
        make_topic(name="Topic C", query="Query C", sources=["google_search"]),
    ]
    data = make_config(topics=topics)
    config = NewsletterConfig(**data)
    assert len(config.topics) == 3


def test_valid_config_max_topics():
    """20 topics (boundary). Maps to FR-007 upper bound."""
    topics = [make_topic(name=f"Topic {i}", query=f"Query {i}") for i in range(20)]
    data = make_config(topics=topics)
    config = NewsletterConfig(**data)
    assert len(config.topics) == 20


def test_valid_config_defaults_applied():
    """Topic with no optional fields gets correct defaults. Maps to FR-003."""
    data = make_config()
    config = NewsletterConfig(**data)
    topic = config.topics[0]
    assert topic.search_depth == "standard"
    assert topic.sources == ["google_search", "perplexity"]
    assert config.settings.dry_run is False
    assert config.settings.output_dir == "output/"


def test_valid_config_utf8_topic_name():
    """Topic name with Unicode characters. Maps to spec Edge Cases."""
    topics = [make_topic(name="Resume technique", query="AI research")]
    data = make_config(topics=topics)
    config = NewsletterConfig(**data)
    assert config.topics[0].name == "Resume technique"


def test_valid_config_deep_search_depth():
    """search_depth='deep' is accepted. Maps to FR-003."""
    topics = [make_topic(search_depth="deep")]
    data = make_config(topics=topics)
    config = NewsletterConfig(**data)
    assert config.topics[0].search_depth == "deep"


def test_valid_config_single_source():
    """sources=['google_search'] only. Maps to FR-003."""
    topics = [make_topic(sources=["google_search"])]
    data = make_config(topics=topics)
    config = NewsletterConfig(**data)
    assert config.topics[0].sources == ["google_search"]


def test_valid_config_boundary_name_100_chars():
    """Name at exactly 100 chars should pass."""
    name = "A" * 100
    topics = [make_topic(name=name)]
    data = make_config(topics=topics)
    config = NewsletterConfig(**data)
    assert len(config.topics[0].name) == 100


def test_valid_config_boundary_query_500_chars():
    """Query at exactly 500 chars should pass."""
    query = "Q" * 500
    topics = [make_topic(query=query)]
    data = make_config(topics=topics)
    config = NewsletterConfig(**data)
    assert len(config.topics[0].query) == 500


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


def test_invalid_zero_topics():
    """0 topics raises error. Maps to US-01 Scenario 3, FR-007."""
    data = make_config(topics=[])
    with pytest.raises(ConfigValidationError):
        try:
            NewsletterConfig(**data)
        except Exception as e:
            raise ConfigValidationError(str(e)) from e


def test_invalid_too_many_topics():
    """21 topics raises error. BDD: 'Config with too many topics'. FR-007."""
    topics = [make_topic(name=f"Topic {i}", query=f"Query {i}") for i in range(21)]
    data = make_config(topics=topics)
    with pytest.raises(ConfigValidationError):
        try:
            NewsletterConfig(**data)
        except Exception as e:
            raise ConfigValidationError(str(e)) from e


def test_invalid_missing_topic_name():
    """Topic without name field. Maps to FR-002."""
    topics = [{"query": "Some query"}]
    data = make_config(topics=topics)
    with pytest.raises(ConfigValidationError):
        try:
            NewsletterConfig(**data)
        except Exception as e:
            raise ConfigValidationError(str(e)) from e


def test_invalid_missing_topic_query():
    """Topic without query field. BDD: 'Config with missing required field'."""
    topics = [{"name": "Name Only"}]
    data = make_config(topics=topics)
    with pytest.raises(ConfigValidationError):
        try:
            NewsletterConfig(**data)
        except Exception as e:
            raise ConfigValidationError(str(e)) from e


def test_invalid_name_too_long():
    """name > 100 chars. Maps to FR-002 constraint."""
    topics = [make_topic(name="A" * 101)]
    data = make_config(topics=topics)
    with pytest.raises(ConfigValidationError):
        try:
            NewsletterConfig(**data)
        except Exception as e:
            raise ConfigValidationError(str(e)) from e


def test_invalid_query_too_long():
    """query > 500 chars. Maps to FR-002 constraint."""
    topics = [make_topic(query="Q" * 501)]
    data = make_config(topics=topics)
    with pytest.raises(ConfigValidationError):
        try:
            NewsletterConfig(**data)
        except Exception as e:
            raise ConfigValidationError(str(e)) from e


def test_invalid_search_depth_value():
    """search_depth='ultra' not in enum. Maps to FR-003."""
    topics = [make_topic(search_depth="ultra")]
    data = make_config(topics=topics)
    with pytest.raises(ConfigValidationError):
        try:
            NewsletterConfig(**data)
        except Exception as e:
            raise ConfigValidationError(str(e)) from e


def test_invalid_source_provider():
    """sources=['bing'] unknown provider. Maps to FR-003."""
    topics = [make_topic(sources=["bing"])]
    data = make_config(topics=topics)
    with pytest.raises(ConfigValidationError):
        try:
            NewsletterConfig(**data)
        except Exception as e:
            raise ConfigValidationError(str(e)) from e


def test_invalid_email_format():
    """recipient_email='not-an-email'. Maps to FR-005."""
    data = make_config()
    data["newsletter"]["recipient_email"] = "not-an-email"
    with pytest.raises(ConfigValidationError):
        try:
            NewsletterConfig(**data)
        except Exception as e:
            raise ConfigValidationError(str(e)) from e


def test_invalid_empty_title():
    """newsletter.title=''. Maps to FR-005."""
    data = make_config()
    data["newsletter"]["title"] = ""
    with pytest.raises(ConfigValidationError):
        try:
            NewsletterConfig(**data)
        except Exception as e:
            raise ConfigValidationError(str(e)) from e


def test_invalid_duplicate_topic_names():
    """Two topics with same name. Maps to Section 7.2 uniqueness."""
    topics = [
        make_topic(name="Duplicate", query="Query A"),
        make_topic(name="Duplicate", query="Query B"),
    ]
    data = make_config(topics=topics)
    with pytest.raises(ConfigValidationError):
        try:
            NewsletterConfig(**data)
        except Exception as e:
            raise ConfigValidationError(str(e)) from e


def test_invalid_extra_field_rejected():
    """Unknown field in topic. extra='forbid' enforcement."""
    topics = [make_topic(unknown_field="value")]
    data = make_config(topics=topics)
    with pytest.raises(ConfigValidationError):
        try:
            NewsletterConfig(**data)
        except Exception as e:
            raise ConfigValidationError(str(e)) from e


# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------


def test_default_search_depth():
    """Omitted search_depth defaults to 'standard'. FR-003."""
    topic = TopicConfig(name="Test", query="Test query")
    assert topic.search_depth == "standard"


def test_default_sources():
    """Omitted sources defaults to both providers. FR-003."""
    topic = TopicConfig(name="Test", query="Test query")
    assert topic.sources == ["google_search", "perplexity"]


def test_default_dry_run():
    """Omitted dry_run defaults to False. FR-006."""
    data = make_config()
    # No settings section
    config = NewsletterConfig(**data)
    assert config.settings.dry_run is False


def test_default_output_dir():
    """Omitted output_dir defaults to 'output/'. FR-006."""
    data = make_config()
    config = NewsletterConfig(**data)
    assert config.settings.output_dir == "output/"


def test_empty_sources_replaced_with_default():
    """Empty sources list [] replaced with both providers."""
    topic = TopicConfig(name="Test", query="Test query", sources=[])
    assert topic.sources == ["google_search", "perplexity"]


# ---------------------------------------------------------------------------
# Config loader tests
# ---------------------------------------------------------------------------


def test_load_config_valid_file(sample_topics_yaml):
    """Loads valid YAML and returns NewsletterConfig. FR-001."""
    config = load_config(sample_topics_yaml)
    assert isinstance(config, NewsletterConfig)
    assert config.newsletter.title == "Weekly Tech Digest"
    assert len(config.topics) == 2


def test_load_config_file_not_found():
    """Missing file raises FileNotFoundError. FR-001 error contract."""
    with pytest.raises(FileNotFoundError, match="Config file not found"):
        load_config("/nonexistent/path/topics.yaml")


def test_load_config_invalid_yaml_syntax(tmp_path):
    """Malformed YAML raises ConfigValidationError. FR-004."""
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("  invalid:\n    - [unclosed", encoding="utf-8")
    with pytest.raises(ConfigValidationError, match="Invalid YAML"):
        load_config(str(bad_yaml))


def test_load_config_valid_yaml_invalid_data(make_config_yaml):
    """Valid YAML but failing validation raises ConfigValidationError. FR-004."""
    data = {"newsletter": {"title": ""}}  # missing required fields
    path = make_config_yaml(data)
    with pytest.raises(ConfigValidationError, match="Config validation failed"):
        load_config(path)


def test_load_config_empty_file(tmp_path):
    """Empty YAML file raises ConfigValidationError."""
    empty = tmp_path / "empty.yaml"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ConfigValidationError, match="Empty config file"):
        load_config(str(empty))


def test_load_config_non_mapping(tmp_path):
    """YAML file with a list instead of mapping raises ConfigValidationError."""
    list_yaml = tmp_path / "list.yaml"
    list_yaml.write_text("- item1\n- item2\n", encoding="utf-8")
    with pytest.raises(ConfigValidationError, match="YAML mapping"):
        load_config(str(list_yaml))


def test_config_validation_error_field_details():
    """ConfigValidationError.from_pydantic captures field-level details."""
    data = make_config(topics=[{"name": ""}])  # missing query, empty name
    try:
        NewsletterConfig(**data)
        pytest.fail("Expected ValidationError")
    except Exception as e:
        from pydantic import ValidationError
        if isinstance(e, ValidationError):
            err = ConfigValidationError.from_pydantic(e)
            assert len(err.field_errors) > 0
            assert any("field" in fe for fe in err.field_errors)


# ---------------------------------------------------------------------------
# max_research_rounds config field tests (FR-CFG-001 through FR-CFG-004)
# ---------------------------------------------------------------------------


from newsletter_agent.config.schema import AppSettings


def test_max_research_rounds_default():
    """Omitting max_research_rounds uses default 3. FR-CFG-002."""
    settings = AppSettings()
    assert settings.max_research_rounds == 3


def test_max_research_rounds_default_via_newsletter_config():
    """Omitting max_research_rounds from full config uses default 3. FR-CFG-002."""
    data = make_config()
    config = NewsletterConfig(**data)
    assert config.settings.max_research_rounds == 3


@pytest.mark.parametrize("value", [1, 2, 3, 4, 5])
def test_max_research_rounds_valid_values(value):
    """Values 1-5 are accepted. FR-CFG-001."""
    settings = AppSettings(max_research_rounds=value, min_research_rounds=1)
    assert settings.max_research_rounds == value


def test_max_research_rounds_rejects_zero():
    """Value 0 raises ValidationError. FR-CFG-003."""
    with pytest.raises(Exception, match="greater than or equal to 1"):
        AppSettings(max_research_rounds=0)


def test_max_research_rounds_rejects_six():
    """Value 6 raises ValidationError. FR-CFG-003."""
    with pytest.raises(Exception, match="less than or equal to 5"):
        AppSettings(max_research_rounds=6)


def test_max_research_rounds_rejects_negative():
    """Negative value raises ValidationError. FR-CFG-003."""
    with pytest.raises(Exception, match="greater than or equal to 1"):
        AppSettings(max_research_rounds=-1)


def test_max_research_rounds_rejects_non_integer():
    """Non-integer value raises ValidationError. FR-CFG-003."""
    with pytest.raises(Exception):
        AppSettings(max_research_rounds="abc")


def test_max_research_rounds_in_yaml_config(make_config_yaml):
    """max_research_rounds is loaded from YAML settings section. FR-CFG-004."""
    data = make_config()
    data["settings"] = {"max_research_rounds": 5}
    path = make_config_yaml(data)
    config = load_config(path)
    assert config.settings.max_research_rounds == 5


# ---------------------------------------------------------------------------
# Adaptive config field tests (FR-ADR-060 through FR-ADR-065)
# ---------------------------------------------------------------------------


class TestAdaptiveConfigFields:
    """Tests for max_searches_per_topic and min_research_rounds fields."""

    # --- max_searches_per_topic defaults ---

    def test_max_searches_per_topic_defaults_to_max_research_rounds(self):
        """Omitted max_searches_per_topic defaults to max_research_rounds. FR-ADR-061."""
        settings = AppSettings()
        assert settings.max_searches_per_topic == 3  # max_research_rounds default

    def test_max_searches_per_topic_defaults_to_custom_max_research_rounds(self):
        """max_searches_per_topic follows custom max_research_rounds. FR-ADR-061."""
        settings = AppSettings(max_research_rounds=5)
        assert settings.max_searches_per_topic == 5

    # --- max_searches_per_topic valid values ---

    @pytest.mark.parametrize("value", [1, 5, 10, 15])
    def test_max_searches_per_topic_accepts_valid_values(self, value):
        """Boundary values 1, 5, 10, 15 accepted. FR-ADR-061."""
        settings = AppSettings(max_searches_per_topic=value)
        assert settings.max_searches_per_topic == value

    # --- max_searches_per_topic invalid values ---

    def test_max_searches_per_topic_rejects_zero(self):
        """Value 0 is below minimum. FR-ADR-061."""
        with pytest.raises(Exception, match="greater than or equal to 1"):
            AppSettings(max_searches_per_topic=0)

    def test_max_searches_per_topic_rejects_sixteen(self):
        """Value 16 is above maximum. FR-ADR-061."""
        with pytest.raises(Exception, match="less than or equal to 15"):
            AppSettings(max_searches_per_topic=16)

    def test_max_searches_per_topic_rejects_non_integer(self):
        """Non-integer value rejected. FR-ADR-061."""
        with pytest.raises(Exception):
            AppSettings(max_searches_per_topic="abc")

    # --- min_research_rounds defaults ---

    def test_min_research_rounds_defaults_to_two(self):
        """Omitted min_research_rounds defaults to 2. FR-ADR-064."""
        settings = AppSettings()
        assert settings.min_research_rounds == 2

    # --- min_research_rounds valid values ---

    @pytest.mark.parametrize("value", [1, 2, 3])
    def test_min_research_rounds_accepts_valid_values(self, value):
        """Boundary values 1, 2, 3 accepted. FR-ADR-064."""
        settings = AppSettings(min_research_rounds=value)
        assert settings.min_research_rounds == value

    # --- min_research_rounds invalid values ---

    def test_min_research_rounds_rejects_zero(self):
        """Value 0 is below minimum. FR-ADR-064."""
        with pytest.raises(Exception, match="greater than or equal to 1"):
            AppSettings(min_research_rounds=0)

    def test_min_research_rounds_rejects_four(self):
        """Value 4 is above maximum. FR-ADR-064."""
        with pytest.raises(Exception, match="less than or equal to 3"):
            AppSettings(min_research_rounds=4)

    # --- cross-field validation ---

    def test_cross_field_min_greater_than_max_raises_error(self):
        """min_research_rounds > max_research_rounds raises ValueError. FR-ADR-065."""
        with pytest.raises(Exception, match="min_research_rounds.*must be.*<=.*max_research_rounds"):
            AppSettings(min_research_rounds=3, max_research_rounds=2)

    def test_cross_field_min_equals_max_succeeds(self):
        """min_research_rounds == max_research_rounds is valid edge case. FR-ADR-065."""
        settings = AppSettings(min_research_rounds=1, max_research_rounds=1)
        assert settings.min_research_rounds == 1
        assert settings.max_research_rounds == 1

    # --- backward compatibility ---

    def test_backward_compat_no_new_fields(self):
        """Existing config without new fields loads with correct defaults."""
        settings = AppSettings()
        assert settings.max_research_rounds == 3
        assert settings.max_searches_per_topic == 3
        assert settings.min_research_rounds == 2

    def test_backward_compat_yaml_no_new_fields(self, make_config_yaml):
        """YAML config without new fields loads successfully. FR-ADR-060."""
        data = make_config()
        path = make_config_yaml(data)
        config = load_config(path)
        assert config.settings.max_searches_per_topic == 3
        assert config.settings.min_research_rounds == 2
