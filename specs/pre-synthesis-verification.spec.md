# Pre-Synthesis Source Verification - Specification

> **Source brief**: User request - verify sources before synthesis, increase source counts
> **Status**: Draft
> **Version**: 1.0

---

## 1. Overview

This specification changes the pipeline order to move link verification
BEFORE synthesis, and increases the number of sources requested from each
search provider. Currently, link verification runs after synthesis, which
means the synthesizer cites sources that may be broken -- and the verifier
then removes them, leaving sparse citations. The new flow verifies research
sources first and feeds only verified sources into synthesis.

---

## 2. Goals & Success Criteria

- **SC-001**: Link verification runs on raw research results before synthesis.
- **SC-002**: Research agents request more sources (5+ standard, 8+ deep for
  Google Search).
- **SC-003**: Synthesis only receives pre-verified source URLs and avoids
  citing broken links.
- **SC-004**: All existing backward-compatibility tests continue to pass.

---

## 3. Functional Requirements

### 3.1 Pipeline Order Change

- **FR-PSV-001**: The pipeline order SHALL be: ConfigLoader, ResearchPhase,
  ResearchValidator, PipelineAbortCheck, **LinkVerifier**, Synthesizer,
  SynthesisPostProcessor, OutputPhase.
- **FR-PSV-002**: LinkVerifier SHALL run after ResearchValidator and before
  the Synthesizer.

### 3.2 LinkVerifier Rework (Research-Phase Mode)

- **FR-PSV-003**: When verify_links is enabled, LinkVerifier SHALL read
  source URLs from `research_N_google` and `research_N_perplexity` state
  keys (instead of `synthesis_N`).
- **FR-PSV-004**: LinkVerifier SHALL remove broken URLs and their references
  from the research text content, so the synthesis LLM never sees them.
- **FR-PSV-005**: LinkVerifier SHALL update the research state keys in-place
  with cleaned sources lists and cleaned text.
- **FR-PSV-006**: LinkVerifier SHALL log the count of verified vs removed
  URLs per the existing pattern.

### 3.3 Increased Source Counts

- **FR-PSV-007**: Google Search standard-mode prompt SHALL request at least
  5 sources (up from 3).
- **FR-PSV-008**: Google Search deep-mode prompt SHALL request at least 8
  sources (up from 5).

### 3.4 Synthesis Prompt Update

- **FR-PSV-009**: The synthesis instruction SHALL note that research sources
  have been pre-verified, so the LLM can trust the URLs provided.

### 3.5 Backward Compatibility

- **FR-PSV-010**: When verify_links is false, the pipeline SHALL behave
  identically to before (LinkVerifier no-ops, synthesis receives raw
  research data).
- **FR-PSV-011**: All existing tests SHALL continue to pass.

---

## 4. Data Model Changes

### Research state keys (modified by LinkVerifier)

When verify_links is true, after LinkVerifier runs:
```
research_N_google.sources  -> broken URLs removed
research_N_google.text     -> broken link references cleaned
research_N_perplexity.sources -> broken URLs removed
research_N_perplexity.text    -> broken link references cleaned
```

---

## 5. Test Requirements

- Unit: LinkVerifier reads from research_N_* keys and cleans them
- Unit: Pipeline order has LinkVerifier before Synthesizer
- Unit: Google Search prompts request increased source counts
- Integration: Existing backward compatibility tests pass
