---
lane: for_review
review_status:
---

# WP02 - Research Pipeline

> **Spec**: `specs/newsletter-agent.spec.md`
> **Status**: Complete
> **Priority**: P1
> **Goal**: Each configured topic is researched in parallel via Google Search grounding and Perplexity Sonar API, with results stored in ADK session state
> **Independent Test**: Configure 2 topics, run the research pipeline, verify session state contains `research_0_google`, `research_0_perplexity`, `research_1_google`, `research_1_perplexity` keys with text and source URLs
> **Depends on**: WP01
> **Parallelisable**: No (depends on WP01 foundation)
> **Prompt**: `plans/WP02-research-pipeline.md`

## Objective

This work package delivers the complete research pipeline for the Newsletter Agent. It implements the Google Search grounding agent, the Perplexity Sonar API custom tool, the dynamic agent factory that constructs per-topic research sub-pipelines, and the ParallelAgent orchestration that runs all topic research concurrently. Upon completion, triggering the research phase with a validated config produces fully populated session state entries for every topic/provider combination, with graceful degradation when individual providers fail.

This is the first work package that creates actual ADK agents and tools. It builds directly on the project scaffolding and config system from WP01, using the validated `NewsletterConfig` to dynamically construct the agent tree.

## Spec References

- FR-008: Google Search grounding query via dedicated LlmAgent
- FR-009: Perplexity Sonar API via custom FunctionTool in separate LlmAgent
- FR-010: Parallel research execution via ParallelAgent
- FR-011: Namespaced session state keys (`research_{topic_index}_{provider}`)
- FR-012: Research result structure (text, sources, provider)
- FR-013: Provider failure resilience - log and continue
- FR-014: Deep search_depth behavior (detailed prompts, sonar-pro model)
- FR-015: Perplexity tool function signature and return format
- US-02: Multi-source research per topic
- Section 7.3: ResearchResult data model
- Section 7.4: SourceRef data model
- Section 8.2: Perplexity Sonar tool function signature
- Section 9.1: System architecture - research phase structure
- Section 9.4: Key Design Decisions 1 and 2
- Section 9.5: External integrations (Google Search, Perplexity)
- Section 10.1: Performance requirements for research phase
- Section 10.2: Security - SSRF mitigation, secrets management
- Section 11.1: Unit test requirements for Perplexity tool and agent factory
- Section 11.2: BDD scenarios for research pipeline
- Section 11.3: Integration test requirements for research

## Tasks

### T02-01 - Implement Perplexity Sonar API FunctionTool

- **Description**: Create the `search_perplexity` function in `newsletter_agent/tools/perplexity_search.py` that wraps the Perplexity Sonar API. The function must accept `query` (str) and `search_depth` (str) parameters, call the Perplexity chat completions endpoint using the `openai` SDK (Perplexity uses OpenAI-compatible API), and return a dict with `text`, `sources`, and `provider` keys. On any failure, the function must catch the exception and return an error dict instead of raising. The function is then wrapped as an ADK `FunctionTool` for use by a dedicated LlmAgent.

- **Spec refs**: FR-009, FR-014, FR-015, Section 8.2, Section 9.5 (Perplexity integration)

- **Parallel**: Yes (can be developed alongside T02-02)

- **Acceptance criteria**:
  - [ ] File `newsletter_agent/tools/perplexity_search.py` exists and exports `search_perplexity` function and `perplexity_search_tool` (ADK FunctionTool instance)
  - [ ] `search_perplexity(query="test", search_depth="standard")` calls the Perplexity API with model `sonar` and returns `{"text": str, "sources": list[{"url": str, "title": str}], "provider": "perplexity"}`
  - [ ] `search_perplexity(query="test", search_depth="deep")` uses model `sonar-pro` instead of `sonar`
  - [ ] When the Perplexity API is unreachable or returns an error, the function returns `{"error": True, "message": str, "provider": "perplexity"}` without raising an exception
  - [ ] The function reads `PERPLEXITY_API_KEY` from environment variables (loaded via python-dotenv in dev)
  - [ ] The function does NOT make requests to any user-controlled URLs - only the hardcoded Perplexity API endpoint (SSRF mitigation per Section 10.2)
  - [ ] Source URLs returned by Perplexity are extracted from the API response `citations` field and paired with content-derived titles

- **Test requirements**: unit (mock Perplexity API), integration (real API call with test key)

- **Depends on**: T01-01 (project scaffolding must exist)

- **Implementation Guidance**:
  - Official docs: Perplexity API uses OpenAI-compatible format. Use the `openai` Python SDK with `base_url="https://api.perplexity.ai"`. See https://docs.perplexity.ai/api-reference/chat-completions
  - Recommended pattern: Use the OpenAI SDK client directly rather than the `perplexityai` package, as the OpenAI SDK is more mature and Perplexity's API is OpenAI-compatible. This simplifies the dependency chain.
  - Model selection: `sonar` for standard depth, `sonar-pro` for deep depth. The model name is the only parameter that changes between depths.
  - Known pitfalls:
    - Perplexity returns citations as a list of URLs in the response metadata, not inline in the text. The function must extract these from `response.citations` (a list of URL strings).
    - The `citations` field may not always be present (e.g., if no web sources were found). Handle gracefully.
    - Rate limiting: Perplexity returns HTTP 429 on rate limit. The error dict must include the status code or message so downstream agents can distinguish rate limits from other failures.
    - The Perplexity API may return partial or empty responses for obscure queries. The function should still return a valid dict structure even if `text` is empty.
  - Error handling: Catch `openai.APIError`, `openai.APIConnectionError`, `openai.RateLimitError`, and generic `Exception`. Each should produce an error dict with a descriptive message.
  - Spec validation rules: Return dict must always have `provider` key set to `"perplexity"`. The `sources` list must contain dicts with `url` (str) and `title` (str) keys per Section 7.4.
  - ADK FunctionTool wrapping: After defining the function, create the tool with:
    ```python
    from google.adk.tools import FunctionTool
    perplexity_search_tool = FunctionTool(func=search_perplexity)
    ```
  - Environment variable: `PERPLEXITY_API_KEY` must be loaded from environment. In local dev, `python-dotenv` loads from `.env`. In production, the env var is injected by Cloud Run from Secret Manager.
  - Reference implementation structure:
    ```python
    import os
    import logging
    from openai import OpenAI, APIError, APIConnectionError, RateLimitError
    from google.adk.tools import FunctionTool

    logger = logging.getLogger(__name__)

    _PERPLEXITY_BASE_URL = "https://api.perplexity.ai"
    _MODEL_MAP = {"standard": "sonar", "deep": "sonar-pro"}

    def search_perplexity(query: str, search_depth: str = "standard") -> dict:
        # Implementation here
        ...

    perplexity_search_tool = FunctionTool(func=search_perplexity)
    ```

---

### T02-02 - Create Google Search Agent Instruction Prompts

- **Description**: Create instruction prompt templates for the Google Search grounding agent in `newsletter_agent/prompts/research_google.py`. Two prompt variants are needed: one for `search_depth="standard"` and one for `search_depth="deep"`. The standard prompt instructs the agent to search for the topic and return a structured summary with source URLs. The deep prompt instructs the agent to perform a more comprehensive, multi-faceted analysis. Both prompts must instruct the agent to return results in a structured format that can be parsed into the `ResearchResult` schema (text + sources list).

- **Spec refs**: FR-008, FR-014, Section 9.1 (Google Search agent structure), Section 9.4 Decision 2

- **Parallel**: Yes (can be developed alongside T02-01)

- **Acceptance criteria**:
  - [ ] File `newsletter_agent/prompts/research_google.py` exists and exports `get_google_search_instruction(topic_name: str, query: str, search_depth: str) -> str`
  - [ ] For `search_depth="standard"`, the returned instruction asks the agent to research the topic, summarize findings, and list source URLs with titles
  - [ ] For `search_depth="deep"`, the returned instruction asks for comprehensive multi-faceted analysis covering multiple angles, trends, and implications
  - [ ] Both prompts instruct the agent to output results in a parseable format with clear separation between summary text and source list
  - [ ] The prompts explicitly instruct the agent NOT to fabricate information or sources not found by the search tool
  - [ ] The prompt text does not contain any hardcoded API keys, secrets, or credentials

- **Test requirements**: unit (verify prompt generation for both depths, verify template substitution)

- **Depends on**: none (pure text/template work)

- **Implementation Guidance**:
  - ADK google_search tool: The LlmAgent using this tool gets grounded responses automatically. The agent's instruction prompt shapes what the LLM asks the tool and how it formats the response.
  - Recommended pattern: Use Python f-strings or string templates. The prompt should be a function that takes topic metadata and returns a complete instruction string. This keeps prompts testable and versionable.
  - Known pitfalls:
    - The google_search tool returns grounded text with inline source references. The agent instruction must ask the LLM to preserve these references and additionally list them at the end in a structured format.
    - Very broad queries (e.g., "everything about AI") may return unfocused results. The prompt should instruct the agent to focus on recent developments and key facts.
    - The instruction must be clear about the output format so the result can be parsed. Suggest using a structured format like:
      ```
      SUMMARY:
      [multi-paragraph summary text with inline citations]
      
      SOURCES:
      - [Title](URL)
      - [Title](URL)
      ```
  - Prompt quality: The research quality depends heavily on these prompts. They should be specific, include the topic name and query, and guide the LLM to produce well-structured output.
  - The standard prompt should be 100-200 words. The deep prompt should be 200-400 words with explicit instructions for multi-angle analysis.
  - Edge cases:
    - Topic names with special characters (quotes, brackets) must not break the prompt
    - Very long queries (up to 500 chars per spec) must fit within the prompt without truncation
    - Queries in languages other than English are out of scope (A-006) but the prompt should be robust to unusual query text

---

### T02-03 - Create Perplexity Agent Instruction Prompts

- **Description**: Create instruction prompt templates for the Perplexity search agent in `newsletter_agent/prompts/research_perplexity.py`. These prompts instruct the LlmAgent that wraps the `search_perplexity` FunctionTool. The agent needs to call the tool with the correct parameters (query and search_depth from the topic config) and then format the tool's response into the session state format. Two variants for standard and deep research.

- **Spec refs**: FR-009, FR-014, FR-015, Section 9.1 (Perplexity agent structure)

- **Parallel**: Yes (can be developed alongside T02-01 and T02-02)

- **Acceptance criteria**:
  - [ ] File `newsletter_agent/prompts/research_perplexity.py` exists and exports `get_perplexity_search_instruction(topic_name: str, query: str, search_depth: str) -> str`
  - [ ] The instruction tells the agent to call the `search_perplexity` tool with the provided query and search_depth
  - [ ] The instruction tells the agent to return the tool's response as-is if successful, or to note the error if the tool returned an error dict
  - [ ] For deep search_depth, the instruction asks for more comprehensive analysis framing in the tool call
  - [ ] The prompts do not contain hardcoded API keys or secrets

- **Test requirements**: unit (verify prompt generation for both depths)

- **Depends on**: none (pure text/template work)

