---
lane: done
review_status:
---

# WP01 - Project Scaffolding & Configuration System

> **Spec**: `specs/newsletter-agent.spec.md`
> **Status**: Complete
> **Priority**: P0
> **Goal**: Establish the ADK project structure, dependency management, configuration loading with validation, and sample config so that all subsequent WPs have a runnable foundation.
> **Independent Test**: Run `python -m pytest tests/` from project root. All config validation unit tests pass. Run `python -c "from newsletter_agent.config.schema import NewsletterConfig"` to verify the module imports cleanly.
> **Depends on**: none
> **Parallelisable**: No (all other WPs depend on this)
> **Prompt**: `plans/WP01-project-scaffolding.md`

## Objective

This work package creates the entire project skeleton: directory structure matching the spec's Section 9.3,
dependency management via requirements.txt, environment variable handling via .env, version control hygiene
via .gitignore, and - most importantly - the Pydantic-based configuration system that loads and validates
`config/topics.yaml`. Every subsequent work package depends on this foundation. By the end of WP01,
`adk web` should be able to launch (even if the agent graph is a stub), config loading should be fully
testable, and the test harness should be wired.

## Spec References

- Section 4.1 (FR-001 through FR-007) - Topic Configuration
- Section 7.1 (NewsletterConfig data model)
- Section 7.2 (TopicConfig data model)
- Section 8.4 (Config YAML schema)
- Section 9.2 (Technology Stack - PyYAML, Pydantic, python-dotenv, ADK)
- Section 9.3 (Directory & Module Structure)
- Section 10.2 (Security - .env gitignored, secrets never committed)
- Section 11.1 (Unit Tests - config validation)
- Section 11.2 (BDD - Topic Configuration feature)
- Section 12 (Constraints & Assumptions - Python 3.11+, ADK)

## Tasks

### T01-01 - Initialize ADK project directory structure

- **Description**: Create the full directory tree as defined in spec Section 9.3. This includes
  the `newsletter_agent/` package directory with `__init__.py`, subdirectories for config, tools,
  templates, prompts, and output. Also create the test directory structure at `tests/` with
  `__init__.py` files and subdirectory stubs for unit, integration, and e2e tests. The
  `newsletter_agent/__init__.py` must contain the ADK entry point comment but the actual agent
  import will be wired in WP05 once the root agent exists.
- **Spec refs**: Section 9.3 Directory & Module Structure
- **Parallel**: Yes
- **Acceptance criteria**:
  - [ ] Directory tree matches spec Section 9.3 layout exactly:
        `newsletter_agent/` with subdirs `config/`, `tools/`, `templates/`, `prompts/`, `output/`
  - [ ] `newsletter_agent/__init__.py` exists and is a valid Python file
  - [ ] `tests/` directory exists with `__init__.py` and subdirs `tests/unit/`, `tests/integration/`,
        `tests/e2e/` each with their own `__init__.py`
  - [ ] All `__init__.py` files are importable without error
  - [ ] `newsletter_agent/config/__init__.py` exists
  - [ ] `newsletter_agent/tools/__init__.py` exists
  - [ ] `newsletter_agent/templates/` directory exists (no __init__.py needed, holds Jinja2 templates)
  - [ ] `newsletter_agent/prompts/__init__.py` exists
- **Test requirements**: none (structural verification only)
- **Depends on**: none
- **Implementation Guidance**:
  - ADK project structure docs: https://google.github.io/adk-docs/get-started/quickstart/
  - ADK expects the agent package to have an `__init__.py` that exposes a `root_agent` variable
    or imports from an `agent` module. For now, create a placeholder comment in `__init__.py`.
  - The `output/` directory inside `newsletter_agent/` should have a `.gitkeep` file so it is
    tracked by git but its contents (generated newsletters) are ignored.
  - Known pitfall: ADK's `adk web` command looks for the agent package by directory name. The
    package must be named exactly `newsletter_agent` (with underscore, not hyphen).
  - Do NOT create `newsletter_agent/config/topics.yaml` here - that is done in T01-05 at the
    project root level `config/topics.yaml` path. The `newsletter_agent/config/` directory holds
    only Python modules (schema.py).
  - Complete directory tree to create:
    ```
    newsletter_agent/
      __init__.py              # Placeholder: "# ADK entry point - wired in WP05"
      agent.py                 # Created in T01-09, not here
      config/
        __init__.py            # Empty
        schema.py              # Created in T01-06, not here
      tools/
        __init__.py            # Empty
      templates/               # No __init__.py - holds .j2 files only
      prompts/
        __init__.py            # Empty
      output/
        .gitkeep               # Ensures dir is tracked; contents gitignored
    config/                    # Project-level config (separate from newsletter_agent/config/)
    tests/
      __init__.py              # Empty
      conftest.py              # Created in T01-10, not here
      unit/
        __init__.py            # Empty
      integration/
        __init__.py            # Empty
      e2e/
        __init__.py            # Empty
    ```
  - Each `__init__.py` should be an empty file (or contain a single-line comment).
  - The `config/` directory at project root is just a directory with no `__init__.py`
    because it is not a Python package - it holds YAML configuration.
  - Verify all directories can be imported after creation:
    `python -c "import newsletter_agent; import newsletter_agent.config; import newsletter_agent.tools; import newsletter_agent.prompts"`
  - Edge case: on Windows, ensure directory separators work correctly. Python's `pathlib`
    handles this transparently.

### T01-02 - Create requirements.txt with all dependencies

- **Description**: Create `requirements.txt` at the project root listing all Python dependencies
  from spec Section 9.2 Technology Stack. Pin major versions where possible for reproducibility.
  Include both runtime and test dependencies. The file should be organized into sections with
  comments for clarity.
- **Spec refs**: Section 9.2 Technology Stack
- **Parallel**: Yes
- **Acceptance criteria**:
  - [ ] `requirements.txt` exists at project root
  - [ ] Contains `google-adk` (ADK framework)
  - [ ] Contains `pyyaml` (YAML parsing)
  - [ ] Contains `pydantic` (config validation)
  - [ ] Contains `python-dotenv` (local .env loading)
  - [ ] Contains `jinja2` (HTML templating)
  - [ ] Contains `bleach` or `nh3` (HTML sanitization - prefer `nh3` as `bleach` is deprecated)
  - [ ] Contains `google-api-python-client` (Gmail API)
  - [ ] Contains `google-auth` and `google-auth-oauthlib` (OAuth2)
  - [ ] Contains `httpx` (for Perplexity API calls and E2E tests)
  - [ ] Contains test dependencies: `pytest`, `pytest-asyncio`, `pytest-cov`
  - [ ] Running `pip install -r requirements.txt` succeeds without errors
- **Test requirements**: none (installation verification)
- **Depends on**: none
- **Implementation Guidance**:
  - ADK package: `google-adk>=1.0.0` - check PyPI for latest stable version
  - Pydantic v2: `pydantic>=2.0` - use v2 model syntax (model_validator, field_validator)
  - For Perplexity API: use `httpx` directly rather than the `perplexityai` SDK, as the SDK
    may not be maintained. The Perplexity API is OpenAI-compatible, so `httpx` POST to
    `https://api.perplexity.ai/chat/completions` is sufficient and avoids a fragile dependency.
  - HTML sanitization: prefer `nh3` over `bleach` as bleach is in maintenance mode.
    See https://github.com/messense/nh3 - Rust-based, faster, actively maintained.
  - `markdown` library for converting LLM markdown output to HTML before inserting into Jinja2
    template.
  - Separate runtime deps from test deps with comments:
    ```
    # Runtime
    google-adk>=1.0.0
    ...
    # Testing
    pytest>=8.0
    ...
    ```
  - Full expected requirements.txt content (versions may need adjustment at implementation time):
    ```
    # =============================================================================
    # Runtime Dependencies
    # =============================================================================
    
    # Agent framework
    google-adk>=1.0.0
    
    # Configuration
    pyyaml>=6.0
    pydantic>=2.0
    
    # Environment
    python-dotenv>=1.0
    
    # Templating and content processing
    jinja2>=3.1
    markdown>=3.5
    nh3>=0.2                         # HTML sanitization (bleach replacement)
    
    # Gmail API
    google-api-python-client>=2.100
    google-auth>=2.20
    google-auth-oauthlib>=1.2
    
    # HTTP client (Perplexity API + E2E tests)
    httpx>=0.27
    
    # =============================================================================
    # Test Dependencies
    # =============================================================================
    pytest>=8.0
    pytest-asyncio>=0.23
    pytest-cov>=5.0
    ```
  - After creating the file, run `pip install -r requirements.txt` and verify with `pip check`
    to detect any dependency conflicts.
  - Known issue: `google-adk` may transitively install its own `pydantic` version.
    If there is a conflict, loosen the pydantic pin to `pydantic>=2.0,<3.0`.
  - Do NOT include `perplexityai` SDK. The spec decided to use `httpx` directly
    for the Perplexity API (see WP02 T02-01 for details).

