# Developer Guide

## Project Structure

```
NewsletterAgent/
  config/
    topics.yaml              # Newsletter configuration (topics, settings)
  newsletter_agent/
    __init__.py
    __main__.py              # Autonomous CLI entry point (python -m newsletter_agent)
    agent.py                 # Root agent, pipeline factory, custom agents
    logging_config.py        # Structured logging setup
    timing.py                # Pipeline timing instrumentation
    http_handler.py          # Cloud Run HTTP endpoint (Flask)
    config/
      schema.py              # Pydantic models and config loader
    prompts/
      research_google.py     # Google Search agent instruction builder
      research_perplexity.py # Perplexity agent instruction builder
      query_expansion.py     # Query expansion prompt for deep research
      synthesis.py           # Synthesis agent instruction builder
    tools/
      perplexity_search.py   # Perplexity Sonar API FunctionTool
      deep_research.py       # DeepResearchOrchestrator (multi-round deep search)
      research_utils.py      # Research output parsing utilities
      synthesis_utils.py     # Synthesis JSON parsing utilities
      sanitizer.py           # HTML sanitization (markdown + nh3)
      formatter.py           # FormatterAgent (Jinja2 HTML rendering)
      delivery.py            # DeliveryAgent (Gmail/file output)
      gmail_auth.py          # Gmail OAuth2 credential management
      gmail_send.py          # Gmail API email send function
      file_output.py         # Local HTML file output
    templates/
      newsletter.html.j2     # Jinja2 HTML newsletter template
  tests/
    conftest.py              # Shared test fixtures
    unit/                    # Unit tests
    bdd/                     # BDD scenario tests
    e2e/                     # End-to-end pipeline tests
    security/                # Security-focused tests (XSS, sanitization)
    performance/             # Performance validation tests
  docs/                      # Documentation
  specs/                     # Specification documents
  plans/                     # Work package plans
  setup_gmail_oauth.py       # One-time Gmail OAuth2 setup script
  requirements.txt           # Python dependencies
  pyproject.toml             # Project metadata and tool config
```

## Development Setup

```bash
# Clone and enter the project
git clone <repo-url> && cd NewsletterAgent

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate       # Windows
# source .venv/bin/activate  # Linux/macOS

# Install dependencies
pip install -r requirements.txt

# Copy environment file
cp .env.example .env
# Edit .env with your API keys
```

## Key Concepts

### ADK Agent Types Used

| Agent Type | ADK Class | Use Case |
|-----------|-----------|----------|
| `SequentialAgent` | Workflow | Runs sub-agents in order (pipeline root, per-topic research, output phase) |
| `ParallelAgent` | Workflow | Runs sub-agents concurrently (research phase across topics) |
| `LlmAgent` | Model | Calls Gemini with instructions and tools (search agents, synthesizer) |
| `BaseAgent` | Custom | Programmatic logic without LLM calls (ConfigLoader, Formatter, Delivery, DeepResearchOrchestrator, etc.) |

### Session State

All inter-agent communication happens through ADK session state (a shared dict). Agents read from and write to state keys. See [Architecture](architecture.md) for the complete state key inventory.

### Custom BaseAgent Pattern

Custom agents extend `google.adk.agents.BaseAgent` and implement `_run_async_impl`:

```python
from collections.abc import AsyncGenerator
from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types

class MyAgent(BaseAgent):
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        # Read from state
        input_data = state.get("some_key", "default")
        # Do work
        result = process(input_data)
        # Write to state
        state["output_key"] = result
        # Yield exactly one event
        yield Event(
            author=self.name,
            content=types.Content(
                parts=[types.Part(text="Done")]
            ),
        )
```

### FunctionTool Pattern

The Perplexity search is wrapped as an ADK `FunctionTool`:

```python
from google.adk.tools import FunctionTool

def search_perplexity(query: str, search_depth: str = "standard") -> dict:
    # ... implementation ...
    return {"text": "...", "sources": [...], "provider": "perplexity"}

perplexity_search_tool = FunctionTool(search_perplexity)
```

The function signature defines the tool's parameters. ADK handles serialization and invocation.

## Testing

### Test Organization

| Directory | Marker | Description |
|-----------|--------|-------------|
| `tests/unit/` | `unit` | Pure logic tests, no external dependencies |
| `tests/bdd/` | -- | BDD scenario tests |
| `tests/e2e/` | `e2e` | Pipeline integration, mocked LLM calls |
| `tests/security/` | -- | XSS, sanitization, injection tests |
| `tests/performance/` | `performance` | Timing and resource validation |

### Running Tests

