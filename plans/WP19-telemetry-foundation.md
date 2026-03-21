---
lane: planned
---

# WP19 - Telemetry Foundation: Dependencies, OTel Init & Config Schema

> **Spec**: `specs/003-observability-cost-tracing.spec.md`
> **Status**: Not Started
> **Priority**: P0
> **Goal**: OTel SDK is installed, telemetry initializes at import, shuts down at exit, and PricingConfig is available in the config schema
> **Independent Test**: Run `python -c "from newsletter_agent.telemetry import init_telemetry, is_enabled; init_telemetry(); assert is_enabled()"` and verify it exits 0. Run `python -c "from newsletter_agent.config.schema import PricingConfig; p = PricingConfig(); print(p)"` and verify defaults.
> **Depends on**: WP15-WP18 (base system complete)
> **Parallelisable**: No
> **Prompt**: `plans/WP19-telemetry-foundation.md`

## Objective

Establish the foundational telemetry infrastructure that all subsequent observability work packages depend on. This WP installs OpenTelemetry Python SDK packages, creates the `telemetry.py` module with init/shutdown/tracer/is_enabled functions, adds the `PricingConfig` Pydantic models to the config schema, wires initialization into entry points (`__init__.py`, `__main__.py`, `http_handler.py`), and updates `.env.example`. No span creation, cost tracking, or log correlation happens yet -- those are WP20 and WP21.

## Spec References

- FR-101 through FR-106 (OTel Initialization & Configuration)
- FR-601 (PricingConfig in AppSettings)
- FR-602 through FR-604 (Export Configuration)
- FR-605 (.env.example)
- Section 7.1, 7.2, 7.3 (Data Model: ModelPricingConfig, PricingConfig, AppSettings)
- Section 8.1 (telemetry.py public interface -- init, shutdown, get_tracer, is_enabled only)
- Section 9.2 (Technology Stack)
- Section 9.3 (Directory & Module Structure)
- Section 9.4 Decision 4 (Console in dev, OTLP in production)
- SC-004, SC-007

## Tasks

### T19-01 - Add OpenTelemetry dependencies to requirements.txt

- **Description**: Add the three OTel packages to the runtime dependencies section of `requirements.txt`.
- **Spec refs**: Section 9.2 (Technology Stack)
- **Parallel**: No (must be first)
- **Acceptance criteria**:
  - [ ] `requirements.txt` contains `opentelemetry-api>=1.20.0`
  - [ ] `requirements.txt` contains `opentelemetry-sdk>=1.20.0`
  - [ ] `requirements.txt` contains `opentelemetry-exporter-otlp-proto-grpc>=1.20.0`
  - [ ] All three packages install successfully in the project virtual environment with `pip install -r requirements.txt`
  - [ ] No version conflicts with existing dependencies (google-adk, pydantic, etc.)
- **Test requirements**: none (manual verification via pip install)
- **Depends on**: none
- **Implementation Guidance**:
  - Official docs: https://opentelemetry.io/docs/languages/python/getting-started/
  - Add under a new `# Observability` comment section in requirements.txt, after the existing `# HTTP client` section
  - Known pitfalls: `opentelemetry-exporter-otlp-proto-grpc` pulls in `grpcio`. Verify no conflict with google-adk's grpc dependency. Both use `grpcio>=1.0` so this should be fine.
  - Run `pip install -r requirements.txt` and verify import: `python -c "import opentelemetry; print(opentelemetry.version.__version__)"`

### T19-02 - Create telemetry.py with init, shutdown, get_tracer, is_enabled