### T01-03 - Create .gitignore

- **Description**: Create a comprehensive `.gitignore` at the project root that prevents secrets,
  build artifacts, IDE files, Python bytecode, and generated output from being committed. This is
  a security requirement from spec Section 10.2.
- **Spec refs**: Section 10.2 Security (secrets never committed), Section 11.6 Security Tests
- **Parallel**: Yes
- **Acceptance criteria**:
  - [ ] `.gitignore` exists at project root
  - [ ] Ignores `.env` files (`.env`, `.env.*`, `!.env.example`)
  - [ ] Ignores Python bytecode (`__pycache__/`, `*.pyc`, `*.pyo`)
  - [ ] Ignores virtual environments (`venv/`, `.venv/`, `env/`)
  - [ ] Ignores IDE files (`.vscode/`, `.idea/`, `*.swp`)
  - [ ] Ignores output directory contents (`newsletter_agent/output/*.html`,
        but NOT the directory itself)
  - [ ] Ignores `*.egg-info/`, `dist/`, `build/`
  - [ ] Ignores OAuth token files (`token.json`, `credentials.json` if placed at root)
  - [ ] Does NOT ignore `config/topics.yaml` (this is user config, should be tracked)
  - [ ] `.env.example` is NOT ignored (it is a template without real secrets)
- **Test requirements**: security (Section 11.6 - verify .env is gitignored)
- **Depends on**: none
- **Implementation Guidance**:
  - Start from GitHub's Python .gitignore template:
    https://github.com/github/gitignore/blob/main/Python.gitignore
  - Add project-specific entries for OAuth tokens and newsletter output
  - Critical security requirement: `.env` must be ignored. This is tested in Section 11.6.
  - Also ignore `gmail_token.json` or similar OAuth token cache files that the
    `setup_gmail_oauth.py` script might create.
  - The `output/` directory needs a `.gitkeep` to be tracked, but `output/*.html` should
    be ignored. Use `newsletter_agent/output/*.html` in .gitignore.
  - Full recommended .gitignore structure:
    ```
    # === Secrets (SECURITY CRITICAL) ===
    .env
    .env.*
    !.env.example
    token.json
    gmail_token.json
    credentials.json
    
    # === Python ===
    __pycache__/
    *.py[cod]
    *$py.class
    *.egg-info/
    dist/
    build/
    *.egg
    
    # === Virtual Environments ===
    venv/
    .venv/
    env/
    ENV/
    
    # === IDE ===
    .vscode/
    .idea/
    *.swp
    *.swo
    *~
    
    # === Generated Output ===
    newsletter_agent/output/*.html
    output/*.html
    
    # === OS ===
    .DS_Store
    Thumbs.db
    ```
  - Verify after creation: `git status` should not show `.env` if it exists.
  - Edge case: Ensure the negation `!.env.example` works correctly (Git processes
    .gitignore rules sequentially; the negation must come after the wildcard match).

### T01-04 - Create .env.example template

- **Description**: Create `.env.example` at the project root with placeholder values for all
  required environment variables. This serves as documentation for the operator during initial
  setup. It must NOT contain real credentials. The file lists every secret referenced in spec
  Section 9.5 External Integrations and Section 12 Constraints.
- **Spec refs**: Section 9.5 External Integrations, Section 10.2 Security, FR-041
- **Parallel**: Yes
- **Acceptance criteria**:
  - [ ] `.env.example` exists at project root
  - [ ] Contains `GOOGLE_API_KEY=your-google-api-key-here` placeholder
  - [ ] Contains `PERPLEXITY_API_KEY=your-perplexity-api-key-here` placeholder
  - [ ] Contains `GMAIL_CLIENT_ID=your-gmail-client-id-here` placeholder
  - [ ] Contains `GMAIL_CLIENT_SECRET=your-gmail-client-secret-here` placeholder
  - [ ] Contains `GMAIL_REFRESH_TOKEN=your-gmail-refresh-token-here` placeholder
  - [ ] Contains explanatory comments above each variable describing where to obtain the value
  - [ ] File does NOT contain any real credentials
- **Test requirements**: security (verify no real credentials)
- **Depends on**: none
- **Implementation Guidance**:
  - Include comment headers grouping variables by service:
    ```
    # =============================================================================
    # Newsletter Agent - Environment Variables
    # =============================================================================
    # Copy this file to .env and replace placeholder values with real credentials.
    # NEVER commit the .env file to version control.
    # =============================================================================
    
    # --- Google AI / ADK ---
    # Required for Gemini model access and Google Search grounding.
    # Get your API key from: https://aistudio.google.com/apikey
    GOOGLE_API_KEY=your-google-api-key-here
    
    # --- Perplexity AI ---
    # Required for Perplexity Sonar search tool.
    # Get your API key from: https://www.perplexity.ai/settings/api
    PERPLEXITY_API_KEY=your-perplexity-api-key-here
    
    # --- Gmail OAuth2 ---
    # Required for email delivery. Run setup_gmail_oauth.py to obtain these.
    # 1. Create OAuth2 credentials in Google Cloud Console:
    #    https://console.cloud.google.com/apis/credentials
    # 2. Download the client ID and secret
    # 3. Run: python setup_gmail_oauth.py
    # 4. Complete the browser OAuth flow
    # 5. Copy the refresh token here
    GMAIL_CLIENT_ID=your-gmail-client-id-here
    GMAIL_CLIENT_SECRET=your-gmail-client-secret-here
    GMAIL_REFRESH_TOKEN=your-gmail-refresh-token-here
    ```
  - The python-dotenv library loads these via `load_dotenv()` at startup.
  - On Cloud Run, these become Secret Manager references injected as env vars (WP05).
  - The Operator copies this file to `.env` and fills in real values.
  - Verification: Grep the committed `.env.example` for patterns like real API key formats
    (e.g., `AIza...` for Google, `pplx-...` for Perplexity) - none should be present.

### T01-05 - Create sample config/topics.yaml

- **Description**: Create `config/topics.yaml` at the project root (NOT inside newsletter_agent/)
  with the example configuration from spec Section 8.4. This serves as both a working sample and
  documentation of the schema. The sample should include 2-3 topics demonstrating all field
  options (required and optional). Set `dry_run: true` by default so the sample is safe to run
  without Gmail credentials.
- **Spec refs**: Section 8.4 Config YAML Schema, FR-001 through FR-007, Section 7.1, Section 7.2
- **Parallel**: Yes
- **Acceptance criteria**:
  - [ ] `config/topics.yaml` exists at project root level
  - [ ] Contains `newsletter` section with `title`, `schedule`, `recipient_email`
  - [ ] Contains `settings` section with `dry_run: true` and `output_dir: "output/"`
  - [ ] Contains `topics` list with at least 2 entries
  - [ ] First topic demonstrates all fields including optional `search_depth: "deep"`
        and explicit `sources` list
  - [ ] Second topic demonstrates minimal required fields only (uses defaults)
  - [ ] YAML is valid and parseable by PyYAML
  - [ ] File includes inline comments explaining each field
- **Test requirements**: none (reference config, validated by T01-07 tests)
- **Depends on**: none
- **Implementation Guidance**:
  - Use the exact example from spec Section 8.4 as the starting point
  - Add a third topic with minimal fields to demonstrate defaults
  - Set `dry_run: true` so local development is safe by default
  - Schedule format is standard 5-field cron: `"0 8 * * 0"` = Sunday 8am UTC
  - FR-001 specifies the path as `config/topics.yaml` relative to project root.
    This is a top-level `config/` directory, separate from `newsletter_agent/config/`
    which holds Python modules.
  - Validation note: `recipient_email` must be a valid email format per FR-005.
    Use a placeholder like `"your-email@gmail.com"`.
  - Full recommended content:
    ```yaml
    # =============================================================================
    # Newsletter Agent - Topic Configuration
    # =============================================================================
    # This file defines the newsletter content, schedule, and delivery settings.
    # See specs/newsletter-agent.spec.md Sections 7.1, 7.2, 8.4 for full schema.
    # =============================================================================
    
    # Newsletter metadata and delivery settings
    newsletter:
      title: "Weekly Tech Digest"            # Display title (1-200 chars)
      schedule: "0 8 * * 0"                  # Cron: Sunday 8am UTC
      recipient_email: "your-email@gmail.com" # Delivery target
    
    # Application settings
    settings:
      dry_run: true                          # true = save HTML only, no email
      output_dir: "output/"                  # Where to save HTML output
    
    # Research topics (1-20 items)
    topics:
      # Topic with all options specified (deep research, both providers)
      - name: "AI Frameworks"
        query: >-
          Latest developments in AI agent frameworks, including LangChain,
          CrewAI, Google ADK, and AutoGen. Focus on new releases, benchmarks,
          and adoption trends.
        search_depth: "deep"
        sources:
          - google_search
          - perplexity
    
      # Topic with minimal config (uses defaults: standard depth, both sources)
      - name: "Cloud Native"
        query: >-
          Recent developments in cloud-native technologies, Kubernetes,
          serverless platforms, and major cloud provider announcements.
    
      # Topic with single source
      - name: "Open Source Highlights"
        query: >-
          Notable new open source projects, major releases, and community
          trends in software development.
        sources:
          - google_search
    ```
  - The `>-` YAML syntax for multi-line strings strips trailing newlines and folds
    lines, producing a clean single-line query string. This is the recommended format
    for long natural language queries.

