---
lane: for_review
---

# WP10 - Pre-Synthesis Source Verification

> **Spec**: `specs/pre-synthesis-verification.spec.md`
> **Status**: Complete
> **Priority**: P2
> **Goal**: Move link verification before synthesis so only verified sources
>   feed into content generation, and increase source counts from search providers.
> **Depends on**: WP01-WP08 (completed)

## Tasks

### T10-01 - Increase Google Search source counts in prompts

- **Spec refs**: FR-PSV-007, FR-PSV-008
- **Status**: Complete
- **Acceptance criteria**:
  - [x] Standard mode requests at least 5 sources (up from 3)
  - [x] Deep mode requests at least 8 sources (up from 5)
- **Test requirements**: unit

### T10-02 - Refactor LinkVerifierAgent to read research state keys

- **Spec refs**: FR-PSV-003, FR-PSV-004, FR-PSV-005, FR-PSV-006
- **Status**: Complete
- **Acceptance criteria**:
  - [x] Reads from research_N_google and research_N_perplexity keys
  - [x] Removes broken URLs from sources lists
  - [x] Cleans broken link references from research text
  - [x] Updates research state keys in-place
  - [x] Logs verified vs removed counts
  - [x] No-ops when verify_links is false
- **Test requirements**: unit

### T10-03 - Reorder pipeline: LinkVerifier before Synthesizer

- **Spec refs**: FR-PSV-001, FR-PSV-002
- **Status**: Complete
- **Acceptance criteria**:
  - [x] Pipeline order: ConfigLoader, ResearchPhase, ResearchValidator,
        PipelineAbortCheck, LinkVerifier, Synthesizer, SynthesisPostProcessor,
        OutputPhase
  - [x] LinkVerifier runs before Synthesizer
- **Test requirements**: unit

### T10-04 - Update synthesis prompt for pre-verified sources

- **Spec refs**: FR-PSV-009
- **Status**: Complete
- **Acceptance criteria**:
  - [x] Synthesis instruction notes sources are pre-verified
- **Test requirements**: none

### T10-05 - Update tests for new pipeline order

- **Spec refs**: FR-PSV-010, FR-PSV-011
- **Status**: Complete
- **Acceptance criteria**:
  - [x] Existing tests pass (383 passed)
  - [x] New tests for LinkVerifier reading research state
  - [x] Pipeline order test updated
- **Test requirements**: unit, integration

### T10-06 - Update documentation

- **Status**: Complete
- **Acceptance criteria**:
  - [x] architecture.md updated with new pipeline order
  - [x] api-reference.md updated with LinkVerifier section
  - [x] plans/README.md updated with WP10

## Self-Review

- [x] Every spec FR implemented
- [x] All 383 tests pass
- [x] Research keys cleaned before synthesis
- [x] No unused code or dead imports
- [x] No hardcoded values or secrets
- [x] Scope discipline maintained - no unasked-for abstractions
- [x] Plain ASCII only in all files

## Activity Log

- 2026-03-15T12:00:00Z - coder - lane=doing - WP10 created, implementation starting
- 2026-03-15T12:30:00Z - coder - lane=for_review - All tasks complete, submitted for review