- **Description**: Create `newsletter_agent/telemetry.py` implementing `init_telemetry()`, `shutdown_telemetry()`, `get_tracer()`, and `is_enabled()` per the implementation contract in Section 8.1 and FR-101 through FR-106.
- **Spec refs**: FR-101, FR-102, FR-103, FR-104, FR-105, FR-106, FR-602, FR-603, FR-604, Section 8.1
- **Parallel**: No (depends on T19-01)
- **Acceptance criteria**:
  - [ ] `init_telemetry()` reads `OTEL_ENABLED` env var; when `"false"` (case-insensitive), sets `NoOpTracerProvider` via `trace.set_tracer_provider()` (FR-102)
  - [ ] `init_telemetry()` creates a `Resource` with `service.name` from `OTEL_SERVICE_NAME` (default `"newsletter-agent"`), `service.version` from package version `"0.1.0"`, and `deployment.environment` = `"production"` if `K_SERVICE` is set else `"development"` (FR-103, FR-104, FR-105)
  - [ ] When `OTEL_EXPORTER_OTLP_ENDPOINT` is set (non-empty), configures `BatchSpanProcessor` with `OTLPSpanExporter(endpoint=...)` passing `OTEL_EXPORTER_OTLP_HEADERS` for auth (FR-602)
  - [ ] When `OTEL_EXPORTER_OTLP_ENDPOINT` is NOT set, configures `BatchSpanProcessor` with `ConsoleSpanExporter` (FR-603)
  - [ ] In development mode AND with OTLP endpoint set, ALSO attaches a `SimpleSpanProcessor` with `ConsoleSpanExporter` (FR-604)
  - [ ] Sets module-level `_initialized = True` on success, `False` on any failure
  - [ ] `init_telemetry()` is idempotent -- second call is a no-op
  - [ ] On `ImportError` for OTel packages: logs WARNING `"OpenTelemetry SDK not available. Install opentelemetry-sdk to enable tracing."`, sets `_initialized = False`, returns (FR-101 error)
  - [ ] On any other exception: logs WARNING with traceback, sets `_initialized = False`, returns
  - [ ] `shutdown_telemetry()` calls `TracerProvider.shutdown(timeout_millis=5000)`. On timeout: logs WARNING, returns. Never raises. (FR-106)
  - [ ] `get_tracer(name)` returns `trace.get_tracer(name)` if `_initialized` else a `NoOpTracer` equivalent
  - [ ] `is_enabled()` returns `_initialized`
- **Test requirements**: unit (T19-07)
- **Depends on**: T19-01
- **Implementation Guidance**:
  - Official docs: https://opentelemetry.io/docs/languages/python/instrumentation/
  - Exporter docs: https://opentelemetry.io/docs/languages/python/exporters/
  - Key imports:
    ```python
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
        SimpleSpanProcessor,
    )
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.semconv.resource import ResourceAttributes
    ```
  - For OTLP exporter:
    ```python
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    ```
  - `NoOpTracerProvider` is available as `trace.NoOpTracerProvider()` in the API package
  - Use `os.environ.get()` for all env var reads, not `os.getenv()` (consistency with codebase)
  - Package version: read from `importlib.metadata.version("newsletter-agent")` with fallback to `"0.1.0"`
  - Known pitfall: `trace.set_tracer_provider()` is a global operation. Must be called before any `trace.get_tracer()` calls. The import-time call in `__init__.py` (T19-04) ensures this.
  - Error handling pattern: wrap entire init body in try/except with broad exception catch

### T19-03 - Add PricingConfig and ModelPricingConfig to config/schema.py

- **Description**: Add `ModelPricingConfig` and `PricingConfig` Pydantic models to `newsletter_agent/config/schema.py` and add the `pricing` field to `AppSettings`.
- **Spec refs**: FR-601, Section 7.1, 7.2, 7.3
- **Parallel**: Yes (independent of T19-02)
- **Acceptance criteria**:
  - [ ] `ModelPricingConfig(BaseModel)` has `input_per_million: float` and `output_per_million: float`, both with `ge=0.0` constraint
  - [ ] `PricingConfig(BaseModel)` has `models: dict[str, ModelPricingConfig]` with default containing `gemini-2.5-flash` (0.30/2.50) and `gemini-2.5-pro` (1.25/10.00)
  - [ ] `PricingConfig` has `cost_budget_usd: float | None = None` with `ge=0.0` when not None
  - [ ] `AppSettings` has new field `pricing: PricingConfig = Field(default_factory=PricingConfig)`
  - [ ] All existing fields on `AppSettings` remain unchanged
  - [ ] `PricingConfig()` with no args produces valid defaults
  - [ ] `PricingConfig(models={})` or empty dict raises validation error (min_length=1 on models)
  - [ ] Negative `input_per_million` or `output_per_million` raises validation error
  - [ ] The entire `pricing` section is optional in YAML config (AppSettings default handles it)