### T01-06 - Implement Pydantic configuration models (schema.py)

- **Description**: Create `newsletter_agent/config/schema.py` with Pydantic v2 models that
  represent the full configuration schema from spec Section 7.1 and 7.2. This includes
  `TopicConfig`, `NewsletterSettings`, `AppSettings`, and the root `NewsletterConfig` model.
  All validation constraints from the spec must be enforced: field types, string length limits,
  enum values, list size bounds (1-20 topics), email format, and defaults.
- **Spec refs**: FR-002 through FR-007, Section 7.1 NewsletterConfig, Section 7.2 TopicConfig,
  Section 4.1 Implementation Contract
- **Parallel**: No (core deliverable of this WP)
- **Acceptance criteria**:
  - [ ] `newsletter_agent/config/schema.py` exists and is importable
  - [ ] `TopicConfig` model enforces:
        - `name`: str, required, min_length=1, max_length=100
        - `query`: str, required, min_length=1, max_length=500
        - `search_depth`: Literal["standard", "deep"], default="standard"
        - `sources`: list of Literal["google_search", "perplexity"],
          default=["google_search", "perplexity"]
  - [ ] `NewsletterSettings` model enforces:
        - `title`: str, required, min_length=1, max_length=200
        - `schedule`: str, required (cron expression)
        - `recipient_email`: str, required, valid email format (use Pydantic EmailStr or regex)
  - [ ] `AppSettings` model enforces:
        - `dry_run`: bool, default=False
        - `output_dir`: str, default="output/"
  - [ ] `NewsletterConfig` root model enforces:
        - `newsletter`: NewsletterSettings, required
        - `settings`: AppSettings, optional (defaults applied)
        - `topics`: list[TopicConfig], required, min 1 item, max 20 items
  - [ ] All `TopicConfig.name` values within a config are unique (model_validator)
  - [ ] Pydantic `ValidationError` raised on any constraint violation with
        human-readable error messages identifying the offending field
  - [ ] A custom `ConfigValidationError` exception wraps Pydantic errors with
        context about which topic or section failed
- **Test requirements**: unit (extensive - see T01-07)
- **Depends on**: T01-01 (directory structure), T01-02 (pydantic dependency)
- **Implementation Guidance**:
  - Use Pydantic v2 syntax: `from pydantic import BaseModel, Field, field_validator, model_validator`
  - For email validation, use `pydantic[email]` extra or a regex validator.
    Pydantic v2 EmailStr requires `pip install pydantic[email]` (installs email-validator).
    Add `email-validator` to requirements.txt OR use a regex pattern:
    `re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")`
  - For topic uniqueness, use a `@model_validator(mode="after")` on `NewsletterConfig`
    that checks `len(set(t.name for t in self.topics)) == len(self.topics)`
  - For topic count bounds (FR-007: 1-20), use `Field(min_length=1, max_length=20)` on
    the `topics` list field. Pydantic v2 supports min_length/max_length on list fields.
  - Create a `ConfigValidationError` custom exception class in the same module that
    stores the original Pydantic `ValidationError` and adds a human-readable summary.
  - Spec Section 4.1 Implementation Contract: output is `NewsletterConfig` dataclass.
    Pydantic models satisfy this - they are dataclass-like with validation.
  - Edge case: empty `sources` list should default to both providers, not be allowed
    as an empty list. Add a validator that replaces `[]` with the default.
  - Complete reference implementation for schema.py (the coder should use this as a guide,
    adjusting as needed for the actual Pydantic and ADK versions installed):
    ```python
    """
    Configuration models and loader for Newsletter Agent.
    
    Loads and validates config/topics.yaml using Pydantic v2 models.
    Spec refs: FR-001 through FR-007, Section 7.1, 7.2, 8.4.
    """
    
    from __future__ import annotations
    
    import re
    from typing import Literal
    
    import yaml
    from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
    from pydantic import ValidationError
    
    
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
        
        @field_validator("sources", mode="before")
        @classmethod
        def default_empty_sources(cls, v):
            if v is not None and isinstance(v, list) and len(v) == 0:
                return ["google_search", "perplexity"]
            return v
    
    
    class NewsletterSettings(BaseModel):
        model_config = ConfigDict(extra="forbid")
        
        title: str = Field(min_length=1, max_length=200)
        schedule: str = Field(min_length=1)
        recipient_email: str
        
        @field_validator("recipient_email")
        @classmethod
        def validate_email(cls, v: str) -> str:
            if not _EMAIL_PATTERN.match(v):
                raise ValueError(f"'{v}' is not a valid email address")
            return v
    
    
    class AppSettings(BaseModel):
        model_config = ConfigDict(extra="forbid")
        
        dry_run: bool = False
        output_dir: str = "output/"
    
    
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
    ```
  - This reference implementation covers all spec requirements, validation rules,
    and error handling. The coder may adjust import paths and add type annotations
    as needed for the actual project structure.

### T01-07 - Implement config loader function

- **Description**: Create a `load_config()` function in `newsletter_agent/config/schema.py`
  (or a separate `newsletter_agent/config/loader.py`) that reads the YAML file from disk,
  parses it with PyYAML, and validates it through the Pydantic models. This function is the
  single entry point for all config access throughout the application.
- **Spec refs**: FR-001, FR-004, Section 4.1 Implementation Contract
- **Parallel**: No
- **Acceptance criteria**:
  - [ ] `load_config(path: str = "config/topics.yaml") -> NewsletterConfig` function exists
  - [ ] Function reads the YAML file using `yaml.safe_load()` (NOT `yaml.load()` - security)
  - [ ] Function passes parsed dict to `NewsletterConfig(**data)` for Pydantic validation
  - [ ] On `FileNotFoundError`, raises with clear message: "Config file not found: {path}"
  - [ ] On YAML parse error, raises `ConfigValidationError` with parse error details
  - [ ] On Pydantic validation error, raises `ConfigValidationError` wrapping the
        Pydantic error with field-level details
  - [ ] Function accepts an optional `path` parameter to support test configs
  - [ ] Returns a fully validated `NewsletterConfig` instance on success
- **Test requirements**: unit
- **Depends on**: T01-06 (Pydantic models)
- **Implementation Guidance**:
  - SECURITY: Always use `yaml.safe_load()`, never `yaml.load()`. The `yaml.load()` function
    can execute arbitrary Python code via YAML tags. This is an injection risk (OWASP A03:2021).
  - Pattern: 
    ```python
    def load_config(path: str = "config/topics.yaml") -> NewsletterConfig:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"Config file not found: {path}")
        except yaml.YAMLError as e:
            raise ConfigValidationError(f"Invalid YAML: {e}")
        try:
            return NewsletterConfig(**data)
        except ValidationError as e:
            raise ConfigValidationError.from_pydantic(e)
    ```
  - The `encoding="utf-8"` parameter handles the edge case of UTF-8 special characters
    in topic names (spec Section 5 Edge Cases).
  - The function should accept both absolute and relative paths.

### T01-08 - Write unit tests for configuration system

- **Description**: Create comprehensive unit tests for the Pydantic models and config loader
  covering all valid/invalid scenarios from spec Section 11.1 and the BDD scenarios from
  Section 11.2 (Topic Configuration feature). Tests must cover happy paths, boundary values,
  missing fields, wrong types, and all constraint violations.
- **Spec refs**: Section 11.1 Unit Tests (config validation), Section 11.2 BDD (Topic Config),
  US-01 Acceptance Scenarios 1-4
