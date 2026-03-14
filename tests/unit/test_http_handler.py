"""Unit tests for the Cloud Run HTTP trigger handler.

Spec refs: FR-037, Section 8.1.
"""

from unittest.mock import AsyncMock, patch

import pytest

from newsletter_agent.http_handler import app


@pytest.fixture()
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class TestRunEndpoint:

    @patch(
        "newsletter_agent.http_handler._execute_pipeline",
        new_callable=AsyncMock,
    )
    def test_success_returns_200(self, mock_exec, client):
        mock_exec.return_value = {
            "delivery_status": {"status": "sent", "message_id": "abc123"},
            "newsletter_metadata": {"topic_count": 3},
        }
        resp = client.post("/run")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["topics_processed"] == 3
        assert data["email_sent"] is True

    @patch(
        "newsletter_agent.http_handler._execute_pipeline",
        new_callable=AsyncMock,
    )
    def test_dry_run_includes_output_file(self, mock_exec, client):
        mock_exec.return_value = {
            "delivery_status": {
                "status": "dry_run",
                "output_file": "output/2025-01-01-newsletter.html",
            },
            "newsletter_metadata": {"topic_count": 2},
        }
        resp = client.post("/run")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["output_file"] == "output/2025-01-01-newsletter.html"
        assert data["email_sent"] is False

    @patch(
        "newsletter_agent.http_handler._execute_pipeline",
        new_callable=AsyncMock,
    )
    def test_pipeline_failure_returns_500(self, mock_exec, client):
        mock_exec.side_effect = RuntimeError("LLM quota exceeded")
        resp = client.post("/run")
        assert resp.status_code == 500
        data = resp.get_json()
        assert data["status"] == "error"
        assert "RuntimeError" in data["message"]

    def test_get_not_allowed(self, client):
        resp = client.get("/run")
        assert resp.status_code == 405

    @patch(
        "newsletter_agent.http_handler._execute_pipeline",
        new_callable=AsyncMock,
    )
    def test_empty_post_body_accepted(self, mock_exec, client):
        mock_exec.return_value = {
            "delivery_status": {"status": "sent"},
            "newsletter_metadata": {"topic_count": 1},
        }
        resp = client.post("/run", data=b"")
        assert resp.status_code == 200

    @patch(
        "newsletter_agent.http_handler._execute_pipeline",
        new_callable=AsyncMock,
    )
    def test_response_contains_newsletter_date(self, mock_exec, client):
        mock_exec.return_value = {
            "delivery_status": {"status": "sent"},
            "newsletter_metadata": {"topic_count": 1},
        }
        resp = client.post("/run")
        data = resp.get_json()
        assert "newsletter_date" in data
        # Date should be ISO format YYYY-MM-DD
        assert len(data["newsletter_date"]) == 10