- **Test requirements**: unit (T19-08)
- **Depends on**: T19-01
- **Implementation Guidance**:
  - Add models BEFORE the `AppSettings` class definition in schema.py
  - Use `ConfigDict(extra="forbid")` on both new models to match existing convention
  - Default models dict as a `default_factory` lambda or inline:
    ```python
    models: dict[str, ModelPricingConfig] = Field(
        default_factory=lambda: {
            "gemini-2.5-flash": ModelPricingConfig(input_per_million=0.30, output_per_million=2.50),
            "gemini-2.5-pro": ModelPricingConfig(input_per_million=1.25, output_per_million=10.00),
        },
        min_length=1,
    )
    ```
  - For `cost_budget_usd`, use a validator or `Field(default=None, ge=0.0)`. Note: pydantic v2 allows `ge=0.0` on Optional float fields -- it only validates when the value is not None.
  - Spec validation rules to enforce:
    - `input_per_million >= 0.0`
    - `output_per_million >= 0.0`
    - `models` dict must have at least 1 entry
    - `cost_budget_usd >= 0.0` when provided (None is valid)

### T19-04 - Wire init_telemetry() into __init__.py

- **Description**: Call `init_telemetry()` in `newsletter_agent/__init__.py` at module import time, after `load_dotenv()` but before the agent import.
- **Spec refs**: FR-101 (initialize TracerProvider at module import time)
- **Parallel**: No (depends on T19-02)
- **Acceptance criteria**:
  - [ ] `newsletter_agent/__init__.py` imports and calls `init_telemetry()` after `load_dotenv()` and before `from . import agent`
  - [ ] If `init_telemetry()` fails (returns gracefully after logging WARNING), the agent import still proceeds
  - [ ] `trace.get_tracer_provider()` returns the configured provider after `import newsletter_agent`
- **Test requirements**: unit (verified as part of T19-07)
- **Depends on**: T19-02
- **Implementation Guidance**:
  - Current `__init__.py` content:
    ```python
    from dotenv import load_dotenv
    load_dotenv()
    from . import agent  # noqa: F401
    ```
  - Add between load_dotenv and agent import:
    ```python
    from .telemetry import init_telemetry
    init_telemetry()
    ```
  - Known pitfall: `init_telemetry()` must never raise. All exceptions are caught internally (FR-101 error handling). This ensures the agent import always succeeds.

### T19-05 - Wire shutdown_telemetry() into __main__.py and http_handler.py

- **Description**: Add `shutdown_telemetry()` calls to both entry points per FR-106.
- **Spec refs**: FR-106
- **Parallel**: Yes (independent of T19-04, but depends on T19-02)
- **Acceptance criteria**:
  - [ ] In `__main__.py`, `shutdown_telemetry()` is called in a `finally` block of the main execution path, ensuring it runs even if the pipeline fails
  - [ ] In `http_handler.py`, `shutdown_telemetry()` is called after each `/run` request completes (both success and error paths)
  - [ ] If `shutdown_telemetry()` times out (>5 seconds), it logs a WARNING and the process exits normally
  - [ ] Existing behavior of both entry points is preserved
- **Test requirements**: unit (verified as part of T19-07)
- **Depends on**: T19-02
- **Implementation Guidance**:
  - In `__main__.py`, the `main()` function (or `run_pipeline()`) should wrap the pipeline execution in try/finally:
    ```python
    from newsletter_agent.telemetry import shutdown_telemetry
    try:
        # ... existing pipeline execution ...
    finally:
        shutdown_telemetry()
    ```
  - In `http_handler.py`, add to the `/run` endpoint handler:
    ```python
    from newsletter_agent.telemetry import shutdown_telemetry
    # After pipeline execution (in finally or after return):
    shutdown_telemetry()
    ```
  - Known pitfall: `http_handler.py` uses Flask which may handle multiple requests. `shutdown_telemetry()` should be safe to call multiple times (idempotent or at least non-destructive). The OTel SDK's `TracerProvider.shutdown()` is safe to call after already shut down. Actually, per the spec, telemetry init is done once at import time in `__init__.py`, so re-init is not needed between requests. `shutdown_telemetry()` after each request flushes pending spans but the provider remains available. Verify this behavior.

### T19-06 - Update .env.example with OTel environment variables

- **Description**: Add OTel-related environment variables to `.env.example` per FR-605.
- **Spec refs**: FR-605
- **Parallel**: Yes (independent of all other tasks)
- **Acceptance criteria**:
  - [ ] `.env.example` contains `OTEL_ENABLED=true` (commented example)
  - [ ] `.env.example` contains `OTEL_SERVICE_NAME=newsletter-agent` (commented example)
  - [ ] `.env.example` contains `OTEL_EXPORTER_OTLP_ENDPOINT=` (commented, empty default)
  - [ ] `.env.example` contains `OTEL_EXPORTER_OTLP_HEADERS=` (commented, empty default)
  - [ ] Variables are under a new `# --- OpenTelemetry ---` section header with descriptive comments
