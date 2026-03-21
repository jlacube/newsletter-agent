"""Cost tracking for LLM API calls.

Provides ModelPricing, LlmCallRecord, CostSummary, ModelCostDetail data classes
and the CostTracker class for accumulating per-call cost data. Module-level
init/get/reset functions follow the same pattern as OTel's global provider.

Spec refs: FR-401 through FR-406, Section 4.4, 7.1b, 7.4, 7.5, 7.6, 8.2.
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger("newsletter_agent.cost_tracker")


# ---------------------------------------------------------------------------
# Data model classes (Section 7.1b, 7.4, 7.5, 7.6)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelPricing:
    """Per-model token pricing in USD per million tokens."""

    input_per_million: float
    output_per_million: float


@dataclass(frozen=True)
class LlmCallRecord:
    """Immutable record of a single LLM API call."""

    model: str
    agent_name: str
    phase: str  # "research", "synthesis", "refinement", "unknown"
    topic_name: str | None
    topic_index: int | None
    prompt_tokens: int
    completion_tokens: int
    thinking_tokens: int
    total_tokens: int
    input_cost_usd: float
    output_cost_usd: float
    total_cost_usd: float
    timestamp: str


@dataclass
class ModelCostDetail:
    """Aggregated cost detail for a single model."""

    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    cost_usd: float = 0.0
    call_count: int = 0


@dataclass
class CostSummary:
    """Aggregated cost summary across all LLM calls.

    Note: per_topic and per_phase use ModelCostDetail instead of the spec's
    dict[str, float] (Section 7.5). This is a deliberate enhancement -- the
    richer breakdown (input/output/thinking tokens + call_count) is more
    useful for debugging and cost attribution. The spec's float value maps
    to ModelCostDetail.cost_usd.
    """

    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_thinking_tokens: int = 0
    total_cost_usd: float = 0.0
    call_count: int = 0
    per_model: dict[str, ModelCostDetail] = field(default_factory=dict)
    per_topic: dict[str, ModelCostDetail] = field(default_factory=dict)
    per_phase: dict[str, ModelCostDetail] = field(default_factory=dict)


_ZERO_PRICING = ModelPricing(input_per_million=0.0, output_per_million=0.0)


# ---------------------------------------------------------------------------
# CostTracker (Section 4.4, 8.2)
# ---------------------------------------------------------------------------


class CostTracker:
    """Thread-safe accumulator for LLM call cost data."""

    def __init__(
        self,
        pricing: dict[str, ModelPricing],
        cost_budget_usd: float | None = None,
    ) -> None:
        self._pricing = pricing
        self._cost_budget_usd = cost_budget_usd
        self._calls: list[LlmCallRecord] = []
        self._lock = threading.Lock()
        self._total_cost: float = 0.0

    def record_llm_call(
        self,
        *,
        model: str,
        agent_name: str,
        phase: str,
        topic_name: str | None = None,
        topic_index: int | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        thinking_tokens: int = 0,
    ) -> LlmCallRecord:
        """Record an LLM call and return the created record."""
        pricing = self._pricing.get(model)
        if pricing is None:
            logger.warning("Unknown model for cost tracking: %s", model)
            pricing = _ZERO_PRICING

        input_cost = prompt_tokens * pricing.input_per_million / 1_000_000
        output_cost = (
            (completion_tokens + thinking_tokens) * pricing.output_per_million / 1_000_000
        )
        total_cost = input_cost + output_cost
        total_tokens = prompt_tokens + completion_tokens + thinking_tokens

        record = LlmCallRecord(
            model=model,
            agent_name=agent_name,
            phase=phase,
            topic_name=topic_name,
            topic_index=topic_index,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            thinking_tokens=thinking_tokens,
            total_tokens=total_tokens,
            input_cost_usd=input_cost,
            output_cost_usd=output_cost,
            total_cost_usd=total_cost,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        with self._lock:
            self._calls.append(record)
            self._total_cost += total_cost

            if (
                self._cost_budget_usd is not None
                and self._total_cost > self._cost_budget_usd
            ):
                logger.warning(
                    "Cost budget exceeded: $%.4f > $%.4f USD",
                    self._total_cost,
                    self._cost_budget_usd,
                )

        return record

    def get_summary(self) -> CostSummary:
        """Return aggregated cost summary. Thread-safe."""
        with self._lock:
            calls = list(self._calls)

        summary = CostSummary()
        for call in calls:
            summary.total_input_tokens += call.prompt_tokens
            summary.total_output_tokens += call.completion_tokens
            summary.total_thinking_tokens += call.thinking_tokens
            summary.total_cost_usd += call.total_cost_usd
            summary.call_count += 1

            # Per-model aggregation
            model_detail = summary.per_model.setdefault(
                call.model, ModelCostDetail()
            )
            model_detail.input_tokens += call.prompt_tokens
            model_detail.output_tokens += call.completion_tokens
            model_detail.thinking_tokens += call.thinking_tokens
            model_detail.cost_usd += call.total_cost_usd
            model_detail.call_count += 1

            # Per-topic aggregation
            topic_key = call.topic_name or "unknown"
            topic_detail = summary.per_topic.setdefault(
                topic_key, ModelCostDetail()
            )
            topic_detail.input_tokens += call.prompt_tokens
            topic_detail.output_tokens += call.completion_tokens
            topic_detail.thinking_tokens += call.thinking_tokens
            topic_detail.cost_usd += call.total_cost_usd
            topic_detail.call_count += 1

            # Per-phase aggregation
            phase_detail = summary.per_phase.setdefault(
                call.phase, ModelCostDetail()
            )
            phase_detail.input_tokens += call.prompt_tokens
            phase_detail.output_tokens += call.completion_tokens
            phase_detail.thinking_tokens += call.thinking_tokens
            phase_detail.cost_usd += call.total_cost_usd
            phase_detail.call_count += 1

        return summary

    def has_pricing(self, model: str) -> bool:
        """Return True if the model has known pricing."""
        return model in self._pricing

    def get_calls(self) -> list[LlmCallRecord]:
        """Return a shallow copy of all recorded calls."""
        with self._lock:
            return list(self._calls)


# ---------------------------------------------------------------------------
# No-op tracker for when cost tracking is disabled
# ---------------------------------------------------------------------------


class _NoOpCostTracker:
    """Silent no-op tracker that discards all calls."""

    def record_llm_call(self, **kwargs) -> LlmCallRecord:
        return LlmCallRecord(
            model="",
            agent_name="",
            phase="unknown",
            topic_name=None,
            topic_index=None,
            prompt_tokens=0,
            completion_tokens=0,
            thinking_tokens=0,
            total_tokens=0,
            input_cost_usd=0.0,
            output_cost_usd=0.0,
            total_cost_usd=0.0,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def get_summary(self) -> CostSummary:
        return CostSummary()

    def has_pricing(self, model: str) -> bool:
        return False

    def get_calls(self) -> list[LlmCallRecord]:
        return []


# ---------------------------------------------------------------------------
# Module-level functions (Section 8.2)
# ---------------------------------------------------------------------------

_tracker: CostTracker | None = None
_noop = _NoOpCostTracker()


def init_cost_tracker(
    pricing: dict[str, ModelPricing],
    cost_budget_usd: float | None = None,
) -> None:
    """Initialize the global CostTracker instance."""
    global _tracker
    _tracker = CostTracker(pricing, cost_budget_usd)


def get_cost_tracker() -> CostTracker | _NoOpCostTracker:
    """Return the active CostTracker, or a no-op if not initialized."""
    return _tracker if _tracker is not None else _noop


def reset_cost_tracker() -> None:
    """Reset the global tracker to None (for test teardown)."""
    global _tracker
    _tracker = None
