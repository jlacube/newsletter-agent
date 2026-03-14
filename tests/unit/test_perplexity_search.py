"""Unit tests for the Perplexity search tool.

Spec refs: Section 11.1, FR-015.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from newsletter_agent.tools.perplexity_search import search_perplexity


# ---------------------------------------------------------------------------
# Success cases
# ---------------------------------------------------------------------------


class TestSearchPerplexitySuccess:

    @patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"})
    @patch("newsletter_agent.tools.perplexity_search.OpenAI")
    def test_standard_search_returns_text_and_sources(self, mock_openai_class):
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content="AI frameworks are evolving rapidly..."))
        ]
        mock_response.citations = [
            "https://example.com/ai-frameworks",
            "https://techblog.com/adk-release",
        ]
        mock_client.chat.completions.create.return_value = mock_response

        result = search_perplexity("AI frameworks", "standard")

        assert result["provider"] == "perplexity"
        assert "error" not in result
        assert result["text"] == "AI frameworks are evolving rapidly..."
        assert len(result["sources"]) == 2
        assert result["sources"][0]["url"] == "https://example.com/ai-frameworks"

        call_args = mock_client.chat.completions.create.call_args
        assert call_args.kwargs["model"] == "sonar"

    @patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"})
    @patch("newsletter_agent.tools.perplexity_search.OpenAI")
    def test_deep_search_uses_sonar_pro_model(self, mock_openai_class):
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Deep analysis..."))]
        mock_response.citations = []
        mock_client.chat.completions.create.return_value = mock_response

        search_perplexity("AI frameworks", "deep")

        call_args = mock_client.chat.completions.create.call_args
        assert call_args.kwargs["model"] == "sonar-pro"

    @patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"})
    @patch("newsletter_agent.tools.perplexity_search.OpenAI")
    def test_empty_citations_returns_empty_sources(self, mock_openai_class):
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Some text"))]
        mock_response.citations = None
        mock_client.chat.completions.create.return_value = mock_response

        result = search_perplexity("test query", "standard")

        assert result["sources"] == []
        assert result["text"] == "Some text"

    @patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"})
    @patch("newsletter_agent.tools.perplexity_search.OpenAI")
    def test_none_content_returns_empty_text(self, mock_openai_class):
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content=None))]
        mock_response.citations = []
        mock_client.chat.completions.create.return_value = mock_response

        result = search_perplexity("test", "standard")

        assert result["text"] == ""
        assert result["provider"] == "perplexity"

    @patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"})
    @patch("newsletter_agent.tools.perplexity_search.OpenAI")
    def test_non_http_citations_filtered(self, mock_openai_class):
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Text"))]
        mock_response.citations = ["https://valid.com", "ftp://invalid.com", "not-a-url"]
        mock_client.chat.completions.create.return_value = mock_response

        result = search_perplexity("test", "standard")

        assert len(result["sources"]) == 1
        assert result["sources"][0]["url"] == "https://valid.com"


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestSearchPerplexityErrors:

    @patch.dict(os.environ, {}, clear=False)
    def test_missing_api_key_returns_error(self):
        env = os.environ.copy()
        env.pop("PERPLEXITY_API_KEY", None)
        with patch.dict(os.environ, env, clear=True):
            result = search_perplexity("test", "standard")
            assert result["error"] is True
            assert "PERPLEXITY_API_KEY" in result["message"]
            assert result["provider"] == "perplexity"

    @patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"})
    @patch("newsletter_agent.tools.perplexity_search.OpenAI")
    def test_api_connection_error_returns_error_dict(self, mock_openai_class):
        from openai import APIConnectionError

        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client
        mock_client.chat.completions.create.side_effect = APIConnectionError(
            request=MagicMock()
        )

        result = search_perplexity("test", "standard")

        assert result["error"] is True
        assert result["provider"] == "perplexity"

    @patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"})
    @patch("newsletter_agent.tools.perplexity_search.OpenAI")
    def test_rate_limit_error_returns_error_dict(self, mock_openai_class):
        from openai import RateLimitError

        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client
        mock_client.chat.completions.create.side_effect = RateLimitError(
            message="Rate limit exceeded",
            response=MagicMock(status_code=429),
            body=None,
        )

        result = search_perplexity("test", "standard")

        assert result["error"] is True
        assert result["provider"] == "perplexity"

    @patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"})
    @patch("newsletter_agent.tools.perplexity_search.OpenAI")
    def test_generic_exception_returns_error_dict(self, mock_openai_class):
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client
        mock_client.chat.completions.create.side_effect = RuntimeError("unexpected")

        result = search_perplexity("test", "standard")

        assert result["error"] is True
        assert "RuntimeError" in result["message"]
        assert result["provider"] == "perplexity"
