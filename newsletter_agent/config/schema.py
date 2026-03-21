"""
Configuration models and loader for Newsletter Agent.

Loads and validates config/topics.yaml using Pydantic v2 models.
Spec refs: FR-001 through FR-007, Section 7.1, 7.2, 8.4.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError, field_validator, model_validator

from newsletter_agent.config.timeframe import validate_timeframe

TimeframeValue = Annotated[str | None, BeforeValidator(validate_timeframe)]


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class ConfigValidationError(Exception):
    """Raised when config loading or validation fails.

    Wraps both YAML parse errors and Pydantic validation errors with
    a unified interface providing field-level error details.
    """

    def __init__(self, message: str, field_errors: list[dict] | None = None):
        super().__init__(message)
        self.field_errors = field_errors or []

    @classmethod
    def from_pydantic(cls, error: ValidationError) -> ConfigValidationError:
        field_errors = [
            {
                "field": ".".join(str(loc) for loc in e["loc"]),
                "message": e["msg"],
                "type": e["type"],
            }
            for e in error.errors()
        ]
        summary = f"Config validation failed with {len(field_errors)} error(s): "
        details = "; ".join(
            f'{e["field"]}: {e["message"]}' for e in field_errors[:3]
        )
        summary += details
        if len(field_errors) > 3:
            summary += f" ... and {len(field_errors) - 3} more"
        return cls(summary, field_errors)


# ---------------------------------------------------------------------------
# Email validation pattern
# ---------------------------------------------------------------------------

_EMAIL_PATTERN = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)


def _validate_email_list(emails: list[str]) -> None:
    """Validate a list of 1-10 unique, well-formed email addresses."""
    if len(emails) == 0:
        raise ValueError("recipient_emails must contain at least 1 email")
    if len(emails) > 10:
        raise ValueError("recipient_emails must contain at most 10 emails")
    seen: set[str] = set()
    for email in emails:
        if not _EMAIL_PATTERN.match(email):
            raise ValueError(f"'{email}' is not a valid email address")
        lower = email.lower()
        if lower in seen:
            raise ValueError(f"Duplicate email address: '{email}'")
        seen.add(lower)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class TopicConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    query: str = Field(min_length=1, max_length=500)
    search_depth: Literal["standard", "deep"] = "standard"
    sources: list[Literal["google_search", "perplexity"]] = Field(
        default=["google_search", "perplexity"]
    )
    timeframe: TimeframeValue = None

    @field_validator("sources", mode="before")
    @classmethod
    def default_empty_sources(cls, v: object) -> object:
        if isinstance(v, list) and len(v) == 0:
            return ["google_search", "perplexity"]
        return v


class NewsletterSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    schedule: str = Field(min_length=1)
    recipient_email: str | None = None
    recipient_emails: list[str] | None = None

    @model_validator(mode="before")
    @classmethod
    def check_conflicting_recipients(cls, data: object) -> object:
        """Reject raw input that specifies both recipient fields."""
        if isinstance(data, dict):
            has_singular = data.get("recipient_email") is not None
            has_plural = data.get("recipient_emails") is not None
            if has_singular and has_plural:
                raise ValueError(
                    "Cannot specify both 'recipient_email' and 'recipient_emails'. "
                    "Use 'recipient_emails' for multiple recipients."
                )
        return data

    @model_validator(mode="after")
    def resolve_recipients(self) -> NewsletterSettings:
        has_singular = self.recipient_email is not None
        has_plural = self.recipient_emails is not None

        if has_plural:
            _validate_email_list(self.recipient_emails)
            self.recipient_email = self.recipient_emails[0]
        elif has_singular:
            if not _EMAIL_PATTERN.match(self.recipient_email):
                raise ValueError(
                    f"'{self.recipient_email}' is not a valid email address"
                )
            self.recipient_emails = [self.recipient_email]
        else:
            raise ValueError(
                "Either 'recipient_email' or 'recipient_emails' must be provided"
            )

        return self


class ModelPricingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_per_million: float = Field(ge=0.0)
    output_per_million: float = Field(ge=0.0)


class PricingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    models: dict[str, ModelPricingConfig] = Field(
        default_factory=lambda: {
            "gemini-2.5-flash": ModelPricingConfig(input_per_million=0.30, output_per_million=2.50),
            "gemini-2.5-pro": ModelPricingConfig(input_per_million=1.25, output_per_million=10.00),
        },
        min_length=1,
    )
    cost_budget_usd: float | None = Field(default=None, ge=0.0)


class AppSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool = False
    output_dir: str = "output/"
    timeframe: TimeframeValue = None
    verify_links: bool = False
    max_research_rounds: int = Field(default=3, ge=1, le=5)
    max_searches_per_topic: int | None = Field(default=None, ge=1, le=20)
    min_research_rounds: int = Field(default=2, ge=1, le=3)
    pricing: PricingConfig = Field(default_factory=PricingConfig)

    @model_validator(mode="after")
    def resolve_adaptive_defaults(self) -> AppSettings:
        if self.max_searches_per_topic is None:
            self.max_searches_per_topic = self.max_research_rounds
        if self.min_research_rounds > self.max_research_rounds:
            raise ValueError(
                f"min_research_rounds ({self.min_research_rounds}) must be "
                f"<= max_research_rounds ({self.max_research_rounds})"
            )
        return self


class NewsletterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    newsletter: NewsletterSettings
    settings: AppSettings = Field(default_factory=AppSettings)
    topics: list[TopicConfig] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_unique_topic_names(self) -> NewsletterConfig:
        names = [t.name for t in self.topics]
        if len(names) != len(set(names)):
            dupes = {n for n in names if names.count(n) > 1}
            raise ValueError(
                f"Topic names must be unique. Duplicates found: {dupes}"
            )
        return self


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------


def load_config(path: str = "config/topics.yaml") -> NewsletterConfig:
    """Load and validate newsletter config from a YAML file.

    Args:
        path: Path to the YAML config file.

    Returns:
        Validated NewsletterConfig instance.

    Raises:
        FileNotFoundError: If the config file does not exist.
        ConfigValidationError: If YAML is invalid or data fails validation.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"Config file not found: {path}")
    except yaml.YAMLError as e:
        raise ConfigValidationError(f"Invalid YAML in {path}: {e}")

    if data is None:
        raise ConfigValidationError(f"Empty config file: {path}")

    if not isinstance(data, dict):
        raise ConfigValidationError(
            f"Config file must contain a YAML mapping, got {type(data).__name__}"
        )

    try:
        return NewsletterConfig(**data)
    except ValidationError as e:
        raise ConfigValidationError.from_pydantic(e) from e