- **Parallel**: No
- **Acceptance criteria**:
  - [ ] Test file exists at `tests/unit/test_config.py`
  - [ ] Tests cover valid config with 1, 3, and 20 topics (boundary values)
  - [ ] Tests cover invalid: 0 topics raises ConfigValidationError
  - [ ] Tests cover invalid: 21 topics raises ConfigValidationError
  - [ ] Tests cover invalid: topic missing `name` field
  - [ ] Tests cover invalid: topic missing `query` field
  - [ ] Tests cover invalid: topic name exceeds 100 chars
  - [ ] Tests cover invalid: topic query exceeds 500 chars
  - [ ] Tests cover invalid: `search_depth` value not in ["standard", "deep"]
  - [ ] Tests cover invalid: `sources` contains unknown provider string
  - [ ] Tests cover invalid: `recipient_email` is not a valid email format
  - [ ] Tests cover invalid: `newsletter.title` is empty string
  - [ ] Tests cover default values: `search_depth` defaults to "standard",
        `sources` defaults to both, `dry_run` defaults to false,
        `output_dir` defaults to "output/"
  - [ ] Tests cover duplicate topic names raise ConfigValidationError
  - [ ] Tests cover `load_config()` with valid YAML file returns NewsletterConfig
  - [ ] Tests cover `load_config()` with missing file raises FileNotFoundError
  - [ ] Tests cover `load_config()` with invalid YAML syntax raises ConfigValidationError
  - [ ] Tests cover UTF-8 characters in topic names (spec edge case)
  - [ ] All tests pass with `pytest tests/unit/test_config.py`
  - [ ] Minimum 15 test cases
- **Test requirements**: unit (this IS the test task)
- **Depends on**: T01-06 (models), T01-07 (loader)
- **Implementation Guidance**:
  - Use `pytest` with `tmp_path` fixture for creating temporary YAML files
  - Pattern for YAML test fixtures:
    ```python
    def write_yaml(tmp_path, data):
        path = tmp_path / "topics.yaml"
        path.write_text(yaml.dump(data), encoding="utf-8")
        return str(path)
    ```
  - Use `pytest.raises(ConfigValidationError)` for error cases
  - Test boundary values: name at exactly 100 chars (valid), 101 chars (invalid)
  - Test empty sources list is replaced with default (both providers)
  - BDD Scenario mapping:
    - "Valid config with 3 topics" -> test_valid_config_three_topics
    - "Config with missing required field" -> test_missing_query_field
    - "Config with too many topics" -> test_too_many_topics (21)
  - Coverage target: 80% line coverage on `newsletter_agent/config/` (spec Section 11.1)
  - Suggested test function names and their mapping to spec requirements:
    ```python
    # --- Happy path tests ---
    def test_valid_config_minimal():
        """1 topic with required fields only. Maps to US-01 Scenario 1."""
    
    def test_valid_config_three_topics():
        """3 topics, all with full fields. BDD: 'Valid config with 3 topics'."""
    
    def test_valid_config_max_topics():
        """20 topics (boundary). Maps to FR-007 upper bound."""
    
    def test_valid_config_defaults_applied():
        """Topic with no optional fields gets correct defaults. Maps to FR-003."""
    
    def test_valid_config_utf8_topic_name():
        """Topic name with Unicode characters. Maps to spec Edge Cases."""
    
    def test_valid_config_deep_search_depth():
        """search_depth='deep' is accepted. Maps to FR-003."""
    
    def test_valid_config_single_source():
        """sources=['google_search'] only. Maps to FR-003."""
    
    # --- Error cases ---
    def test_invalid_zero_topics():
        """0 topics raises error. Maps to US-01 Scenario 3, FR-007."""
    
    def test_invalid_too_many_topics():
        """21 topics raises error. BDD: 'Config with too many topics'. FR-007."""
    
    def test_invalid_missing_topic_name():
        """Topic without name field. Maps to FR-002."""
    
    def test_invalid_missing_topic_query():
        """Topic without query field. BDD: 'Config with missing required field'."""
    
    def test_invalid_name_too_long():
        """name > 100 chars. Maps to FR-002 constraint."""
    
    def test_invalid_query_too_long():
        """query > 500 chars. Maps to FR-002 constraint."""
    
    def test_invalid_search_depth_value():
        """search_depth='ultra' not in enum. Maps to FR-003."""
    
    def test_invalid_source_provider():
        """sources=['bing'] unknown provider. Maps to FR-003."""
    
    def test_invalid_email_format():
        """recipient_email='not-an-email'. Maps to FR-005."""
    
    def test_invalid_empty_title():
        """newsletter.title=''. Maps to FR-005."""
    
    def test_invalid_duplicate_topic_names():
        """Two topics with same name. Maps to Section 7.2 uniqueness."""
    
    def test_invalid_extra_field_rejected():
        """Unknown field in topic. extra='forbid' enforcement."""
    
    # --- Default values ---
    def test_default_search_depth():
        """Omitted search_depth defaults to 'standard'. FR-003."""
    
    def test_default_sources():
        """Omitted sources defaults to both providers. FR-003."""
    
    def test_default_dry_run():
        """Omitted dry_run defaults to False. FR-006."""
    
    def test_default_output_dir():
        """Omitted output_dir defaults to 'output/'. FR-006."""
    
    def test_empty_sources_replaced_with_default():
        """Empty sources list [] replaced with both providers."""
    
    # --- Config loader ---
    def test_load_config_valid_file():
        """Loads valid YAML and returns NewsletterConfig. FR-001."""
    
    def test_load_config_file_not_found():
        """Missing file raises FileNotFoundError. FR-001 error contract."""
    
    def test_load_config_invalid_yaml_syntax():
        """Malformed YAML raises ConfigValidationError. FR-004."""
    
    def test_load_config_valid_yaml_invalid_data():
        """Valid YAML but failing validation raises ConfigValidationError. FR-004."""
    ```
  - For boundary value testing, create helpers:
    ```python
    def make_topic(name="Test Topic", query="Test query", **overrides):
        base = {"name": name, "query": query}
        base.update(overrides)
        return base
    
    def make_config(topics=None, **overrides):
        data = {
            "newsletter": {
                "title": "Test Newsletter",
                "schedule": "0 8 * * 0",
                "recipient_email": "test@example.com",
            },
            "topics": topics or [make_topic()],
        }
        data.update(overrides)
        return data
    ```

### T01-09 - Create stub root agent for ADK verification

- **Description**: Create a minimal `newsletter_agent/agent.py` with a stub `root_agent` that
  ADK can load. This is NOT the full pipeline agent (that is WP05) - it is just enough to verify
  that `adk web` launches successfully and the project structure is correct. Also wire the
  `__init__.py` to expose the agent.
- **Spec refs**: Section 9.3 (agent.py), Section 9.1 (root_agent SequentialAgent)
- **Parallel**: No
- **Acceptance criteria**:
  - [ ] `newsletter_agent/agent.py` exists with a `root_agent` variable
  - [ ] `root_agent` is a valid ADK agent (can be a simple LlmAgent with a
        placeholder instruction like "You are the Newsletter Agent. Pipeline not yet wired.")
  - [ ] `newsletter_agent/__init__.py` contains `from . import agent` (or equivalent
        ADK entry point)
  - [ ] Running `adk web newsletter_agent` from the project root launches the ADK
        web UI without errors (manual verification)
  - [ ] The agent responds to a test message in the ADK web UI
- **Test requirements**: none (manual ADK verification)
- **Depends on**: T01-01 (directory), T01-02 (requirements installed)
- **Implementation Guidance**:
  - ADK entry point pattern (from quickstart docs):
    ```python
    # newsletter_agent/__init__.py
    from . import agent
    ```
    ```python
    # newsletter_agent/agent.py
    from google.adk.agents import LlmAgent
    
    root_agent = LlmAgent(
        name="newsletter_agent",
        model="gemini-2.5-flash",
        instruction="You are the Newsletter Agent. The pipeline is not yet wired.",
    )
    ```
  - This stub will be replaced in WP05 with the full SequentialAgent pipeline.
  - Known pitfall: ADK requires the `GOOGLE_API_KEY` environment variable to be set
    even for the stub agent. The operator must have `.env` configured with at least
    this key before running `adk web`.
  - Test with: `cd <project_root> && adk web newsletter_agent`

### T01-10 - Configure pytest and test infrastructure

- **Description**: Create `pytest.ini` (or `pyproject.toml` [tool.pytest] section) with test
  configuration including test paths, markers, and coverage settings. Create a `conftest.py`
  with shared fixtures that will be used across all test types.