- **Implementation Guidance**:
  - ADK FunctionTool agents: The LlmAgent receives the instruction, sees the available tool (search_perplexity), and decides to call it based on the instruction. The instruction must clearly state what tool to call and what parameters to pass.
  - Recommended pattern: Same structure as the Google Search prompts - a Python function returning an instruction string. Keep consistent with T02-02.
  - Known pitfalls:
    - The LlmAgent may not always call the tool on the first attempt. The instruction should be very direct: "You MUST call the search_perplexity tool with the following parameters..."
    - The tool returns a Python dict, but the LlmAgent sees it as text in the conversation. The instruction should tell the agent to relay the tool's full response.
    - If the tool returns an error dict, the agent should still produce a response noting the failure, not just silently fail.
  - Edge cases:
    - Same special character and long query concerns as T02-02
    - The search_depth parameter must be passed through to the tool call exactly as received ("standard" or "deep")

---

### T02-04 - Implement Dynamic Agent Factory for Research Phase

- **Description**: Implement the agent factory function in `newsletter_agent/agent.py` that dynamically constructs the research phase agent tree based on the loaded config. For each topic in the config, the factory creates a `SequentialAgent` containing a Google Search `LlmAgent` and a Perplexity `LlmAgent`. All per-topic SequentialAgents are wrapped in a `ParallelAgent` for concurrent execution. The factory must handle 1-20 topics and respect each topic's `sources` setting (skip providers not listed in `sources`).

- **Spec refs**: FR-008, FR-009, FR-010, FR-011, Section 9.1 (architecture), Section 9.4 Decision 1, Decision 2

- **Parallel**: No (requires T02-01, T02-02, T02-03 outputs)

- **Acceptance criteria**:
  - [ ] Function `build_research_phase(config: NewsletterConfig) -> ParallelAgent` exists in `newsletter_agent/agent.py`
  - [ ] For a config with N topics, the function returns a ParallelAgent containing N sub-agents
  - [ ] Each sub-agent is a SequentialAgent containing up to 2 LlmAgents (one for Google Search, one for Perplexity)
  - [ ] If a topic has `sources: ["google_search"]` only, its sub-agent contains only the Google Search LlmAgent
  - [ ] If a topic has `sources: ["perplexity"]` only, its sub-agent contains only the Perplexity LlmAgent
  - [ ] Each Google Search LlmAgent has exactly one tool: `google_search` (ADK built-in)
  - [ ] Each Perplexity LlmAgent has exactly one tool: `perplexity_search_tool` (FunctionTool)
  - [ ] Each LlmAgent's `output_key` is set to the correct namespaced key: `research_{topic_index}_{provider}`
  - [ ] Google Search agents use model `gemini-2.5-flash`
  - [ ] Perplexity agents use model `gemini-2.5-flash`
  - [ ] The factory function handles 1 topic, 5 topics, and 20 topics correctly
  - [ ] Agent names are unique and descriptive (e.g., `GoogleSearcher_0`, `PerplexitySearcher_0`)

- **Test requirements**: unit (test factory output structure for various topic counts and source configs)

- **Depends on**: T02-01, T02-02, T02-03

- **Implementation Guidance**:
  - Official docs: ADK ParallelAgent - https://google.github.io/adk-docs/agents/workflow-agents/parallel-agents/
  - Official docs: ADK LlmAgent - https://google.github.io/adk-docs/agents/llm-agents/
  - Official docs: ADK google_search tool - built-in tool, import from `google.adk.tools`
  - Recommended pattern: The factory function should be a standalone function at module level in agent.py. It takes the validated config and returns the constructed ParallelAgent. The root agent definition then calls this factory.
  - Key ADK APIs:
    ```python
    from google.adk.agents import LlmAgent, SequentialAgent, ParallelAgent
    from google.adk.tools import google_search
    from newsletter_agent.tools.perplexity_search import perplexity_search_tool
    ```
  - LlmAgent construction:
    ```python
    google_agent = LlmAgent(
        name=f"GoogleSearcher_{topic_idx}",
        model="gemini-2.5-flash",
        instruction=get_google_search_instruction(topic.name, topic.query, topic.search_depth),
        tools=[google_search],
        output_key=f"research_{topic_idx}_google",
    )
    ```
  - Known pitfalls:
    - ADK's `google_search` tool has a SINGLE-TOOL-PER-AGENT constraint. The Google Search LlmAgent must have `tools=[google_search]` with no other tools. This is a hard framework constraint (Section 9.4 Decision 2).
    - Agent names must be unique across the entire agent tree. Use the topic index in the name to ensure uniqueness.
    - The `output_key` property on LlmAgent automatically saves the agent's text response to the session state at that key. However, the raw text needs to be parseable into the ResearchResult format. The prompt instructions (T02-02, T02-03) must produce structured output that can be parsed.
    - ParallelAgent executes all sub-agents concurrently. If one fails, the others continue. This aligns with FR-013.
    - For topics with only one source, the SequentialAgent has only one child. This is valid in ADK.
  - Edge cases:
    - Config with 1 topic: ParallelAgent with a single child SequentialAgent. This is valid.
    - Config with 20 topics: 20 parallel SequentialAgents, each with 2 LlmAgents = 40 concurrent LLM calls. This may hit Gemini rate limits. The factory should not add any rate limiting itself (that is an operational concern).
    - Topic with empty sources list: per WP01 validation, this is normalized to both sources. The factory should handle both providers.
  - Testing strategy: Unit tests should verify the agent tree structure by inspecting the returned ParallelAgent's sub_agents list, checking names, tools, output_keys, and models. No actual LLM calls needed.

---

### T02-05 - Implement Research Result Parsing and State Storage

- **Description**: Implement utility functions that parse the raw text output from research agents into structured `ResearchResult` dicts conforming to Section 7.3 of the spec. The Google Search agent returns grounded text with inline citations that need to be extracted. The Perplexity agent returns tool output that may already be structured. Both need to be normalized into a consistent format before storage in session state. This may be implemented as a callback or post-processing step that runs after each research agent completes.

- **Spec refs**: FR-011, FR-012, FR-013, Section 7.3, Section 7.4

- **Parallel**: No (requires understanding of agent output formats from T02-01 through T02-04)

- **Acceptance criteria**:
  - [ ] A utility function `parse_research_result(raw_output: str, provider: str) -> dict` exists that converts raw agent text output into the ResearchResult schema
  - [ ] For Google Search output, the parser extracts: summary text, list of source URLs and titles from inline citations or appended source list
  - [ ] For Perplexity output, the parser extracts: text content, sources from the tool's return dict
  - [ ] If the raw output contains an error marker (e.g., the Perplexity tool returned an error dict), the parser returns `{"error": True, "message": str, "provider": str}`
  - [ ] The parsed result always contains the `provider` field set correctly
  - [ ] The `sources` list in the result contains dicts with `url` (str) and `title` (str) keys per Section 7.4
  - [ ] Invalid or unparseable output returns a fallback result with error flag rather than raising an exception

- **Test requirements**: unit (test parsing of various output formats, error cases, edge cases)

- **Depends on**: T02-01, T02-02, T02-03

- **Implementation Guidance**:
  - Recommended pattern: Create a `newsletter_agent/tools/research_utils.py` module with the parsing function. This keeps tool code separate from parsing logic.
  - Google Search output parsing:
    - ADK's google_search tool returns grounded text with citations. The exact format depends on the model version and grounding configuration.
    - The prompt (T02-02) instructs the agent to output in a SUMMARY/SOURCES format. The parser should look for this structure.
    - Fallback: If the structured format is not found, treat the entire output as summary text with no sources.
    - URL extraction: Use regex to find `[Title](URL)` patterns in the text.
  - Perplexity output parsing:
    - The Perplexity tool (T02-01) returns a dict as a string through the LLM agent. The parser needs to handle this being returned as the LLM's text representation of the dict.
    - If the LLM faithfully relays the tool output, it may be parseable as JSON or as a Python dict repr.
    - Fallback: If parsing fails, use the raw text as the summary with no sources.
  - Error handling:
    - Any exception during parsing should be caught and logged, with a fallback error result returned
    - The parser should never raise - it is a safety net for unpredictable LLM output
  - Known pitfalls:
    - LLMs may not perfectly preserve JSON structure when relaying tool output. The parser must be tolerant of formatting variations.
    - Source URLs may be truncated or malformed by the LLM. Basic URL validation (starts with http/https) should filter out garbage.
    - The google_search grounding may return sources in a metadata field rather than in the text. Check ADK documentation for the exact grounding response format.
  - Edge cases:
    - Output is empty string: return error result
    - Output contains no sources: return result with empty sources list and text only
    - Output is a valid error dict from the Perplexity tool: return as-is with error flag
    - Output contains malformed URLs: filter them out, keep only valid URLs
    - Output contains duplicate sources: deduplicate by URL

---

### T02-06 - Implement Error Handling and Provider Failure Resilience

- **Description**: Implement the error handling strategy for the research pipeline that ensures individual provider failures do not abort the entire pipeline. When a Google Search or Perplexity agent fails, the error must be caught, logged at ERROR level, and an error marker stored in session state for that topic/provider combination. The pipeline continues with other topics and providers. If ALL providers fail for ALL topics, the pipeline should detect this condition and abort gracefully.

- **Spec refs**: FR-013, Section 6.3 (partial failure flow), Section 4.2 implementation contract

- **Parallel**: No (builds on T02-04 and T02-05)

- **Acceptance criteria**:
  - [ ] When a single provider fails for a single topic, the error is logged at ERROR level with the topic name, provider name, and error message
  - [ ] The error marker stored in session state follows the format: `{"error": True, "message": str, "provider": str}` matching Section 7.3
  - [ ] Other topics and providers continue executing normally when one fails
  - [ ] When ALL providers fail for ALL topics, the pipeline detects this by checking all research state keys and logs a critical error
  - [ ] The total-failure detection returns a clear signal that downstream agents (synthesis) can check
  - [ ] Error logging uses Python's standard `logging` module with the structured format: `{timestamp} {level} {agent_name} {message}` per FR-044
  - [ ] No exception propagation from individual agent failures crashes the ParallelAgent

- **Test requirements**: unit (mock various failure scenarios), BDD (Scenario: Single provider failure)

- **Depends on**: T02-04, T02-05

- **Implementation Guidance**:
  - ADK error handling: ParallelAgent continues executing remaining sub-agents even if one fails. However, the exact behavior depends on the ADK version. Check the ADK docs for `ParallelAgent` error handling semantics.
  - Recommended pattern: Use ADK's `before_agent_callback` and `after_agent_callback` on the research agents to add error handling and state inspection. Alternatively, wrap each LlmAgent's execution in a try/except within a custom agent.
  - Logging setup: Use the logging configuration established in WP01. Research agents should log to a logger named after their agent (e.g., `newsletter_agent.research.GoogleSearcher_0`).
  - Total failure detection: After the ParallelAgent completes, a post-processing step inspects all `research_{N}_{provider}` session state keys. If every key is either missing or has `error: true`, the pipeline should store a `research_all_failed: true` flag in state.
  - Known pitfalls:
    - ADK may handle agent exceptions differently than expected. Some errors may be swallowed, others may propagate. Test with intentional failures.
    - The ParallelAgent may not set state keys for agents that entirely fail to execute (vs. agents that execute but return error results). Account for missing keys.
    - Rate limiting from Gemini API (40 concurrent calls for 20 topics) could cause cascading failures that appear as total failure. This is an operational concern, not a code concern.
  - Edge cases:
    - One provider fails for all topics, other provider succeeds for all: should continue normally
    - Timeout on one agent while others complete: ADK should handle this via async timeout
    - Provider returns empty response (not an error, but no useful content): this is not a failure, but should be noted in the research result

