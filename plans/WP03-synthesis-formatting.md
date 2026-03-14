---
lane: for_review
review_status: acknowledged
---

# WP03 - Content Synthesis and Newsletter Formatting

> **Spec**: `specs/newsletter-agent.spec.md`
> **Status**: Complete
> **Priority**: P1
> **Goal**: Research results are synthesized into deep analysis sections with citations, and rendered into a professional HTML newsletter with executive summary, TOC, and inline CSS
> **Independent Test**: Populate session state with mock research results for 3 topics, run synthesis and formatting, verify the output HTML contains all required sections with correct structure
> **Depends on**: WP01, WP02
> **Parallelisable**: No (depends on WP02 research output format)
> **Prompt**: `plans/WP03-synthesis-formatting.md`

## Objective

This work package delivers the synthesis agent and the HTML newsletter formatter. The synthesis agent reads research results from session state, produces deep multi-paragraph analysis per topic with inline citations, generates an executive summary, and stores everything back in session state. The formatter then reads the synthesis output and renders a complete HTML newsletter using a Jinja2 template with inline CSS, suitable for email delivery in Gmail web and mobile clients.

Together, these two components transform raw research data into a polished, professional newsletter document. This is the core output quality differentiator of the system.

## Spec References

- FR-016: Synthesis via Gemini Pro LlmAgent
- FR-017: Deep analysis quality - multi-paragraph, 200+ words, cross-reference, inline citations
- FR-018: Executive summary generation - 1-3 sentences per topic
- FR-019: Synthesis state structure (`synthesis_{topic_index}`)
- FR-020: No fabricated facts or sources
- FR-021: HTML rendering with inline CSS
- FR-022: Newsletter section order (title/date, exec summary, TOC, topic sections, source appendix, footer)
- FR-023: Responsive single-column 600px max width layout
- FR-024: Topic section content (heading, body with citations, source list)
- FR-025: Executive summary display as bulleted list
- FR-026: Store `newsletter_html` and `newsletter_metadata` in state
- US-03: Deep analysis synthesis
- US-04: HTML newsletter formatting
- US-08: Executive summary
- Section 7.5: SynthesisResult data model
- Section 7.6: NewsletterMetadata data model
- Section 9.1: Architecture - synthesis agent and formatter agent
- Section 9.2: Gemini Pro for synthesis
- Section 9.4: Decision 3 (Flash vs Pro), Decision 4 (Jinja2 templates)
- Section 10.2: Security - Jinja2 autoescaping, HTML sanitization
- Section 11.1: Unit tests for HTML formatter, synthesis
- Section 11.2: BDD scenarios for synthesis and formatting

## Tasks

### T03-01 - Create Synthesis Agent Instruction Prompt

- **Description**: Create the instruction prompt template for the synthesis agent in `newsletter_agent/prompts/synthesis.py`. This prompt instructs the Gemini Pro LlmAgent to read research results from session state, produce a deep multi-paragraph analysis per topic with inline citations, and generate an executive summary. The prompt must explicitly prohibit fabricating facts or sources.

- **Spec refs**: FR-016, FR-017, FR-018, FR-019, FR-020, Section 9.1

- **Parallel**: Yes (can be developed alongside T03-02)

- **Acceptance criteria**:
  - [ ] File `newsletter_agent/prompts/synthesis.py` exists and exports `get_synthesis_instruction(topic_names: list[str], topic_count: int) -> str`
  - [ ] The instruction tells the agent to read `research_{N}_{provider}` keys from session state for each topic
  - [ ] The instruction requires each topic section to be multi-paragraph with minimum 200 words
  - [ ] The instruction requires inline citations in `[Source Title](URL)` format using only sources found in the research results
  - [ ] The instruction explicitly prohibits fabricating facts, statistics, or source URLs not present in the research data
  - [ ] The instruction requires an executive summary with 1-3 sentence overview per topic
  - [ ] The instruction specifies the output format for `synthesis_{N}` state keys with `title`, `body_markdown`, and `sources` fields
  - [ ] The instruction specifies the output format for the `executive_summary` state key

- **Test requirements**: unit (verify prompt content and template substitution)

- **Depends on**: none

- **Implementation Guidance**:
  - The synthesis agent is the most critical prompt in the system. Output quality depends heavily on this instruction.
  - The prompt must be very specific about the output format because the formatter (T03-03) needs to parse the synthesis output from session state.
  - Recommended approach: Use ADK's `output_key` to automatically save the agent's response to state. However, the synthesis agent needs to produce MULTIPLE state keys (one per topic + executive summary). Options:
    1. Use a single `output_key` and have the formatter parse the full response into sections
    2. Use a custom BaseAgent that runs the LLM and manually writes multiple state keys
    3. Have the synthesis agent output a JSON structure that a post-processing step parses into state keys
  - Option 3 is recommended for MVP: instruct the LLM to output a JSON blob with all synthesis results, store it as `synthesis_output` via `output_key`, and then a post-processing function parses it into individual state keys.
  - Prompt structure:
    ```
    You are a senior analyst synthesizing research findings into deep analysis.
    
    RESEARCH DATA:
    The following research results are available in session state:
    [List of state keys and their contents]
    
    OUTPUT FORMAT:
    Produce a JSON object with the following structure:
    {
      "executive_summary": [
        {"topic": "Topic Name", "summary": "1-3 sentence overview"}
      ],
      "sections": [
        {
          "title": "Topic Name",
          "body_markdown": "Multi-paragraph analysis with [Source](URL) citations...",
          "sources": [{"url": "...", "title": "..."}]
        }
      ]
    }
    
    RULES:
    - Each section must be at least 200 words
    - Cross-reference findings from multiple sources
    - Include at least 3 inline citations per section
    - NEVER fabricate facts, statistics, or URLs
    - Use only sources present in the research data
    ```
  - Known pitfalls:
    - LLMs may not produce valid JSON consistently. The post-processing step must handle JSON parse failures gracefully.
    - The 200-word minimum is a quality guideline, not a hard constraint the LLM will always follow. The acceptance test should verify typical output meets this bar.
    - Cross-referencing requires the model to see results from both providers simultaneously. The prompt must present all research for a topic together.
    - The prohibition on fabrication should be repeated and emphasized - LLMs tend to "help" by adding plausible-sounding details.

---

### T03-02 - Implement Synthesis Post-Processing

- **Description**: Create a utility function that takes the raw synthesis agent output (expected JSON or structured text) and parses it into individual session state entries: `synthesis_{topic_index}` for each topic and `executive_summary`. This function handles JSON parse failures, validates the output structure, and falls back gracefully when the synthesis output is malformed.

- **Spec refs**: FR-019, FR-018, Section 7.5, Section 7.6

- **Parallel**: Yes (can be developed alongside T03-01)

- **Acceptance criteria**:
  - [ ] Function `parse_synthesis_output(raw_output: str, expected_topics: list[str]) -> dict` exists in `newsletter_agent/tools/synthesis_utils.py`
  - [ ] For valid JSON output, the function returns a dict with `synthesis_0`, `synthesis_1`, etc. keys and an `executive_summary` key
  - [ ] Each `synthesis_{N}` value is a dict with `title` (str), `body_markdown` (str), and `sources` (list of {url, title} dicts)
  - [ ] The `executive_summary` value is a list of dicts with `topic` (str) and `summary` (str)
  - [ ] For invalid JSON output, the function attempts text-based parsing as a fallback
  - [ ] For completely unparseable output, the function returns a minimal valid structure with error notes
  - [ ] The function never raises an exception - always returns a valid dict

- **Test requirements**: unit (various JSON formats, malformed input, edge cases)

- **Depends on**: none

- **Implementation Guidance**:
  - Try `json.loads()` first. If that fails, try extracting JSON from markdown code blocks (the LLM may wrap output in ```json ... ```).
  - Fallback text parsing: look for section headings (e.g., "## Topic Name") and treat content between headings as section bodies.
  - Validate that each section's `body_markdown` contains at least one `[Title](URL)` inline citation.
  - Known pitfalls:
    - LLMs often produce JSON with trailing commas, single quotes, or comments - all invalid JSON. Consider using `json5` or a lenient parser if `json.loads` fails frequently.
    - The LLM may output extra text before/after the JSON block (e.g., "Here is the synthesis:"). Strip non-JSON prefix/suffix.
    - Source deduplication: the `sources` list per section may contain duplicates. Deduplicate by URL.

---

### T03-03 - Create Jinja2 HTML Newsletter Template

- **Description**: Create the Jinja2 HTML template at `newsletter_agent/templates/newsletter.html.j2` that renders the complete newsletter. The template must use inline CSS (no external stylesheets), produce a responsive single-column layout at max 600px width, and include all required sections in the specified order per FR-022.

- **Spec refs**: FR-021, FR-022, FR-023, FR-024, FR-025, Section 9.4 Decision 4, Section 10.2

- **Parallel**: Yes (independent of synthesis implementation)

- **Acceptance criteria**:
  - [ ] File `newsletter_agent/templates/newsletter.html.j2` exists
  - [ ] Template renders valid HTML5 with all CSS inline (no `<link>` tags, no external stylesheet references)
  - [ ] The rendered output contains sections in order: newsletter title + date, executive summary, table of contents, topic deep-dive sections, source appendix, footer
  - [ ] The executive summary section displays each topic as a bulleted list item with 1-3 sentence summary
  - [ ] The table of contents contains linked entries (anchor links) for each topic section
  - [ ] Each topic section displays: topic name as heading, synthesized body with inline citations, list of sources with URLs
  - [ ] The source appendix lists all sources from all topics, deduplicated
  - [ ] The layout uses a single-column design with max-width 600px centered
  - [ ] All fonts use web-safe font stacks (Arial, Helvetica, sans-serif)
  - [ ] Colors use a clean, professional palette with sufficient contrast for readability
  - [ ] The template has Jinja2 autoescaping enabled to prevent XSS from LLM-generated content

- **Test requirements**: unit (render with mock data, verify structure)

- **Depends on**: none

