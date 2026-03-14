import pytest
import yaml


@pytest.fixture
def sample_config_data():
    """Returns a valid config dict matching spec Section 8.4 schema."""
    return {
        "newsletter": {
            "title": "Weekly Tech Digest",
            "schedule": "0 8 * * 0",
            "recipient_email": "test@example.com",
        },
        "settings": {
            "dry_run": True,
            "output_dir": "output/",
        },
        "topics": [
            {
                "name": "AI Frameworks",
                "query": "Latest developments in AI agent frameworks",
                "search_depth": "deep",
                "sources": ["google_search", "perplexity"],
            },
            {
                "name": "Cloud Native",
                "query": "Recent cloud-native technology developments",
            },
        ],
    }


@pytest.fixture
def sample_topics_yaml(tmp_path, sample_config_data):
    """Writes a valid YAML config file and returns its path."""
    path = tmp_path / "topics.yaml"
    path.write_text(
        yaml.dump(sample_config_data, allow_unicode=True), encoding="utf-8"
    )
    return str(path)


@pytest.fixture
def make_config_yaml(tmp_path):
    """Factory fixture: creates a YAML config file with custom data."""
    def _make(data: dict) -> str:
        path = tmp_path / "topics.yaml"
        path.write_text(
            yaml.dump(data, allow_unicode=True), encoding="utf-8"
        )
        return str(path)
    return _make