```bash
# Full suite
pytest tests/ -v

# Unit tests only
pytest tests/unit/ -v

# With coverage
pytest tests/ --cov=newsletter_agent --cov-report=term-missing

# Specific test class
pytest tests/unit/test_agent_factory.py::TestBuildPipeline -v

# By marker
pytest -m performance -v
```

### Test Configuration

From `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"

[tool.coverage.run]
source = ["newsletter_agent"]

[tool.coverage.report]
fail_under = 80
```

### Writing Tests

**Unit tests** mock external dependencies and test individual functions/classes:

```python
@pytest.mark.asyncio
async def test_formatter_produces_html(self):
    state = {"synthesis_0": {...}, "config_newsletter_title": "Test"}
    ctx = MagicMock()
    ctx.session.state = state

    agent = FormatterAgent(name="Test")
    async for event in agent._run_async_impl(ctx):
        pass

    assert "<html" in state["newsletter_html"]
```

**Async tests** use `pytest-asyncio` with `asyncio_mode = "auto"` (no decorator needed when using the auto mode, but `@pytest.mark.asyncio` is used explicitly for clarity).

### Test Fixtures

Shared fixtures are defined in `tests/conftest.py`:

- `sample_config_data` -- Valid config dict matching the YAML schema
- `sample_topics_yaml` -- Writes a valid YAML file to a temp directory
- `make_config_yaml` -- Factory fixture for custom config files

## Code Conventions

### Naming

- Agent classes: `{Name}Agent` (e.g., `FormatterAgent`, `DeliveryAgent`)
- State keys: `snake_case` with namespace prefix (e.g., `config_dry_run`, `research_0_google`, `deep_queries_0_google`)
- Factory functions: `build_{thing}` (e.g., `build_pipeline`, `build_research_phase`)
- Private helpers: `_{name}` (e.g., `_normalize_sources`, `_strip_html`)

### Logging

All modules use `logging.getLogger(__name__)`. Log levels:

- `DEBUG`: Detailed internal state (disabled by default)
- `INFO`: Phase transitions, timing, normal operations
- `WARNING`: Fallback behavior, non-critical issues
- `ERROR`: Provider failures, delivery failures
- `CRITICAL`: Total research failure (pipeline will abort)

### Error Handling

- External API calls (Perplexity, Gmail) are wrapped in try/except and return error dicts
- Config validation uses Pydantic with custom `ConfigValidationError` wrapping
- Pipeline-level failures raise `RuntimeError` (caught by HTTP handler)
- Individual agent failures are logged but do not crash the pipeline (except total research failure)

### HTML Security

All LLM-generated content passes through:

1. `markdown.markdown()` -- Markdown to HTML conversion
2. `nh3.clean()` -- Tag/attribute allowlist sanitization
3. Jinja2 `autoescape=True` -- Template-level XSS prevention

Source URLs are filtered to `http://` and `https://` schemes in both `research_utils.py` and `synthesis_utils.py`.

## Adding a New Search Provider

To add a new search provider (e.g., Tavily, Brave Search):

1. Create `newsletter_agent/tools/{provider}_search.py` with a function matching the `FunctionTool` pattern
2. Create `newsletter_agent/prompts/research_{provider}.py` with an instruction builder
3. Add the provider name to `TopicConfig.sources` in `config/schema.py`
4. Update `build_research_phase()` in `agent.py` to create agents for the new provider (both standard and deep modes)
5. Update `DeepResearchOrchestrator._make_search_agent()` in `tools/deep_research.py` to support the new provider
5. Update `ResearchValidatorAgent` provider list construction
6. Add unit tests in `tests/unit/test_{provider}_search.py`

## Adding a New Topic Field

To add a new per-topic configuration field:

1. Add the field to `TopicConfig` in `config/schema.py` with appropriate validation
2. Update the prompt builders in `prompts/` if the field affects agent instructions
3. Update `config/topics.yaml` with the new field
4. Add unit tests for validation in `tests/unit/test_config.py`

## Modifying the Newsletter Template

The HTML template is at `newsletter_agent/templates/newsletter.html.j2`. It uses:

- Inline CSS (no external stylesheets, for email compatibility)
- Table-based layout with 600px max-width
- Jinja2 autoescape for security
- `{{ section.body_html|safe }}` for pre-sanitized LLM content

To modify the template:

1. Edit `newsletter.html.j2`
2. Run `pytest tests/unit/test_html_formatter.py -v` to verify rendering
3. Run `pytest tests/security/ -v` to verify sanitization still works
4. Generate a test newsletter in dry-run mode to preview the visual result
