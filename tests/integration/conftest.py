"""Shared fixtures for integration tests.

Provides config objects and synthesis state fixtures used across
integration test files for WP06/WP07/WP08.
"""

import pytest

from newsletter_agent.config.schema import (
    AppSettings,
    NewsletterConfig,
    NewsletterSettings,
    TopicConfig,
)


@pytest.fixture
def config_with_both_features(tmp_path):
    """Config with timeframe and verify_links enabled."""
    return NewsletterConfig(
        newsletter=NewsletterSettings(
            title="Integration Test Newsletter",
            schedule="0 8 * * 0",
            recipient_email="test@example.com",
        ),
        settings=AppSettings(
            dry_run=True,
            output_dir=str(tmp_path),
            timeframe="last_week",
            verify_links=True,
        ),
        topics=[
            TopicConfig(
                name="AI News",
                query="Latest AI developments",
            ),
            TopicConfig(
                name="Cloud Updates",
                query="Cloud computing news",
                timeframe="last_month",
            ),
        ],
    )


@pytest.fixture
def config_old_format(tmp_path):
    """Config with NO new fields - backward compatibility baseline."""
    return NewsletterConfig(
        newsletter=NewsletterSettings(
            title="Legacy Config Test",
            schedule="0 8 * * 0",
            recipient_email="test@example.com",
        ),
        settings=AppSettings(
            dry_run=True,
            output_dir=str(tmp_path),
        ),
        topics=[
            TopicConfig(
                name="General Tech",
                query="Technology news",
            ),
        ],
    )


@pytest.fixture
def synthesis_state_with_mixed_urls():
    """Research state with some valid and some broken URLs.

    Uses research_N_{provider} keys matching the refactored
    LinkVerifierAgent (WP10).
    """
    return {
        "config_verify_links": True,
        "research_0_google": (
            "## AI News\n\n"
            "See [Good Link](https://good.example.com/ai) for details. "
            "Also check [Broken Link](https://broken.example.com/gone).\n\n"
            "More at [Another Good](https://good2.example.com)."
        ),
        "research_1_google": (
            "## Cloud Updates\n\n"
            "The [Cloud Doc](https://cloud.example.com) is comprehensive.\n\n"
            "See also [Dead Page](https://dead.example.com/404) for history."
        ),
    }