---

### T02-07 - Integrate Research Phase into Root Agent

- **Description**: Wire the research phase ParallelAgent into the root `SequentialAgent` pipeline in `newsletter_agent/agent.py`. The root agent already has the config loader from WP01; now add the research phase as the second step. The research phase reads the validated config from session state, builds the dynamic agent tree via the factory function, and executes. After completion, session state contains all research results ready for the synthesis phase (WP03).

- **Spec refs**: FR-010, Section 9.1 (root agent structure), Section 6.2 (generation flow steps 3-4)

- **Parallel**: No (requires T02-04, T02-06)

- **Acceptance criteria**:
  - [ ] The root `SequentialAgent` in `agent.py` includes the research phase ParallelAgent as its second child (after config loader)
  - [ ] The research phase reads topic configs from session state (stored by config loader in WP01)
  - [ ] After the research phase completes, session state contains all expected `research_{N}_{provider}` keys
  - [ ] The ADK web UI (`adk web`) shows the research phase agents executing with their individual names visible in the event stream
  - [ ] Running the full pipeline via `adk web` or `adk run` with a valid config and API keys produces research results in state
  - [ ] Dry-run compatible: research phase runs normally regardless of `dry_run` setting

- **Test requirements**: integration (run research phase with real APIs), E2E (verify via `adk web`)

- **Depends on**: T02-04, T02-06

- **Implementation Guidance**:
  - ADK agent wiring: The root agent is a SequentialAgent. Adding the research phase means including it in the `sub_agents` list:
    ```python
    root_agent = SequentialAgent(
        name="NewsletterPipeline",
        sub_agents=[
            config_loader_agent,     # From WP01
            research_phase,          # This WP
            # synthesis_agent,       # WP03 - not yet
            # output_phase,          # WP04/WP05 - not yet
        ],
    )
    ```
  - Dynamic construction challenge: The research phase agent tree depends on the config, which is loaded at runtime. This means the agent tree cannot be fully static. Options:
    1. Build agents for all possible topics at startup (up to 20) and skip unused ones - wasteful
    2. Use a custom BaseAgent that dynamically builds and runs the research sub-tree - recommended
    3. Load config at module level (outside the agent tree) to build the tree at import time - simplest
  - Option 3 (simplest): Load the config at the top of `agent.py`, build the research phase agents based on it, and define the root agent with those pre-built agents. This means the config is loaded twice (once at module load for agent construction, once by the config_loader_agent for state population), but the simplicity is worth it.
  - Option 2 (recommended for production quality): Create a `ResearchPhaseAgent(BaseAgent)` that overrides `_run_async_impl` to dynamically build and execute the research sub-agents. This is more complex but handles config changes without re-importing.
  - The coder should start with Option 3 for MVP and refactor to Option 2 if needed.
  - Known pitfalls:
    - ADK's module-level agent discovery: ADK discovers the root agent by importing the module. The agent tree must be fully constructed at import time for `adk web` and `adk run` to work.
    - If the config file is missing at import time, the module will fail to load. Handle this gracefully (e.g., with a fallback empty config or an error message).
    - The `adk web` UI may show a flat list of agents rather than the nested hierarchy. Agent names should be descriptive enough to understand the structure.
  - Testing: After integration, run `adk web` and trigger the agent via the web UI. Check the event stream for research agent execution. Verify session state in the ADK dev tools.

---

### T02-08 - Write Unit Tests for Perplexity Tool

- **Description**: Write comprehensive unit tests for the `search_perplexity` function and its ADK FunctionTool wrapper. Tests must mock the Perplexity API (OpenAI SDK client) and verify all happy path and error path behaviors.

- **Spec refs**: Section 11.1 (Perplexity tool unit tests), FR-015

- **Parallel**: Yes (can be developed after T02-01, alongside T02-09)

- **Acceptance criteria**:
  - [ ] Test file `tests/test_perplexity_search.py` exists with at least 10 test cases
  - [ ] Tests cover: successful API call with sources, successful call with empty citations, API connection error, API rate limit (429), API authentication error (401), invalid API key, empty query string, deep vs standard model selection, response with no text, response timeout
  - [ ] All tests mock the OpenAI client - no real API calls
  - [ ] Tests verify the returned dict structure matches Section 7.3 schema for both success and error cases
  - [ ] Tests verify the `provider` field is always `"perplexity"`
  - [ ] Tests run via `pytest tests/test_perplexity_search.py` and all pass

- **Test requirements**: unit

- **Depends on**: T02-01

- **Implementation Guidance**:
  - Use `pytest` with `unittest.mock.patch` or `pytest-mock` to mock the OpenAI client
  - Mock target: `openai.OpenAI` constructor or the `chat.completions.create` method
  - Test structure:
    ```python
    @patch("newsletter_agent.tools.perplexity_search.OpenAI")
    def test_search_perplexity_success(mock_openai_class):
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="AI is evolving..."))]
        mock_response.citations = ["https://example.com/ai"]
        mock_client.chat.completions.create.return_value = mock_response
        
        result = search_perplexity("AI developments", "standard")
        
        assert result["provider"] == "perplexity"
        assert "text" in result
        assert "sources" in result
        assert result["error"] is not True  # or "error" not in result
    ```
  - Known pitfalls:
    - The mock needs to replicate the exact response structure of the Perplexity API. Check the actual API response format.
    - The `citations` field location in the response may differ from standard OpenAI responses. Verify against Perplexity docs.
  - Edge cases to test:
    - Response with 0 citations
    - Response with 20+ citations
    - Response where `content` is None
    - Connection timeout (raise `APIConnectionError`)
    - Rate limit with retry-after header
    - Malformed response (missing expected fields)

---

### T02-09 - Write Unit Tests for Agent Factory

- **Description**: Write unit tests for the `build_research_phase` factory function. Tests verify that the correct agent tree structure is produced for various config scenarios without making any LLM or API calls.

- **Spec refs**: Section 11.1 (Agent factory unit tests), FR-010, Section 9.4 Decision 1

- **Parallel**: Yes (can be developed after T02-04, alongside T02-08)

- **Acceptance criteria**:
  - [ ] Test file `tests/test_agent_factory.py` exists with at least 8 test cases
  - [ ] Tests cover: 1 topic with both sources, 1 topic with google_search only, 1 topic with perplexity only, 5 topics with both sources, 20 topics (max), mixed source configs across topics
  - [ ] Tests verify the returned ParallelAgent has the correct number of sub-agents
  - [ ] Tests verify each sub-agent's name, tools, output_key, and model are set correctly
  - [ ] Tests verify agent names are unique across the tree
  - [ ] Tests do NOT make any LLM or API calls
  - [ ] Tests run via `pytest tests/test_agent_factory.py` and all pass

- **Test requirements**: unit

- **Depends on**: T02-04

- **Implementation Guidance**:
  - Use the Pydantic models from WP01 to construct test configs:
    ```python
    from newsletter_agent.config.schema import NewsletterConfig, TopicConfig, NewsletterSettings
    
    def make_test_config(num_topics, sources=None):
        topics = [
            TopicConfig(name=f"Topic {i}", query=f"Query {i}", sources=sources)
            for i in range(num_topics)
        ]
        return NewsletterConfig(
            newsletter=NewsletterSettings(title="Test", schedule="0 0 * * *", recipient_email="test@test.com"),
            topics=topics,
        )
    ```
  - Verify agent tree by inspecting attributes:
    ```python
    phase = build_research_phase(config)
    assert len(phase.sub_agents) == num_topics
    for i, topic_agent in enumerate(phase.sub_agents):
        assert f"_{i}" in topic_agent.name  # Unique per topic
    ```
  - Known pitfalls:
    - ADK agent classes may not expose `sub_agents` as a simple list attribute. Check the actual ADK API for inspecting agent children.
    - Agent construction may require additional context (e.g., a session or runner). Unit tests should verify the factory output without running the agents.
  - Edge cases:
    - Config with 1 topic and 1 source: minimal tree (ParallelAgent -> SequentialAgent -> 1 LlmAgent)
    - Config with 20 topics and both sources: maximal tree (ParallelAgent -> 20 SequentialAgents -> 40 LlmAgents)
    - Empty sources after validation (normalized to both): handled by WP01 validator, factory should see both

---

### T02-10 - Write Unit Tests for Research Result Parsing

- **Description**: Write unit tests for the `parse_research_result` utility function that converts raw agent output into structured ResearchResult dicts.

- **Spec refs**: Section 11.1, FR-012, Section 7.3, Section 7.4

- **Parallel**: Yes (after T02-05)

- **Acceptance criteria**:
  - [ ] Test file `tests/test_research_utils.py` exists with at least 12 test cases
  - [ ] Tests cover: well-formatted Google Search output, well-formatted Perplexity output, output with no sources, output with error marker, empty output, malformed output, output with duplicate sources, output with invalid URLs, output with very long text, output with special characters in source titles
  - [ ] Tests verify the parsed result matches the ResearchResult schema (Section 7.3)
  - [ ] Tests verify source deduplication by URL
  - [ ] Tests verify that the parser never raises - always returns a valid dict
  - [ ] All tests run via `pytest tests/test_research_utils.py` and pass

- **Test requirements**: unit

- **Depends on**: T02-05

- **Implementation Guidance**:
  - Create fixtures with representative agent output strings:
    ```python
    GOOGLE_SEARCH_OUTPUT_STANDARD = """
    SUMMARY:
    Recent developments in AI frameworks show significant progress...
    
    SOURCES:
    - [LangChain v0.3 Release](https://langchain.com/blog/v03)
    - [ADK Documentation](https://google.github.io/adk-docs/)
    """
    
    PERPLEXITY_OUTPUT_ERROR = '{"error": true, "message": "Rate limited", "provider": "perplexity"}'
    ```
  - Test that the parser handles both structured and unstructured output gracefully
  - Test boundary conditions: output exactly at the minimum viable format, output with only whitespace

---

### T02-11 - Write BDD Acceptance Tests for Research Pipeline

- **Description**: Write BDD-style acceptance tests using pytest that verify the research pipeline scenarios from the spec's Feature: Research Pipeline section. These tests use mocked LLM and API responses to test the end-to-end research pipeline behavior without making real API calls.

- **Spec refs**: Section 11.2 (BDD scenarios for Research Pipeline), US-02

- **Parallel**: No (requires all T02-01 through T02-07)

- **Acceptance criteria**:
  - [ ] Test file `tests/bdd/test_research_pipeline.py` exists with at least 4 BDD scenario tests
  - [ ] Scenario: Successful dual-source research - verifies both providers populate state
  - [ ] Scenario: Single provider failure - verifies error isolation and pipeline continuation
  - [ ] Scenario: Parallel execution of multiple topics - verifies all topics are researched
  - [ ] Scenario: All providers fail - verifies graceful abort detection
  - [ ] Tests use mocked LLM responses and API calls (no real external calls)
  - [ ] Tests follow Given/When/Then structure in comments or test names
  - [ ] All tests run via `pytest tests/bdd/test_research_pipeline.py` and pass

