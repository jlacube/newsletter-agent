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