- **Spec refs**: Section 11.1 (unit tests), Section 11.4 (pytest + pytest-asyncio)
- **Parallel**: Yes
- **Acceptance criteria**:
  - [ ] `pyproject.toml` or `pytest.ini` exists with pytest configuration
  - [ ] Test discovery configured to find tests in `tests/` directory
  - [ ] `asyncio_mode = "auto"` configured for pytest-asyncio
  - [ ] Coverage configured to measure `newsletter_agent/` package
  - [ ] `tests/conftest.py` exists with at least:
        - A `sample_config_data` fixture returning a valid config dict
        - A `sample_topics_yaml` fixture that writes a valid YAML file to tmp_path
  - [ ] Running `pytest --co` (collect only) discovers all tests from T01-08
  - [ ] Running `pytest tests/unit/test_config.py -v` executes all config tests
- **Test requirements**: none (infrastructure task)
- **Depends on**: T01-02 (test dependencies)
- **Implementation Guidance**:
  - Prefer `pyproject.toml` over `pytest.ini` for modern Python projects:
    ```toml
    [tool.pytest.ini_options]
    testpaths = ["tests"]
    asyncio_mode = "auto"
    markers = [
        "unit: Unit tests (no external dependencies)",
        "integration: Integration tests (requires API keys)",
        "e2e: End-to-end tests (requires full environment)",
    ]
    
    [tool.coverage.run]
    source = ["newsletter_agent"]
    
    [tool.coverage.report]
    fail_under = 80
    ```
  - Shared fixtures in `tests/conftest.py` reduce duplication across test files.
  - The `sample_config_data` fixture should return a dict matching the spec's YAML schema
    so that individual tests can modify specific fields without rebuilding the whole structure.
  - Additional pyproject.toml content for the project:
    ```toml
    [project]
    name = "newsletter-agent"
    version = "0.1.0"
    description = "Autonomous multi-agent newsletter system built on Google ADK"
    requires-python = ">=3.11"
    
    [tool.pytest.ini_options]
    testpaths = ["tests"]
    asyncio_mode = "auto"
    markers = [
        "unit: Unit tests (no external dependencies)",
        "integration: Integration tests (requires API keys)",
        "e2e: End-to-end tests (requires full environment)",
    ]
    
    [tool.coverage.run]
    source = ["newsletter_agent"]
    omit = ["tests/*", "newsletter_agent/output/*"]
    
    [tool.coverage.report]
    fail_under = 80
    show_missing = true
    exclude_lines = [
        "pragma: no cover",
        "if __name__ == .__main__.",
        "if TYPE_CHECKING:",
    ]
    ```
  - The `conftest.py` file should also include a factory fixture for creating configs
    with arbitrary modifications:
    ```python
    @pytest.fixture
    def make_config_yaml(tmp_path):
        """Factory fixture: creates a YAML config file with custom data."""
        def _make(data: dict) -> str:
            path = tmp_path / "topics.yaml"
            path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
            return str(path)
        return _make
    ```
  - The `allow_unicode=True` in `yaml.dump` ensures UTF-8 characters in topic names
    survive the round-trip through YAML serialization in test fixtures.

## Edge Cases and Boundary Conditions

This section documents specific edge cases that the implementation must handle correctly.
These are drawn from spec Section 5 (Edge Cases) and the data model constraints.

### YAML Parsing Edge Cases

1. **Boolean coercion**: PyYAML `safe_load` treats unquoted `true`, `false`, `yes`, `no`,
   `on`, `off` as booleans. If a topic name is literally "Yes" or "True", it must be quoted
   in the YAML file. The Pydantic model will catch type errors (expecting str, getting bool)
   but the error message should hint at quoting. Test: create a config with
   `name: true` (unquoted) and verify the error message is helpful.

2. **Numeric strings**: PyYAML treats unquoted `123` as an integer. If a topic name starts
   with a number, it must be quoted. Same Pydantic type-check catch applies.

3. **Multi-line strings**: YAML supports multiple multi-line string formats:
   - `|` (literal block): preserves newlines
   - `>` (folded block): folds newlines to spaces
   - `>-` (folded, strip): folds and strips trailing newline
   For the `query` field, `>-` is recommended for long natural language descriptions.
   All formats should produce valid strings that pass Pydantic validation.

4. **Empty file**: A completely empty YAML file returns `None` from `safe_load`.
   The loader must handle this case and raise `ConfigValidationError("Empty config file")`.

5. **YAML with only comments**: A file containing only comments also returns `None`.
   Same handling as empty file.

6. **Duplicate YAML keys**: YAML allows duplicate keys (last one wins). This is a YAML
   spec behavior, not something we need to validate. But Pydantic will see only the last
   value, which may surprise the user. Document this in README.

### Config Validation Edge Cases

1. **Name at exact boundary**: Topic name with exactly 100 characters should be valid.
   101 characters should fail. Test both boundaries.

2. **Query at exact boundary**: Query with exactly 500 characters should be valid.
   501 characters should fail.

3. **Single-character strings**: `name: "A"` and `query: "Q"` should be valid (min_length=1).
   Empty string `name: ""` should fail.

4. **Whitespace-only strings**: `name: "   "` (all spaces) - technically passes min_length
   but is semantically empty. Decision: allow it in MVP (Pydantic does not strip by default).
   The operator is responsible for meaningful names.

5. **Unicode topic names**: Names with accented characters ("Resume technique"),
   CJK characters, emoji - all should be valid UTF-8 strings that pass length constraints.
   Note: Python's `len()` counts characters (code points), not bytes.

6. **Empty sources after filtering**: If `sources: []` is provided, the validator should
   replace it with the default `["google_search", "perplexity"]`. An explicit empty list
   is treated as "use defaults", not "use no sources".

7. **Settings section omitted entirely**: If the YAML has no `settings:` key, Pydantic
   should apply the `AppSettings` defaults (`dry_run=False`, `output_dir="output/"`).

8. **Cron expression validation**: FR-005 requires a "valid cron" schedule string. In MVP,
   we validate it is a non-empty string. Full cron syntax validation (5-field format,
   valid ranges) is not required - the cron expression is consumed by Cloud Scheduler,
   which will validate it at scheduling time. If Pydantic validation of cron format is
   desired, use a regex: `r"^(\S+\s+){4}\S+$"` (5 space-separated fields).

9. **Email format edge cases**: The email regex should accept standard formats:
   - `user@domain.com` (basic)
   - `user.name@domain.com` (dots)
   - `user+tag@domain.com` (plus addressing, common with Gmail)
   - `user@subdomain.domain.com` (subdomain)
   It should reject:
   - `@domain.com` (no local part)
   - `user@` (no domain)
   - `user@domain` (no TLD)
   - `user domain.com` (no @)

### File System Edge Cases

1. **Config path with spaces**: The `load_config()` function should handle paths with spaces
   (e.g., `C:\My Projects\config\topics.yaml`). Python's `open()` handles this natively.

2. **Config path with special characters**: Unicode in path names should work on modern OS.
   Test with standard ASCII paths in CI.

3. **Read permissions**: If the config file exists but is not readable, `open()` raises
   `PermissionError`. The loader should let this propagate with a clear message.

4. **Config file is a directory**: If the path points to a directory, `open()` raises
   `IsADirectoryError`. Let it propagate.

## Cross-Task Integration Points

This section documents how WP01 deliverables integrate with subsequent work packages.

### Config models used by WP02 (Research Pipeline)

The research pipeline (WP02) reads topic configs to:
- Extract `topic.query` as the search prompt for Google Search and Perplexity agents
- Check `topic.search_depth` to select Perplexity model (sonar vs sonar-pro)
- Check `topic.sources` to determine which providers to invoke
- Use the topic index for state key naming: `research_{index}_{provider}`

The `TopicConfig` model must be importable from `newsletter_agent.config.schema` by WP02 code.

### Config models used by WP03 (Synthesis & Formatting)

The formatter (WP03) reads:
- `config.newsletter.title` for the newsletter header
- `config.topics[i].name` for section headings
- Topic count for the table of contents

### Config models used by WP04 (Email Delivery)

The delivery agent (WP04) reads:
- `config.newsletter.recipient_email` for the To: field
- `config.newsletter.title` for the Subject: line
- `config.settings.dry_run` to decide email vs file output
- `config.settings.output_dir` for the HTML file save path

### Config models used by WP05 (Assembly)

The root agent factory (WP05) reads:
- The entire `NewsletterConfig` to dynamically construct the agent tree
- `config.topics` list to create per-topic research sub-agents
- `config.settings.dry_run` to configure the delivery agent behavior

## Implementation Notes

### Directory creation order
1. Create all directories and `__init__.py` files first (T01-01)
2. Create `requirements.txt` (T01-02) and install dependencies
3. Create `.gitignore` (T01-03) and `.env.example` (T01-04) - can be parallel
4. Create sample config (T01-05) - can be parallel with above
5. Implement Pydantic models (T01-06) - requires dependencies installed
6. Implement config loader (T01-07) - requires models
7. Write tests (T01-08) - requires loader
8. Create stub agent (T01-09) - requires dependencies installed
9. Configure test infra (T01-10) - can be parallel with T01-08

