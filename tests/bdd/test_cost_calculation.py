"""BDD tests: Cost Calculation.

Spec refs: US-02, FR-401, FR-404, Section 11.2.

Feature: Cost Calculation
  Scenario: Cost computed correctly for gemini-2.5-pro
  Scenario: Unknown model uses zero cost
"""

import logging

import pytest

from newsletter_agent.cost_tracker import (
    CostTracker,
    ModelPricing,
    init_cost_tracker,
    get_cost_tracker,
    reset_cost_tracker,
)


@pytest.fixture(autouse=True)
def _reset_cost():
    yield
    reset_cost_tracker()


class TestCostCalculationScenarios:
    """Feature: Cost Calculation."""

    def test_cost_computed_correctly_for_gemini_pro(self):
        """Scenario: Cost computed correctly for gemini-2.5-pro.

        Given pricing config with gemini-2.5-pro
            input_per_million=1.25 and output_per_million=10.00
        And an LLM call with prompt_tokens=10000,
            completion_tokens=2000, thinking_tokens=500
        When cost is calculated
        Then input_cost_usd = 0.0125
        And output_cost_usd = 0.025
        And total_cost_usd = 0.0375
        """
        pricing = {"gemini-2.5-pro": ModelPricing(1.25, 10.00)}
        tracker = CostTracker(pricing)

        record = tracker.record_llm_call(
            model="gemini-2.5-pro",
            agent_name="PerTopicSynthesizer_0",
            phase="synthesis",
            prompt_tokens=10000,
            completion_tokens=2000,
            thinking_tokens=500,
        )

        assert record.input_cost_usd == pytest.approx(0.0125)
        assert record.output_cost_usd == pytest.approx(0.025)
        assert record.total_cost_usd == pytest.approx(0.0375)

    def test_unknown_model_uses_zero_cost(self, caplog):
        """Scenario: Unknown model uses zero cost.

        Given pricing config without model "gemini-3.0-flash"
        And an LLM call with model "gemini-3.0-flash"
        When cost is calculated
        Then total_cost_usd = 0.0
        And a WARNING log contains "gemini-3.0-flash"
        """
        pricing = {"gemini-2.5-pro": ModelPricing(1.25, 10.00)}
        tracker = CostTracker(pricing)

        with caplog.at_level(logging.WARNING, logger="newsletter_agent.cost_tracker"):
            record = tracker.record_llm_call(
                model="gemini-3.0-flash",
                agent_name="TestAgent",
                phase="research",
                prompt_tokens=5000,
                completion_tokens=1000,
                thinking_tokens=0,
            )

        assert record.total_cost_usd == 0.0
        assert record.input_cost_usd == 0.0
        assert record.output_cost_usd == 0.0
        assert "gemini-3.0-flash" in caplog.text