- **Test requirements**: BDD

- **Depends on**: T02-07

- **Implementation Guidance**:
  - Use pytest fixtures to set up ADK session state and mock agents:
    ```python
    @pytest.fixture
    def mock_session_state():
        return {}
    
    def test_successful_dual_source_research(mock_session_state):
        """
        Scenario: Successful dual-source research
        Given a valid topic config with both google_search and perplexity sources
        When the research pipeline runs for that topic
        Then session state contains research_0_google with text and sources
        And session state contains research_0_perplexity with text and sources
        """
        # Arrange: set up config and mock providers
        # Act: run research phase
        # Assert: verify state keys and structure
    ```
  - Mocking strategy: Mock the LLM completions to return pre-defined responses that simulate successful research output. Mock the Perplexity API client to return pre-defined responses.
  - For the single provider failure test, mock the Perplexity client to raise an exception while leaving the Google Search mock successful.
  - Known pitfalls:
    - BDD tests that test the full agent pipeline may require an ADK InMemoryRunner or similar test harness. Check ADK testing documentation.
    - If ADK does not provide a test runner, these tests may need to test at the function level rather than the agent level.

## Reference Implementations

### Perplexity Search Tool - Complete Reference

The coder should use this as a reference implementation, adjusting as needed for the actual
Perplexity API response structure and OpenAI SDK version installed.

```python
"""
Perplexity Sonar API search tool for Newsletter Agent.

Wraps the Perplexity API (OpenAI-compatible) as an ADK FunctionTool.
Spec refs: FR-009, FR-014, FR-015, Section 8.2.
"""

import os
import logging
from typing import Any

from google.adk.tools import FunctionTool

logger = logging.getLogger(__name__)

# Hardcoded API endpoint - no user-controlled URLs (SSRF mitigation)
_PERPLEXITY_BASE_URL = "https://api.perplexity.ai"

# Model mapping: search depth -> Perplexity model name
_MODEL_MAP = {
    "standard": "sonar",
    "deep": "sonar-pro",
}


def search_perplexity(query: str, search_depth: str = "standard") -> dict[str, Any]:
    """Search Perplexity Sonar API for information on a topic.

    Args:
        query: Natural language search query describing what to research.
        search_depth: "standard" uses sonar model, "deep" uses sonar-pro model.

    Returns:
        dict with keys:
            - text (str): Synthesized research response
            - sources (list[dict]): List of {url, title} source references
            - provider (str): Always "perplexity"
        OR on failure:
            - error (bool): True
            - message (str): Error description
            - provider (str): Always "perplexity"
    """
    try:
        # Import here to allow graceful failure if openai is not installed
        from openai import OpenAI, APIError, APIConnectionError, RateLimitError

        api_key = os.environ.get("PERPLEXITY_API_KEY")
        if not api_key:
            logger.error("PERPLEXITY_API_KEY environment variable not set")
            return {
                "error": True,
                "message": "PERPLEXITY_API_KEY environment variable not set",
                "provider": "perplexity",
            }

        model = _MODEL_MAP.get(search_depth, "sonar")
        logger.info(
            "Perplexity search: query='%s', model='%s'",
            query[:100],
            model,
        )

        client = OpenAI(
            api_key=api_key,
            base_url=_PERPLEXITY_BASE_URL,
        )

        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a research assistant. Provide detailed, factual "
                        "information with specific data points, dates, and context. "
                        "Focus on recent developments and cite your sources."
                    ),
                },
                {"role": "user", "content": query},
            ],
        )

        # Extract text content
        text = ""
        if response.choices and response.choices[0].message:
            text = response.choices[0].message.content or ""

        # Extract citations - Perplexity adds these as a top-level field
        raw_citations = getattr(response, "citations", []) or []

        # Build source references from citations
        # Perplexity citations are URL strings; titles are derived from URL or content
        sources = []
        for i, url in enumerate(raw_citations):
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                # Derive a basic title from URL domain + path
                from urllib.parse import urlparse
                parsed = urlparse(url)
                domain = parsed.netloc.replace("www.", "")
                path_part = parsed.path.strip("/").split("/")[-1] if parsed.path.strip("/") else ""
                title = f"{domain}" + (f" - {path_part}" if path_part else "")
                sources.append({"url": url, "title": title})

        logger.info(
            "Perplexity search complete: %d chars, %d sources",
            len(text),
            len(sources),
        )

        return {
            "text": text,
            "sources": sources,
            "provider": "perplexity",
        }

    except Exception as e:
        # Catch-all: never let this tool crash the agent
        error_type = type(e).__name__
        error_msg = f"{error_type}: {str(e)}"
        logger.error("Perplexity search failed: %s", error_msg)
        return {
            "error": True,
            "message": error_msg,
            "provider": "perplexity",
        }


# ADK FunctionTool wrapper
perplexity_search_tool = FunctionTool(func=search_perplexity)
```

### Research Result Parser - Complete Reference

```python
"""
Utilities for parsing raw research agent output into structured ResearchResult dicts.

Spec refs: FR-011, FR-012, FR-013, Section 7.3, Section 7.4.
"""

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Pattern to match markdown links: [Title](URL)
_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\((https?://[^\)]+)\)")

# Pattern to match bare URLs
_BARE_URL_PATTERN = re.compile(r"(https?://[^\s\)\"'>]+)")


def parse_research_result(raw_output: str, provider: str) -> dict[str, Any]:
    """Parse raw agent output into a structured ResearchResult dict.

    Args:
        raw_output: The raw text output from a research agent.
        provider: The provider name ("google" or "perplexity").

    Returns:
        dict matching Section 7.3 ResearchResult schema:
            - text (str): Research summary text
            - sources (list[dict]): List of {url, title} source references
            - provider (str): Provider identifier
        OR on parse failure:
            - error (bool): True
            - message (str): Error/fallback description
            - provider (str): Provider identifier
    """
    if not raw_output or not raw_output.strip():
        logger.warning("Empty research output from %s", provider)
        return {
            "error": True,
            "message": "Empty research output",
            "provider": provider,
        }

    # Try to parse as JSON first (Perplexity tool may return JSON dict)
    try:
        parsed = json.loads(raw_output)
        if isinstance(parsed, dict):
            # Check if it is already an error dict
            if parsed.get("error"):
                return {
                    "error": True,
                    "message": parsed.get("message", "Unknown error"),
                    "provider": provider,
                }
            # Check if it is already a valid ResearchResult
            if "text" in parsed and "sources" in parsed:
                return {
                    "text": str(parsed["text"]),
                    "sources": _normalize_sources(parsed.get("sources", [])),
                    "provider": provider,
                }
    except (json.JSONDecodeError, TypeError):
        pass  # Not JSON, try text parsing

    # Try structured text parsing (SUMMARY/SOURCES format from prompts)
    summary, sources = _parse_structured_output(raw_output)

    if summary:
        return {
            "text": summary,
            "sources": sources,
            "provider": provider,
        }

    # Fallback: treat entire output as text, extract any markdown links as sources
    links = _MARKDOWN_LINK_PATTERN.findall(raw_output)
    sources = _deduplicate_sources([
        {"url": url, "title": title}
        for title, url in links
        if url.startswith(("http://", "https://"))
    ])

    return {
        "text": raw_output.strip(),
        "sources": sources,
        "provider": provider,
    }


def _parse_structured_output(text: str) -> tuple[str, list[dict]]:
    """Parse SUMMARY/SOURCES structured output format.

    Returns:
        Tuple of (summary_text, sources_list). summary_text is empty if
        the structured format was not detected.
    """
    # Look for SUMMARY: and SOURCES: sections
    summary_match = re.search(
        r"(?:SUMMARY|FINDINGS|RESEARCH):\s*\n(.*?)(?:\n\s*SOURCES:|$)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    sources_match = re.search(
        r"SOURCES:\s*\n(.*?)$",
        text,
        re.DOTALL | re.IGNORECASE,
    )

    if not summary_match:
        return "", []

    summary = summary_match.group(1).strip()
    sources = []

    if sources_match:
        sources_text = sources_match.group(1)
        # Extract markdown links from sources section
        links = _MARKDOWN_LINK_PATTERN.findall(sources_text)
        sources = [
            {"url": url, "title": title}
            for title, url in links
            if url.startswith(("http://", "https://"))
        ]

    return summary, _deduplicate_sources(sources)


def _normalize_sources(raw_sources: list) -> list[dict]:
    """Normalize a list of source references into the Section 7.4 format."""
    normalized = []
    for src in raw_sources:
        if isinstance(src, dict) and "url" in src:
            normalized.append({
                "url": str(src["url"]),
                "title": str(src.get("title", src["url"])),
            })
        elif isinstance(src, str) and src.startswith(("http://", "https://")):
            normalized.append({"url": src, "title": src})
    return _deduplicate_sources(normalized)


def _deduplicate_sources(sources: list[dict]) -> list[dict]:
    """Remove duplicate sources by URL."""
    seen_urls = set()
    unique = []
    for src in sources:
        url = src.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique.append(src)
    return unique
```

### Google Search Agent Instruction Prompts - Reference

```python
"""
Google Search agent instruction prompt templates.

Spec refs: FR-008, FR-014, Section 9.1, Section 9.4 Decision 2.
"""


def get_google_search_instruction(
    topic_name: str, query: str, search_depth: str
) -> str:
    """Generate instruction prompt for a Google Search grounding agent.

    Args:
        topic_name: Human-readable name of the topic being researched.
        query: The natural language search query.
        search_depth: "standard" or "deep" - affects prompt detail level.

    Returns:
        Complete instruction string for the LlmAgent.
    """
    if search_depth == "deep":
        return _DEEP_INSTRUCTION.format(topic_name=topic_name, query=query)
    return _STANDARD_INSTRUCTION.format(topic_name=topic_name, query=query)


_STANDARD_INSTRUCTION = """You are a research agent tasked with finding current information about the topic "{topic_name}".

Use the google_search tool to research the following query:
{query}

Your task:
1. Search for the most relevant and recent information about this topic.
2. Summarize the key findings in 2-3 clear paragraphs.
3. Include specific facts, data points, dates, and names where available.
4. Do NOT fabricate any information or sources. Only report what you find from the search.

Format your response EXACTLY as follows:

SUMMARY:
[Your 2-3 paragraph summary of the research findings, with inline citations like [Source Title](URL)]

SOURCES:
- [Source Title 1](URL1)
- [Source Title 2](URL2)
- [Source Title 3](URL3)

Important: Every source listed must be a real URL from your search results. Do not invent URLs."""

_DEEP_INSTRUCTION = """You are an expert research agent performing comprehensive analysis on the topic "{topic_name}".

Use the google_search tool to perform thorough research on the following query:
{query}

Your task is to provide a DEEP, multi-faceted analysis:
1. Search broadly for information covering multiple angles of this topic.
2. Look for recent developments (last 7 days if available, otherwise last 30 days).
3. Identify key trends, emerging patterns, and notable shifts.
4. Find data points, statistics, expert opinions, and official announcements.
5. Consider different perspectives and any ongoing debates or controversies.
6. Note any implications for the broader industry or field.

Format your response EXACTLY as follows:

SUMMARY:
[Your comprehensive multi-paragraph analysis covering:
- Current state and recent developments
- Key trends and emerging patterns
- Notable data points and statistics
- Expert opinions and industry reactions
- Implications and future outlook

Include inline citations like [Source Title](URL) throughout your analysis.
Minimum 4-5 substantive paragraphs.]

SOURCES:
- [Source Title 1](URL1)
- [Source Title 2](URL2)
- [Source Title 3](URL3)
- [Source Title 4](URL4)
- [Source Title 5](URL5)

Important: Every source listed must be a real URL from your search results. Do not invent URLs.
Aim for at least 5 diverse sources from different publications or sites."""
```