- **Implementation Guidance**:
  - Jinja2 autoescaping: Enable with `autoescape=True` in the `Environment` constructor. This is critical for security (Section 10.2 - OWASP A03 injection mitigation).
  - However, `body_markdown` contains intentional HTML (inline links). Use the `|safe` filter ONLY on content that has been sanitized by `nh3` first (see T03-04).
  - Email HTML constraints:
    - Gmail strips `<style>` blocks in the `<head>`. ALL CSS must be inline on each element.
    - No JavaScript, no `<form>`, no `<video>`, no `<iframe>`.
    - Use `<table>` for layout structure (email clients render tables more consistently than CSS flexbox/grid).
    - Images: avoid external images (may be blocked). If used, always include `alt` text.
    - Use `bgcolor` attributes alongside `background-color` CSS for maximum compatibility.
  - Template variables expected:
    ```jinja2
    {{ newsletter_title }}        - str: Newsletter title
    {{ newsletter_date }}         - str: Generation date (YYYY-MM-DD)
    {{ executive_summary }}       - list[dict]: [{topic, summary}]
    {{ sections }}                - list[dict]: [{title, body_html, sources}]
    {{ all_sources }}             - list[dict]: [{url, title}] deduplicated
    {{ generation_time_seconds }} - float: Pipeline timing
    ```
  - Template structure reference:
    ```html
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>{{ newsletter_title }} - {{ newsletter_date }}</title>
    </head>
    <body style="margin: 0; padding: 0; background-color: #f4f4f4; font-family: Arial, Helvetica, sans-serif;">
      <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%">
        <tr>
          <td style="padding: 20px 0;" align="center">
            <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="600" style="max-width: 600px; background-color: #ffffff;">
              <!-- Header -->
              <!-- Executive Summary -->
              <!-- Table of Contents -->
              <!-- Topic Sections -->
              <!-- Source Appendix -->
              <!-- Footer -->
            </table>
          </td>
        </tr>
      </table>
    </body>
    </html>
    ```
  - Known pitfalls:
    - Gmail on mobile may override font sizes smaller than 13px
    - Outlook may not respect max-width on divs - use table-based layout for safety
    - The `<a>` tag styles in Gmail may be overridden. Use inline `style` and `color` on each link.
    - Anchor links (`<a href="#section-N">`) work in most email clients for TOC navigation
  - Edge cases:
    - Topic with empty body (research failed): show a "Research unavailable" message
    - Very long topic names: truncate or wrap gracefully
    - Sources with very long URLs: consider truncating display text while keeping full href

---

### T03-04 - Implement HTML Sanitization for LLM Content

- **Description**: Implement a sanitization step that processes the synthesis markdown output (which may contain LLM-generated HTML or markdown) into safe HTML suitable for embedding in the newsletter template. Use `nh3` (or `bleach` as fallback) to strip dangerous HTML tags/attributes while preserving safe formatting (links, paragraphs, emphasis). Convert markdown inline links to HTML links.

- **Spec refs**: Section 10.2 (OWASP A03 injection mitigation), Section 9.2 (nh3 for HTML sanitization)

- **Parallel**: Yes (can be developed alongside T03-03)

- **Acceptance criteria**:
  - [ ] Function `sanitize_synthesis_html(markdown_text: str) -> str` exists in `newsletter_agent/tools/sanitizer.py`
  - [ ] Markdown inline links `[Title](URL)` are converted to HTML `<a href="URL">Title</a>` links
  - [ ] Basic markdown formatting (bold, italic, paragraphs) is converted to HTML equivalents
  - [ ] Dangerous HTML tags are stripped: `<script>`, `<iframe>`, `<form>`, `<object>`, `<embed>`, event handlers (`onclick`, etc.)
  - [ ] XSS payloads in topic names or synthesized content are neutralized (e.g., `<script>alert('xss')</script>` becomes escaped text)
  - [ ] Safe tags are preserved: `<a>`, `<p>`, `<strong>`, `<em>`, `<ul>`, `<ol>`, `<li>`, `<h3>`, `<h4>`, `<br>`
  - [ ] Only `href` attribute is allowed on `<a>` tags, and only `http://` and `https://` schemes

- **Test requirements**: unit (XSS payloads, markdown conversion, allowed/disallowed tags)

- **Depends on**: none

- **Implementation Guidance**:
  - Use `nh3` (Rust-based, fast, secure) as the primary sanitizer. If `nh3` is not available, fall back to `bleach`.
  - Processing pipeline:
    1. Convert markdown links to HTML links: `re.sub(r'\[([^\]]+)\]\((https?://[^\)]+)\)', r'<a href="\2">\1</a>', text)`
    2. Convert markdown paragraphs (double newlines) to `<p>` tags
    3. Convert `**bold**` to `<strong>` and `*italic*` to `<em>`
    4. Run through `nh3.clean()` with allowed tags whitelist
  - nh3 configuration:
    ```python
    import nh3
    
    ALLOWED_TAGS = {"a", "p", "strong", "em", "ul", "ol", "li", "h3", "h4", "br"}
    ALLOWED_ATTRIBUTES = {"a": {"href"}}
    
    def sanitize_synthesis_html(markdown_text: str) -> str:
        html = _markdown_to_html(markdown_text)
        return nh3.clean(
            html,
            tags=ALLOWED_TAGS,
            attributes=ALLOWED_ATTRIBUTES,
            url_schemes={"http", "https"},
        )
    ```
  - Known pitfalls:
    - `nh3` API differs from `bleach`. Check the installed version's API.
    - Markdown-to-HTML conversion is intentionally minimal here - not using a full markdown parser to keep dependencies simple. The synthesis output is mostly prose with inline links.
    - The sanitizer must run BEFORE the Jinja2 `|safe` filter is applied in the template. The rendering pipeline must be: synthesis output -> markdown-to-HTML -> nh3 sanitize -> Jinja2 template with `|safe`.
  - Security tests (Section 11.6):
    - Input: `<script>alert('xss')</script>` - must be stripped entirely
    - Input: `<a href="javascript:alert('xss')">click</a>` - must strip the javascript: URL
    - Input: `<img src=x onerror=alert('xss')>` - must strip the img tag or the onerror handler
    - Input: `[Legit Link](https://example.com)` - must be converted to a safe `<a>` tag

---

### T03-05 - Implement Newsletter Formatter Agent

- **Description**: Implement the formatter as a custom `BaseAgent` (or Python function) in `newsletter_agent/agent.py` or a separate module. The formatter reads synthesis results and executive summary from session state, renders the Jinja2 HTML template with sanitized content, and stores the final HTML and metadata in session state.

- **Spec refs**: FR-021, FR-022, FR-026, Section 9.1 (formatter agent), Section 4.4 implementation contract

- **Parallel**: No (requires T03-02, T03-03, T03-04)

- **Acceptance criteria**:
  - [ ] A formatter component exists (either a BaseAgent subclass or a function called by a BaseAgent)
  - [ ] The formatter reads `synthesis_{N}` and `executive_summary` keys from session state
  - [ ] The formatter sanitizes all synthesis body content through the sanitizer (T03-04) before rendering
  - [ ] The formatter renders the Jinja2 template (T03-03) with all required data
  - [ ] The formatter stores the complete HTML string in state as `newsletter_html`
  - [ ] The formatter stores metadata in state as `newsletter_metadata` with fields: `title`, `date`, `topic_count`, `generation_time_seconds`
  - [ ] If a synthesis section is missing for a topic, the formatter includes a "Research unavailable" note instead of failing
  - [ ] The formatter deduplicates all sources for the source appendix

- **Test requirements**: unit (render with mock state data)

- **Depends on**: T03-02, T03-03, T03-04

- **Implementation Guidance**:
  - ADK BaseAgent pattern: For non-LLM agents, subclass `BaseAgent` and override `_run_async_impl`:
    ```python
    from google.adk.agents import BaseAgent
    from google.adk.agents.invocation_context import InvocationContext
    from google.genai import types
    import jinja2
    
    class FormatterAgent(BaseAgent):
        async def _run_async_impl(self, ctx: InvocationContext):
            state = ctx.session.state
            # Read synthesis data from state
            # Render template
            # Store newsletter_html in state
            yield types.Content(parts=[types.Part(text="Newsletter formatted successfully")])
    ```
  - Jinja2 Environment:
    ```python
    import jinja2
    import os
    
    _TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
    _jinja_env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(_TEMPLATE_DIR),
        autoescape=True,
    )
    
    def render_newsletter(data: dict) -> str:
        template = _jinja_env.get_template("newsletter.html.j2")
        return template.render(**data)
    ```
  - Data preparation: Before rendering, the formatter must:
    1. Read all `synthesis_{N}` keys and collect them into a list
    2. Sanitize each section's `body_markdown` through the sanitizer
    3. Read `executive_summary` from state
    4. Collect and deduplicate all sources across all sections
    5. Calculate `generation_time_seconds` (pipeline start time should be stored in state by the root agent)
    6. Build the template context dict
  - Known pitfalls:
    - The Jinja2 `autoescape=True` will escape ALL content by default. The sanitized HTML must be passed through the `|safe` filter in the template. This is safe because `nh3` has already sanitized it.
    - Missing synthesis sections (research failed for a topic): must not crash the formatter. Check for each section and provide a fallback.
    - The `generation_time_seconds` requires knowing the pipeline start time. This should be stored in state at the beginning of the pipeline execution.

---

### T03-06 - Implement Synthesis Agent and Wire into Root Pipeline

- **Description**: Create the synthesis LlmAgent using Gemini Pro model, connect it to the synthesis instruction prompt (T03-01), and wire it into the root SequentialAgent after the research phase. The agent reads research results from state and produces synthesis output via its `output_key`. The post-processing step (T03-02) then parses the output into individual state keys.

- **Spec refs**: FR-016, Section 9.1 (architecture), Section 9.2 (Gemini Pro)

- **Parallel**: No (requires T03-01, T03-02)

- **Acceptance criteria**:
  - [ ] A synthesis LlmAgent exists with model `gemini-2.5-pro`
  - [ ] The agent's instruction is generated by `get_synthesis_instruction()` from T03-01
  - [ ] The agent's `output_key` stores its raw output in session state
  - [ ] A post-processing step (callback or custom agent wrapper) parses the raw output into `synthesis_{N}` and `executive_summary` state keys using the utility from T03-02
  - [ ] The synthesis agent is wired into the root SequentialAgent as the third step (after config loader and research phase)
  - [ ] Running the pipeline through synthesis via `adk web` produces synthesis state entries for each topic

- **Test requirements**: integration (run with mock research state)

- **Depends on**: T03-01, T03-02

