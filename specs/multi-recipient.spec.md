# Multi-Recipient Email Delivery - Specification

> **Source brief**: User request - support multiple newsletter recipients
> **Status**: Draft
> **Version**: 1.0

---

## 1. Overview

This specification extends the Newsletter Agent email delivery system to support
multiple recipient email addresses. Currently, the `newsletter.recipient_email`
field accepts a single email string. This change replaces it with
`recipient_emails` (a list of 1-10 valid email addresses) while maintaining
full backward compatibility with existing configs that use the singular field.

---

## 2. Goals & Success Criteria

- **SC-001**: Operators can specify 1-10 recipient email addresses in `topics.yaml`.
- **SC-002**: The newsletter is delivered to every valid recipient individually.
- **SC-003**: Existing configs using `recipient_email` (singular) continue to work
  without modification (backward compatibility via field alias).
- **SC-004**: Partial delivery failures are logged per-recipient; a single
  recipient's failure does not block delivery to the others.

---

## 3. Functional Requirements

### 3.1 Configuration

- **FR-MR-001**: The `newsletter` section SHALL accept a `recipient_emails` field
  containing a list of 1 to 10 valid email address strings.
- **FR-MR-002**: The singular `recipient_email` field SHALL continue to be
  accepted as a backward-compatible alias. When present, it SHALL be treated
  as a single-element list.
- **FR-MR-003**: If both `recipient_email` and `recipient_emails` are present,
  validation SHALL raise a `ConfigValidationError` with a clear message.
- **FR-MR-004**: Each email in the list SHALL be validated using the existing
  email regex pattern. Duplicate emails SHALL be rejected.
- **FR-MR-005**: An empty list SHALL be rejected at config validation time.

### 3.2 Session State

- **FR-MR-006**: `ConfigLoaderAgent` SHALL store the resolved list of recipients
  in session state as `config_recipient_emails` (list of strings).
- **FR-MR-007**: The legacy key `config_recipient_email` SHALL also be set to
  the first email in the list for backward compatibility with any code that
  reads the singular key.

### 3.3 Email Delivery

- **FR-MR-008**: `send_newsletter_email()` SHALL accept either a single email
  string or a list of email strings as the `recipient_email` parameter.
- **FR-MR-009**: When given a list, the function SHALL send one email per
  recipient (individual sends, not CC/BCC) to provide per-recipient delivery
  status tracking.
- **FR-MR-010**: The `delivery_status` in session state SHALL include a
  per-recipient breakdown: `{"status": "sent"|"partial"|"failed",
  "recipients": [{"email": "...", "status": "sent"|"error", "message_id"|"error": "..."}]}`.
- **FR-MR-011**: If some recipients succeed and others fail, the overall status
  SHALL be `"partial"` and the HTML SHALL still be saved as fallback.
- **FR-MR-012**: The `DeliveryAgent` SHALL read from `config_recipient_emails`
  (the list key).

### 3.4 Backward Compatibility

- **FR-MR-013**: Existing YAML configs with `recipient_email: "single@email.com"`
  SHALL load without errors and deliver to that single address.
- **FR-MR-014**: All existing tests SHALL continue to pass without modification
  (existing fixtures use the singular field).

---

## 4. Data Model Changes

### NewsletterSettings (modified)

```
recipient_emails: list[str]  # 1-10 valid email addresses
recipient_email: str          # Deprecated alias, accepted for backward compat
```

Model validator: if `recipient_email` is provided (singular), convert to
single-element `recipient_emails` list. If both provided, raise error.

### Session State (modified)

| Key | Type | Description |
|-----|------|-------------|
| `config_recipient_emails` | `list[str]` | All recipient addresses |
| `config_recipient_email` | `str` | First recipient (backward compat) |

### delivery_status (modified)

```python
{
    "status": "sent" | "partial" | "failed" | "dry_run",
    "recipients": [
        {"email": "a@b.com", "status": "sent", "message_id": "..."},
        {"email": "c@d.com", "status": "error", "error": "..."},
    ],
    "fallback_file": "..."  # present on partial/failed
}
```

---

## 5. Test Requirements

- Unit: NewsletterSettings accepts list and singular forms; rejects both;
  rejects duplicates; rejects empty list; rejects >10
- Unit: send_newsletter_email handles list of recipients
- Unit: DeliveryAgent reads list, reports per-recipient status
- Unit: ConfigLoaderAgent stores both state keys
- BDD: Multi-recipient delivery scenario (all succeed, some fail)
- Integration: Backward compatibility with singular field