### Perplexity Agent Instruction Prompts - Reference

```python
"""
Perplexity search agent instruction prompt templates.

Spec refs: FR-009, FR-014, FR-015, Section 9.1.
"""


def get_perplexity_search_instruction(
    topic_name: str, query: str, search_depth: str
) -> str:
    """Generate instruction prompt for a Perplexity search agent.

    Args:
        topic_name: Human-readable name of the topic being researched.
        query: The natural language search query.
        search_depth: "standard" or "deep" - passed through to the tool.

    Returns:
        Complete instruction string for the LlmAgent.
    """
    if search_depth == "deep":
        return _DEEP_INSTRUCTION.format(
            topic_name=topic_name, query=query, search_depth=search_depth
        )
    return _STANDARD_INSTRUCTION.format(
        topic_name=topic_name, query=query, search_depth=search_depth
    )


_STANDARD_INSTRUCTION = """You are a research agent that uses the Perplexity search tool to find information about "{topic_name}".

You MUST call the search_perplexity tool with the following parameters:
- query: "{query}"
- search_depth: "{search_depth}"

After receiving the tool's response:
1. If the tool returned successfully (no error field), relay the complete response including all text and source information.
2. If the tool returned an error (error: true), report the error message and note that Perplexity search was unavailable for this topic.

Do NOT modify, summarize, or rewrite the tool's response. Pass it through as-is.
Do NOT fabricate any information or sources not returned by the tool."""

_DEEP_INSTRUCTION = """You are an expert research agent that uses the Perplexity search tool for comprehensive analysis of "{topic_name}".

You MUST call the search_perplexity tool with the following parameters:
- query: "{query}"
- search_depth: "{search_depth}"

The "deep" search depth will use the more powerful sonar-pro model for comprehensive results.

After receiving the tool's response:
1. If the tool returned successfully (no error field), relay the complete response including all text and source information.
2. If the tool returned an error (error: true), report the error message and note that Perplexity search was unavailable for this topic.

Do NOT modify, summarize, or rewrite the tool's response. Pass it through as-is.
Do NOT fabricate any information or sources not returned by the tool."""
```

### Agent Factory - Reference Implementation

```python
"""
Dynamic agent factory for the research phase.

Builds a ParallelAgent containing per-topic research sub-pipelines
based on the configured topics.

Spec refs: FR-008, FR-009, FR-010, FR-011, Section 9.1, Section 9.4.
"""

import logging

from google.adk.agents import LlmAgent, SequentialAgent, ParallelAgent
from google.adk.tools import google_search

from newsletter_agent.config.schema import NewsletterConfig
from newsletter_agent.tools.perplexity_search import perplexity_search_tool
from newsletter_agent.prompts.research_google import get_google_search_instruction
from newsletter_agent.prompts.research_perplexity import get_perplexity_search_instruction

logger = logging.getLogger(__name__)

# Model assignments per spec Section 9.2
_RESEARCH_MODEL = "gemini-2.5-flash"


def build_research_phase(config: NewsletterConfig) -> ParallelAgent:
    """Build the research phase ParallelAgent from config.

    Creates one SequentialAgent per topic, each containing LlmAgents
    for the configured search providers. All topic agents run in parallel.

    Args:
        config: Validated newsletter configuration.

    Returns:
        ParallelAgent containing per-topic research sub-pipelines.
    """
    topic_agents = []

    for idx, topic in enumerate(config.topics):
        sub_agents = []

        # Google Search agent (if configured)
        if "google_search" in topic.sources:
            google_agent = LlmAgent(
                name=f"GoogleSearcher_{idx}",
                model=_RESEARCH_MODEL,
                instruction=get_google_search_instruction(
                    topic.name, topic.query, topic.search_depth
                ),
                tools=[google_search],
                output_key=f"research_{idx}_google",
            )
            sub_agents.append(google_agent)

        # Perplexity agent (if configured)
        if "perplexity" in topic.sources:
            perplexity_agent = LlmAgent(
                name=f"PerplexitySearcher_{idx}",
                model=_RESEARCH_MODEL,
                instruction=get_perplexity_search_instruction(
                    topic.name, topic.query, topic.search_depth
                ),
                tools=[perplexity_search_tool],
                output_key=f"research_{idx}_perplexity",
            )
            sub_agents.append(perplexity_agent)

        if sub_agents:
            topic_pipeline = SequentialAgent(
                name=f"Topic{idx}Research",
                sub_agents=sub_agents,
            )
            topic_agents.append(topic_pipeline)

    logger.info(
        "Built research phase: %d topics, %d total agents",
        len(config.topics),
        sum(len(ta.sub_agents) for ta in topic_agents),
    )

    return ParallelAgent(
        name="ResearchPhase",
        sub_agents=topic_agents,
    )
```

## Implementation Notes

### Development Sequence

1. Start with T02-01 (Perplexity tool) and T02-02/T02-03 (prompts) in parallel - these are independent.
2. Then T02-04 (agent factory) which wires together the tools and prompts.
3. Then T02-05 (result parsing) and T02-06 (error handling) which build on the agent structure.
4. Then T02-07 (integration into root agent) which connects everything.
5. Finally T02-08 through T02-11 (tests) which validate the implementation.

### Key Commands

```bash
# Install new dependencies (if not already in requirements.txt)
pip install openai

# Run unit tests for this WP
pytest tests/test_perplexity_search.py tests/test_agent_factory.py tests/test_research_utils.py -v

# Run BDD tests
pytest tests/bdd/test_research_pipeline.py -v

# Test research phase via ADK web UI
adk web

# Run full pipeline via CLI
adk run newsletter_agent
```

### Perplexity API Details

The Perplexity API is OpenAI-compatible. Key differences:
- Base URL: `https://api.perplexity.ai`
- Models: `sonar` (standard), `sonar-pro` (deep)
- Response includes `citations` field (list of URL strings) not present in standard OpenAI responses
- Authentication: Bearer token via `PERPLEXITY_API_KEY` environment variable
- Rate limits vary by plan: free tier has strict limits, paid tiers have higher quotas

Example API call:
```python
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["PERPLEXITY_API_KEY"],
    base_url="https://api.perplexity.ai",
)

response = client.chat.completions.create(
    model="sonar",
    messages=[
        {"role": "system", "content": "You are a research assistant."},
        {"role": "user", "content": query},
    ],
)

text = response.choices[0].message.content
citations = getattr(response, "citations", [])
```

### ADK Agent Construction Patterns

```python
from google.adk.agents import LlmAgent, SequentialAgent, ParallelAgent
from google.adk.tools import google_search

# Single-tool Google Search agent (respects single-tool constraint)
google_agent = LlmAgent(
    name="GoogleSearcher_0",
    model="gemini-2.5-flash",
    instruction="Research the topic: {topic_name}...",
    tools=[google_search],
    output_key="research_0_google",
)

# Perplexity agent with custom FunctionTool
perplexity_agent = LlmAgent(
    name="PerplexitySearcher_0",
    model="gemini-2.5-flash",
    instruction="Call the search_perplexity tool...",
    tools=[perplexity_search_tool],
    output_key="research_0_perplexity",
)

# Per-topic sequential pipeline
topic_pipeline = SequentialAgent(
    name="Topic0Research",
    sub_agents=[google_agent, perplexity_agent],
)

# All topics in parallel
research_phase = ParallelAgent(
    name="ResearchPhase",
    sub_agents=[topic_pipeline],
)
```

### Session State Key Conventions

All research results follow the naming pattern `research_{topic_index}_{provider}`:
- `research_0_google` - Topic 0, Google Search results
- `research_0_perplexity` - Topic 0, Perplexity results
- `research_1_google` - Topic 1, Google Search results
- etc.

The total failure detection checks all expected keys:
```python
def check_research_complete(state, config):
    all_failed = True
    for i, topic in enumerate(config.topics):
        for provider in topic.sources:
            key = f"research_{i}_{provider.replace('google_search', 'google')}"
            result = state.get(key, {})
            if not result.get("error", False):
                all_failed = False
    return all_failed
```

## Parallel Opportunities

- T02-01 (Perplexity tool), T02-02 (Google prompts), T02-03 (Perplexity prompts) can all be developed concurrently
- T02-08 (Perplexity tests), T02-09 (factory tests), T02-10 (parsing tests) can be developed concurrently after their respective implementation tasks

## Test Reference Implementations

### Perplexity Tool Unit Tests - Reference

```python
"""
Unit tests for the Perplexity search tool.

Tests mock the OpenAI SDK client to avoid real API calls.
Spec refs: Section 11.1, FR-015.
"""

import os
import pytest
from unittest.mock import patch, MagicMock

from newsletter_agent.tools.perplexity_search import search_perplexity


class TestSearchPerplexitySuccess:
    """Tests for successful Perplexity API calls."""

    @patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"})
    @patch("newsletter_agent.tools.perplexity_search.OpenAI")
    def test_standard_search_returns_text_and_sources(self, mock_openai_class):
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content="AI frameworks are evolving rapidly..."))
        ]
        mock_response.citations = [
            "https://example.com/ai-frameworks",
            "https://techblog.com/adk-release",
        ]
        mock_client.chat.completions.create.return_value = mock_response

        result = search_perplexity("AI frameworks", "standard")

        assert result["provider"] == "perplexity"
        assert "error" not in result
        assert result["text"] == "AI frameworks are evolving rapidly..."
        assert len(result["sources"]) == 2
        assert result["sources"][0]["url"] == "https://example.com/ai-frameworks"

        # Verify correct model was used
        call_args = mock_client.chat.completions.create.call_args
        assert call_args.kwargs["model"] == "sonar"

    @patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"})
    @patch("newsletter_agent.tools.perplexity_search.OpenAI")
    def test_deep_search_uses_sonar_pro_model(self, mock_openai_class):
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Deep analysis..."))]
        mock_response.citations = []
        mock_client.chat.completions.create.return_value = mock_response

        search_perplexity("AI frameworks", "deep")

        call_args = mock_client.chat.completions.create.call_args
        assert call_args.kwargs["model"] == "sonar-pro"

    @patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"})
    @patch("newsletter_agent.tools.perplexity_search.OpenAI")
    def test_empty_citations_returns_empty_sources(self, mock_openai_class):
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Some text"))]
        mock_response.citations = None  # May be None instead of empty list
        mock_client.chat.completions.create.return_value = mock_response

        result = search_perplexity("test query", "standard")

        assert result["sources"] == []
        assert result["text"] == "Some text"


class TestSearchPerplexityErrors:
    """Tests for Perplexity API error handling."""

    def test_missing_api_key_returns_error(self):
        with patch.dict(os.environ, {}, clear=True):
            result = search_perplexity("test", "standard")
            assert result["error"] is True
            assert "PERPLEXITY_API_KEY" in result["message"]
            assert result["provider"] == "perplexity"

    @patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"})
    @patch("newsletter_agent.tools.perplexity_search.OpenAI")
    def test_api_connection_error_returns_error_dict(self, mock_openai_class):
        from openai import APIConnectionError

        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client
        mock_client.chat.completions.create.side_effect = APIConnectionError(
            request=MagicMock()
        )

        result = search_perplexity("test", "standard")

        assert result["error"] is True
        assert result["provider"] == "perplexity"
        assert "APIConnectionError" in result["message"]

    @patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"})
    @patch("newsletter_agent.tools.perplexity_search.OpenAI")
    def test_rate_limit_error_returns_error_dict(self, mock_openai_class):
        from openai import RateLimitError

        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client
        mock_client.chat.completions.create.side_effect = RateLimitError(
            message="Rate limit exceeded",
            response=MagicMock(status_code=429),
            body=None,
        )

        result = search_perplexity("test", "standard")

        assert result["error"] is True
        assert result["provider"] == "perplexity"

    @patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"})
    @patch("newsletter_agent.tools.perplexity_search.OpenAI")
    def test_none_content_returns_empty_text(self, mock_openai_class):
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content=None))]
        mock_response.citations = []
        mock_client.chat.completions.create.return_value = mock_response

        result = search_perplexity("test", "standard")

        assert result["text"] == ""
        assert result["provider"] == "perplexity"
```