- **Implementation Guidance**:
  - The synthesis agent needs to READ from session state (research results) and WRITE to session state (synthesis results). ADK LlmAgent can read state via instruction templating and write via `output_key`.
  - Challenge: The instruction needs to contain the actual research data. Options:
    1. Use instruction templating with state references: `"Research for topic 0: {research_0_google}"`
    2. Use a custom BaseAgent wrapper that reads state, builds the instruction dynamically, and runs the LLM
  - Option 2 is recommended because the instruction needs to be very long (all research data for all topics) and state templating may not work well for multi-key reads.
  - Post-processing approach: After the LLM produces its response, a callback or wrapper agent calls `parse_synthesis_output()` to split the response into individual state keys.
  - Wiring into root agent:
    ```python
    root_agent = SequentialAgent(
        name="NewsletterPipeline",
        sub_agents=[
            config_loader_agent,     # WP01
            research_phase,          # WP02
            synthesis_agent,         # This task
            # output_phase,          # T03-05 + WP04
        ],
    )
    ```

---

### T03-07 - Wire Formatter into Root Pipeline

- **Description**: Add the formatter agent (T03-05) into the root SequentialAgent pipeline after the synthesis agent. After this task, running the full pipeline produces a complete HTML newsletter stored in session state.

- **Spec refs**: FR-026, Section 9.1 (output phase)

- **Parallel**: No (requires T03-05, T03-06)

- **Acceptance criteria**:
  - [ ] The formatter agent is wired into the root SequentialAgent as the fourth step (after synthesis)
  - [ ] Running the full pipeline via `adk web` with valid config and API keys produces `newsletter_html` in session state
  - [ ] The `newsletter_html` state key contains a complete HTML document
  - [ ] The `newsletter_metadata` state key contains title, date, topic_count, and generation_time_seconds
  - [ ] In dry-run mode, the pipeline reaches the formatter without sending any email

- **Test requirements**: integration, E2E (via `adk web`)

- **Depends on**: T03-05, T03-06

- **Implementation Guidance**:
  - The root SequentialAgent now has 4 children: config_loader, research_phase, synthesis_agent, formatter_agent (delivery comes in WP04).
  - After this task, a dry-run test should produce the newsletter HTML. The coder should visually inspect the HTML in a browser to verify layout and content quality.

---

### T03-08 - Write Unit Tests for Synthesis Post-Processing

- **Description**: Write unit tests for the `parse_synthesis_output()` function covering various output formats and failure modes.

- **Spec refs**: Section 11.1

- **Parallel**: Yes (after T03-02)

- **Acceptance criteria**:
  - [ ] Test file `tests/test_synthesis_utils.py` exists with at least 10 test cases
  - [ ] Tests cover: valid JSON output, JSON wrapped in markdown code blocks, malformed JSON with trailing commas, completely unstructured text, missing sections for some topics, empty output, output with missing sources, output with very short body (under 200 words), executive summary missing, duplicate sources in sections
  - [ ] Tests verify the function never raises an exception
  - [ ] Tests verify the output structure matches Section 7.5 SynthesisResult schema
  - [ ] All tests pass via `pytest tests/test_synthesis_utils.py`

- **Test requirements**: unit

- **Depends on**: T03-02

- **Implementation Guidance**:
  - Create fixture JSON strings that represent various LLM output formats:
    ```python
    VALID_SYNTHESIS_JSON = '''
    {
      "executive_summary": [
        {"topic": "AI Frameworks", "summary": "ADK and LangChain lead the pack..."}
      ],
      "sections": [
        {
          "title": "AI Frameworks",
          "body_markdown": "The AI framework landscape has evolved significantly...",
          "sources": [{"url": "https://example.com", "title": "Example"}]
        }
      ]
    }
    '''
    
    MARKDOWN_WRAPPED_JSON = '```json\n' + VALID_SYNTHESIS_JSON + '\n```'
    ```

---

### T03-09 - Write Unit Tests for HTML Sanitizer

- **Description**: Write unit tests for the `sanitize_synthesis_html()` function covering XSS payloads, markdown conversion, and tag filtering.

- **Spec refs**: Section 11.6 (security tests), Section 10.2

- **Parallel**: Yes (after T03-04)

- **Acceptance criteria**:
  - [ ] Test file `tests/test_sanitizer.py` exists with at least 12 test cases
  - [ ] Tests cover XSS payloads: `<script>` tags, `javascript:` URLs, event handlers (`onclick`, `onerror`), data URIs, CSS expression attacks
  - [ ] Tests verify markdown link conversion: `[Title](URL)` -> `<a href="URL">Title</a>`
  - [ ] Tests verify markdown formatting: bold, italic, paragraphs
  - [ ] Tests verify allowed tags pass through: `<a>`, `<p>`, `<strong>`, `<em>`, `<ul>`, `<li>`
  - [ ] Tests verify disallowed tags are stripped: `<script>`, `<iframe>`, `<form>`, `<img>` (unless explicitly allowed)
  - [ ] Tests verify only `http://` and `https://` URL schemes are allowed in links
  - [ ] All tests pass via `pytest tests/test_sanitizer.py`

- **Test requirements**: unit, security

- **Depends on**: T03-04

- **Implementation Guidance**:
  - XSS test payloads to include:
    ```python
    XSS_PAYLOADS = [
        '<script>alert("xss")</script>',
        '<img src=x onerror=alert("xss")>',
        '<a href="javascript:alert(\'xss\')">click</a>',
        '<div onmouseover="alert(\'xss\')">hover</div>',
        '<a href="data:text/html,<script>alert(1)</script>">data</a>',
        '"><script>alert(document.cookie)</script>',
        '<svg onload=alert("xss")>',
    ]
    ```
  - Each payload should be passed through `sanitize_synthesis_html()` and the output verified to contain no executable content.

---

### T03-10 - Write Unit Tests for HTML Template Rendering

- **Description**: Write unit tests that render the Jinja2 newsletter template with mock data and verify the output HTML structure.

- **Spec refs**: Section 11.1 (HTML formatter unit tests), FR-022, FR-023, FR-024, FR-025

- **Parallel**: Yes (after T03-03)

- **Acceptance criteria**:
  - [ ] Test file `tests/test_html_formatter.py` exists with at least 8 test cases
  - [ ] Tests render the template with mock data for 1, 3, and 5 topic configurations
  - [ ] Tests verify all required sections are present in order: title/date, executive summary, TOC, topic sections, source appendix, footer
  - [ ] Tests verify the executive summary contains bulleted items for each topic
  - [ ] Tests verify the TOC contains anchor links matching topic section IDs
  - [ ] Tests verify all CSS is inline (no `<link>` or external `<style>` references)
  - [ ] Tests verify the max-width 600px constraint is present in the wrapper element
  - [ ] Tests verify the template handles missing sections gracefully (topic with no synthesis data)
  - [ ] All tests pass via `pytest tests/test_html_formatter.py`

- **Test requirements**: unit

- **Depends on**: T03-03

- **Implementation Guidance**:
  - Use `BeautifulSoup` or simple string matching to verify HTML structure
  - Create mock data fixtures:
    ```python
    MOCK_3_TOPICS = {
        "newsletter_title": "Weekly Tech Digest",
        "newsletter_date": "2026-03-14",
        "executive_summary": [
            {"topic": "AI", "summary": "AI continues to advance..."},
            {"topic": "Cloud", "summary": "Cloud adoption grows..."},
            {"topic": "Security", "summary": "New threats emerge..."},
        ],
        "sections": [
            {
                "title": "AI",
                "body_html": "<p>The AI landscape has shifted...</p>",
                "sources": [{"url": "https://a.com", "title": "Source A"}],
            },
            # ... more sections
        ],
        "all_sources": [...],
        "generation_time_seconds": 120.5,
    }
    ```

---

### T03-11 - Write BDD Acceptance Tests for Synthesis and Formatting

- **Description**: Write BDD-style acceptance tests that verify the end-to-end synthesis and formatting pipeline against the spec's Feature: Synthesis and Feature: Newsletter Formatting scenarios.

- **Spec refs**: Section 11.2 (BDD scenarios), US-03, US-04, US-08

- **Parallel**: No (requires all T03-01 through T03-07)

- **Acceptance criteria**:
  - [ ] Test file `tests/bdd/test_synthesis_formatting.py` exists with at least 6 BDD scenario tests
  - [ ] Scenario: Deep analysis with citations - verifies 200+ word output with 3+ inline citations
  - [ ] Scenario: Synthesis with partial research - verifies output produced with limited source note
  - [ ] Scenario: Synthesis with no research data - verifies "Research unavailable" message
  - [ ] Scenario: Complete HTML newsletter - verifies all sections in correct order
  - [ ] Scenario: Executive summary generation - verifies 1-3 sentence summaries per topic
  - [ ] Scenario: Responsive layout verification - verifies 600px max width
  - [ ] Tests use mocked synthesis data (no real LLM calls required for formatting tests)
  - [ ] All tests pass via `pytest tests/bdd/test_synthesis_formatting.py`

- **Test requirements**: BDD

- **Depends on**: T03-07

- **Implementation Guidance**:
  - For synthesis quality tests (200+ words, citations), these may require mocked LLM responses or pre-recorded outputs since we cannot guarantee LLM output quality in unit tests.
  - For formatting tests, mock synthesis data can be used directly.

## Reference Implementations

