"""Integration test: Config + Perplexity Timeframe Passthrough.

Verifies that search_recency_filter is correctly passed to the Perplexity API
when a timeframe is configured, and that the retry-without-filter logic works.

Spec refs: FR-007, FR-010, Section 11.3.
"""

import pytest
from unittest.mock import MagicMock, patch, call

from newsletter_agent.tools.perplexity_search import search_perplexity


class TestPerplexityRecencyFilter:
    @patch.dict("os.environ", {"PERPLEXITY_API_KEY": "test-key"})
    @patch("newsletter_agent.tools.perplexity_search.OpenAI")
    def test_week_filter_passed(self, mock_openai_cls):
        """When timeframe is last_week, extra_body contains search_recency_filter: week."""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "AI news from last week"
        mock_response.citations = ["https://example.com/ai"]
        mock_client.chat.completions.create.return_value = mock_response

        result = search_perplexity("AI news", "standard", search_recency_filter="week")

        # Verify extra_body was passed
        create_call = mock_client.chat.completions.create.call_args
        assert create_call.kwargs.get("extra_body") == {"search_recency_filter": "week"} or \
               create_call[1].get("extra_body") == {"search_recency_filter": "week"}

    @patch.dict("os.environ", {"PERPLEXITY_API_KEY": "test-key"})
    @patch("newsletter_agent.tools.perplexity_search.OpenAI")
    def test_month_filter_passed(self, mock_openai_cls):
        """When timeframe is last_month, extra_body contains search_recency_filter: month."""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Cloud news"
        mock_response.citations = []
        mock_client.chat.completions.create.return_value = mock_response

        search_perplexity("Cloud news", "standard", search_recency_filter="month")

        create_call = mock_client.chat.completions.create.call_args
        assert "extra_body" in create_call[1]
        assert create_call[1]["extra_body"]["search_recency_filter"] == "month"

    @patch.dict("os.environ", {"PERPLEXITY_API_KEY": "test-key"})
    @patch("newsletter_agent.tools.perplexity_search.OpenAI")
    def test_day_filter_passed(self, mock_openai_cls):
        """When timeframe maps to day, extra_body contains search_recency_filter: day."""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Today's news"
        mock_response.citations = []
        mock_client.chat.completions.create.return_value = mock_response

        search_perplexity("News", "standard", search_recency_filter="day")

        create_call = mock_client.chat.completions.create.call_args
        assert create_call[1]["extra_body"]["search_recency_filter"] == "day"

    @patch.dict("os.environ", {"PERPLEXITY_API_KEY": "test-key"})
    @patch("newsletter_agent.tools.perplexity_search.OpenAI")
    def test_no_filter_no_extra_body(self, mock_openai_cls):
        """When no timeframe, no extra_body is sent."""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "General news"
        mock_response.citations = []
        mock_client.chat.completions.create.return_value = mock_response

        search_perplexity("News", "standard", search_recency_filter=None)

        create_call = mock_client.chat.completions.create.call_args
        assert "extra_body" not in create_call[1]

    @patch.dict("os.environ", {"PERPLEXITY_API_KEY": "test-key"})
    @patch("newsletter_agent.tools.perplexity_search.OpenAI")
    def test_retry_without_filter_on_rejection(self, mock_openai_cls):
        """When Perplexity rejects the filter (400), retry without it."""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        # First call with filter raises, second without filter succeeds
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Fallback results"
        mock_response.citations = []

        mock_client.chat.completions.create.side_effect = [
            Exception("400 Bad Request: unsupported filter"),
            mock_response,
        ]

        result = search_perplexity("News", "standard", search_recency_filter="week")

        # Should have been called twice
        assert mock_client.chat.completions.create.call_count == 2

        # First call had extra_body
        first_call = mock_client.chat.completions.create.call_args_list[0]
        assert "extra_body" in first_call[1]

        # Second call had no extra_body
        second_call = mock_client.chat.completions.create.call_args_list[1]
        assert "extra_body" not in second_call[1]

        # Result should be valid (from retry)
        assert result.get("error") is not True
        assert result["text"] == "Fallback results"
