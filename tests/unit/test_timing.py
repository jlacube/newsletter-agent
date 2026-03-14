"""Unit tests for pipeline timing instrumentation.

Spec refs: FR-042, Section 7.6, Section 10.1.
"""

import logging
import time
from unittest.mock import MagicMock

import pytest

from newsletter_agent.timing import (
    _phase_starts,
    after_agent_callback,
    before_agent_callback,
)


def _make_callback_context(agent_name="TestAgent", invocation_id="inv-1"):
    ctx = MagicMock()
    ctx.agent_name = agent_name
    ctx.invocation_id = invocation_id
    ctx.state = {}
    return ctx


class TestBeforeAgentCallback:

    def test_records_start_time(self):
        ctx = _make_callback_context()
        before_agent_callback(ctx)
        key = f"{ctx.invocation_id}:{ctx.agent_name}"
        assert key in _phase_starts
        _phase_starts.pop(key, None)

    def test_root_agent_sets_pipeline_start_time(self):
        ctx = _make_callback_context(agent_name="newsletter_agent")
        before_agent_callback(ctx)
        assert "pipeline_start_time" in ctx.state
        key = f"{ctx.invocation_id}:{ctx.agent_name}"
        _phase_starts.pop(key, None)

    def test_non_root_does_not_set_pipeline_start_time(self):
        ctx = _make_callback_context(agent_name="ResearchPhase")
        before_agent_callback(ctx)
        assert "pipeline_start_time" not in ctx.state
        key = f"{ctx.invocation_id}:{ctx.agent_name}"
        _phase_starts.pop(key, None)

    def test_returns_none(self):
        ctx = _make_callback_context()
        result = before_agent_callback(ctx)
        assert result is None
        key = f"{ctx.invocation_id}:{ctx.agent_name}"
        _phase_starts.pop(key, None)


class TestAfterAgentCallback:

    def test_logs_elapsed_time(self, caplog):
        ctx = _make_callback_context(agent_name="ResearchPhase")
        before_agent_callback(ctx)
        time.sleep(0.05)
        with caplog.at_level(logging.INFO, logger="newsletter_agent.timing"):
            after_agent_callback(ctx)
        assert "ResearchPhase completed in" in caplog.text

    def test_root_agent_logs_pipeline_completed(self, caplog):
        ctx = _make_callback_context(agent_name="newsletter_agent")
        before_agent_callback(ctx)
        with caplog.at_level(logging.INFO, logger="newsletter_agent.timing"):
            after_agent_callback(ctx)
        assert "Pipeline completed in" in caplog.text

    def test_root_agent_stores_generation_time(self):
        ctx = _make_callback_context(agent_name="newsletter_agent")
        before_agent_callback(ctx)
        time.sleep(0.01)
        after_agent_callback(ctx)
        assert "newsletter_metadata" in ctx.state
        assert ctx.state["newsletter_metadata"]["generation_time_seconds"] > 0

    def test_returns_none(self):
        ctx = _make_callback_context()
        before_agent_callback(ctx)
        result = after_agent_callback(ctx)
        assert result is None

    def test_missing_start_time_no_error(self):
        """after_agent_callback should not fail if before was never called."""
        ctx = _make_callback_context(agent_name="Orphan")
        after_agent_callback(ctx)  # should not raise