### Jinja2 Newsletter Template - Structural Reference

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{{ newsletter_title }} - {{ newsletter_date }}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f4f4f4; font-family: Arial, Helvetica, sans-serif; -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%;">
  <!-- Outer wrapper table for centering -->
  <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="background-color: #f4f4f4;">
    <tr>
      <td style="padding: 20px 0;" align="center">
        <!-- Inner content table - max 600px -->
        <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="600" style="max-width: 600px; background-color: #ffffff; border-radius: 4px; overflow: hidden;">

          <!-- HEADER SECTION -->
          <tr>
            <td style="padding: 30px 40px; background-color: #1a237e; color: #ffffff;">
              <h1 style="margin: 0 0 8px; font-size: 24px; font-weight: 700; color: #ffffff;">{{ newsletter_title }}</h1>
              <p style="margin: 0; font-size: 14px; color: #c5cae9;">{{ newsletter_date }}</p>
            </td>
          </tr>

          <!-- EXECUTIVE SUMMARY -->
          <tr>
            <td style="padding: 30px 40px; border-bottom: 1px solid #e0e0e0;">
              <h2 style="margin: 0 0 16px; font-size: 20px; color: #1a237e;">Executive Summary</h2>
              <ul style="margin: 0; padding-left: 20px;">
                {% for item in executive_summary %}
                <li style="margin-bottom: 10px; font-size: 14px; line-height: 1.6; color: #333333;">
                  <strong>{{ item.topic }}</strong>: {{ item.summary }}
                </li>
                {% endfor %}
              </ul>
            </td>
          </tr>

          <!-- TABLE OF CONTENTS -->
          <tr>
            <td style="padding: 20px 40px; background-color: #f5f5f5; border-bottom: 1px solid #e0e0e0;">
              <h2 style="margin: 0 0 12px; font-size: 16px; color: #1a237e;">In This Issue</h2>
              {% for section in sections %}
              <p style="margin: 4px 0;">
                <a href="#section-{{ loop.index0 }}" style="color: #1565c0; text-decoration: none; font-size: 14px;">{{ section.title }}</a>
              </p>
              {% endfor %}
            </td>
          </tr>

          <!-- TOPIC SECTIONS -->
          {% for section in sections %}
          <tr>
            <td id="section-{{ loop.index0 }}" style="padding: 30px 40px; border-bottom: 1px solid #e0e0e0;">
              <h2 style="margin: 0 0 16px; font-size: 20px; color: #1a237e;">{{ section.title }}</h2>
              <div style="font-size: 14px; line-height: 1.7; color: #333333;">
                {{ section.body_html|safe }}
              </div>
              {% if section.sources %}
              <div style="margin-top: 20px; padding-top: 12px; border-top: 1px solid #e0e0e0;">
                <p style="margin: 0 0 8px; font-size: 12px; font-weight: 700; color: #757575; text-transform: uppercase;">Sources</p>
                <ul style="margin: 0; padding-left: 16px;">
                  {% for src in section.sources %}
                  <li style="margin-bottom: 4px; font-size: 12px;">
                    <a href="{{ src.url }}" style="color: #1565c0; text-decoration: none;">{{ src.title }}</a>
                  </li>
                  {% endfor %}
                </ul>
              </div>
              {% endif %}
            </td>
          </tr>
          {% endfor %}

          <!-- SOURCE APPENDIX -->
          <tr>
            <td style="padding: 30px 40px; background-color: #fafafa; border-bottom: 1px solid #e0e0e0;">
              <h2 style="margin: 0 0 16px; font-size: 18px; color: #1a237e;">All Sources</h2>
              <ol style="margin: 0; padding-left: 20px;">
                {% for src in all_sources %}
                <li style="margin-bottom: 6px; font-size: 12px; line-height: 1.5; color: #555555;">
                  <a href="{{ src.url }}" style="color: #1565c0; text-decoration: none;">{{ src.title }}</a>
                </li>
                {% endfor %}
              </ol>
            </td>
          </tr>

          <!-- FOOTER -->
          <tr>
            <td style="padding: 20px 40px; background-color: #f5f5f5; text-align: center;">
              <p style="margin: 0; font-size: 11px; color: #9e9e9e;">
                Generated by Newsletter Agent | {{ newsletter_date }} | {{ generation_time_seconds|round(1) }}s
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
```

### Sanitizer - Reference Implementation

```python
"""
HTML sanitization for LLM-generated synthesis content.

Converts markdown to safe HTML and strips dangerous tags/attributes.
Spec refs: Section 10.2, OWASP A03 injection mitigation.
"""

import re
import logging

logger = logging.getLogger(__name__)

# Allowed HTML tags after sanitization
_ALLOWED_TAGS = {"a", "p", "strong", "em", "ul", "ol", "li", "h3", "h4", "br"}
_ALLOWED_ATTRIBUTES = {"a": {"href"}}
_ALLOWED_URL_SCHEMES = {"http", "https"}

# Markdown patterns
_MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\)]+)\)")
_MD_BOLD = re.compile(r"\*\*(.+?)\*\*")
_MD_ITALIC = re.compile(r"\*(.+?)\*")
_MD_PARAGRAPH = re.compile(r"\n{2,}")


def sanitize_synthesis_html(markdown_text: str) -> str:
    """Convert markdown to HTML and sanitize for safe email embedding.

    Args:
        markdown_text: Raw markdown text from synthesis agent.

    Returns:
        Sanitized HTML string safe for embedding with Jinja2 |safe filter.
    """
    if not markdown_text:
        return ""

    # Step 1: Convert markdown to HTML
    html = _markdown_to_html(markdown_text)

    # Step 2: Sanitize with nh3
    try:
        import nh3
        return nh3.clean(
            html,
            tags=_ALLOWED_TAGS,
            attributes=_ALLOWED_ATTRIBUTES,
            url_schemes=_ALLOWED_URL_SCHEMES,
        )
    except ImportError:
        logger.warning("nh3 not available, falling back to basic sanitization")
        return _basic_sanitize(html)


def _markdown_to_html(text: str) -> str:
    """Convert basic markdown formatting to HTML."""
    # Convert links first (before other patterns interfere)
    html = _MD_LINK.sub(r'<a href="\2">\1</a>', text)
    # Convert bold
    html = _MD_BOLD.sub(r"<strong>\1</strong>", html)
    # Convert italic
    html = _MD_ITALIC.sub(r"<em>\1</em>", html)
    # Convert paragraphs
    paragraphs = _MD_PARAGRAPH.split(html)
    html = "".join(f"<p>{p.strip()}</p>" for p in paragraphs if p.strip())
    return html


def _basic_sanitize(html: str) -> str:
    """Fallback sanitization when nh3 is not available."""
    # Strip script tags
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Strip iframe tags
    html = re.sub(r"<iframe[^>]*>.*?</iframe>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Strip event handlers
    html = re.sub(r'\s+on\w+\s*=\s*["\'][^"\']*["\']', "", html, flags=re.IGNORECASE)
    # Strip javascript: URLs
    html = re.sub(r'href\s*=\s*["\']javascript:[^"\']*["\']', 'href="#"', html, flags=re.IGNORECASE)
    return html
```

## Additional Reference Implementations

### Synthesis Instruction Prompt - Reference

```python
"""
Synthesis agent instruction prompt template.

Spec refs: FR-016, FR-017, FR-018, FR-019, FR-020, Section 9.1.
"""


def get_synthesis_instruction(topic_names: list[str], topic_count: int) -> str:
    """Generate instruction prompt for the synthesis agent.

    Args:
        topic_names: List of topic names to synthesize.
        topic_count: Number of topics.

    Returns:
        Complete instruction string for the synthesis LlmAgent.
    """
    topics_listing = "\n".join(
        f"  - Topic {i}: \"{name}\" (state keys: research_{i}_google, research_{i}_perplexity)"
        for i, name in enumerate(topic_names)
    )

    return f"""You are a senior research analyst producing a professional newsletter synthesis.

TASK:
Analyze the research data in session state and produce a deep, well-cited analysis for each topic, plus an executive summary.

TOPICS TO SYNTHESIZE ({topic_count} topics):
{topics_listing}

FOR EACH TOPIC:
Read the research results from the corresponding session state keys (research_N_google and research_N_perplexity). Some keys may contain error markers (error: true) indicating that provider failed - work with whatever data is available.

PRODUCE:
1. A multi-paragraph analysis section (minimum 200 words per topic)
2. Cross-reference findings from multiple sources when available
3. Include at least 3 inline citations in [Source Title](URL) format
4. Highlight key developments, trends, data points, and implications
5. An executive summary with 1-3 sentences per topic

OUTPUT FORMAT:
You MUST output a valid JSON object with exactly this structure:
{{{{
  "executive_summary": [
    {{{{"topic": "Topic Name", "summary": "1-3 sentence overview of key finding."}}}}
  ],
  "sections": [
    {{{{
      "title": "Topic Name",
      "body_markdown": "Multi-paragraph analysis text with [Source Title](URL) inline citations. This must be at least 200 words. Cross-reference findings from multiple search providers when available. Highlight key trends, data points, and implications.",
      "sources": [{{{{"url": "https://...", "title": "Source Title"}}}}]
    }}}}
  ]
}}}}

CRITICAL RULES:
- NEVER fabricate facts, statistics, quotes, or data points not present in the research results
- NEVER invent or guess source URLs - use ONLY URLs that appear in the research data
- If a research source has error=true, note that the provider was unavailable
- If ALL research for a topic failed, state: "Research was unavailable for this topic in this cycle."
- Every [Source Title](URL) citation MUST reference a real URL from the research results
- The executive_summary must have exactly {topic_count} entries, one per topic
- The sections must have exactly {topic_count} entries, one per topic, in the same order

QUALITY GUIDELINES:
- Write in a professional, analytical tone suitable for a senior tech audience
- Lead each section with the most important finding or development
- Provide context and explain why developments matter
- Include specific dates, version numbers, and data points when available
- End each section with forward-looking implications or next steps to watch"""
```

### Synthesis Post-Processing - Reference

```python
"""
Utilities for parsing synthesis agent output into structured state entries.

Spec refs: FR-018, FR-019, Section 7.5, Section 7.6.
"""

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def parse_synthesis_output(
    raw_output: str, expected_topics: list[str]
) -> dict[str, Any]:
    """Parse raw synthesis agent output into structured state entries.

    Args:
        raw_output: Raw text output from the synthesis LlmAgent.
        expected_topics: List of expected topic names in order.

    Returns:
        dict with keys:
            - synthesis_0, synthesis_1, ... (SynthesisResult dicts per Section 7.5)
            - executive_summary (list of {topic, summary} dicts)
            - _parse_errors (list of str, if any parse issues occurred)
    """
    result = {}
    errors = []

    # Attempt JSON parsing with multiple strategies
    parsed_json = _extract_json(raw_output)

    if parsed_json:
        # Parse executive summary
        exec_summary = parsed_json.get("executive_summary", [])
        if isinstance(exec_summary, list):
            result["executive_summary"] = [
                {
                    "topic": item.get("topic", f"Topic {i}"),
                    "summary": item.get("summary", "Summary unavailable."),
                }
                for i, item in enumerate(exec_summary)
            ]
        else:
            errors.append("executive_summary is not a list")
            result["executive_summary"] = [
                {"topic": name, "summary": "Summary unavailable."}
                for name in expected_topics
            ]

        # Parse sections
        sections = parsed_json.get("sections", [])
        if isinstance(sections, list):
            for i, section in enumerate(sections):
                key = f"synthesis_{i}"
                result[key] = {
                    "title": section.get("title", expected_topics[i] if i < len(expected_topics) else f"Topic {i}"),
                    "body_markdown": section.get("body_markdown", "Synthesis unavailable for this topic."),
                    "sources": _normalize_sources(section.get("sources", [])),
                }
        else:
            errors.append("sections is not a list")

    else:
        # Fallback: text-based parsing
        errors.append("Could not parse JSON from synthesis output")
        result = _fallback_text_parse(raw_output, expected_topics)

    # Ensure all expected topics have entries
    for i, name in enumerate(expected_topics):
        key = f"synthesis_{i}"
        if key not in result:
            errors.append(f"Missing synthesis for topic {i}: {name}")
            result[key] = {
                "title": name,
                "body_markdown": "Synthesis was not produced for this topic.",
                "sources": [],
            }

    if "executive_summary" not in result:
        result["executive_summary"] = [
            {"topic": name, "summary": "Summary unavailable."}
            for name in expected_topics
        ]

    if errors:
        result["_parse_errors"] = errors
        logger.warning("Synthesis parse issues: %s", "; ".join(errors))

    return result


def _extract_json(text: str) -> dict | None:
    """Extract JSON from text, trying multiple strategies."""
    # Strategy 1: Direct JSON parse
    try:
        parsed = json.loads(text.strip())
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass

    # Strategy 2: Extract from markdown code block
    code_block_match = re.search(
        r"```(?:json)?\s*\n?(.*?)\n?```",
        text,
        re.DOTALL,
    )
    if code_block_match:
        try:
            parsed = json.loads(code_block_match.group(1).strip())
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass

    # Strategy 3: Find JSON object boundaries
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end > brace_start:
        try:
            parsed = json.loads(text[brace_start : brace_end + 1])
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass

    return None


def _fallback_text_parse(
    text: str, expected_topics: list[str]
) -> dict[str, Any]:
    """Parse synthesis output as plain text when JSON parsing fails."""
    result = {}

    # Try to split by topic headings
    for i, name in enumerate(expected_topics):
        # Look for heading-like patterns
        pattern = re.compile(
            rf"(?:#{1,3}\s*)?{re.escape(name)}.*?\n(.*?)(?=(?:#{1,3}\s)|$)",
            re.DOTALL | re.IGNORECASE,
        )
        match = pattern.search(text)
        body = match.group(1).strip() if match else "Synthesis unavailable."

        result[f"synthesis_{i}"] = {
            "title": name,
            "body_markdown": body,
            "sources": _extract_links_from_text(body),
        }

    # Generate basic executive summary from first sentences
    result["executive_summary"] = [
        {
            "topic": name,
            "summary": _first_sentence(result.get(f"synthesis_{i}", {}).get("body_markdown", "")),
        }
        for i, name in enumerate(expected_topics)
    ]

    return result


def _first_sentence(text: str) -> str:
    """Extract the first sentence from text."""
    match = re.match(r"([^.!?]+[.!?])", text)
    return match.group(1) if match else text[:200] + "..."


def _extract_links_from_text(text: str) -> list[dict]:
    """Extract markdown links from text."""
    links = re.findall(r"\[([^\]]+)\]\((https?://[^\)]+)\)", text)
    seen = set()
    sources = []
    for title, url in links:
        if url not in seen:
            seen.add(url)
            sources.append({"url": url, "title": title})
    return sources


def _normalize_sources(raw_sources: list) -> list[dict]:
    """Normalize source list to Section 7.4 format."""
    seen = set()
    sources = []
    for src in raw_sources:
        if isinstance(src, dict) and "url" in src:
            url = str(src["url"])
            if url not in seen:
                seen.add(url)
                sources.append({
                    "url": url,
                    "title": str(src.get("title", url)),
                })
    return sources
```

### Formatter Agent - Reference Implementation

```python
"""
Newsletter formatter agent - renders HTML from synthesis state data.

Spec refs: FR-021, FR-022, FR-026, Section 9.1.
"""

import os
import logging
from datetime import date, timezone, datetime
from typing import AsyncGenerator

import jinja2
from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.genai import types

from newsletter_agent.tools.sanitizer import sanitize_synthesis_html

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")

_jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(_TEMPLATE_DIR),
    autoescape=True,
)


