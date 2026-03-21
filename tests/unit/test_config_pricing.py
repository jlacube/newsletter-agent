"""Unit tests for PricingConfig and ModelPricingConfig.

Spec refs: FR-601, Section 7.1, 7.2, 7.3, Section 11.1.
"""

import pytest
from pydantic import ValidationError

from newsletter_agent.config.schema import (
    AppSettings,
    ModelPricingConfig,
    PricingConfig,
)


class TestModelPricingConfig:

    def test_valid_pricing(self):
        m = ModelPricingConfig(input_per_million=1.0, output_per_million=2.0)
        assert m.input_per_million == 1.0
        assert m.output_per_million == 2.0

    def test_zero_values_valid(self):
        m = ModelPricingConfig(input_per_million=0.0, output_per_million=0.0)
        assert m.input_per_million == 0.0

    def test_negative_input_raises(self):
        with pytest.raises(ValidationError, match="input_per_million"):
            ModelPricingConfig(input_per_million=-1.0, output_per_million=2.0)

    def test_negative_output_raises(self):
        with pytest.raises(ValidationError, match="output_per_million"):
            ModelPricingConfig(input_per_million=1.0, output_per_million=-0.01)

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            ModelPricingConfig(input_per_million=1.0, output_per_million=2.0, extra_field="x")


class TestPricingConfig:

    def test_defaults(self):
        p = PricingConfig()
        assert "gemini-2.5-flash" in p.models
        assert "gemini-2.5-pro" in p.models
        assert len(p.models) == 2
        assert p.cost_budget_usd is None

    def test_default_flash_pricing(self):
        p = PricingConfig()
        flash = p.models["gemini-2.5-flash"]
        assert flash.input_per_million == 0.30
        assert flash.output_per_million == 2.50

    def test_default_pro_pricing(self):
        p = PricingConfig()
        pro = p.models["gemini-2.5-pro"]
        assert pro.input_per_million == 1.25
        assert pro.output_per_million == 10.00

    def test_custom_model(self):
        p = PricingConfig(
            models={"custom-model": ModelPricingConfig(input_per_million=1.0, output_per_million=2.0)}
        )
        assert "custom-model" in p.models
        assert len(p.models) == 1

    def test_cost_budget_none(self):
        p = PricingConfig(cost_budget_usd=None)
        assert p.cost_budget_usd is None

    def test_cost_budget_zero(self):
        p = PricingConfig(cost_budget_usd=0.0)
        assert p.cost_budget_usd == 0.0

    def test_cost_budget_positive(self):
        p = PricingConfig(cost_budget_usd=5.00)
        assert p.cost_budget_usd == 5.00

    def test_cost_budget_negative_raises(self):
        with pytest.raises(ValidationError, match="cost_budget_usd"):
            PricingConfig(cost_budget_usd=-0.01)

    def test_empty_models_raises(self):
        with pytest.raises(ValidationError):
            PricingConfig(models={})

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            PricingConfig(extra="value")


class TestAppSettingsPricing:

    def test_default_includes_pricing(self):
        s = AppSettings()
        assert isinstance(s.pricing, PricingConfig)
        assert "gemini-2.5-flash" in s.pricing.models

    def test_custom_pricing_in_settings(self):
        s = AppSettings(
            pricing=PricingConfig(
                models={"custom": ModelPricingConfig(input_per_million=0.5, output_per_million=1.0)},
                cost_budget_usd=10.0,
            )
        )
        assert s.pricing.cost_budget_usd == 10.0
        assert "custom" in s.pricing.models

    def test_pricing_from_dict(self):
        """AppSettings accepts pricing as a dict (YAML deserialization path)."""
        s = AppSettings(
            pricing={
                "models": {
                    "test-model": {"input_per_million": 0.1, "output_per_million": 0.2},
                },
                "cost_budget_usd": 1.5,
            }
        )
        assert s.pricing.cost_budget_usd == 1.5
        assert s.pricing.models["test-model"].input_per_million == 0.1