### Key commands
- Install deps: `pip install -r requirements.txt`
- Run tests: `pytest tests/unit/test_config.py -v`
- Run with coverage: `pytest --cov=newsletter_agent --cov-report=term-missing tests/unit/`
- Verify ADK: `adk web newsletter_agent`

### Pydantic v2 patterns to use
- `BaseModel` for all config models
- `Field(min_length=..., max_length=...)` for string constraints
- `Field(min_length=..., max_length=...)` on list fields for collection size bounds
- `Literal["standard", "deep"]` for enum-like string fields
- `field_validator` for custom field-level validation
- `model_validator(mode="after")` for cross-field validation (topic name uniqueness)
- `ConfigDict(extra="forbid")` to reject unknown fields in YAML

### Security considerations
- `yaml.safe_load()` only - never `yaml.load()` (OWASP A03 injection prevention)
- `.env` added to `.gitignore` before any secrets are created
- `.env.example` contains only placeholder values
- No real API keys in any committed file

### ADK project setup reference

The ADK expects a specific package layout to function correctly with `adk web` and `adk run`.
The critical conventions are:

1. The agent package must be a proper Python package (directory with `__init__.py`)
2. The package `__init__.py` must import the `agent` module: `from . import agent`
3. The `agent.py` module must expose a `root_agent` variable
4. When running `adk web newsletter_agent`, ADK looks for the `newsletter_agent` package
   in the current working directory
5. The `GOOGLE_API_KEY` environment variable must be set for any Gemini model usage

For Cloud Run deployment (WP05), the package structure also needs:
- A `Dockerfile` or reliance on ADK's built-in deployment which generates one
- The `adk deploy cloud_run` command handles containerization automatically

### Config YAML loading architecture

The config system follows a clean two-layer architecture:

```
YAML file (disk) --> yaml.safe_load() --> raw dict --> Pydantic model --> validated NewsletterConfig
```

This separation means:
- PyYAML handles parsing only (no validation logic in YAML layer)
- Pydantic handles all validation, type coercion, and defaults
- A single `ConfigValidationError` exception type wraps both YAML parse errors
  and Pydantic validation errors, providing a unified error interface

The `ConfigValidationError` class should support:
```python
class ConfigValidationError(Exception):
    def __init__(self, message: str, field_errors: list[dict] | None = None):
        super().__init__(message)
        self.field_errors = field_errors or []
    
    @classmethod
    def from_pydantic(cls, error: ValidationError) -> "ConfigValidationError":
        field_errors = [
            {"field": ".".join(str(loc) for loc in e["loc"]), "message": e["msg"]}
            for e in error.errors()
        ]
        summary = f"Config validation failed with {len(field_errors)} error(s): "
        summary += "; ".join(f"{e['field']}: {e['message']}" for e in field_errors[:3])
        if len(field_errors) > 3:
            summary += f" ... and {len(field_errors) - 3} more"
        return cls(summary, field_errors)
```

### Pydantic model design details

**TopicConfig model structure:**
```python
from pydantic import BaseModel, Field, field_validator
from typing import Literal

class TopicConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    name: str = Field(min_length=1, max_length=100)
    query: str = Field(min_length=1, max_length=500)
    search_depth: Literal["standard", "deep"] = "standard"
    sources: list[Literal["google_search", "perplexity"]] = Field(
        default=["google_search", "perplexity"]
    )
    
    @field_validator("sources", mode="before")
    @classmethod
    def default_empty_sources(cls, v):
        if v is not None and len(v) == 0:
            return ["google_search", "perplexity"]
        return v
```

**NewsletterConfig root model with cross-field validation:**
```python
class NewsletterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    newsletter: NewsletterSettings
    settings: AppSettings = Field(default_factory=AppSettings)
    topics: list[TopicConfig] = Field(min_length=1, max_length=20)
    
    @model_validator(mode="after")
    def validate_unique_topic_names(self) -> "NewsletterConfig":
        names = [t.name for t in self.topics]
        if len(names) != len(set(names)):
            duplicates = [n for n in names if names.count(n) > 1]
            raise ValueError(
                f"Topic names must be unique. Duplicates found: {set(duplicates)}"
            )
        return self
```

### Test architecture and fixtures

The test suite for WP01 should follow this structure:

```
tests/
  conftest.py              # Shared fixtures
  unit/
    __init__.py
    test_config.py          # Config model + loader tests
```

**Core fixtures in conftest.py:**
```python
import pytest
import yaml
from pathlib import Path

@pytest.fixture
def sample_config_data():
    """Returns a valid config dict matching spec Section 8.4 schema."""
    return {
        "newsletter": {
            "title": "Weekly Tech Digest",
            "schedule": "0 8 * * 0",
            "recipient_email": "test@example.com",
        },
        "settings": {
            "dry_run": True,
            "output_dir": "output/",
        },
        "topics": [
            {
                "name": "AI Frameworks",
                "query": "Latest developments in AI agent frameworks",
                "search_depth": "deep",
                "sources": ["google_search", "perplexity"],
            },
            {
                "name": "Cloud Native",
                "query": "Recent cloud-native technology developments",
            },
        ],
    }

@pytest.fixture
def sample_topics_yaml(tmp_path, sample_config_data):
    """Writes a valid YAML config file and returns its path."""
    path = tmp_path / "topics.yaml"
    path.write_text(yaml.dump(sample_config_data), encoding="utf-8")
    return str(path)

@pytest.fixture
def make_config_yaml(tmp_path):
    """Factory fixture for creating custom YAML config files."""
    def _make(data: dict) -> str:
        path = tmp_path / "topics.yaml"
        path.write_text(yaml.dump(data), encoding="utf-8")
        return str(path)
    return _make
```

**Test case categories for test_config.py:**

1. **Model validation - happy path** (5+ tests):
   - Valid minimal config (1 topic, required fields only)
   - Valid full config (all optional fields specified)
   - Valid config with maximum topics (20)
   - Valid config with UTF-8 topic names
   - Valid config with deep search_depth

2. **Model validation - error cases** (10+ tests):
   - Zero topics
   - 21 topics (exceeds maximum)
   - Missing topic name
   - Missing topic query
   - Name exceeds 100 characters
   - Query exceeds 500 characters
   - Invalid search_depth value
   - Invalid source provider
   - Duplicate topic names
   - Invalid email format
   - Missing newsletter title
   - Empty newsletter title
   - Extra/unknown field in topic (extra="forbid")

3. **Default values** (3+ tests):
   - search_depth defaults to "standard"
   - sources defaults to both providers
   - dry_run defaults to false
   - output_dir defaults to "output/"
   - Empty sources list replaced with default

4. **Config loader** (4+ tests):
   - Valid YAML file loads correctly
   - Missing file raises FileNotFoundError
   - Invalid YAML syntax raises ConfigValidationError
   - Valid YAML with invalid data raises ConfigValidationError

### Expected file inventory after WP01 completion

```
newsletter_agent/
  __init__.py                    # ADK entry point
  agent.py                       # Stub root_agent
  config/
    __init__.py
    schema.py                    # Pydantic models + load_config()
  tools/
    __init__.py
  templates/                     # Empty, ready for WP03
  prompts/
    __init__.py
  output/
    .gitkeep
config/
  topics.yaml                    # Sample configuration
tests/
  __init__.py
  conftest.py                    # Shared test fixtures
  unit/
    __init__.py
    test_config.py               # Config validation tests
  integration/
    __init__.py
  e2e/
    __init__.py
.env.example                     # Environment variable template
.gitignore                       # Version control exclusions
requirements.txt                 # Python dependencies
pyproject.toml                   # Pytest + coverage config
```

## Parallel Opportunities

Tasks that can be worked concurrently:
- [P] T01-01, T01-02, T01-03, T01-04, T01-05 are all independent and can be created in parallel
- [P] T01-09 and T01-10 can run in parallel once T01-01 and T01-02 are done
- T01-06 -> T01-07 -> T01-08 is strictly sequential (models -> loader -> tests)

## Risks & Mitigations

- **Risk**: `google-adk` package version incompatibility with Python 3.11+.
  **Mitigation**: Check PyPI for latest version. Pin to known-good version in requirements.txt.
  If ADK requires a different Python version, document this in README.
  Source: ADK quickstart specifies Python 3.11+ compatibility.