class FormatterAgent(BaseAgent):
    """Custom BaseAgent that renders the newsletter HTML from synthesis state."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[types.Content, None]:
        state = ctx.session.state
        config_title = state.get("config_newsletter_title", "Newsletter")
        today = date.today().isoformat()

        # Collect synthesis sections
        sections = []
        all_sources = []
        topic_index = 0

        while True:
            key = f"synthesis_{topic_index}"
            section_data = state.get(key)
            if section_data is None:
                break

            # Sanitize body content before rendering
            body_html = sanitize_synthesis_html(
                section_data.get("body_markdown", "")
            )

            section = {
                "title": section_data.get("title", f"Topic {topic_index}"),
                "body_html": body_html,
                "sources": section_data.get("sources", []),
            }
            sections.append(section)
            all_sources.extend(section["sources"])
            topic_index += 1

        # Deduplicate all sources
        seen_urls = set()
        unique_sources = []
        for src in all_sources:
            url = src.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_sources.append(src)

        # Get executive summary
        executive_summary = state.get("executive_summary", [])

        # Calculate generation time
        start_time = state.get("pipeline_start_time")
        gen_time = 0.0
        if start_time:
            gen_time = (datetime.now(timezone.utc) - datetime.fromisoformat(start_time)).total_seconds()

        # Build template context
        template_data = {
            "newsletter_title": config_title,
            "newsletter_date": today,
            "executive_summary": executive_summary,
            "sections": sections,
            "all_sources": unique_sources,
            "generation_time_seconds": gen_time,
        }

        # Render template
        template = _jinja_env.get_template("newsletter.html.j2")
        newsletter_html = template.render(**template_data)

        # Store in state
        state["newsletter_html"] = newsletter_html
        state["newsletter_metadata"] = {
            "title": config_title,
            "date": today,
            "topic_count": len(sections),
            "generation_time_seconds": gen_time,
        }

        logger.info(
            "Newsletter formatted: %d sections, %d sources, %d chars HTML",
            len(sections),
            len(unique_sources),
            len(newsletter_html),
        )

        yield types.Content(
            parts=[types.Part(text=f"Newsletter formatted: {len(sections)} sections")]
        )
```

### Test Fixtures for Template Rendering

```python
"""
Shared test fixtures for synthesis and formatting tests.
"""

import pytest


@pytest.fixture
def mock_single_topic_synthesis():
    """Mock synthesis data for a single topic."""
    return {
        "synthesis_0": {
            "title": "AI Frameworks",
            "body_markdown": (
                "The AI framework landscape has seen significant shifts in recent months. "
                "Google's [Agent Development Kit](https://google.github.io/adk-docs/) has "
                "emerged as a strong contender for building multi-agent systems, offering "
                "native Gemini integration and built-in tools like Google Search grounding.\n\n"
                "Meanwhile, [LangChain v0.3](https://langchain.com/blog) has focused on "
                "simplifying its API surface and improving developer experience. The framework "
                "now supports more efficient chain composition and better error handling.\n\n"
                "Industry analysts note that the market is consolidating around a few key "
                "players. According to [TechCrunch](https://techcrunch.com/ai-agents), "
                "enterprise adoption of AI agent frameworks grew 340% in Q4 2025, with "
                "Google ADK and LangChain leading in market share."
            ),
            "sources": [
                {"url": "https://google.github.io/adk-docs/", "title": "ADK Documentation"},
                {"url": "https://langchain.com/blog", "title": "LangChain Blog"},
                {"url": "https://techcrunch.com/ai-agents", "title": "TechCrunch AI Agents"},
            ],
        },
        "executive_summary": [
            {
                "topic": "AI Frameworks",
                "summary": "Google ADK and LangChain dominate the AI agent framework market, with enterprise adoption growing 340% in Q4 2025.",
            }
        ],
    }


@pytest.fixture
def mock_three_topic_synthesis():
    """Mock synthesis data for three topics."""
    return {
        "synthesis_0": {
            "title": "AI Frameworks",
            "body_markdown": "The AI framework landscape continues to evolve rapidly...",
            "sources": [{"url": "https://example.com/ai", "title": "AI Source"}],
        },
        "synthesis_1": {
            "title": "Cloud Native",
            "body_markdown": "Cloud-native technologies are reaching new maturity levels...",
            "sources": [{"url": "https://example.com/cloud", "title": "Cloud Source"}],
        },
        "synthesis_2": {
            "title": "Cybersecurity",
            "body_markdown": "The threat landscape has shifted dramatically with AI-powered attacks...",
            "sources": [{"url": "https://example.com/security", "title": "Security Source"}],
        },
        "executive_summary": [
            {"topic": "AI Frameworks", "summary": "ADK and LangChain lead the pack."},
            {"topic": "Cloud Native", "summary": "Kubernetes adoption reaches 78% in enterprises."},
            {"topic": "Cybersecurity", "summary": "AI-powered attacks increase 200% year-over-year."},
        ],
    }


@pytest.fixture
def mock_failed_topic_synthesis():
    """Mock synthesis with one failed topic."""
    return {
        "synthesis_0": {
            "title": "AI Frameworks",
            "body_markdown": "Results available for this topic...",
            "sources": [{"url": "https://example.com", "title": "Source"}],
        },
        "synthesis_1": {
            "title": "Unavailable Topic",
            "body_markdown": "Research was unavailable for this topic in this cycle.",
            "sources": [],
        },
        "executive_summary": [
            {"topic": "AI Frameworks", "summary": "Key findings available."},
            {"topic": "Unavailable Topic", "summary": "Research was unavailable for this topic."},
        ],
    }
```

## Detailed Edge Cases and Validation Rules

### Synthesis Edge Cases

1. **Research data with error markers**: When `research_{N}_{provider}` contains `{"error": true, "message": "..."}`, the synthesis agent must recognize this and note the provider was unavailable. The synthesis instruction must explicitly handle this case.

2. **All research failed for a topic**: When both `research_{N}_google` and `research_{N}_perplexity` are error markers, the synthesis for that topic should state "Research was unavailable for this topic in this cycle." The executive summary entry for that topic should also reflect this.

3. **Mixed research quality**: When one provider returns rich data with many sources and the other returns sparse data, the synthesis should weight the rich data more heavily but still note both providers.

4. **Very long research results**: When providers return very detailed responses (5000+ characters), the synthesis agent must distill key findings rather than just concatenating. The prompt should guide selective analysis.

5. **Conflicting information between providers**: When Google Search and Perplexity return contradictory information, the synthesis should note the discrepancy: "According to [Source A], X, while [Source B] reports Y."

6. **Duplicate sources across providers**: Both Google and Perplexity may cite the same source URL. The synthesis sources list must be deduplicated by URL.

7. **Non-English content in research results**: Although the system is English-only (A-006), search results may contain snippets in other languages. The synthesis should work in English regardless.

8. **Research results with no source URLs**: Some search results may include text but no extractable source URLs. The synthesis should still produce analysis but note limited citation ability.

### Formatting Edge Cases

1. **Empty executive summary**: If the synthesis post-processing fails to extract executive summary entries, the template should render a fallback message instead of crashing.

2. **Single topic newsletter**: A newsletter with only 1 topic should still have a proper TOC (with 1 entry), executive summary (with 1 bullet), and source appendix.

3. **20 topic newsletter**: The maximum topic count (20) should render without layout issues. The TOC may become very long; this is acceptable for MVP.

4. **Topic names with HTML special characters**: Names like `"AI & Machine Learning"` or `"C++ Frameworks"` must be properly escaped in the HTML output. Jinja2 autoescaping handles this automatically.

5. **Very long topic names**: Names up to 100 characters (spec max) should not break the layout. Long names should wrap naturally within the 600px container.

6. **Source URLs with special characters**: URLs containing query parameters, fragments, or encoded characters must be preserved correctly in `<a href="...">` attributes.

7. **Empty source appendix**: If no topics had any source URLs, the source appendix section should either be hidden or show a message.

8. **Generation time edge cases**: If `pipeline_start_time` is not set in state (e.g., during testing), `generation_time_seconds` should default to 0.

### Security Validation Rules

1. **Jinja2 autoescaping MUST be enabled**: The `jinja2.Environment` must be created with `autoescape=True`. This is the primary XSS defense.

2. **The `|safe` filter MUST only be used on nh3-sanitized content**: The `body_html` field in template sections must be the output of `sanitize_synthesis_html()`, never raw LLM output.

3. **Source URLs in `<a href="...">` MUST be validated**: Only `http://` and `https://` schemes are allowed. The sanitizer must strip `javascript:`, `data:`, and other dangerous URI schemes.

4. **No external resource loading**: The template must not include `<link>`, `<script>`, `<img src="http://...">`, or any other external resource references. All content must be self-contained inline HTML + CSS.

5. **Jinja2 template sandboxing**: Although we control the template (it is not user-provided), the `autoescape=True` setting provides defense-in-depth against any content that might contain template injection patterns.

### Validation Checklist for Formatter Output

The following checks should be performed on every formatted newsletter:

- [ ] HTML is valid (no unclosed tags, proper nesting)
- [ ] All CSS is inline (no `<style>` blocks, no `<link>` tags)
- [ ] Executive summary has exactly N bullet items (one per topic)
- [ ] TOC has exactly N linked entries
- [ ] Each topic section has a heading, body, and source list
- [ ] Source appendix contains deduplicated sources from all sections
- [ ] Footer contains generation date and timing
- [ ] No `<script>`, `<iframe>`, `<form>` tags present anywhere
- [ ] All `<a>` links use only `http://` or `https://` schemes
- [ ] Max-width 600px is set on the outer content container

## Implementation Notes

### Development Sequence

1. Start with T03-01 (synthesis prompt), T03-02 (post-processing), T03-03 (template), T03-04 (sanitizer) in parallel
2. Then T03-05 (formatter agent) which wires template + sanitizer together
3. Then T03-06 (synthesis agent wiring) and T03-07 (formatter wiring)
4. Finally T03-08 through T03-11 (tests)

### Key Quality Consideration

The synthesis agent's output quality is the single most important factor in newsletter quality. During development:
- Test with real API keys and inspect the actual Gemini Pro output
- Iterate on the synthesis prompt (T03-01) until the output consistently meets the 200-word, 3-citation minimum
- Compare standard vs deep search depth synthesis quality

### Markdown-to-HTML Pipeline

The content pipeline is: Research (raw text + sources) -> Synthesis (markdown with inline links) -> Sanitizer (safe HTML) -> Template (complete email HTML). Each step must preserve the information needed by the next step.

### Key Commands

```bash
# Run unit tests for this WP
pytest tests/test_synthesis_utils.py tests/test_sanitizer.py tests/test_html_formatter.py -v

# Run BDD tests
pytest tests/bdd/test_synthesis_formatting.py -v

# Run all WP03 tests with coverage
pytest tests/test_synthesis_utils.py tests/test_sanitizer.py tests/test_html_formatter.py tests/bdd/test_synthesis_formatting.py --cov=newsletter_agent -v

# Render a test newsletter and inspect in browser
# (create a script or use adk web with dry_run)
adk web
```

### BDD Test Reference Implementation

```python
"""
BDD-style acceptance tests for synthesis and formatting.

