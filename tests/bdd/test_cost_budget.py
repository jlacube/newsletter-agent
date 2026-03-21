"""BDD tests: Cost Budget Warning.

Spec refs: US-06, FR-406, Section 11.2.

Feature: Cost Budget Warning
  Scenario: Budget exceeded logs warning
  Scenario: No budget means no warning
"""

import logging

import pytest

from newsletter_agent.cost_tracker import (
    CostTracker,
    ModelPricing,
    reset_cost_tracker,
)


@pytest.fixture(autouse=True)
def _reset_cost():
    yield
    reset_cost_tracker()


class TestCostBudgetScenarios:
    """Feature: Cost Budget Warning."""

    def test_budget_exceeded_logs_warning(self, caplog):
        """Scenario: Budget exceeded logs warning.

        Given cost_budget_usd = 0.01
        And accumulated cost is 0.009
        When an LLM call adds 0.005 to the cost
        Then a WARNING log contains "Cost budget exceeded"
        And the pipeline continues running
        """
        pricing = {"gemini-2.5-pro": ModelPricing(1.25, 10.00)}
        tracker = CostTracker(pricing, cost_budget_usd=0.01)

        # First call: accumulate ~0.009 (small call)
        # input: 5000 * 1.25/1M = 0.00625, output: 300 * 10.00/1M = 0.003
        # total = 0.00925 (under budget)
        with caplog.at_level(logging.WARNING, logger="newsletter_agent.cost_tracker"):
            tracker.record_llm_call(
                model="gemini-2.5-pro",
                agent_name="TestAgent",
                phase="research",
                prompt_tokens=5000,
                completion_tokens=300,
                thinking_tokens=0,
            )

        # Budget not yet exceeded
        assert "Cost budget exceeded" not in caplog.text

        # Second call: push over budget
        # input: 2000 * 1.25/1M = 0.0025, output: 500 * 10.00/1M = 0.005
        # total added = 0.0075, cumulative ~0.01675 > 0.01
        with caplog.at_level(logging.WARNING, logger="newsletter_agent.cost_tracker"):
            record = tracker.record_llm_call(
                model="gemini-2.5-pro",
                agent_name="TestAgent",
                phase="research",
                prompt_tokens=2000,
                completion_tokens=500,
                thinking_tokens=0,
            )

        assert "Cost budget exceeded" in caplog.text
        # Pipeline continues - record was still created
        assert record.total_cost_usd > 0

    def test_no_budget_means_no_warning(self, caplog):
        """Scenario: No budget means no warning.

        Given cost_budget_usd is null
        And accumulated cost is 100.0
        When another LLM call completes
        Then no budget warning is logged
        """
        pricing = {"gemini-2.5-pro": ModelPricing(1.25, 10.00)}
        tracker = CostTracker(pricing, cost_budget_usd=None)

        # Make a large call (no budget set, so no warning expected)
        with caplog.at_level(logging.WARNING, logger="newsletter_agent.cost_tracker"):
            tracker.record_llm_call(
                model="gemini-2.5-pro",
                agent_name="TestAgent",
                phase="synthesis",
                prompt_tokens=10_000_000,
                completion_tokens=5_000_000,
                thinking_tokens=1_000_000,
            )

        assert "Cost budget exceeded" not in caplog.text
