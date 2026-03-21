"""Unit tests for CostTracker, module-level functions, and no-op behavior.

Covers: T20-08 (CostTracker), T20-10 (no-op CostTracker).
Spec refs: FR-401, FR-404, FR-405, FR-406, Section 8.2, 11.1.
"""

import logging
import threading

import pytest

from newsletter_agent.cost_tracker import (
    CostSummary,
    CostTracker,
    LlmCallRecord,
    ModelCostDetail,
    ModelPricing,
    _NoOpCostTracker,
    get_cost_tracker,
    init_cost_tracker,
    reset_cost_tracker,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_PRO_PRICING = ModelPricing(input_per_million=1.25, output_per_million=10.0)
_FLASH_PRICING = ModelPricing(input_per_million=0.15, output_per_million=0.60)


@pytest.fixture(autouse=True)
def _reset_global_tracker():
    """Ensure global tracker is reset before and after each test."""
    reset_cost_tracker()
    yield
    reset_cost_tracker()


def _make_tracker(budget=None):
    return CostTracker(
        pricing={"gemini-2.5-pro": _PRO_PRICING, "gemini-2.5-flash": _FLASH_PRICING},
        cost_budget_usd=budget,
    )


# ---------------------------------------------------------------------------
# T20-08: CostTracker.record_llm_call cost calculation (FR-401)
# ---------------------------------------------------------------------------


class TestRecordLlmCallCost:

    def test_correct_cost_for_known_model(self):
        """FR-401: Given pro pricing (1.25/10.00) and 10000 prompt + 2000 completion
        + 500 thinking tokens: input_cost = 0.0125, output_cost = 0.025, total = 0.0375."""
        tracker = _make_tracker()
        record = tracker.record_llm_call(
            model="gemini-2.5-pro",
            agent_name="PerTopicSynthesizer",
            phase="synthesis",
            topic_name="AI News",
            topic_index=0,
            prompt_tokens=10000,
            completion_tokens=2000,
            thinking_tokens=500,
        )
        assert record.input_cost_usd == pytest.approx(0.0125)
        assert record.output_cost_usd == pytest.approx(0.025)
        assert record.total_cost_usd == pytest.approx(0.0375)
        assert record.total_tokens == 12500

    def test_flash_model_cost(self):
        """Flash pricing (0.15/0.60) with 5000 prompt + 1000 completion."""
        tracker = _make_tracker()
        record = tracker.record_llm_call(
            model="gemini-2.5-flash",
            agent_name="DeepResearchRefiner",
            phase="refinement",
            prompt_tokens=5000,
            completion_tokens=1000,
            thinking_tokens=0,
        )
        assert record.input_cost_usd == pytest.approx(0.00075)
        assert record.output_cost_usd == pytest.approx(0.0006)
        assert record.total_cost_usd == pytest.approx(0.00135)

    def test_returns_immutable_record(self):
        tracker = _make_tracker()
        record = tracker.record_llm_call(
            model="gemini-2.5-pro",
            agent_name="test",
            phase="synthesis",
            prompt_tokens=100,
            completion_tokens=50,
        )
        assert isinstance(record, LlmCallRecord)
        with pytest.raises(AttributeError):
            record.model = "changed"

    def test_record_has_timestamp(self):
        tracker = _make_tracker()
        record = tracker.record_llm_call(
            model="gemini-2.5-pro",
            agent_name="test",
            phase="synthesis",
            prompt_tokens=100,
        )
        assert record.timestamp  # non-empty
        assert "T" in record.timestamp  # ISO format


# ---------------------------------------------------------------------------
# T20-08: Unknown model (FR-404)
# ---------------------------------------------------------------------------


class TestUnknownModel:

    def test_unknown_model_zero_cost_and_warning(self, caplog):
        """FR-404: Unknown model uses zero pricing and logs WARNING."""
        tracker = _make_tracker()
        with caplog.at_level(logging.WARNING):
            record = tracker.record_llm_call(
                model="unknown-model-3000",
                agent_name="test",
                phase="synthesis",
                prompt_tokens=10000,
                completion_tokens=5000,
            )
        assert record.input_cost_usd == 0.0
        assert record.output_cost_usd == 0.0
        assert record.total_cost_usd == 0.0
        assert "Unknown model" in caplog.text
        assert "unknown-model-3000" in caplog.text


# ---------------------------------------------------------------------------
# T20-08: get_summary aggregation
# ---------------------------------------------------------------------------


class TestGetSummary:

    def test_aggregates_per_model(self):
        tracker = _make_tracker()
        tracker.record_llm_call(
            model="gemini-2.5-pro", agent_name="synth", phase="synthesis",
            prompt_tokens=1000, completion_tokens=500,
        )
        tracker.record_llm_call(
            model="gemini-2.5-flash", agent_name="refiner", phase="refinement",
            prompt_tokens=2000, completion_tokens=300,
        )
        summary = tracker.get_summary()
        assert summary.call_count == 2
        assert "gemini-2.5-pro" in summary.per_model
        assert "gemini-2.5-flash" in summary.per_model
        assert summary.per_model["gemini-2.5-pro"].call_count == 1
        assert summary.per_model["gemini-2.5-flash"].call_count == 1

    def test_aggregates_per_topic(self):
        tracker = _make_tracker()
        tracker.record_llm_call(
            model="gemini-2.5-pro", agent_name="synth", phase="synthesis",
            topic_name="AI News", prompt_tokens=1000, completion_tokens=500,
        )
        tracker.record_llm_call(
            model="gemini-2.5-pro", agent_name="synth", phase="synthesis",
            topic_name="AI News", prompt_tokens=500, completion_tokens=200,
        )
        tracker.record_llm_call(
            model="gemini-2.5-pro", agent_name="synth", phase="synthesis",
            topic_name="Crypto", prompt_tokens=800, completion_tokens=400,
        )
        summary = tracker.get_summary()
        assert summary.per_topic["AI News"].call_count == 2
        assert summary.per_topic["Crypto"].call_count == 1

    def test_aggregates_per_phase(self):
        tracker = _make_tracker()
        tracker.record_llm_call(
            model="gemini-2.5-pro", agent_name="synth", phase="synthesis",
            prompt_tokens=1000, completion_tokens=500,
        )
        tracker.record_llm_call(
            model="gemini-2.5-flash", agent_name="refiner", phase="refinement",
            prompt_tokens=2000, completion_tokens=300,
        )
        summary = tracker.get_summary()
        assert "synthesis" in summary.per_phase
        assert "refinement" in summary.per_phase
        assert summary.per_phase["synthesis"].call_count == 1
        assert summary.per_phase["refinement"].call_count == 1

    def test_none_topic_mapped_to_unknown(self):
        tracker = _make_tracker()
        tracker.record_llm_call(
            model="gemini-2.5-pro", agent_name="test", phase="synthesis",
            topic_name=None, prompt_tokens=100,
        )
        summary = tracker.get_summary()
        assert "unknown" in summary.per_topic

    def test_empty_tracker_returns_zero_summary(self):
        tracker = _make_tracker()
        summary = tracker.get_summary()
        assert summary.call_count == 0
        assert summary.total_cost_usd == 0.0
        assert summary.total_input_tokens == 0
        assert summary.per_model == {}

    def test_total_tokens_accumulated_correctly(self):
        tracker = _make_tracker()
        tracker.record_llm_call(
            model="gemini-2.5-pro", agent_name="synth", phase="synthesis",
            prompt_tokens=1000, completion_tokens=500, thinking_tokens=200,
        )
        tracker.record_llm_call(
            model="gemini-2.5-pro", agent_name="synth", phase="synthesis",
            prompt_tokens=2000, completion_tokens=800, thinking_tokens=0,
        )
        summary = tracker.get_summary()
        assert summary.total_input_tokens == 3000
        assert summary.total_output_tokens == 1300
        assert summary.total_thinking_tokens == 200


# ---------------------------------------------------------------------------
# T20-08: Thread safety (FR-405)
# ---------------------------------------------------------------------------


class TestThreadSafety:

    def test_concurrent_calls_produce_correct_count(self):
        """FR-405: 10 concurrent threads each record 1 call -> 10 total."""
        tracker = _make_tracker()

        def record():
            tracker.record_llm_call(
                model="gemini-2.5-pro",
                agent_name="thread-test",
                phase="synthesis",
                prompt_tokens=100,
                completion_tokens=50,
            )

        threads = [threading.Thread(target=record) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        summary = tracker.get_summary()
        assert summary.call_count == 10

    def test_concurrent_cost_accumulation(self):
        """Thread-safe cost accumulation matches expected total."""
        tracker = _make_tracker()

        def record():
            tracker.record_llm_call(
                model="gemini-2.5-pro",
                agent_name="thread-test",
                phase="synthesis",
                prompt_tokens=1000000,  # $1.25 input
                completion_tokens=0,
            )

        threads = [threading.Thread(target=record) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        summary = tracker.get_summary()
        assert summary.total_cost_usd == pytest.approx(12.5)


# ---------------------------------------------------------------------------
# T20-08: Budget warnings (FR-406)
# ---------------------------------------------------------------------------


class TestBudgetWarnings:

    def test_budget_exceeded_logs_warning(self, caplog):
        """FR-406: When total_cost > budget, log WARNING."""
        tracker = _make_tracker(budget=0.01)
        with caplog.at_level(logging.WARNING):
            tracker.record_llm_call(
                model="gemini-2.5-pro",
                agent_name="test",
                phase="synthesis",
                prompt_tokens=100000,  # $0.125 > $0.01
                completion_tokens=0,
            )
        assert "Cost budget exceeded" in caplog.text

    def test_budget_none_no_warning(self, caplog):
        """FR-406: When budget is None, no warning regardless of cost."""
        tracker = _make_tracker(budget=None)
        with caplog.at_level(logging.WARNING):
            tracker.record_llm_call(
                model="gemini-2.5-pro",
                agent_name="test",
                phase="synthesis",
                prompt_tokens=10000000,  # $12.50
                completion_tokens=0,
            )
        assert "Cost budget exceeded" not in caplog.text

    def test_budget_not_exceeded_no_warning(self, caplog):
        """No warning when cost is within budget."""
        tracker = _make_tracker(budget=100.0)
        with caplog.at_level(logging.WARNING):
            tracker.record_llm_call(
                model="gemini-2.5-pro",
                agent_name="test",
                phase="synthesis",
                prompt_tokens=100,
                completion_tokens=50,
            )
        assert "Cost budget exceeded" not in caplog.text


# ---------------------------------------------------------------------------
# T20-08: get_calls
# ---------------------------------------------------------------------------


class TestGetCalls:

    def test_returns_all_recorded_calls(self):
        tracker = _make_tracker()
        tracker.record_llm_call(
            model="gemini-2.5-pro", agent_name="a", phase="synthesis",
            prompt_tokens=100, completion_tokens=50,
        )
        tracker.record_llm_call(
            model="gemini-2.5-flash", agent_name="b", phase="refinement",
            prompt_tokens=200, completion_tokens=100,
        )
        calls = tracker.get_calls()
        assert len(calls) == 2
        assert calls[0].model == "gemini-2.5-pro"
        assert calls[1].model == "gemini-2.5-flash"

    def test_returns_shallow_copy(self):
        tracker = _make_tracker()
        tracker.record_llm_call(
            model="gemini-2.5-pro", agent_name="a", phase="synthesis",
            prompt_tokens=100,
        )
        calls1 = tracker.get_calls()
        calls2 = tracker.get_calls()
        assert calls1 is not calls2
        assert calls1 == calls2


# ---------------------------------------------------------------------------
# T20-08: has_pricing
# ---------------------------------------------------------------------------


class TestHasPricing:

    def test_known_model_returns_true(self):
        tracker = _make_tracker()
        assert tracker.has_pricing("gemini-2.5-pro") is True

    def test_unknown_model_returns_false(self):
        tracker = _make_tracker()
        assert tracker.has_pricing("unknown-model") is False

    def test_noop_always_returns_false(self):
        noop = _NoOpCostTracker()
        assert noop.has_pricing("gemini-2.5-pro") is False


# ---------------------------------------------------------------------------
# T20-08 / T20-10: Module-level functions
# ---------------------------------------------------------------------------


class TestModuleLevelFunctions:

    def test_get_cost_tracker_returns_noop_when_not_initialized(self):
        """Section 8.2: get_cost_tracker returns no-op when not initialized."""
        tracker = get_cost_tracker()
        assert isinstance(tracker, _NoOpCostTracker)

    def test_init_creates_real_tracker(self):
        init_cost_tracker({"gemini-2.5-pro": _PRO_PRICING})
        tracker = get_cost_tracker()
        assert isinstance(tracker, CostTracker)

    def test_reset_clears_global_state(self):
        init_cost_tracker({"gemini-2.5-pro": _PRO_PRICING})
        assert isinstance(get_cost_tracker(), CostTracker)
        reset_cost_tracker()
        assert isinstance(get_cost_tracker(), _NoOpCostTracker)

    def test_init_passes_budget(self):
        init_cost_tracker({"gemini-2.5-pro": _PRO_PRICING}, cost_budget_usd=5.0)
        tracker = get_cost_tracker()
        assert isinstance(tracker, CostTracker)
        assert tracker._cost_budget_usd == 5.0


# ---------------------------------------------------------------------------
# T20-10: No-op CostTracker behavior
# ---------------------------------------------------------------------------


class TestNoOpCostTracker:

    def test_record_does_not_raise(self):
        """No-op tracker silently discards calls."""
        noop = _NoOpCostTracker()
        record = noop.record_llm_call(
            model="gemini-2.5-pro",
            agent_name="test",
            phase="synthesis",
            prompt_tokens=1000,
        )
        assert isinstance(record, LlmCallRecord)
        assert record.total_cost_usd == 0.0

    def test_get_summary_returns_zeros(self):
        noop = _NoOpCostTracker()
        summary = noop.get_summary()
        assert isinstance(summary, CostSummary)
        assert summary.call_count == 0
        assert summary.total_cost_usd == 0.0

    def test_get_calls_returns_empty(self):
        noop = _NoOpCostTracker()
        assert noop.get_calls() == []

    def test_no_warnings_logged(self, caplog):
        """No-op operations should not log warnings."""
        noop = _NoOpCostTracker()
        with caplog.at_level(logging.WARNING):
            noop.record_llm_call(model="x", agent_name="y", phase="z")
            noop.get_summary()
            noop.get_calls()
        assert caplog.text == ""

    def test_get_cost_tracker_noop_after_reset(self):
        """After reset, get_cost_tracker returns no-op."""
        init_cost_tracker({"gemini-2.5-pro": _PRO_PRICING})
        reset_cost_tracker()
        tracker = get_cost_tracker()
        assert isinstance(tracker, _NoOpCostTracker)


# ---------------------------------------------------------------------------
# T20-08: Data model classes
# ---------------------------------------------------------------------------


class TestDataModels:

    def test_model_pricing_frozen(self):
        p = ModelPricing(input_per_million=1.0, output_per_million=2.0)
        with pytest.raises(AttributeError):
            p.input_per_million = 5.0

    def test_llm_call_record_frozen(self):
        r = LlmCallRecord(
            model="m", agent_name="a", phase="synthesis",
            topic_name=None, topic_index=None,
            prompt_tokens=0, completion_tokens=0, thinking_tokens=0,
            total_tokens=0, input_cost_usd=0, output_cost_usd=0,
            total_cost_usd=0, timestamp="t",
        )
        with pytest.raises(AttributeError):
            r.model = "changed"

    def test_cost_summary_defaults(self):
        s = CostSummary()
        assert s.total_input_tokens == 0
        assert s.total_output_tokens == 0
        assert s.total_thinking_tokens == 0
        assert s.total_cost_usd == 0.0
        assert s.call_count == 0
        assert s.per_model == {}
        assert s.per_topic == {}
        assert s.per_phase == {}

    def test_model_cost_detail_defaults(self):
        d = ModelCostDetail()
        assert d.input_tokens == 0
        assert d.output_tokens == 0
        assert d.cost_usd == 0.0
        assert d.call_count == 0