- **Risk**: Pydantic v2 breaking changes from v1 patterns found in online examples.
  **Mitigation**: Use only v2 syntax (BaseModel, Field, field_validator, model_validator).
  Reference Pydantic v2 migration guide: https://docs.pydantic.dev/latest/migration/
  Key v1->v2 changes: `validator` -> `field_validator`, `root_validator` -> `model_validator`,
  `Config` inner class -> `model_config = ConfigDict(...)`.

- **Risk**: `adk web` fails to launch with stub agent due to missing configuration.
  **Mitigation**: Ensure `.env` exists with `GOOGLE_API_KEY` before running `adk web`.
  Document this in the task acceptance criteria and README.

- **Risk**: YAML safe_load behavior differences between PyYAML versions for edge cases
  (e.g., boolean coercion of "true"/"false" strings, numeric strings).
  **Mitigation**: Use explicit string quoting in sample YAML. Add unit tests for edge cases.
  PyYAML safe_load treats unquoted `true`/`false` as booleans - topic names should be quoted
  if they could be confused with YAML special values.

- **Risk**: Pydantic EmailStr requires optional `email-validator` dependency.
  **Mitigation**: Either add `email-validator` to requirements.txt or use a regex-based
  validator instead. Regex is simpler and avoids the extra dependency. The email format
  validation does not need to be RFC-compliant - a basic format check is sufficient for
  a personal tool.

- **Risk**: ADK package may ship with its own Pydantic dependency at a conflicting version.
  **Mitigation**: Check `google-adk` dependency requirements before pinning Pydantic version.
  Use `pip check` after installation to verify no conflicts.

## Verification Checklist

After all tasks are complete, verify the following end-to-end:

1. [ ] `pip install -r requirements.txt` succeeds with no dependency conflicts
2. [ ] `pip check` reports no broken dependencies
3. [ ] `python -c "from newsletter_agent.config.schema import NewsletterConfig"` succeeds
4. [ ] `python -c "from newsletter_agent.config.schema import load_config; c = load_config('config/topics.yaml'); print(c.newsletter.title)"` prints the newsletter title
5. [ ] `pytest tests/unit/test_config.py -v` shows all tests passing (15+ tests)
6. [ ] `pytest --cov=newsletter_agent tests/unit/ --cov-report=term-missing` shows 80%+ coverage on config module
7. [ ] `.env` is NOT tracked by git (`git status` does not show it)
8. [ ] `.env.example` IS tracked by git
9. [ ] `adk web newsletter_agent` launches without errors (requires GOOGLE_API_KEY in .env)
10. [ ] The directory structure matches spec Section 9.3

## Dependency Resolution Guide

This section provides guidance for resolving common dependency issues the coder may encounter.

### google-adk version selection

The `google-adk` package is relatively new. Check PyPI for the latest version:
```bash
pip index versions google-adk
```

If the package is not on PyPI, it may need to be installed from the ADK GitHub repository:
```bash
pip install google-adk
```

If there is a version conflict with other Google packages, try:
```bash
pip install --upgrade google-adk google-api-python-client google-auth
```

ADK's own dependencies typically include:
- `google-generativeai` or `google-cloud-aiplatform` (for Gemini model access)
- `fastapi` and `uvicorn` (for `adk web` UI server)
- `pydantic` (ADK uses Pydantic internally for its own models)

If ADK pins Pydantic to a specific range, adjust our requirements.txt to be compatible.

### Pydantic v2 compatibility

Pydantic v2 has significant API changes from v1. Common gotchas:
- `validator` is now `field_validator` and must be a `@classmethod`
- `root_validator` is now `model_validator`
- `Config` inner class is now `model_config = ConfigDict(...)`
- `schema()` is now `model_json_schema()`
- `dict()` is now `model_dump()`
- `parse_obj()` is now `model_validate()`

Reference: https://docs.pydantic.dev/latest/migration/

### httpx vs requests

