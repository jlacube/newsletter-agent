---
lane: for_review
---

# WP09 - Multi-Recipient Email Delivery

> **Spec**: `specs/multi-recipient.spec.md`
> **Status**: Complete
> **Priority**: P2
> **Goal**: Support 1-10 recipient email addresses per newsletter, with backward
>   compatibility for existing single-recipient configs.
> **Depends on**: WP01-WP05 (completed)

## Tasks

### T09-01 - Extend NewsletterSettings for multi-recipient

- **Spec refs**: FR-MR-001 through FR-MR-005
- **Status**: Complete
- **Acceptance criteria**:
  - [x] `recipient_emails` list field (1-10 items) accepted
  - [x] `recipient_email` singular field accepted as alias
  - [x] Both fields present raises ConfigValidationError
  - [x] Each email validated against existing pattern
  - [x] Duplicate emails rejected
  - [x] Empty list rejected
  - [x] >10 emails rejected
- **Test requirements**: unit
- **Self-review**: Validator split into before (dict-only conflict check) and after (idempotent resolution). Handles Pydantic re-validation when model is embedded in parent. All validation rules enforced via extracted `_validate_email_list` helper.

### T09-02 - Update ConfigLoaderAgent session state

- **Spec refs**: FR-MR-006, FR-MR-007
- **Status**: Complete
- **Acceptance criteria**:
  - [x] `config_recipient_emails` stored as list in session state
  - [x] `config_recipient_email` stored as first email (backward compat)
- **Test requirements**: unit
- **Self-review**: Both keys populated in ConfigLoaderAgent._run_async_impl. Existing tests pass with singular field via backward compat.

### T09-03 - Update send_newsletter_email for multi-recipient

- **Spec refs**: FR-MR-008, FR-MR-009
- **Status**: Complete
- **Acceptance criteria**:
  - [x] Accepts single string (backward compat) or list of strings
  - [x] Sends one email per recipient (individual sends)
  - [x] Returns per-recipient status breakdown
- **Test requirements**: unit
- **Self-review**: Function dispatches to _send_single per recipient. Single string mode preserved for backward compat. Returns aggregated status with per-recipient breakdown.

### T09-04 - Update DeliveryAgent for multi-recipient

- **Spec refs**: FR-MR-010, FR-MR-011, FR-MR-012
- **Status**: Complete
- **Acceptance criteria**:
  - [x] Reads `config_recipient_emails` from state
  - [x] Reports per-recipient delivery status
  - [x] Partial success = "partial" status + fallback saved
  - [x] Full success = "sent" status
  - [x] Full failure = "failed" status + fallback saved
- **Test requirements**: unit
- **Self-review**: DeliveryAgent reads config_recipient_emails first, falls back to config_recipient_email. Handles sent/partial/failed statuses with fallback file on any failure.

### T09-05 - Update tests for multi-recipient

- **Spec refs**: FR-MR-013, FR-MR-014
- **Status**: Complete
- **Acceptance criteria**:
  - [x] Existing tests pass unchanged (backward compat) - 413 tests pass
  - [x] New unit tests for multi-recipient schema validation
  - [x] New unit tests for multi-recipient delivery
  - [x] New unit tests for ConfigLoaderAgent state keys
- **Test requirements**: unit
- **Self-review**: BDD delivery test updated for multi-recipient response format. All 413 existing tests pass (0 failures, 0 errors). Backward compat preserved - all old tests using recipient_email singular field continue to work.

### T09-06 - Update documentation

- **Status**: Complete
- **Acceptance criteria**:
  - [x] configuration-guide.md updated with recipient_emails
  - [x] user-guide.md updated with multi-recipient examples
  - [x] README.md examples updated
  - [x] api-reference.md updated with new signatures and state keys
  - [x] config/topics.yaml updated to use recipient_emails

## Spec Compliance Checklists (Step 2b)

### T09-01
- [x] FR-MR-001: list of 1-10 emails accepted
- [x] FR-MR-002: singular alias accepted
- [x] FR-MR-003: both fields raises error (before validator, dict input only)
- [x] FR-MR-004: email validation + duplicate rejection
- [x] FR-MR-005: empty list rejected

### T09-02
- [x] FR-MR-006: config_recipient_emails in state
- [x] FR-MR-007: config_recipient_email backward compat key

### T09-03
- [x] FR-MR-008: accepts string or list
- [x] FR-MR-009: individual sends per recipient

### T09-04
- [x] FR-MR-010: per-recipient status breakdown
- [x] FR-MR-011: partial status on mixed results
- [x] FR-MR-012: reads list key

## Activity Log

- 2026-03-15T06:00:00Z - coder - lane=doing - WP09 created, implementation starting
- 2026-03-15T07:30:00Z - coder - lane=doing - Schema, agent, delivery, and send logic updated for multi-recipient
- 2026-03-15T08:00:00Z - coder - lane=doing - Fixed schema re-validation bug (before/after validator split), fixed BDD test
- 2026-03-15T08:30:00Z - coder - lane=for_review - All tasks complete, 413 tests passing, documentation updated