Uses Given/When/Then structure to verify spec scenarios.
Spec refs: Section 11.2, US-03, US-04, US-08.
"""

import pytest
import json
from unittest.mock import MagicMock, patch, AsyncMock

from newsletter_agent.tools.synthesis_utils import parse_synthesis_output
from newsletter_agent.tools.sanitizer import sanitize_synthesis_html


class TestSynthesisDeepAnalysis:
    """Feature: Synthesis - Scenario: Deep analysis with citations"""

    def test_deep_analysis_meets_word_count_minimum(self):
        """
        Given completed research for a topic from both Google and Perplexity
        When the synthesis output is parsed
        Then the body_markdown is at least 200 words
        """
        synthesis_json = json.dumps({
            "executive_summary": [
                {"topic": "AI", "summary": "AI continues to advance."}
            ],
            "sections": [{
                "title": "AI",
                "body_markdown": " ".join(["word"] * 250) + " [Source](https://example.com)",
                "sources": [{"url": "https://example.com", "title": "Source"}],
            }],
        })

        result = parse_synthesis_output(synthesis_json, ["AI"])
        body = result["synthesis_0"]["body_markdown"]
        word_count = len(body.split())
        assert word_count >= 200

    def test_deep_analysis_contains_inline_citations(self):
        """
        Given completed research with source URLs
        When synthesis is produced
        Then the output contains at least 3 inline [Title](URL) citations
        """
        body = (
            "According to [Source A](https://a.com), progress continues. "
            "Meanwhile [Source B](https://b.com) reports growth. "
            "Experts at [Source C](https://c.com) agree. "
            "Additionally [Source D](https://d.com) notes trends."
        )
        synthesis_json = json.dumps({
            "executive_summary": [{"topic": "AI", "summary": "Progress."}],
            "sections": [{
                "title": "AI",
                "body_markdown": body,
                "sources": [
                    {"url": "https://a.com", "title": "Source A"},
                    {"url": "https://b.com", "title": "Source B"},
                    {"url": "https://c.com", "title": "Source C"},
                    {"url": "https://d.com", "title": "Source D"},
                ],
            }],
        })

        result = parse_synthesis_output(synthesis_json, ["AI"])
        import re
        citations = re.findall(
            r"\[([^\]]+)\]\((https?://[^\)]+)\)",
            result["synthesis_0"]["body_markdown"],
        )
        assert len(citations) >= 3


class TestSynthesisPartialResearch:
    """Feature: Synthesis - Scenario: Synthesis with partial research"""

    def test_partial_research_still_produces_output(self):
        """
        Given research results from only 1 provider (other failed)
        When synthesis is parsed
        Then output is still produced using available data
        """
        synthesis_json = json.dumps({
            "executive_summary": [
                {"topic": "AI", "summary": "Based on limited sources, AI progresses."}
            ],
            "sections": [{
                "title": "AI",
                "body_markdown": "Based on Google Search results only (Perplexity was unavailable)...",
                "sources": [{"url": "https://google.com/result", "title": "Google Result"}],
            }],
        })

        result = parse_synthesis_output(synthesis_json, ["AI"])
        assert "synthesis_0" in result
        assert result["synthesis_0"]["body_markdown"]
        assert len(result["synthesis_0"]["sources"]) >= 1


class TestNewsletterFormatting:
    """Feature: Newsletter Formatting"""

    def test_complete_html_contains_all_sections(self):
        """
        Given synthesis results for 3 topics and an executive summary
        When the formatter renders the template
        Then the HTML contains all required sections in correct order
        """
        # This test requires rendering the Jinja2 template
        import jinja2
        import os

        template_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "newsletter_agent", "templates"
        )

        if not os.path.exists(os.path.join(template_dir, "newsletter.html.j2")):
            pytest.skip("Template not yet created")

        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(template_dir),
            autoescape=True,
        )
        template = env.get_template("newsletter.html.j2")

        html = template.render(
            newsletter_title="Test Newsletter",
            newsletter_date="2026-03-14",
            executive_summary=[
                {"topic": "T1", "summary": "S1"},
                {"topic": "T2", "summary": "S2"},
                {"topic": "T3", "summary": "S3"},
            ],
            sections=[
                {"title": "T1", "body_html": "<p>Body 1</p>", "sources": []},
                {"title": "T2", "body_html": "<p>Body 2</p>", "sources": []},
                {"title": "T3", "body_html": "<p>Body 3</p>", "sources": []},
            ],
            all_sources=[],
            generation_time_seconds=120.0,
        )

        # Verify section order: title appears before exec summary before TOC before sections
        title_pos = html.find("Test Newsletter")
        exec_pos = html.find("Executive Summary")
        toc_pos = html.find("In This Issue")

        assert title_pos < exec_pos < toc_pos
        assert "T1" in html
        assert "T2" in html
        assert "T3" in html
```

## Parallel Opportunities

- T03-01 (synthesis prompt), T03-02 (post-processing), T03-03 (template), T03-04 (sanitizer) are all independent
- T03-08, T03-09, T03-10 can be developed concurrently after their respective implementation tasks

## Risks & Mitigations

- **Risk**: Gemini Pro synthesis output quality may not consistently meet the 200-word, 3-citation minimum.
  **Mitigation**: Iterate on the synthesis prompt. Add explicit length/citation requirements. Consider adding a validation step that retries synthesis if output is too short.

- **Risk**: LLM may not produce valid JSON for synthesis output, breaking post-processing.
  **Mitigation**: Implement robust JSON extraction with multiple fallback strategies (code block extraction, lenient parsing, text-based fallback). Never depend on perfect JSON.

- **Risk**: Gmail may strip or modify parts of the HTML template, breaking layout.
  **Mitigation**: Use table-based layout (most robust for email), inline all CSS, test by sending actual emails to Gmail and inspecting rendering. Avoid CSS features with poor email client support.

- **Risk**: nh3 package may not be available on all platforms or Python versions.
  **Mitigation**: Include a basic fallback sanitizer using regex. The fallback is less secure but provides baseline protection. Document nh3 as the recommended dependency.

- **Risk**: The synthesis agent may fabricate sources despite the prompt prohibition.
  **Mitigation**: Add a post-processing validation step that checks all cited URLs against the source URLs from the research phase. Flag or remove citations that do not appear in research results.

- **Risk**: Jinja2 autoescaping may double-escape content that has already been HTML-encoded.
  **Mitigation**: Use `|safe` filter only on content that has been explicitly sanitized by nh3. Do not mix autoescaped and safe content in the same template variable.

## Spec Compliance Checklist

### T03-01 Spec Compliance Checklist
- [x] File exports `get_synthesis_instruction(topic_names, topic_count) -> str` - verified in synthesis.py
- [x] Instruction tells agent to read `research_{N}_{provider}` keys from state - verified in synthesis.py
- [x] Instruction requires multi-paragraph with minimum 200 words - verified in synthesis.py
- [x] Instruction requires inline citations in `[Source Title](URL)` format - verified in synthesis.py
- [x] Instruction explicitly prohibits fabricating facts, statistics, or source URLs - verified in synthesis.py
- [x] Instruction requires executive summary with 1-3 sentence overview per topic - verified in synthesis.py
- [x] Instruction specifies `synthesis_{N}` output format with title, body_markdown, sources - verified in synthesis.py
- [x] Instruction specifies `executive_summary` state key format - verified in synthesis.py

### T03-02 Spec Compliance Checklist
- [x] `parse_synthesis_output(raw_output, expected_topics) -> dict` exists - verified in synthesis_utils.py
- [x] Valid JSON returns dict with `synthesis_0`, `synthesis_1`, etc. and `executive_summary` - verified in synthesis_utils.py
- [x] Each `synthesis_{N}` is a dict with title, body_markdown, sources - verified in synthesis_utils.py
- [x] `executive_summary` is a list of dicts with topic and summary - verified in synthesis_utils.py
- [x] Invalid JSON triggers fallback parsing attempt - verified in synthesis_utils.py
- [x] Completely unparseable output returns minimal valid structure - verified in synthesis_utils.py (`_fallback_output`)
- [x] Function never raises an exception - verified in synthesis_utils.py

### T03-03 Spec Compliance Checklist
- [x] File `newsletter.html.j2` exists - verified in templates/
- [x] Valid HTML5, all CSS inline, no `<link>` tags or external stylesheets - verified in newsletter.html.j2
- [x] Sections in order: title+date, exec summary, TOC, topic sections, source appendix, footer - verified
- [x] Executive summary displays topics as bulleted list items - verified in newsletter.html.j2
- [x] TOC contains anchor links for each topic section - verified in newsletter.html.j2
- [x] Each topic section has heading, body with citations, source list - verified in newsletter.html.j2
- [x] Source appendix lists all sources from all topics - verified in newsletter.html.j2
- [x] Single-column layout with max-width 600px centered - verified in newsletter.html.j2
- [x] Web-safe font stacks (Arial, Helvetica, sans-serif) - verified in newsletter.html.j2
- [x] Clean professional palette with sufficient contrast - verified in newsletter.html.j2
- [x] Jinja2 autoescaping enabled - verified in formatter.py (`autoescape=True`)

### T03-04 Spec Compliance Checklist
- [x] `sanitize_synthesis_html(markdown_text) -> str` exists - verified in sanitizer.py
- [x] Markdown inline links converted to HTML `<a>` tags - verified in sanitizer.py (via markdown library)
- [x] Basic markdown formatting converted to HTML - verified in sanitizer.py
- [x] Dangerous HTML tags stripped - verified in sanitizer.py (nh3.clean with ALLOWED_TAGS)
- [x] XSS payloads neutralized - verified in sanitizer.py (nh3.clean)
- [x] Safe tags preserved - verified in sanitizer.py (ALLOWED_TAGS whitelist)
- [x] Only `href` on `<a>` tags, only http/https schemes - verified in sanitizer.py

### T03-05 Spec Compliance Checklist
- [x] Formatter component exists as BaseAgent subclass - verified in formatter.py
- [x] Reads `synthesis_{N}` and `executive_summary` from state - verified in formatter.py
- [x] Sanitizes all body content through sanitizer before rendering - verified in formatter.py
- [x] Renders Jinja2 template with all required data - verified in formatter.py
- [x] Stores HTML in state as `newsletter_html` - verified in formatter.py
- [x] Stores metadata in state as `newsletter_metadata` - verified in formatter.py
- [x] Missing synthesis section produces "Research unavailable" note - verified in formatter.py
- [x] Deduplicates all sources for source appendix - verified in formatter.py

### T03-06 Spec Compliance Checklist
- [x] Synthesis LlmAgent exists with model `gemini-2.5-pro` - verified in agent.py
- [x] Instruction generated by `get_synthesis_instruction()` - verified in agent.py
- [x] `output_key` stores raw output as `synthesis_raw` - verified in agent.py
- [x] Post-processing step parses raw output into `synthesis_{N}` and `executive_summary` - verified in agent.py (SynthesisPostProcessorAgent)
- [x] Synthesis agent wired into root SequentialAgent after research phase - verified in agent.py

### T03-07 Spec Compliance Checklist
- [x] Formatter wired into root SequentialAgent after synthesis - verified in agent.py (OutputPhase)
- [x] `newsletter_html` contains complete HTML document - verified in formatter.py
- [x] `newsletter_metadata` contains title, date, topic_count, generation_time_seconds - verified in formatter.py
- [x] Dry-run mode reaches formatter without sending email - verified in agent.py

### T03-08 Spec Compliance Checklist
- [x] Test file exists with at least 10 test cases - verified in test_synthesis_utils.py (17+ tests)
- [x] Tests verify function never raises exception - verified in test_synthesis_utils.py
- [x] Tests verify output structure matches SynthesisResult schema - verified
- [x] All tests pass - verified

### T03-09 Spec Compliance Checklist
- [x] Test file exists with at least 12 test cases - verified in test_sanitizer.py (16+ tests)
- [x] Tests verify markdown link conversion - verified
- [x] Tests verify markdown formatting - verified
- [x] Tests verify allowed tags pass through - verified
- [x] Tests verify disallowed tags stripped - verified
- [x] Tests verify only http/https URL schemes allowed - verified
- [x] All tests pass - verified

### T03-10 Spec Compliance Checklist
- [x] Test file exists with at least 8 test cases - verified in test_html_formatter.py (18+ tests)
- [x] Tests render with 1, 3, and 5 topic configurations - verified
- [x] Tests verify all sections present in order - verified
- [x] Tests verify executive summary has bulleted items - verified
- [x] Tests verify TOC has anchor links - verified
- [x] Tests verify all CSS is inline - verified
- [x] Tests verify max-width 600px - verified
- [x] Tests verify graceful handling of missing data - verified
- [x] All tests pass - verified

### T03-11 Spec Compliance Checklist
- [x] Test file exists with at least 6 BDD scenarios - verified in test_synthesis_formatting.py (6 classes)
- [x] Scenario: Deep analysis with citations - verified
- [x] Scenario: Synthesis with partial research - verified
- [x] Scenario: Synthesis with no research data - verified
- [x] Scenario: Complete HTML newsletter with all sections - verified
- [x] Scenario: Executive summary generation - verified
- [x] Scenario: Responsive layout verification - verified
- [x] All tests pass - verified

## Activity Log

- 2025-01-01T00:00:00Z - planner - lane=planned - Work package created
- 2026-03-14T00:00:00Z - reviewer - lane=to_do - Verdict: Changes Required (4 FAILs) -- awaiting remediation
- 2026-03-14T05:00:00Z - coder - lane=doing - Addressing reviewer feedback (FB-01, FB-02, FB-03, FB-04)
- 2026-03-14T06:00:00Z - coder - lane=for_review - All feedback items addressed, resubmitted for review

## Review

> **Reviewed by**: Reviewer Agent
> **Date**: 2026-03-14
> **Verdict**: Changes Required
> **review_status**: has_feedback

### Summary

Changes Required. The WP has one critical functional failure: `parse_synthesis_output()` is implemented and thoroughly tested but never called in the production pipeline. The synthesis LlmAgent stores raw JSON as `synthesis_raw` in session state, but no component converts it into the `synthesis_{N}` and `executive_summary` state keys that the FormatterAgent reads. At runtime, the pipeline would produce a newsletter with zero topic sections. Additionally, three process compliance failures: no Spec Compliance Checklist, no coder activity log entries, and all 11 tasks batched into a single commit.

### Review Feedback

> Implementers: if `review_status: has_feedback` is set in the WP frontmatter, address every item below before returning for re-review. Update `review_status: acknowledged` once you begin remediation.

- [x] **FB-01**: Wire `parse_synthesis_output()` into the pipeline between the synthesis LlmAgent and the FormatterAgent. After the Synthesizer agent runs, its `synthesis_raw` output must be parsed into `synthesis_{N}` and `executive_summary` state keys. Implement as either: (a) a custom BaseAgent wrapper around the LlmAgent that calls `parse_synthesis_output()` after the LLM responds and writes the parsed results to state, or (b) a standalone post-processing BaseAgent inserted as a step between the Synthesizer and the OutputPhase in the root SequentialAgent.
- [x] **FB-02**: In `FormatterAgent._run_async_impl`, add handling for missing synthesis sections. The formatter must know the expected topic count (e.g., by reading a `config_topic_count` or `config_topic_names` state key). When `synthesis_{N}` is None for an expected topic, insert a section with "Research unavailable for this topic" instead of silently omitting it. This is required by T03-05 acceptance criterion. **RESOLVED**: FormatterAgent now reads `config_topic_count` from state and inserts placeholder sections.
- [x] **FB-03**: Add Spec Compliance Checklist (Step 2b) to the WP file for each task (T03-01 through T03-11) and check off each acceptance criterion. **RESOLVED**: Checklist added above Activity Log section.
- [x] **FB-04**: Add Activity Log entries for coder lane transitions (lane=doing, task completions, lane=for_review). **RESOLVED**: Activity Log entries added.

### Findings

#### FAIL - Process Compliance: Spec Compliance Checklist
- **Requirement**: Step 2b process requirement
- **Status**: Missing
- **Detail**: No Spec Compliance Checklist exists in the WP file for any of the 11 tasks.
- **Evidence**: WP file contains no "Spec Compliance Checklist" or "Step 2b" section.

#### FAIL - Process Compliance: Activity Log
- **Requirement**: Activity Log entries for coder lane transitions
- **Status**: Missing
- **Detail**: Activity Log only contains the planner's initial entry. No coder entries for `lane=doing`, task completions, or `lane=for_review`.
- **Evidence**: [Activity Log](WP03-synthesis-formatting.md#L1555) shows only one entry.

#### FAIL - Process Compliance: Commit Discipline
- **Requirement**: One commit per task
- **Status**: Deviating
- **Detail**: All 11 WP03 tasks (T03-01 through T03-11) are batched into a single commit `a3e3f63 feat(synthesis): add synthesis, sanitizer, formatter, HTML template with tests (WP03)` instead of one commit per task.
- **Evidence**: `git log --oneline` shows only one WP03-related commit.

#### FAIL - Spec Adherence: Synthesis Post-Processing Wiring (FR-019, FR-026, T03-06)
- **Requirement**: FR-019 (synthesis state structure), FR-026 (newsletter_html in state), T03-06 AC "A post-processing step parses the raw output into `synthesis_{N}` and `executive_summary` state keys"
- **Status**: Missing
- **Detail**: `parse_synthesis_output()` in [newsletter_agent/tools/synthesis_utils.py](newsletter_agent/tools/synthesis_utils.py) is correctly implemented and has 22 passing unit tests, but it is **never imported or called anywhere in production code**. The synthesis LlmAgent has `output_key="synthesis_raw"` ([agent.py line 97](newsletter_agent/agent.py#L97)), storing raw JSON text. The FormatterAgent reads `synthesis_{N}` keys from state ([formatter.py lines 60-64](newsletter_agent/tools/formatter.py#L60-L64)), which are never populated. At runtime, the `while True` loop in FormatterAgent immediately breaks on the first iteration (`synthesis_0` is None), producing a newsletter with 0 sections, empty source appendix, and empty executive summary.
- **Evidence**: `grep -r "parse_synthesis_output" newsletter_agent/` returns zero matches. `grep -r "synthesis_utils" newsletter_agent/` returns zero matches. The function is only imported in test files.

#### FAIL - Spec Adherence: Missing Topic Fallback (T03-05)
- **Requirement**: T03-05 AC "If a synthesis section is missing for a topic, the formatter includes a 'Research unavailable' note instead of failing"
- **Status**: Deviating
- **Detail**: FormatterAgent silently omits missing topics by breaking out of the while loop when `section_data is None`. No "Research unavailable" note is inserted. The formatter also has no way to know the expected topic count to detect gaps.
- **Evidence**: [formatter.py lines 60-64](newsletter_agent/tools/formatter.py#L60-L64): `if section_data is None: break`

#### PASS - Spec Adherence: Synthesis Prompt (FR-016, FR-017, FR-018, FR-020, T03-01)
- **Requirement**: FR-016 through FR-020
- **Status**: Compliant
- **Detail**: The synthesis instruction prompt correctly requires 200+ word analysis, inline [Title](URL) citations, executive summary with 1-3 sentences per topic, explicit prohibition on fabricating facts/sources. Output format matches Section 7.5 SynthesisResult structure.
- **Evidence**: [newsletter_agent/prompts/synthesis.py](newsletter_agent/prompts/synthesis.py)

#### PASS - Spec Adherence: HTML Template (FR-021, FR-022, FR-023, FR-024, FR-025)
- **Requirement**: FR-021 through FR-025
- **Status**: Compliant
- **Detail**: Template uses inline CSS only (no `<link>` or `<style>` tags), correct section order (header, executive summary, TOC, topic sections, source appendix, footer), bulleted executive summary, anchor-linked TOC, responsive single-column 600px max-width table layout, web-safe fonts, `bgcolor` attributes alongside `background-color` CSS. Template handles empty executive summary and empty source appendix gracefully.
- **Evidence**: [newsletter_agent/templates/newsletter.html.j2](newsletter_agent/templates/newsletter.html.j2)

#### PASS - Data Model Adherence (Section 7.5, 7.6)
- **Requirement**: SynthesisResult structure, NewsletterMetadata structure
- **Status**: Compliant
- **Detail**: `parse_synthesis_output()` produces dicts matching Section 7.5 (title, body_markdown, sources with url+title). FormatterAgent stores `newsletter_metadata` with title, date, topic_count, generation_time_seconds per Section 7.6. Source deduplication implemented in both synthesis_utils and formatter.
- **Evidence**: [synthesis_utils.py](newsletter_agent/tools/synthesis_utils.py), [formatter.py lines 99-105](newsletter_agent/tools/formatter.py#L99-L105)

#### PASS - Architecture Adherence (Section 9.1, 9.2, 9.3, 9.4)
- **Requirement**: Section 9.1 agent hierarchy, 9.2 technology stack, 9.3 directory structure, 9.4 design decisions
- **Status**: Compliant
- **Detail**: Synthesis agent uses `gemini-2.5-pro` (Decision 3). FormatterAgent is a BaseAgent subclass. Jinja2 template with autoescaping (Decision 4). File locations match Section 9.3: `prompts/synthesis.py`, `templates/newsletter.html.j2`, `tools/sanitizer.py`, `tools/synthesis_utils.py`, `tools/formatter.py`.
- **Evidence**: [agent.py](newsletter_agent/agent.py), [formatter.py](newsletter_agent/tools/formatter.py)

#### PASS - Non-Functional: Security (Section 10.2)
- **Requirement**: OWASP A03 injection mitigation, Jinja2 autoescaping, HTML sanitization
- **Status**: Compliant
- **Detail**: Jinja2 Environment created with `autoescape=True`. The `|safe` filter is used only on content sanitized by `nh3.clean()`. nh3 configured with explicit allowed tags whitelist, allowed attributes (only `href` on `<a>`), and URL schemes (`http`, `https` only). XSS payloads verified stripped in 11 dedicated security tests. No `<script>`, `<iframe>`, `<form>`, `<object>`, `<embed>` pass through.
- **Evidence**: [sanitizer.py](newsletter_agent/tools/sanitizer.py), [newsletter.html.j2 line 60](newsletter_agent/templates/newsletter.html.j2#L60) uses `{{ section.body_html|safe }}`, [test_sanitizer.py](tests/unit/test_sanitizer.py)

#### PASS - Non-Functional: Performance
- **Requirement**: Section 10.1 - HTML rendering within 5 seconds
- **Status**: Compliant
- **Detail**: No N+1 queries, no synchronous blocking. Template rendering is a single Jinja2 call. Sanitization uses Rust-based nh3 which is fast. No performance anti-patterns observed.
- **Evidence**: [formatter.py](newsletter_agent/tools/formatter.py), [sanitizer.py](newsletter_agent/tools/sanitizer.py)

#### PASS - Test Coverage (Section 11.1, 11.2, 11.6)
- **Requirement**: Unit tests for synthesis utils, sanitizer, formatter; BDD tests for synthesis and formatting
- **Status**: Compliant
- **Detail**: 78 tests total, all passing. test_synthesis_utils.py: 22 tests (>10 required). test_sanitizer.py: 26 tests (>12 required). test_html_formatter.py: 23 tests (>8 required). test_synthesis_formatting.py: 7 BDD tests (>6 required). Tests cover valid JSON, malformed input, markdown code blocks, missing sections, XSS payloads, tag filtering, URL schemes, template section order, TOC, inline CSS, topic variants, edge cases.
- **Evidence**: `pytest` output: 78 passed, 0 failed

#### PASS - Documentation Accuracy
- **Requirement**: Docs match implementation
- **Status**: Compliant
- **Detail**: README.md lists synthesis_utils.py in project structure. No `docs/` directory exists (WP05 responsibility). No inaccurate documentation found for WP03 components.
- **Evidence**: [README.md](README.md)

#### PASS - Scope Discipline
- **Requirement**: No code outside WP03 scope
- **Status**: Compliant
- **Detail**: All files created are within scope of WP03 tasks. The `markdown` library was added as a dependency (not in original Section 9.2 tech stack which listed "bleach") but its use as a full markdown parser is a reasonable improvement over the manual regex approach suggested in the WP reference. No unspecified features or abstractions added.
- **Evidence**: Files created: synthesis.py, synthesis_utils.py, sanitizer.py, formatter.py, newsletter.html.j2, and corresponding test files.

#### PASS - Encoding (UTF-8)
- **Requirement**: No em dashes, smart quotes, curly apostrophes
- **Status**: Compliant
- **Detail**: All 9 WP03 source and test files scanned. Zero encoding violations found.
- **Evidence**: Automated scan of all WP03 files returned "No violations".

### Statistics

| Dimension | Pass | Warn | Fail |
|-----------|------|------|------|
| Process Compliance | 0 | 0 | 3 |
| Spec Adherence | 2 | 0 | 2 |
| Data Model | 1 | 0 | 0 |
| API / Interface | 0 | 0 | 0 |
| Architecture | 1 | 0 | 0 |
| Test Coverage | 1 | 0 | 0 |
| Non-Functional | 2 | 0 | 0 |
| Performance | 0 | 0 | 0 |
| Documentation | 1 | 0 | 0 |
| Scope Discipline | 1 | 0 | 0 |
| Encoding (UTF-8) | 1 | 0 | 0 |

### Recommended Actions

1. **(FB-01)** Create a post-processing agent or wrapper that calls `parse_synthesis_output()` on the `synthesis_raw` state value and writes the parsed `synthesis_{N}` and `executive_summary` keys to state. Insert it between the Synthesizer and the OutputPhase in the pipeline sequence.
2. **(FB-02)** Update FormatterAgent to read expected topic count from state and insert "Research unavailable" placeholders for missing synthesis sections.
3. **(FB-03)** Add Spec Compliance Checklists to the WP file.
4. **(FB-04)** Add Activity Log entries for coder lane transitions.