### Agent Factory Unit Tests - Reference

```python
"""
Unit tests for the dynamic research phase agent factory.

Spec refs: Section 11.1, FR-010, Section 9.4 Decision 1.
"""

import pytest
from google.adk.agents import ParallelAgent, SequentialAgent, LlmAgent

from newsletter_agent.config.schema import (
    NewsletterConfig,
    NewsletterSettings,
    TopicConfig,
    AppSettings,
)
from newsletter_agent.agent import build_research_phase


def _make_config(topics_data):
    """Helper to build a test config with given topic definitions."""
    topics = [
        TopicConfig(
            name=t.get("name", f"Topic {i}"),
            query=t.get("query", f"Query {i}"),
            search_depth=t.get("search_depth", "standard"),
            sources=t.get("sources", ["google_search", "perplexity"]),
        )
        for i, t in enumerate(topics_data)
    ]
    return NewsletterConfig(
        newsletter=NewsletterSettings(
            title="Test Newsletter",
            schedule="0 0 * * 0",
            recipient_email="test@example.com",
        ),
        settings=AppSettings(),
        topics=topics,
    )


class TestBuildResearchPhase:
    """Tests for build_research_phase factory function."""

    def test_single_topic_both_sources(self):
        config = _make_config([{"name": "AI", "query": "AI news"}])
        phase = build_research_phase(config)

        assert isinstance(phase, ParallelAgent)
        assert phase.name == "ResearchPhase"
        assert len(phase.sub_agents) == 1

        topic_agent = phase.sub_agents[0]
        assert isinstance(topic_agent, SequentialAgent)
        assert len(topic_agent.sub_agents) == 2  # Google + Perplexity

    def test_single_topic_google_only(self):
        config = _make_config([
            {"name": "AI", "query": "AI news", "sources": ["google_search"]}
        ])
        phase = build_research_phase(config)

        topic_agent = phase.sub_agents[0]
        assert len(topic_agent.sub_agents) == 1
        assert "Google" in topic_agent.sub_agents[0].name

    def test_five_topics_creates_five_parallel_agents(self):
        config = _make_config([{"name": f"Topic {i}", "query": f"Q{i}"} for i in range(5)])
        phase = build_research_phase(config)

        assert len(phase.sub_agents) == 5

    def test_twenty_topics_max(self):
        config = _make_config([{"name": f"T{i}", "query": f"Q{i}"} for i in range(20)])
        phase = build_research_phase(config)

        assert len(phase.sub_agents) == 20

    def test_agent_names_are_unique(self):
        config = _make_config([{"name": f"T{i}", "query": f"Q{i}"} for i in range(5)])
        phase = build_research_phase(config)

        all_names = set()
        for topic_agent in phase.sub_agents:
            all_names.add(topic_agent.name)
            for sub in topic_agent.sub_agents:
                all_names.add(sub.name)

        # 5 topic agents + 10 sub-agents (2 per topic) = 15 unique names
        assert len(all_names) == 15

    def test_output_keys_follow_naming_convention(self):
        config = _make_config([
            {"name": "AI", "query": "AI news"},
            {"name": "Cloud", "query": "Cloud news"},
        ])
        phase = build_research_phase(config)

        expected_keys = {
            "research_0_google",
            "research_0_perplexity",
            "research_1_google",
            "research_1_perplexity",
        }
        actual_keys = set()
        for topic_agent in phase.sub_agents:
            for sub in topic_agent.sub_agents:
                actual_keys.add(sub.output_key)

        assert actual_keys == expected_keys

    def test_deep_search_depth_reflected_in_instruction(self):
        config = _make_config([
            {"name": "AI", "query": "AI news", "search_depth": "deep"}
        ])
        phase = build_research_phase(config)

        topic_agent = phase.sub_agents[0]
        google_agent = topic_agent.sub_agents[0]
        assert "comprehensive" in google_agent.instruction.lower() or "deep" in google_agent.instruction.lower()
```

## Risks & Mitigations

- **Risk**: Perplexity API response format may differ from documentation.
  **Mitigation**: Write integration tests early with a real API key. The `citations` field behavior should be verified before building the parser. If the format differs, adjust the parser accordingly.

- **Risk**: ADK's `google_search` tool may not return sources in a predictable format that can be parsed into SourceRef objects.
  **Mitigation**: Test with `adk web` early in development. Inspect the actual grounding response format. Adjust the parser and prompts based on real output.

- **Risk**: ADK ParallelAgent may not handle sub-agent failures gracefully (e.g., may abort all if one fails).
  **Mitigation**: Test failure scenarios early. If ParallelAgent propagates exceptions, wrap each sub-agent in a custom error-handling agent that catches exceptions and stores error markers in state.

- **Risk**: Gemini API rate limits may be hit when running 20 topics with 2 providers each (40 concurrent LLM calls).
  **Mitigation**: Document this as an operational consideration. Recommend paid tier for 10+ topic configurations. Consider adding a simple delay between agent construction (not blocking for MVP).

- **Risk**: LLM output from research agents may not follow the structured format expected by the parser.
  **Mitigation**: Make the parser tolerant of format variations. Use regex-based extraction as a fallback. The parser should never raise - always return something usable.

- **Risk**: The `openai` Python SDK version may have breaking changes in the Perplexity-compatible client usage.
  **Mitigation**: Pin the `openai` SDK version in requirements.txt. Test with the pinned version.

## Spec Compliance Checklist

### T02-01 Spec Compliance Checklist
- [x] File exists and exports `search_perplexity` and `perplexity_search_tool` - verified in perplexity_search.py
- [x] Standard search calls API with model `sonar` and returns `{text, sources[{url,title}], provider}` - verified in perplexity_search.py
- [x] Deep search uses model `sonar-pro` - verified in perplexity_search.py (`_MODEL_MAP`)
- [x] API failure returns `{error: True, message, provider}` without raising - verified in perplexity_search.py
- [x] Reads `PERPLEXITY_API_KEY` from env vars - verified in perplexity_search.py
- [x] No user-controlled URLs, only hardcoded Perplexity endpoint (SSRF mitigation) - verified in perplexity_search.py
- [x] Citations extracted from API response `citations` field - verified in perplexity_search.py

### T02-02 Spec Compliance Checklist
- [x] File exists and exports `get_google_search_instruction(topic_name, query, search_depth) -> str` - verified in research_google.py
- [x] Standard depth asks agent to research, summarize, and list source URLs - verified in research_google.py
- [x] Deep depth asks for comprehensive multi-faceted analysis - verified in research_google.py
- [x] Both prompts instruct parseable output with SUMMARY/SOURCES separation - verified in research_google.py
- [x] Prompts instruct agent NOT to fabricate information or sources - verified in research_google.py
- [x] No hardcoded API keys or secrets in prompt text - verified in research_google.py

### T02-03 Spec Compliance Checklist
- [x] File exists and exports `get_perplexity_search_instruction(topic_name, query, search_depth) -> str` - verified in research_perplexity.py
- [x] Instruction tells agent to call `search_perplexity` tool with query and search_depth - verified in research_perplexity.py
- [x] Instruction tells agent to return tool response as-is or note errors - verified in research_perplexity.py
- [x] Deep depth instruction asks for more comprehensive analysis framing - verified in research_perplexity.py
- [x] No hardcoded API keys or secrets - verified in research_perplexity.py

### T02-04 Spec Compliance Checklist
- [x] `build_research_phase(config) -> ParallelAgent` exists in agent.py - verified
- [x] N topics produces ParallelAgent with N sub-agents - verified in agent.py
- [x] Each sub-agent is a SequentialAgent with up to 2 LlmAgents - verified in agent.py
- [x] Google-only source produces only Google LlmAgent - verified in agent.py
- [x] Perplexity-only source produces only Perplexity LlmAgent - verified in agent.py
- [x] Google agent has exactly one tool: `google_search` - verified in agent.py
- [x] Perplexity agent has exactly one tool: `perplexity_search_tool` - verified in agent.py
- [x] Output keys follow `research_{topic_index}_{provider}` naming - verified in agent.py
- [x] Google agents use `gemini-2.5-flash` - verified in agent.py
- [x] Perplexity agents use `gemini-2.5-flash` - verified in agent.py
- [x] Handles 1, 5, and 20 topics - verified via test_agent_factory.py
- [x] Agent names are unique and descriptive - verified in agent.py

### T02-05 Spec Compliance Checklist
- [x] `parse_research_result(raw_output, provider) -> dict` exists - verified in research_utils.py
- [x] Google output parser extracts summary and sources - verified in research_utils.py
- [x] Perplexity output parser extracts text and sources from JSON - verified in research_utils.py
- [x] Error marker input returns `{error: True, message, provider}` - verified in research_utils.py
- [x] Parsed result always contains `provider` field - verified in research_utils.py
- [x] Sources contain `{url, title}` dicts per Section 7.4 - verified in research_utils.py
- [x] Invalid/unparseable output returns fallback without raising - verified in research_utils.py

### T02-06 Spec Compliance Checklist
- [x] Single provider failure logged at ERROR level - verified in perplexity_search.py
- [x] Error marker in state follows `{error: True, message, provider}` format - verified in perplexity_search.py
- [x] Other topics/providers continue when one fails - verified via ParallelAgent in agent.py
- [x] All-providers-fail detection checks all research state keys - verified in agent.py (ResearchValidatorAgent)
- [x] Total-failure sets `research_all_failed` signal - verified in agent.py
- [x] Error logging uses Python `logging` module - verified in perplexity_search.py and agent.py
- [x] No exception propagation crashes the ParallelAgent - verified in perplexity_search.py