- **Test requirements**: none (documentation)
- **Depends on**: none
- **Implementation Guidance**:
  - Add after the existing `# --- Logging ---` section
  - Format:
    ```
    # --- OpenTelemetry ---
    # Telemetry kill switch. Set to "false" to disable all tracing and cost tracking.
    # OTEL_ENABLED=true
    # Service name for trace identification.
    # OTEL_SERVICE_NAME=newsletter-agent
    # OTLP gRPC endpoint for trace export. Leave empty for console output.
    # OTEL_EXPORTER_OTLP_ENDPOINT=
    # Auth headers for OTLP endpoint (e.g., "Authorization=Bearer token").
    # OTEL_EXPORTER_OTLP_HEADERS=
    ```

### T19-07 - Unit tests for telemetry initialization and shutdown

- **Description**: Create `tests/test_telemetry.py` with unit tests covering init, shutdown, get_tracer, and is_enabled functions.
- **Spec refs**: FR-101, FR-102, FR-103, FR-104, FR-105, FR-106, FR-602, FR-603, FR-604, SC-004, SC-007, Section 11.1
- **Parallel**: No (depends on T19-02)
- **Acceptance criteria**:
  - [ ] Test: `init_telemetry()` with `OTEL_ENABLED=false` results in `is_enabled() == False` and `trace.get_tracer_provider()` is NoOpTracerProvider (SC-007)
  - [ ] Test: `init_telemetry()` with no OTLP endpoint configures ConsoleSpanExporter (verify via provider's span processors)
  - [ ] Test: `init_telemetry()` with `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317` configures OTLPSpanExporter (SC-004)
  - [ ] Test: `init_telemetry()` is idempotent -- second call does not reconfigure
  - [ ] Test: `is_enabled()` returns True after successful init, False after disabled init
  - [ ] Test: `get_tracer("test")` returns a valid tracer after init
  - [ ] Test: `shutdown_telemetry()` does not raise on timeout or when not initialized
  - [ ] Test: Resource attributes include correct `service.name`, `service.version`, `deployment.environment`
  - [ ] Test: `deployment.environment` is `"production"` when `K_SERVICE` is set, `"development"` otherwise
  - [ ] Test: OTel import failure (simulated via mock) logs WARNING and sets `is_enabled() == False`
  - [ ] All tests use `monkeypatch` or `unittest.mock.patch` for env vars, and reset global state in teardown
  - [ ] Minimum 80% code coverage, 90% branch coverage for `telemetry.py`
- **Test requirements**: unit (pytest)
- **Depends on**: T19-02
- **Implementation Guidance**:
  - Use `opentelemetry.sdk.trace.export.in_memory_span_exporter.InMemorySpanExporter` for assertions about span export
  - Reset global OTel state between tests:
    ```python
    from opentelemetry import trace
    trace.set_tracer_provider(trace.NoOpTracerProvider())
    ```
  - To test OTel import failure, mock the import inside `init_telemetry`:
    ```python
    with patch.dict("sys.modules", {"opentelemetry": None}):
        init_telemetry()
    ```
    Or mock the import check within the function.
  - Use `monkeypatch.setenv` / `monkeypatch.delenv` for env var manipulation
  - Each test should call a reset/teardown to avoid polluting global TracerProvider state. Consider a fixture:
    ```python
    @pytest.fixture(autouse=True)
    def reset_telemetry():
        yield
        # Reset module-level _initialized flag
        import newsletter_agent.telemetry as tel
        tel._initialized = False
        trace.set_tracer_provider(trace.NoOpTracerProvider())
    ```
  - Known pitfall: OTel global state is per-process. Tests must be careful about ordering. Use autouse fixtures.

### T19-08 - Unit tests for PricingConfig and ModelPricingConfig

- **Description**: Create `tests/test_config_pricing.py` with unit tests for the new Pydantic models.
- **Spec refs**: FR-601, Section 7.1, 7.2, 7.3, Section 11.1
- **Parallel**: No (depends on T19-03)
- **Acceptance criteria**:
  - [ ] Test: `PricingConfig()` with no args produces valid defaults with 2 models (gemini-2.5-flash, gemini-2.5-pro) and `cost_budget_usd=None`
  - [ ] Test: `PricingConfig(models={"custom-model": ModelPricingConfig(input_per_million=1.0, output_per_million=2.0)})` is valid
  - [ ] Test: `ModelPricingConfig(input_per_million=-1.0, ...)` raises `ValidationError` (ge=0.0)
  - [ ] Test: `ModelPricingConfig(output_per_million=-1.0, ...)` raises `ValidationError`
  - [ ] Test: `PricingConfig(cost_budget_usd=-0.01)` raises `ValidationError` (ge=0.0)
  - [ ] Test: `PricingConfig(cost_budget_usd=0.0)` is valid (zero budget is allowed)
  - [ ] Test: `PricingConfig(cost_budget_usd=None)` is valid (no budget)
  - [ ] Test: `AppSettings()` includes `pricing` field with default `PricingConfig()`
  - [ ] Test: Loading a YAML config without `pricing` section produces AppSettings with default pricing
  - [ ] Test: Loading a YAML config with custom pricing section populates correctly
  - [ ] Minimum 80% code coverage, 90% branch coverage for new models
- **Test requirements**: unit (pytest)
- **Depends on**: T19-03
- **Implementation Guidance**:
  - Follow existing test patterns in the project (check `tests/` for config test examples)
  - Use `pytest.raises(ValidationError)` for negative tests
  - Test YAML-to-config round trip by creating a minimal YAML string and loading it through `load_config()` or by constructing `NewsletterConfig` directly
  - Verify default pricing values match spec exactly: flash=0.30/2.50, pro=1.25/10.00

### T19-09 - Configure coverage thresholds for new modules

- **Description**: Ensure pytest-cov or equivalent is configured to enforce 80% code / 90% branch coverage for the new `telemetry.py` module and the new config models.
- **Spec refs**: Section 11.1 (minimum coverage)
- **Parallel**: No (depends on T19-07, T19-08)
- **Acceptance criteria**:
  - [ ] Running `pytest --cov=newsletter_agent.telemetry --cov-branch` reports >= 80% code and >= 90% branch coverage
  - [ ] Running `pytest --cov=newsletter_agent.config.schema --cov-branch` on the pricing-related tests reports adequate coverage for new code
  - [ ] Coverage configuration (if using pyproject.toml or .coveragerc) includes the new modules
- **Test requirements**: none (configuration)
- **Depends on**: T19-07, T19-08
- **Implementation Guidance**:
  - Check existing coverage config in `pyproject.toml` or `.coveragerc`
  - If no coverage tooling exists yet, add `pytest-cov` to dev dependencies
  - Known pitfall: Coverage for `__init__.py` changes is hard to measure in isolation. Focus on `telemetry.py` and `config/schema.py` coverage.

## Implementation Notes

- **Execution order**: T19-01 -> T19-02 + T19-03 (parallel) -> T19-04 + T19-05 + T19-06 (parallel) -> T19-07 + T19-08 (parallel) -> T19-09
- **Key files created**: `newsletter_agent/telemetry.py`
- **Key files modified**: `requirements.txt`, `newsletter_agent/__init__.py`, `newsletter_agent/__main__.py`, `newsletter_agent/http_handler.py`, `newsletter_agent/config/schema.py`, `.env.example`
- **Test files created**: `tests/test_telemetry.py`, `tests/test_config_pricing.py`
- **Virtual environment**: Must `pip install -r requirements.txt` after T19-01 to have OTel packages available
- **No `traced_generate()` yet**: That function is part of WP20. This WP only creates the init/shutdown/tracer/is_enabled infrastructure.

## Parallel Opportunities

- T19-02 (telemetry.py) and T19-03 (PricingConfig) are independent and can be developed concurrently [P]
- T19-04, T19-05, and T19-06 are independent of each other (all depend on T19-02 being done) [P]
- T19-07 and T19-08 are independent test tasks [P]

## Risks & Mitigations

- **Risk**: OTel SDK packages conflict with google-adk grpc dependencies. **Mitigation**: Both use grpcio. Run `pip install -r requirements.txt` in CI and verify no conflicts. If conflict arises, pin grpcio version.
- **Risk**: OTel SDK not compatible with Python 3.13. **Mitigation**: Latest OTel SDK (1.28+) supports Python 3.13. Verify import in test. Assumption A7 in spec.
- **Risk**: `trace.set_tracer_provider()` called too late (after agent code creates tracers). **Mitigation**: Init is called in `__init__.py` before `from . import agent`, ensuring global provider is set first.
- **Risk**: `shutdown_telemetry()` causes delays on Cloud Run cold start teardown. **Mitigation**: 5-second timeout per FR-106. BatchSpanProcessor is async and non-blocking.

## Activity Log

- 2025-07-18T00:00:00Z - planner - lane=planned - Work package created