We use `httpx` instead of `requests` because:
- `httpx` supports both sync and async patterns (needed for ADK's async pipeline)
- Consistent API for both sync (`httpx.post()`) and async (`httpx.AsyncClient()`) usage
- No need for both `requests` and `aiohttp` - one library covers both cases
- Used in WP02 for Perplexity API calls and in WP05 for E2E test HTTP triggers

### nh3 vs bleach for HTML sanitization

`bleach` is in maintenance mode (security fixes only, no new features).
`nh3` is the recommended replacement:
- Rust-based (faster, memory-safe)
- API is simpler: `nh3.clean(html_string)` vs complex bleach config
- Actively maintained
- Smaller dependency footprint

Usage in WP03 (formatter):
```python
import nh3
cleaned_html = nh3.clean(
    llm_markdown_html,
    tags={"p", "a", "strong", "em", "ul", "ol", "li", "h1", "h2", "h3", "br"},
    attributes={"a": {"href"}},
)
```

## Common Error Messages Reference

This section documents expected error messages for the coder to verify against.

### Config Validation Errors

| Scenario | Expected Error (or substring) |
|----------|-------------------------------|
| Missing topics.yaml file | "Config file not found: config/topics.yaml" |
| Empty YAML file | "Empty config file" or "Config validation failed" |
| Invalid YAML syntax | "Invalid YAML:" followed by PyYAML error detail |
| Missing topic name | Field path "topics.0.name" in error |
| Missing topic query | Field path "topics.0.query" in error |
| Name too long | "String should have at most 100 characters" |
| Query too long | "String should have at most 500 characters" |
| Invalid search_depth | "Input should be 'standard' or 'deep'" |
| Invalid source | "Input should be 'google_search' or 'perplexity'" |
| 0 topics | "List should have at least 1 item" |
| 21 topics | "List should have at most 20 items" |
| Duplicate names | "Topic names must be unique. Duplicates found:" |
| Invalid email | Pattern match failure or "not a valid email" |
| Missing title | "Field required" at path "newsletter.title" |

These are Pydantic v2 default error messages. The exact wording may vary slightly
by Pydantic version. Tests should use `assert "substring" in str(error)` patterns
rather than exact string matching for robustness.

## Rollback Considerations

WP01 is the foundation package. If it needs to be reverted:

1. **No downstream dependencies yet**: Since WP01 is the first package, reverting it
   means removing all project files. This is a clean rollback with no cascading effects.

2. **Git recovery**: All changes are committed incrementally. Use `git log` to find the
   commit before WP01 work began, then `git reset --soft <commit>` to undo while
   preserving files for inspection.

3. **Dependency cleanup**: If `pip install` was run, the virtual environment may have
   new packages. Either recreate the venv or use `pip uninstall -r requirements.txt`.

4. **No external side effects**: WP01 does not touch any external services (no API calls,
   no email, no Cloud Run). It is fully local and fully reversible.

## Activity Log

- 2026-03-14T00:00:00Z - planner - lane=planned - Work package created
- 2026-03-14T01:30:00Z - coder - lane=doing - Implementation started
- 2026-03-14T02:00:00Z - coder - lane=for_review - All tasks complete, submitted for review
- 2026-03-14T02:45:00Z - reviewer - lane=done - Verdict: Approved with Findings (4 WARNs)

## Self-Review

- [x] Every SHALL obligation from referenced FRs has corresponding code
- [x] Every validation rule from the data model is enforced in code
- [x] All acceptance criteria met (33 tests, 100% coverage)
- [x] No unused code, dead imports, or debug artifacts
- [x] No hardcoded values that belong in config
- [x] No security issues (yaml.safe_load, .env gitignored, no secrets)
- [x] Implementation does not exceed task scope
- [x] No em dashes, smart quotes, or curly apostrophes

## Review

> **Reviewed by**: Reviewer Agent
> **Date**: 2026-03-14
> **Verdict**: Approved with Findings
> **review_status**: (none -- approved)

### Summary

WP01 is Approved with Findings. The implementation is correct, complete, and fully functional. All 7 FR-001 through FR-007 obligations are satisfied. All Pydantic models enforce the specified constraints. The config loader uses yaml.safe_load() per security requirements. All 33 unit tests pass with 100% line coverage on the config module. No encoding violations detected. Four WARNs are recorded below for process and test hygiene items that do not affect correctness.

### Review Feedback

No changes required. WARNs are informational for future work packages.

### Findings

#### PASS - Spec Adherence (FR-001 through FR-007)
- **Requirement**: FR-001 (load from config/topics.yaml), FR-002 (name 1-100, query 1-500), FR-003 (search_depth enum, sources list with defaults), FR-004 (validate and fail fast), FR-005 (newsletter section with title, schedule, recipient_email), FR-006 (settings with dry_run, output_dir), FR-007 (1-20 topics)
- **Status**: Compliant
- **Detail**: All SHALL obligations implemented. TopicConfig enforces name/query length constraints, Literal types for search_depth and sources, field_validator for empty sources list. NewsletterSettings validates email format via regex. NewsletterConfig enforces topic count (min_length=1, max_length=20) and unique topic names via model_validator. ConfigValidationError wraps Pydantic errors with field-level detail. load_config() raises FileNotFoundError and ConfigValidationError as specified in Section 4.1 Implementation Contract.
- **Evidence**: [newsletter_agent/config/schema.py](newsletter_agent/config/schema.py)

#### PASS - Data Model Adherence (Section 7.1, 7.2)
- **Requirement**: Section 7.1 NewsletterConfig, Section 7.2 TopicConfig
- **Status**: Compliant
- **Detail**: All fields, types, constraints, and defaults match the spec. TopicConfig: name (str, 1-100), query (str, 1-500), search_depth (Literal, default "standard"), sources (list[Literal], default both). NewsletterSettings: title (str, 1-200), schedule (str, min_length=1), recipient_email (str, validated). AppSettings: dry_run (bool, default False), output_dir (str, default "output/"). NewsletterConfig: newsletter (required), settings (optional with defaults), topics (1-20).
- **Evidence**: [newsletter_agent/config/schema.py](newsletter_agent/config/schema.py#L69-L125)

#### PASS - API/Interface Adherence (Section 8.4)
- **Requirement**: Section 8.4 Config YAML Schema
- **Status**: Compliant
- **Detail**: Sample config/topics.yaml matches the spec schema exactly with 3 topics demonstrating all field options. YAML structure matches Section 8.4 example. dry_run defaults to true in sample (safe for local dev).
- **Evidence**: [config/topics.yaml](config/topics.yaml)

#### PASS - Architecture Adherence (Section 9.2, 9.3)
- **Requirement**: Section 9.2 Technology Stack, Section 9.3 Directory Structure
- **Status**: Compliant
- **Detail**: Directory tree matches spec: newsletter_agent/ with config/, tools/, templates/, prompts/, output/ subdirectories. All __init__.py files present. .gitkeep in output/. requirements.txt includes all spec Section 9.2 dependencies: google-adk, pyyaml, pydantic, python-dotenv, jinja2, markdown, nh3, google-api-python-client, google-auth, google-auth-oauthlib, httpx, pytest, pytest-asyncio, pytest-cov. pyproject.toml configured with testpaths, asyncio_mode, coverage settings. Note: topics.yaml is at project-level config/ (per FR-001) rather than newsletter_agent/config/ (per Section 9.3 diagram). This follows FR-001 which has higher specificity; the WP plan explicitly documents this decision.
- **Evidence**: [requirements.txt](requirements.txt), [pyproject.toml](pyproject.toml), [newsletter_agent/__init__.py](newsletter_agent/__init__.py)

#### PASS - Test Coverage Adherence (Section 11.1)
- **Requirement**: Section 11.1 Unit Tests - config validation. Minimum 15 test cases. 80% coverage.
- **Status**: Compliant
- **Detail**: 33 test cases covering happy paths (9), error cases (12), defaults (5), loader (5), and field detail verification (2). All pass. 100% line coverage on newsletter_agent/config/ (74 statements, 0 missed). Coverage exceeds the 80% threshold.
- **Evidence**: [tests/unit/test_config.py](tests/unit/test_config.py), [tests/conftest.py](tests/conftest.py)

#### PASS - Non-Functional: Security (Section 10.2)
- **Requirement**: Section 10.2 - secrets never committed, yaml.safe_load, .env gitignored
- **Status**: Compliant
- **Detail**: yaml.safe_load() used exclusively (never yaml.load()). .env properly gitignored. .env.example contains only placeholder values (no real API key patterns). extra="forbid" on all models rejects unknown fields. OAuth token files (token.json, gmail_token.json, credentials.json) gitignored. .env.example is explicitly not ignored via negation rule.
- **Evidence**: [.gitignore](.gitignore), [.env.example](.env.example), [newsletter_agent/config/schema.py](newsletter_agent/config/schema.py#L148)

#### PASS - Scope Discipline
- **Requirement**: WP01 tasks T01-01 through T01-10
- **Status**: Compliant
- **Detail**: All WP01 deliverables present: directory structure, requirements.txt, .gitignore, .env.example, topics.yaml, schema.py with models and loader, test_config.py, conftest.py, pyproject.toml, stub agent.py, __init__.py entry point. No files created beyond what the WP tasks specify. Files from later WPs (http_handler.py, logging_config.py, timing.py, etc.) are from subsequent work packages and not part of WP01 scope.

#### PASS - Encoding (UTF-8)
- **Requirement**: No em dashes, smart quotes, curly apostrophes in created/modified files
- **Status**: Compliant
- **Detail**: All 10 WP01 files checked for U+2013, U+2014, U+2018, U+2019, U+201C, U+201D. None found.

#### WARN - Process: Single Commit for All Tasks
- **Requirement**: Process compliance - one commit per task
- **Status**: Partial
- **Detail**: All 10 tasks (T01-01 through T01-10) were committed in a single commit `dab0ecf feat(config): add project scaffolding and config system (WP01)`. Process guidance expects one commit per task for traceability and rollback granularity. This does not affect correctness but reduces commit-level traceability.
- **Evidence**: git log shows single WP01 commit

#### WARN - Process: No Per-Task Spec Compliance Checklist
- **Requirement**: Process compliance - Step 2b Spec Compliance Checklist per task
- **Status**: Partial
- **Detail**: The WP contains a global "Self-Review" section with 8 checkboxes covering spec compliance themes. However, it does not contain a per-task structured checklist mapping each task's deliverables to specific FR/section references. The self-review is adequate for practical purposes but not in the per-task format expected by process.
- **Evidence**: WP01 Self-Review section (line ~1517)

#### WARN - Test Pattern: Manual Exception Wrapping in Error Cases
- **Requirement**: Section 11.1 - config validation tests
- **Status**: Compliant (functional), suboptimal (pattern)
- **Detail**: Error case unit tests use a pattern that manually wraps any exception into ConfigValidationError: `try: NewsletterConfig(**data) except Exception as e: raise ConfigValidationError(str(e)) from e`. This pattern verifies that invalid data causes an error but does not test the actual ConfigValidationError.from_pydantic() code path used by load_config(). The tests are not falsifiable for the wrong reasons -- any exception type is wrapped. Better approach: test model validation expects ValidationError, test load_config() expects ConfigValidationError.
- **Evidence**: [tests/unit/test_config.py](tests/unit/test_config.py#L132-L198) (all error case tests)

#### WARN - BDD Tests Not Implemented as Formal Gherkin
- **Requirement**: Section 11.2 BDD - Feature: Topic Configuration (3 scenarios)
- **Status**: Partial
- **Detail**: Spec Section 11.2 defines 3 Gherkin scenarios for Topic Configuration: "Valid config with 3 topics", "Config with missing required field", "Config with too many topics". These are functionally covered by unit tests (test_valid_config_three_topics, test_invalid_missing_topic_query, test_invalid_too_many_topics) with BDD scenario references in docstrings. However, they are not implemented as formal pytest-bdd tests with Given/When/Then steps. The tests/bdd/ directory exists but has no config feature tests. This is a gap in test formality, not in coverage.
- **Evidence**: tests/bdd/ contains test_email_delivery.py and test_synthesis_formatting.py but no config BDD tests

### Statistics

| Dimension | Pass | Warn | Fail |
|-----------|------|------|------|
| Process Compliance | 0 | 2 | 0 |
| Spec Adherence | 1 | 0 | 0 |
| Data Model | 1 | 0 | 0 |
| API / Interface | 1 | 0 | 0 |
| Architecture | 1 | 0 | 0 |
| Test Coverage | 1 | 1 | 0 |
| Non-Functional | 1 | 0 | 0 |
| Performance | N/A | N/A | N/A |
| Documentation | N/A | N/A | N/A |
| Scope Discipline | 1 | 0 | 0 |
| Encoding (UTF-8) | 1 | 0 | 0 |
| BDD Tests | 0 | 1 | 0 |

### Recommended Actions

No actions required to proceed. The following are recommended improvements for future WPs:

1. **(WARN-01)** Use one commit per task for better traceability and rollback granularity.
2. **(WARN-02)** Include per-task Spec Compliance Checklists in WP files to demonstrate systematic FR verification.
3. **(WARN-03)** Refactor error case unit tests to either: (a) test model validation with `pytest.raises(ValidationError)`, or (b) test through `load_config()` with `pytest.raises(ConfigValidationError)`. Remove the manual wrapping pattern.
4. **(WARN-04)** Consider adding formal pytest-bdd tests for the Topic Configuration feature to match spec Section 11.2 Gherkin scenarios, particularly if BDD tests exist for other features.