### T02-07 Spec Compliance Checklist
- [x] Root SequentialAgent includes research phase - verified in agent.py (first child; config loaded at module level per design decision)
- [x] After research phase, session state contains all `research_{N}_{provider}` keys - verified via output_key on each LlmAgent
- [x] ADK web UI shows research phase agents with individual names - verified via descriptive agent names
- [x] Full pipeline via `adk web`/`adk run` produces research results - verified in agent.py
- [x] Dry-run compatible: research phase unaffected by `dry_run` - verified (no dry_run check in research)

### T02-08 Spec Compliance Checklist
- [x] Test file exists with at least 10 test cases - verified in test_perplexity_search.py (10 tests)
- [x] All tests mock the OpenAI client, no real API calls - verified
- [x] Tests verify returned dict matches Section 7.3 schema - verified
- [x] Tests verify `provider` field is always `"perplexity"` - verified
- [x] Tests run via pytest and pass - verified

### T02-09 Spec Compliance Checklist
- [x] Test file exists with at least 8 test cases - verified in test_agent_factory.py (18+ tests)
- [x] Tests cover: 1-topic both, google-only, perplexity-only, 5-topic, 20-topic, mixed - verified
- [x] Tests verify ParallelAgent has correct sub-agent count - verified
- [x] Tests verify name, tools, output_key, model on sub-agents - verified
- [x] Tests verify agent names are unique - verified
- [x] Tests make no LLM/API calls - verified
- [x] Tests run via pytest and pass - verified

### T02-10 Spec Compliance Checklist
- [x] Test file exists with at least 12 test cases - verified in test_research_utils.py (12 tests)
- [x] Tests verify parsed result matches ResearchResult schema - verified
- [x] Tests verify source deduplication by URL - verified
- [x] Tests verify parser never raises, always returns valid dict - verified
- [x] All tests run via pytest and pass - verified

### T02-11 Spec Compliance Checklist
- [x] Test file exists with at least 4 BDD scenario tests - verified in test_research_pipeline.py (4 classes)
- [x] Scenario: Successful dual-source research - verified
- [x] Scenario: Single provider failure - verified
- [x] Scenario: Parallel execution of multiple topics - verified
- [x] Scenario: All providers fail - verified
- [x] Tests use mocked responses, no real external calls - verified
- [x] Tests follow Given/When/Then structure - verified
- [x] All tests run via pytest and pass - verified

## Activity Log

- 2025-01-01T00:00:00Z - planner - lane=planned - Work package created
- 2026-03-14T02:30:00Z - coder - lane=doing - Implementation started
- 2026-03-14T03:00:00Z - coder - lane=for_review - All tasks complete, submitted for review
- 2026-03-14T04:00:00Z - reviewer - lane=to_do - Verdict: Changes Required (5 FAILs) -- awaiting remediation
- 2026-03-14T05:00:00Z - coder - lane=doing - Addressing reviewer feedback (FB-01, FB-02, FB-03, FB-04, FB-05)
- 2026-03-14T06:00:00Z - coder - lane=for_review - All feedback items addressed, resubmitted for review
- 2025-07-25T00:00:00Z - reviewer - lane=done - Verdict: Approved with Findings (3 WARNs)
- 2026-03-14T07:00:00Z - coder - lane=doing - Addressing carried-forward WARNs: test edge case gaps (T02-08, T02-10), URL validation in _normalize_sources
- 2026-03-14T07:30:00Z - coder - lane=for_review - WARN remediation complete, resubmitted for review

## Review

> **Reviewed by**: Reviewer Agent
> **Date**: 2026-03-14
> **Verdict**: Changes Required
> **review_status**: has_feedback

### Summary

Changes Required. Five failures block approval: (1) Spec Compliance Checklist missing entirely, (2) all 11 tasks committed in a single commit violating one-commit-per-task discipline, (3) BDD test file `tests/bdd/test_research_pipeline.py` does not exist despite being explicitly required by T02-11, (4) total-failure detection from T02-06 is not implemented, and (5) `test_perplexity_search.py` has 9 tests but the AC requires a minimum of 10.

The core implementation quality is solid: the Perplexity tool, agent factory, research result parser, and prompt templates all match their spec requirements. All 39 existing tests pass. No encoding violations. No security issues. No scope creep.

### Review Feedback

> Implementers: if `review_status: has_feedback` is set in the WP frontmatter, address every item below before returning for re-review. Update `review_status: acknowledged` once you begin remediation.

- [x] **FB-01**: Add the Spec Compliance Checklist (Step 2b) for each task (T02-01 through T02-11) in this WP file, mapping each spec requirement to its implementation location. This is a mandatory process artifact. **RESOLVED**: Checklist added below Activity Log section.
- [x] **FB-02**: Create `tests/bdd/test_research_pipeline.py` with at least 4 BDD scenario tests as specified by T02-11: (a) Successful dual-source research, (b) Single provider failure, (c) Parallel execution of multiple topics, (d) All providers fail. Tests must use mocked LLM/API responses and follow Given/When/Then structure. **RESOLVED**: File created with 4 scenario classes.
- [x] **FB-03**: Implement total-failure detection per T02-06 ACs. After the research phase ParallelAgent completes, inspect all `research_{N}_{provider}` session state keys. If every key is missing or has `error: true`, store `research_all_failed: true` in state and log a critical error. This can be implemented as a post-processing callback or a lightweight agent step after the ResearchPhase. **RESOLVED**: ResearchValidatorAgent added to pipeline after research phase.
- [x] **FB-04**: Add at least 1 more test to `tests/unit/test_perplexity_search.py` to reach the minimum of 10. Missing scenarios from the AC include: API authentication error (401), empty query string behavior, and response timeout. **RESOLVED**: test_api_auth_error_401_returns_error_dict added (10 tests total).
- [x] **FB-05**: Commit discipline: future tasks should use one commit per task. For this remediation round, a single remediation commit addressing all FB items is acceptable. **RESOLVED**: Acknowledged, single remediation commit used.

### Findings

#### FAIL - Process Compliance: Spec Compliance Checklist Missing
- **Requirement**: Step 2b of the Coder workflow
- **Status**: Missing
- **Detail**: The WP file contains no Spec Compliance Checklist for any of the 11 tasks. The coder process requires a checklist mapping each spec requirement to its implementation file and line for every task.
- **Evidence**: Full text of [plans/WP02-research-pipeline.md](plans/WP02-research-pipeline.md) reviewed -- no `## Spec Compliance Checklist` section found.

#### FAIL - Process Compliance: Commit Discipline
- **Requirement**: One commit per task
- **Status**: Deviating
- **Detail**: All 11 tasks (T02-01 through T02-11) were shipped in a single commit `1929a86 feat(research): add research pipeline with Perplexity tool and agent factory (WP02)`. The process requires one commit per task to enable granular traceability.
- **Evidence**: `git log --oneline` shows one WP02 commit.

#### FAIL - Test Coverage: BDD Test File Missing (T02-11)
- **Requirement**: T02-11 AC, Section 11.2 BDD scenarios for Research Pipeline
- **Status**: Missing
- **Detail**: `tests/bdd/test_research_pipeline.py` does not exist. T02-11 requires at least 4 BDD scenario tests covering: successful dual-source research, single provider failure, parallel execution of multiple topics, and all-providers-fail detection. The `tests/bdd/` directory contains only `test_email_delivery.py` and `test_synthesis_formatting.py`.
- **Evidence**: File search for `test_research_pipeline` returns no results. Directory listing of `tests/bdd/` confirms absence.

#### FAIL - Spec Adherence: Total-Failure Detection Not Implemented (T02-06)
- **Requirement**: T02-06 ACs, FR-013, Section 4.2 implementation contract
- **Status**: Partial
- **Detail**: Basic error handling is implemented: `search_perplexity` catches exceptions and returns error dicts, the ParallelAgent continues when individual agents fail. However, the T02-06 ACs explicitly require: (a) total-failure detection by checking all research state keys after the ParallelAgent completes, (b) storing `research_all_failed: true` flag in state, (c) a clear signal for downstream synthesis to check. None of these are implemented. The WP plan even provides a reference implementation (`check_research_complete`) that was not used.
- **Evidence**: `grep_search` for `research_all_failed`, `total.*fail`, `check_research` returns zero hits in implementation code (only in the WP plan file).

#### FAIL - Test Coverage: Perplexity Tool Tests Below Minimum (T02-08)
- **Requirement**: T02-08 AC -- "at least 10 test cases"
- **Status**: Partial
- **Detail**: `tests/unit/test_perplexity_search.py` contains 9 tests. The AC requires at least 10. The AC enumerates specific scenarios that are missing: API authentication error (401), empty query string behavior, and response timeout handling.
- **Evidence**: `grep_search` for `def test_` in the file returns 9 matches.

#### PASS - Spec Adherence: FR-008 Google Search Grounding
- **Requirement**: FR-008
- **Status**: Compliant
- **Detail**: Each topic gets a dedicated `LlmAgent` named `GoogleSearcher_{idx}` with `tools=[google_search]` and `output_key=research_{idx}_google`. The single-tool-per-agent constraint (Section 9.4 Decision 2) is respected.
- **Evidence**: [newsletter_agent/agent.py](newsletter_agent/agent.py#L45-L55) -- `build_research_phase` creates Google Search LlmAgents correctly.

#### PASS - Spec Adherence: FR-009 Perplexity Sonar API Tool
- **Requirement**: FR-009, FR-015, Section 8.2
- **Status**: Compliant
- **Detail**: `search_perplexity` function accepts `query` (str) and `search_depth` (str), calls the Perplexity API via OpenAI SDK, and returns a dict with `text`, `sources` (list of `{url, title}`), and `provider` keys. On failure returns `{error: True, message, provider}`. Function signature matches Section 8.2 exactly.
- **Evidence**: [newsletter_agent/tools/perplexity_search.py](newsletter_agent/tools/perplexity_search.py)

#### PASS - Spec Adherence: FR-010 Parallel Research Execution
- **Requirement**: FR-010
- **Status**: Compliant
- **Detail**: `build_research_phase` returns a `ParallelAgent` named "ResearchPhase" containing one `SequentialAgent` per topic. All topics execute concurrently.
- **Evidence**: [newsletter_agent/agent.py](newsletter_agent/agent.py#L35-L78) -- `build_research_phase` function.

#### PASS - Spec Adherence: FR-011 Namespaced State Keys
- **Requirement**: FR-011
- **Status**: Compliant
- **Detail**: Each LlmAgent uses `output_key=f"research_{idx}_{provider}"` where provider is `google` or `perplexity`. Format matches `research_{topic_index}_{provider}`.
- **Evidence**: [newsletter_agent/agent.py](newsletter_agent/agent.py#L52) and [line 63](newsletter_agent/agent.py#L63).

#### PASS - Spec Adherence: FR-012 Research Result Structure
- **Requirement**: FR-012, Section 7.3, Section 7.4
- **Status**: Compliant
- **Detail**: Perplexity tool returns `{text, sources, provider}` on success and `{error, message, provider}` on failure. `parse_research_result` normalizes various formats to Section 7.3 schema. Sources are deduplicated by URL and contain `{url, title}` per Section 7.4.
- **Evidence**: [newsletter_agent/tools/perplexity_search.py](newsletter_agent/tools/perplexity_search.py), [newsletter_agent/tools/research_utils.py](newsletter_agent/tools/research_utils.py)

#### PASS - Spec Adherence: FR-014 Deep Search Depth Behavior
- **Requirement**: FR-014
- **Status**: Compliant
- **Detail**: Perplexity tool selects `sonar-pro` for deep depth and `sonar` for standard via `_MODEL_MAP`. Google Search deep prompts request comprehensive, multi-faceted analysis. Perplexity deep prompts pass `search_depth="deep"` to the tool.
- **Evidence**: [newsletter_agent/tools/perplexity_search.py](newsletter_agent/tools/perplexity_search.py#L22-L25), [newsletter_agent/prompts/research_google.py](newsletter_agent/prompts/research_google.py) `_DEEP_INSTRUCTION`, [newsletter_agent/prompts/research_perplexity.py](newsletter_agent/prompts/research_perplexity.py) `_DEEP_INSTRUCTION`.

#### PASS - Data Model Adherence
- **Requirement**: Section 7.3 ResearchResult, Section 7.4 SourceRef
- **Status**: Compliant
- **Detail**: ResearchResult fields `text`, `sources`, `provider`, `error`, `message` all implemented. SourceRef fields `url` and `title` both present. Source deduplication by URL implemented. URL validation (http/https prefix) applied.
- **Evidence**: [newsletter_agent/tools/research_utils.py](newsletter_agent/tools/research_utils.py)

#### PASS - API/Interface Adherence
- **Requirement**: Section 8.2 Perplexity Sonar Tool Function Signature
- **Status**: Compliant
- **Detail**: `search_perplexity(query: str, search_depth: str = "standard") -> dict` matches the spec signature exactly. Return keys match. Error handling convention matches.
- **Evidence**: [newsletter_agent/tools/perplexity_search.py](newsletter_agent/tools/perplexity_search.py#L28)

#### PASS - Architecture Adherence
- **Requirement**: Section 9.1, 9.2, 9.3, 9.4
- **Status**: Compliant
- **Detail**: Module structure matches Section 9.3 (`tools/perplexity_search.py`, `prompts/research_google.py`, `prompts/research_perplexity.py`, `tools/research_utils.py`, `agent.py`). Technology stack matches Section 9.2 (google-adk, OpenAI SDK for Perplexity, gemini-2.5-flash for research). Design decisions 1 (dynamic construction) and 2 (separate agents) are honored.
- **Evidence**: File tree and implementation code.

#### WARN - Architecture: Config Loader Agent Absent (T02-07)
- **Requirement**: T02-07 AC -- "research phase ParallelAgent as its second child (after config loader)"
- **Status**: Deviating
- **Detail**: The root pipeline has research_phase as its first child, not second. There is no config_loader_agent sub-agent; config is loaded at module level (Option 3 from T02-07 Implementation Guidance). This contradicts the literal AC text but follows the suggested implementation path. The pipeline functions correctly.
- **Evidence**: [newsletter_agent/agent.py](newsletter_agent/agent.py#L115-L130) -- `build_pipeline` assembles 3 sub-agents: ResearchPhase, Synthesizer, OutputPhase.

#### PASS - Non-Functional: Security
- **Requirement**: Section 10.2
- **Status**: Compliant
- **Detail**: SSRF mitigation implemented: `_PERPLEXITY_BASE_URL = "https://api.perplexity.ai"` is hardcoded, no user-controlled URLs. API key read from environment variable, not hardcoded. No secrets in source code. Prompts explicitly instruct agents not to fabricate information.
- **Evidence**: [newsletter_agent/tools/perplexity_search.py](newsletter_agent/tools/perplexity_search.py#L18)

#### PASS - Non-Functional: Observability
- **Requirement**: FR-042, FR-043, FR-044
- **Status**: Compliant
- **Detail**: Logging at INFO for search start/completion, ERROR for failures. Uses Python `logging` module. Logger named per module convention.
- **Evidence**: [newsletter_agent/tools/perplexity_search.py](newsletter_agent/tools/perplexity_search.py) -- `logger.info` and `logger.error` calls throughout.

#### PASS - Non-Functional: Performance
- **Requirement**: Section 10.1, 4g-ii patterns
- **Status**: Compliant
- **Detail**: No N+1 patterns. No unbounded data fetching. ParallelAgent provides concurrent execution for all topics as required. OpenAI client created per-call (stateless), which is fine for the expected invocation frequency.

#### PASS - Scope Discipline
- **Requirement**: No scope creep
- **Status**: Compliant
- **Detail**: All files created/modified are within WP02's declared scope. No unspecified features, abstractions, or utilities added beyond what the tasks require.

#### PASS - Encoding (UTF-8)
- **Requirement**: No em dashes, smart quotes, curly apostrophes
- **Status**: Compliant
- **Detail**: All implementation and test files scanned for characters U+2014, U+2013, U+2018, U+2019, U+201C, U+201D. None found.
- **Evidence**: Automated scan of all files under `newsletter_agent/` and `tests/`.

#### WARN - Test Coverage: Specific Scenarios Missing (T02-08, T02-10)
- **Requirement**: T02-08 AC enumerated scenarios, T02-10 AC enumerated scenarios
- **Status**: Partial
- **Detail**: T02-08 AC lists these specific scenarios not covered: API authentication error (401), empty query string, response timeout. T02-10 AC lists these scenarios not covered: output with invalid URLs, output with very long text, output with special characters in source titles. While T02-10 meets its minimum count (12), these specific edge cases from the AC are absent.
- **Evidence**: Test file contents reviewed against AC enumeration.

### Statistics

| Dimension | Pass | Warn | Fail |
|-----------|------|------|------|
| Process Compliance | 0 | 0 | 2 |
| Spec Adherence | 6 | 0 | 1 |
| Data Model | 1 | 0 | 0 |
| API / Interface | 1 | 0 | 0 |
| Architecture | 1 | 1 | 0 |
| Test Coverage | 1 | 1 | 2 |
| Non-Functional | 3 | 0 | 0 |
| Performance | 1 | 0 | 0 |
| Documentation | 0 | 0 | 0 |
| Scope Discipline | 1 | 0 | 0 |
| Encoding (UTF-8) | 1 | 0 | 0 |

### Recommended Actions

1. **(FB-01)** Add Spec Compliance Checklist for all 11 tasks in the WP file. Each task needs a table mapping its spec refs to the implementing file/line.
2. **(FB-02)** Create `tests/bdd/test_research_pipeline.py` with 4+ BDD scenarios using mocked agents/APIs. Reference the Gherkin in spec Section 11.2.
3. **(FB-03)** Implement total-failure detection. Add a post-research-phase check (callback or lightweight agent) that inspects all `research_{N}_{provider}` state keys and sets `research_all_failed: true` if all are errors/missing. Log at CRITICAL level.
4. **(FB-04)** Add at least 1 test to `test_perplexity_search.py` to meet the 10-test minimum. Suggested: test for `APIStatusError` with 401 status code.
5. **(FB-05)** Maintain one-commit-per-task discipline going forward. This remediation may use a single commit.

## Re-Review (Round 2)

> **Reviewed by**: Reviewer Agent
> **Date**: 2025-07-25
> **Verdict**: Approved with Findings
> **Scope**: Re-review of FB-01 through FB-05 from Round 1 + regression check

### Summary

All five original FAILs are resolved. The Spec Compliance Checklist is present for all 11 tasks. BDD tests exist with 4 scenarios. ResearchValidatorAgent implements total-failure detection with CRITICAL logging. test_perplexity_search.py has exactly 10 tests meeting the minimum. Two WARNs carry forward from Round 1 (config loader agent absent, test edge case gaps) plus the commit discipline WARN. None block correctness. All 243 tests pass.

### Re-Review Findings

#### PASS - FB-01 Remediation: Spec Compliance Checklist
- **Original**: FAIL - Missing entirely
- **Status**: Resolved
- **Evidence**: Checklist present at WP02-research-pipeline.md lines 1517-1605, covers T02-01 through T02-11.

#### PASS - FB-02 Remediation: BDD Tests
- **Original**: FAIL - tests/bdd/test_research_pipeline.py missing
- **Status**: Resolved
- **Evidence**: File exists with 4 scenario classes: TestSuccessfulDualSourceResearch, TestSingleProviderFailure, TestParallelExecutionMultipleTopics, TestAllProvidersFail.

#### PASS - FB-03 Remediation: Total-Failure Detection
- **Original**: FAIL - Not implemented
- **Status**: Resolved
- **Evidence**: ResearchValidatorAgent at agent.py L96 checks all research keys, sets research_all_failed=True, logs at CRITICAL level.

#### PASS - FB-04 Remediation: Test Count
- **Original**: FAIL - 9 tests, minimum 10
- **Status**: Resolved
- **Evidence**: test_perplexity_search.py now has 10 test methods including test_api_auth_error_401_returns_error_dict.

#### WARN - FB-05 Carried Forward: Commit Discipline
- **Original**: FAIL downgraded to WARN
- **Detail**: Original 11 tasks batched in single commit. Remediation used single remediation commit (acceptable). Future WPs should use one-commit-per-task.

#### WARN - Carried Forward: Config Loader Agent Absent (T02-07)
- **Detail**: Pipeline has research_phase as first child, no config_loader_agent sub-agent. Config loaded at module level. Functionally correct but deviates from literal AC text.

#### WARN - Carried Forward: Test Edge Case Gaps (T02-08, T02-10)
- **Detail**: Some AC-enumerated edge cases absent (empty query, response timeout for T02-08; invalid URLs, very long text for T02-10). Minimum counts met.

#### PASS - Regression Check
- **Detail**: All 243 tests pass. No encoding violations. No new files outside WP scope.

### Statistics (Re-Review)

| Dimension | Pass | Warn | Fail |
|-----------|------|------|------|
| FB Remediation | 4 | 1 | 0 |
| Regression | 1 | 0 | 0 |
| Carried Forward | 0 | 2 | 0 |

## WARN Remediation (Round 3)

> **Implemented by**: Coder Agent
> **Date**: 2026-03-14
> **Scope**: Address carried-forward WARNs from Round 2

### Changes Made

1. **Test Edge Case Gaps (T02-08)**: Added 2 tests to test_perplexity_search.py:
   - `test_empty_query_still_calls_api` - verifies empty query string is passed to API
   - `test_timeout_error_returns_error_dict` - verifies APITimeoutError returns error dict

2. **Test Edge Case Gaps (T02-10)**: Added 3 tests to test_research_utils.py:
   - `test_invalid_urls_filtered_from_sources` - verifies ftp://, javascript:, and non-URL sources are filtered
   - `test_very_long_text_preserved` - verifies 50K character text is preserved
   - `test_special_characters_in_source_titles` - verifies quotes, ampersands, angle brackets in titles

3. **URL Validation Fix (research_utils.py)**: Fixed `_normalize_sources` to filter non-http/https URLs from dict-format sources. Previously only string-format sources were validated.

### Self-Review

- [x] All new tests pass (252 total, 0 failures)
- [x] No encoding violations
- [x] No scope creep - only test files and one validation fix
- [x] WARN for "Config Loader Agent Absent" not addressed - architectural decision, not a bug
- [x] WARN for "Commit Discipline" not addressed - historical, cannot retroactively split
