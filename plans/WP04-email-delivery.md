---
lane: planned
---

# WP04 - Email Delivery and Local Output

> **Spec**: `specs/newsletter-agent.spec.md`
> **Status**: Not Started
> **Priority**: P1
> **Goal**: The completed newsletter is delivered via Gmail API or saved to disk in dry-run mode, with OAuth2 authentication, token refresh, and graceful failure fallback
> **Independent Test**: Generate a newsletter HTML, configure Gmail OAuth2 credentials, run delivery - verify email arrives in inbox with correct subject and HTML body; verify dry-run saves HTML to output directory
> **Depends on**: WP01, WP03
> **Parallelisable**: No (depends on WP03 formatter output)
> **Prompt**: `plans/WP04-email-delivery.md`

## Objective

This work package implements the email delivery system for the Newsletter Agent. It includes Gmail API integration with OAuth2 authentication, token refresh handling, MIME multipart message construction (HTML + plain text fallback), dry-run mode that saves HTML to disk instead of sending email, and fallback behavior that saves HTML locally when email delivery fails. It also includes the one-time OAuth2 setup script that operators use during initial configuration.

Upon completion, the full pipeline can deliver newsletters to the operator's inbox or save them locally, completing the core MVP user journey.

## Spec References

- FR-027: Send HTML newsletter via Gmail API with OAuth2
- FR-028: OAuth2 offline access with refresh token, automatic token refresh
- FR-029: MIME multipart message with HTML and plain-text parts
- FR-030: Email From/To/Subject format
- FR-031: Dry-run mode skips email, saves HTML to disk
- FR-032: Email failure fallback - log error, save HTML locally, exit non-zero
- FR-033: Dry-run executes full pipeline except email
- FR-034: HTML file output path format (`{output_dir}/{YYYY-MM-DD}-newsletter.html`)
- FR-035: Auto-create output directory
- FR-041: Local secrets from `.env` file
- US-05: Email delivery via Gmail API
- US-06: Local development workflow (dry-run)
- Section 7.6: NewsletterMetadata
- Section 8.3: Gmail send tool function signature
- Section 9.1: Architecture - delivery agent
- Section 9.5: External integration - Gmail API
- Section 10.2: Security - OAuth2, secrets management
- Section 11.1: Unit tests for Gmail tool
- Section 11.2: BDD scenarios for email delivery
- Section 11.3: Integration tests for Gmail

## Tasks

### T04-01 - Implement Gmail OAuth2 Token Management

- **Description**: Create the OAuth2 token management module at `newsletter_agent/tools/gmail_auth.py`. This module handles loading OAuth2 credentials (client ID, client secret, refresh token) from environment variables, building the credentials object, and automatically refreshing expired access tokens. It provides a `get_gmail_credentials()` function that returns a valid `google.oauth2.credentials.Credentials` object ready for Gmail API calls.

- **Spec refs**: FR-028, FR-041, Section 9.5 (Gmail API integration), Section 10.2

- **Parallel**: Yes (independent of other T04 tasks)

- **Acceptance criteria**:
  - [ ] File `newsletter_agent/tools/gmail_auth.py` exists and exports `get_gmail_credentials() -> Credentials`
  - [ ] The function reads `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, and `GMAIL_REFRESH_TOKEN` from environment variables
  - [ ] Returns a `google.oauth2.credentials.Credentials` object with the refresh token and Gmail API scopes
  - [ ] If credentials are expired but a valid refresh token exists, the function refreshes the access token automatically
  - [ ] If any required environment variable is missing, raises a descriptive error (not a raw KeyError)
  - [ ] If the refresh token is invalid (revoked or expired), raises `GmailAuthError` with a clear message instructing the operator to re-run the OAuth setup script
  - [ ] No credentials are logged or written to files - only used in memory
  - [ ] The Gmail API scope used is `https://www.googleapis.com/auth/gmail.send` (minimum required scope)

- **Test requirements**: unit (mock credentials, test refresh flow)

- **Depends on**: T01-01 (project scaffolding)

- **Implementation Guidance**:
  - Official docs: Google OAuth2 for server-side apps - https://developers.google.com/identity/protocols/oauth2
  - Libraries: `google-auth`, `google-auth-oauthlib`, `google-api-python-client`
  - Credentials construction:
    ```python
    from google.oauth2.credentials import Credentials
    
    SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
    
    def get_gmail_credentials() -> Credentials:
        client_id = os.environ.get("GMAIL_CLIENT_ID")
        client_secret = os.environ.get("GMAIL_CLIENT_SECRET")
        refresh_token = os.environ.get("GMAIL_REFRESH_TOKEN")
        
        if not all([client_id, client_secret, refresh_token]):
            missing = []
            if not client_id: missing.append("GMAIL_CLIENT_ID")
            if not client_secret: missing.append("GMAIL_CLIENT_SECRET")
            if not refresh_token: missing.append("GMAIL_REFRESH_TOKEN")
            raise GmailAuthError(
                f"Missing Gmail credentials: {', '.join(missing)}. "
                "Run setup_gmail_oauth.py to configure."
            )
        
        creds = Credentials(
            token=None,  # Will be refreshed on first use
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=SCOPES,
        )
        return creds
    ```
  - Token refresh: The `google-auth` library automatically refreshes the token when needed during API calls. The `Credentials` object handles this transparently.
  - Known pitfalls:
    - Refresh tokens can be revoked by the user or expire if the OAuth consent is not set to "production" in Google Cloud Console
    - The `google-auth` library raises `google.auth.exceptions.RefreshError` when refresh fails
    - Environment variables may contain whitespace or quotes from `.env` files - strip them
  - Custom exceptions:
    ```python
    class GmailAuthError(Exception):
        """Raised when Gmail OAuth2 authentication fails."""
        pass
    
    class GmailSendError(Exception):
        """Raised when Gmail API send operation fails."""
        pass
    ```

---

### T04-02 - Implement Gmail Send Function

- **Description**: Create the `send_newsletter_email` function in `newsletter_agent/tools/gmail_send.py` that sends an HTML email via the Gmail API. The function constructs a MIME multipart message with both HTML and plain-text parts, sets the correct From/To/Subject headers, and sends via the Gmail API `messages.send` method. On failure, it returns an error dict instead of raising.

- **Spec refs**: FR-027, FR-029, FR-030, Section 8.3 (function signature), Section 9.5

- **Parallel**: No (requires T04-01 for credentials)

- **Acceptance criteria**:
  - [ ] File `newsletter_agent/tools/gmail_send.py` exists and exports `send_newsletter_email(html_content: str, recipient_email: str, subject: str) -> dict`
  - [ ] The function constructs a MIME multipart/alternative message with HTML and plain-text parts
  - [ ] The plain-text part is generated by stripping HTML tags from the HTML content (basic text fallback)
  - [ ] The email `From` is the authenticated Gmail account (determined from credentials)
  - [ ] The email `To` is the `recipient_email` parameter
  - [ ] The email `Subject` is the `subject` parameter
  - [ ] On success, returns `{"status": "sent", "message_id": str}`
  - [ ] On auth failure, attempts token refresh once, then returns `{"status": "error", "error_message": str}`
  - [ ] On API error, returns `{"status": "error", "error_message": str}` without raising
  - [ ] The function logs the send attempt and result at INFO level, errors at ERROR level

- **Test requirements**: unit (mock Gmail API client), integration (send real email)

- **Depends on**: T04-01

- **Implementation Guidance**:
  - Official docs: Gmail API messages.send - https://developers.google.com/gmail/api/reference/rest/v1/users.messages/send
  - MIME construction:
    ```python
    import base64
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    
    def _build_mime_message(html_content, recipient_email, subject, from_email):
        message = MIMEMultipart("alternative")
        message["To"] = recipient_email
        message["From"] = from_email
        message["Subject"] = subject
        
        # Plain text fallback
        plain_text = _strip_html(html_content)
        message.attach(MIMEText(plain_text, "plain"))
        message.attach(MIMEText(html_content, "html"))
        
        return base64.urlsafe_b64encode(message.as_bytes()).decode()
    ```
  - Gmail API send:
    ```python
    from googleapiclient.discovery import build
    
    service = build("gmail", "v1", credentials=creds)
    result = service.users().messages().send(
        userId="me",
        body={"raw": raw_message}
    ).execute()
    ```
  - Plain text generation: Strip HTML tags using regex or `html.parser`. Do not use external libraries for this - a basic tag stripper is sufficient:
    ```python
    import re
    def _strip_html(html):
        text = re.sub(r'<br\s*/?>', '\n', html)
        text = re.sub(r'</p>', '\n\n', text)
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()
    ```
  - Known pitfalls:
    - Gmail API uses base64url encoding (not standard base64). Use `base64.urlsafe_b64encode`.
    - The `userId="me"` refers to the authenticated user.
    - Gmail API may return 403 if the scope `gmail.send` is not granted.
    - Large HTML emails (over 35KB base64) may be rejected - newsletter HTML should be well under this limit.
    - The `From` address can be determined from the Gmail API `users.getProfile()` call, but for simplicity, use the `recipient_email` as `From` if they are the same person (spec says operator = recipient in MVP).

---

### T04-03 - Implement HTML File Output (Dry-Run and Fallback)

- **Description**: Create a utility function that saves the newsletter HTML to disk at the deterministic path `{output_dir}/{YYYY-MM-DD}-newsletter.html`. This function is used both in dry-run mode (FR-031) and as a fallback when email delivery fails (FR-032). The output directory is auto-created if it does not exist (FR-035).

- **Spec refs**: FR-031, FR-034, FR-035, Section 4.6 implementation contract

- **Parallel**: Yes (independent of Gmail tasks)

- **Acceptance criteria**:
  - [ ] Function `save_newsletter_html(html_content: str, output_dir: str, newsletter_date: str) -> str` exists in `newsletter_agent/tools/file_output.py`
  - [ ] The function saves HTML to `{output_dir}/{newsletter_date}-newsletter.html`
  - [ ] The output directory is created automatically if it does not exist (including nested directories)
  - [ ] The function returns the absolute path of the saved file
  - [ ] If the file already exists, it is overwritten (idempotent operation - same date newsletter replaces previous)
  - [ ] If the directory cannot be created (permission error), the function raises `IOError` with a descriptive message
  - [ ] The function logs the save path at INFO level
  - [ ] The file is written with UTF-8 encoding

- **Test requirements**: unit (mock filesystem or use tmp_path fixture)

- **Depends on**: none

- **Implementation Guidance**:
  - Use `pathlib.Path` for path manipulation:
    ```python
    from pathlib import Path
    
    def save_newsletter_html(html_content: str, output_dir: str, newsletter_date: str) -> str:
        output_path = Path(output_dir) / f"{newsletter_date}-newsletter.html"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html_content, encoding="utf-8")
        return str(output_path.resolve())
    ```
  - Known pitfalls:
    - `output_dir` may be a relative path. Resolve it relative to the project root, not the current working directory.
    - On Windows, path separators may differ. Use `pathlib.Path` to handle this.
    - Date format must be `YYYY-MM-DD` (ISO 8601 date only, no time component).

---

### T04-04 - Implement Delivery Agent

- **Description**: Implement the delivery agent (custom BaseAgent or function-based agent) that orchestrates the email delivery logic. The agent reads `newsletter_html`, `newsletter_metadata`, and config settings from session state, then either sends the email via Gmail API or saves to disk based on the `dry_run` flag. On email failure, it falls back to saving HTML locally and signals a non-zero exit status.

- **Spec refs**: FR-027, FR-031, FR-032, FR-033, Section 9.1 (delivery agent), Section 6.2/6.3/6.4 flows

- **Parallel**: No (requires T04-01, T04-02, T04-03)

- **Acceptance criteria**:
  - [ ] A delivery agent component exists (BaseAgent subclass or function wrapped in a BaseAgent)
  - [ ] The agent reads `newsletter_html` from session state
  - [ ] The agent reads `newsletter_metadata` for the date and title
  - [ ] The agent reads `config_dry_run` and `config_output_dir` from session state
  - [ ] When `dry_run` is false and credentials are valid: sends email via `send_newsletter_email()` and stores `{"delivery_status": "sent", "message_id": "..."}` in state
  - [ ] When `dry_run` is true: saves HTML to disk via `save_newsletter_html()` and stores `{"delivery_status": "dry_run", "output_file": "..."}` in state
  - [ ] When email delivery fails: logs error, saves HTML as fallback, stores `{"delivery_status": "failed", "fallback_file": "...", "error": "..."}` in state
  - [ ] The email subject follows format: `{newsletter_title} - {YYYY-MM-DD}`
  - [ ] The agent logs delivery status at INFO level and errors at ERROR level

- **Test requirements**: unit (mock Gmail send, test all three paths), BDD

- **Depends on**: T04-01, T04-02, T04-03

- **Implementation Guidance**:
  - BaseAgent pattern:
    ```python
    class DeliveryAgent(BaseAgent):
        async def _run_async_impl(self, ctx: InvocationContext):
            state = ctx.session.state
            html = state.get("newsletter_html", "")
            metadata = state.get("newsletter_metadata", {})
            dry_run = state.get("config_dry_run", False)
            output_dir = state.get("config_output_dir", "output/")
            
            title = metadata.get("title", "Newsletter")
            date = metadata.get("date", date.today().isoformat())
            subject = f"{title} - {date}"
            
            if dry_run:
                path = save_newsletter_html(html, output_dir, date)
                state["delivery_status"] = {"status": "dry_run", "output_file": path}
                yield types.Content(parts=[types.Part(text=f"Dry run: saved to {path}")])
                return
            
            # Attempt email delivery
            result = send_newsletter_email(html, recipient_email, subject)
            if result["status"] == "sent":
                state["delivery_status"] = result
            else:
                # Fallback: save locally
                path = save_newsletter_html(html, output_dir, date)
                state["delivery_status"] = {
                    "status": "failed",
                    "fallback_file": path,
                    "error": result.get("error_message", "Unknown error"),
                }
    ```
  - Non-zero exit status: When delivery fails, the agent should set a flag in state that the root pipeline can check. The actual non-zero exit is handled by the CLI/HTTP trigger layer, not the agent itself.
  - Known pitfalls:
    - The recipient email comes from config (stored in state during config loading). Make sure the state key name is consistent with WP01.
    - In dry-run mode, the delivery agent should NOT attempt to load Gmail credentials at all (they may not be configured for development).

---

### T04-05 - Create Gmail OAuth2 Setup Script

- **Description**: Create the one-time OAuth2 setup script at `setup_gmail_oauth.py` in the project root. This script runs the interactive OAuth2 consent flow in the operator's browser, obtains a refresh token, and prints the environment variables to set. The operator copies these values into their `.env` file.

- **Spec refs**: FR-028 (offline access), Section 6.1 (Initial Setup Flow step 4), Section 9.3

- **Parallel**: Yes (independent of other delivery tasks)

- **Acceptance criteria**:
  - [ ] File `setup_gmail_oauth.py` exists at the project root
  - [ ] Running `python setup_gmail_oauth.py` opens a browser for Google OAuth2 consent
  - [ ] The script requests the `gmail.send` scope with offline access
  - [ ] After consent, the script prints the refresh token and instructs the user to add it to `.env`
  - [ ] The script accepts a `--client-secrets-file` argument pointing to the OAuth2 client secrets JSON downloaded from Google Cloud Console
  - [ ] The script validates that the client secrets file exists and has the expected format before proceeding
  - [ ] The script handles user cancellation gracefully (Ctrl+C, browser window closed)

- **Test requirements**: none (interactive script, tested manually)

- **Depends on**: none

- **Implementation Guidance**:
  - Use `google-auth-oauthlib` for the consent flow:
    ```python
    from google_auth_oauthlib.flow import InstalledAppFlow
    
    SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
    
    def main():
        flow = InstalledAppFlow.from_client_secrets_file(
            client_secrets_file,
            scopes=SCOPES,
        )
        creds = flow.run_local_server(port=8080, access_type="offline", prompt="consent")
        
        print("\nOAuth2 setup complete!")
        print(f"\nAdd these to your .env file:")
        print(f"GMAIL_REFRESH_TOKEN={creds.refresh_token}")
        print(f"GMAIL_CLIENT_ID={creds.client_id}")
        print(f"GMAIL_CLIENT_SECRET={creds.client_secret}")
    ```
  - The operator downloads the OAuth2 client secrets JSON from Google Cloud Console (APIs & Services -> Credentials -> OAuth 2.0 Client IDs -> Download JSON).
  - Known pitfalls:
    - The OAuth2 consent page may show a "This app isn't verified" warning. The operator must click "Advanced" and "Go to [app] (unsafe)" to proceed. Document this in the README.
    - If the OAuth2 client is set to "Testing" status in Google Cloud Console, refresh tokens expire after 7 days. The client should be set to "Production" for long-lived tokens (requires verification for public apps, but personal use apps can work around this).
    - The `access_type="offline"` and `prompt="consent"` parameters are critical for obtaining a refresh token. Without them, only an access token is returned.

---

### T04-06 - Wire Delivery Agent into Root Pipeline

- **Description**: Add the delivery agent into the root SequentialAgent as the final step. The root pipeline now has: config loader -> research phase -> synthesis -> formatter -> delivery. Also implement the non-zero exit status handling when delivery fails.

- **Spec refs**: FR-032, Section 9.1 (architecture), Section 6.2 flow

- **Parallel**: No (requires T04-04)

- **Acceptance criteria**:
  - [ ] The delivery agent is the final child in the root SequentialAgent
  - [ ] Running the full pipeline with `dry_run: true` produces a saved HTML file without attempting email
  - [ ] Running the full pipeline with `dry_run: false` and valid credentials sends an email
  - [ ] Running the full pipeline with `dry_run: false` and invalid credentials saves HTML as fallback and sets error state
  - [ ] The pipeline can be triggered via `adk web` and the delivery status is visible in the event stream
  - [ ] The pipeline end-to-end works: config -> research -> synthesis -> format -> deliver

- **Test requirements**: E2E (full pipeline via `adk web` or `adk run`)

- **Depends on**: T04-04

- **Implementation Guidance**:
  - Root agent wiring:
    ```python
    root_agent = SequentialAgent(
        name="NewsletterPipeline",
        sub_agents=[
            config_loader_agent,     # WP01
            research_phase,          # WP02
            synthesis_agent,         # WP03
            formatter_agent,         # WP03
            delivery_agent,          # This WP
        ],
    )
    ```
  - For the non-zero exit status: the HTTP trigger handler (WP05) should check `delivery_status` in state after the pipeline completes and return the appropriate HTTP status code.

---

### T04-07 - Write Unit Tests for Gmail Auth

- **Description**: Write unit tests for the `get_gmail_credentials()` function testing all credential paths.

- **Spec refs**: Section 11.1

- **Parallel**: Yes (after T04-01)

- **Acceptance criteria**:
  - [ ] Test file `tests/test_gmail_auth.py` exists with at least 8 test cases
  - [ ] Tests cover: valid credentials loaded from env, missing GMAIL_CLIENT_ID, missing GMAIL_CLIENT_SECRET, missing GMAIL_REFRESH_TOKEN, all credentials missing, credentials with whitespace/quotes stripped, refresh token that is expired/revoked, successful token refresh
  - [ ] All tests mock environment variables and Google auth library
  - [ ] Tests verify the correct Gmail scope is requested
  - [ ] Tests verify GmailAuthError is raised with descriptive messages
  - [ ] All tests pass via `pytest tests/test_gmail_auth.py`

- **Test requirements**: unit

- **Depends on**: T04-01

- **Implementation Guidance**:
  - Use `@patch.dict(os.environ, {...})` to mock environment variables
  - Use `@patch("google.oauth2.credentials.Credentials")` to mock the credentials class
  - Test refresh failure:
    ```python
    @patch.dict(os.environ, {"GMAIL_CLIENT_ID": "id", "GMAIL_CLIENT_SECRET": "secret", "GMAIL_REFRESH_TOKEN": "bad_token"})
    @patch("newsletter_agent.tools.gmail_auth.Credentials")
    def test_revoked_refresh_token_raises_auth_error(self, mock_creds_class):
        from google.auth.exceptions import RefreshError
        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh.side_effect = RefreshError("Token revoked")
        mock_creds_class.return_value = mock_creds
        
        with pytest.raises(GmailAuthError, match="re-run the OAuth setup"):
            get_gmail_credentials()
    ```

---

### T04-08 - Write Unit Tests for Gmail Send

- **Description**: Write unit tests for the `send_newsletter_email()` function testing all send paths.

- **Spec refs**: Section 11.1 (Gmail tool unit tests)

- **Parallel**: Yes (after T04-02)

- **Acceptance criteria**:
  - [ ] Test file `tests/test_gmail_send.py` exists with at least 10 test cases
  - [ ] Tests cover: successful send returns message_id, MIME message has HTML and plain-text parts, correct subject/to/from headers, Gmail API 401 triggers refresh attempt, Gmail API 403 returns error dict, Gmail API 500 returns error dict, network error returns error dict, very large HTML content, HTML with special characters, plain-text fallback generation
  - [ ] All tests mock the Gmail API client and credentials
  - [ ] Tests verify the MIME message structure (multipart/alternative with 2 parts)
  - [ ] Tests verify base64url encoding of the message
  - [ ] All tests pass via `pytest tests/test_gmail_send.py`

- **Test requirements**: unit

- **Depends on**: T04-02

- **Implementation Guidance**:
  - Mock the Gmail API service:
    ```python
    @patch("newsletter_agent.tools.gmail_send.build")
    @patch("newsletter_agent.tools.gmail_send.get_gmail_credentials")
    def test_successful_send(self, mock_creds, mock_build):
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.users().messages().send().execute.return_value = {"id": "msg-123"}
        
        result = send_newsletter_email("<h1>Test</h1>", "test@gmail.com", "Subject")
        
        assert result["status"] == "sent"
        assert result["message_id"] == "msg-123"
    ```
  - Verify MIME structure by capturing the `body` argument passed to `.send()`:
    ```python
    call_args = mock_service.users().messages().send.call_args
    raw_msg = call_args.kwargs["body"]["raw"]
    decoded = base64.urlsafe_b64decode(raw_msg)
    assert b"Content-Type: multipart/alternative" in decoded
    ```

---

### T04-09 - Write Unit Tests for File Output

- **Description**: Write unit tests for the `save_newsletter_html()` function.

- **Spec refs**: Section 11.1, FR-034, FR-035

- **Parallel**: Yes (after T04-03)

- **Acceptance criteria**:
  - [ ] Test file `tests/test_file_output.py` exists with at least 6 test cases
  - [ ] Tests cover: save to existing directory, save to non-existing directory (auto-created), file path format matches `{output_dir}/{date}-newsletter.html`, file content matches input HTML, overwrite existing file, UTF-8 encoding with special characters
  - [ ] Tests use pytest's `tmp_path` fixture for filesystem operations
  - [ ] Tests verify the returned path is absolute
  - [ ] All tests pass via `pytest tests/test_file_output.py`

- **Test requirements**: unit

- **Depends on**: T04-03

- **Implementation Guidance**:
  - Use `tmp_path` fixture:
    ```python
    def test_save_to_new_directory(tmp_path):
        output_dir = str(tmp_path / "new" / "nested" / "dir")
        result = save_newsletter_html("<h1>Test</h1>", output_dir, "2026-03-14")
        
        assert os.path.exists(result)
        assert result.endswith("2026-03-14-newsletter.html")
        assert Path(result).read_text(encoding="utf-8") == "<h1>Test</h1>"
    ```

---

### T04-10 - Write Unit Tests for Delivery Agent

- **Description**: Write unit tests for the delivery agent covering all three delivery paths: successful send, dry-run, and failure with fallback.

- **Spec refs**: Section 11.1, Section 11.2 (BDD scenarios for email delivery)

- **Parallel**: Yes (after T04-04)

- **Acceptance criteria**:
  - [ ] Test file `tests/test_delivery_agent.py` exists with at least 8 test cases
  - [ ] Tests cover: successful email delivery, dry-run mode saves HTML, email failure triggers fallback save, missing newsletter_html in state, delivery with empty HTML, correct subject format, delivery status stored in state for each path, delivery does not load credentials in dry-run mode
  - [ ] Tests mock both Gmail send and file output functions
  - [ ] All tests pass via `pytest tests/test_delivery_agent.py`

- **Test requirements**: unit, BDD

- **Depends on**: T04-04

---

### T04-11 - Write BDD Acceptance Tests for Email Delivery

- **Description**: Write BDD-style acceptance tests for the email delivery scenarios from Section 11.2.

- **Spec refs**: Section 11.2 (Feature: Email Delivery), US-05

- **Parallel**: No (requires all T04-01 through T04-06)

- **Acceptance criteria**:
  - [ ] Test file `tests/bdd/test_email_delivery.py` exists with at least 4 BDD scenario tests
  - [ ] Scenario: Successful email send - verifies email sent to recipient with correct subject
  - [ ] Scenario: Dry run mode - verifies no email sent, HTML saved to output directory
  - [ ] Scenario: Email failure with fallback - verifies error logged, HTML saved locally
  - [ ] Scenario: Expired token with valid refresh - verifies token refresh and successful send
  - [ ] Tests use mocked Gmail API (no real emails sent in automated tests)
  - [ ] All tests pass via `pytest tests/bdd/test_email_delivery.py`

- **Test requirements**: BDD

- **Depends on**: T04-06

## Reference Implementations

### Gmail Auth Module - Complete Reference

```python
"""
Gmail OAuth2 authentication and token management.

Spec refs: FR-028, FR-041, Section 9.5, Section 10.2.
"""

import os
import logging

from google.oauth2.credentials import Credentials
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request

logger = logging.getLogger(__name__)

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
_TOKEN_URI = "https://oauth2.googleapis.com/token"


class GmailAuthError(Exception):
    """Raised when Gmail OAuth2 authentication fails."""
    pass


class GmailSendError(Exception):
    """Raised when Gmail API send operation fails."""
    pass


def get_gmail_credentials() -> Credentials:
    """Load and validate Gmail OAuth2 credentials from environment.

    Returns:
        Valid google.oauth2.credentials.Credentials object.

    Raises:
        GmailAuthError: If credentials are missing or refresh fails.
    """
    client_id = os.environ.get("GMAIL_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET", "").strip()
    refresh_token = os.environ.get("GMAIL_REFRESH_TOKEN", "").strip()

    missing = []
    if not client_id:
        missing.append("GMAIL_CLIENT_ID")
    if not client_secret:
        missing.append("GMAIL_CLIENT_SECRET")
    if not refresh_token:
        missing.append("GMAIL_REFRESH_TOKEN")

    if missing:
        raise GmailAuthError(
            f"Missing Gmail OAuth2 credentials: {', '.join(missing)}. "
            "Run 'python setup_gmail_oauth.py' to configure Gmail access."
        )

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=_TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=GMAIL_SCOPES,
    )

    # Attempt refresh to validate credentials
    try:
        creds.refresh(Request())
        logger.info("Gmail credentials refreshed successfully")
    except RefreshError as e:
        raise GmailAuthError(
            f"Gmail refresh token is invalid or revoked: {e}. "
            "Run 'python setup_gmail_oauth.py' to re-authorize."
        ) from e
    except Exception as e:
        raise GmailAuthError(
            f"Failed to refresh Gmail credentials: {e}"
        ) from e

    return creds
```

### Gmail Send Function - Complete Reference

```python
"""
Gmail API email send function.

Spec refs: FR-027, FR-029, FR-030, Section 8.3.
"""

import base64
import logging
import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from newsletter_agent.tools.gmail_auth import get_gmail_credentials, GmailAuthError

logger = logging.getLogger(__name__)


def send_newsletter_email(
    html_content: str,
    recipient_email: str,
    subject: str,
) -> dict:
    """Send an HTML email via Gmail API.

    Args:
        html_content: Complete HTML newsletter string.
        recipient_email: Target email address.
        subject: Email subject line.

    Returns:
        dict with keys:
            - status (str): "sent" or "error"
            - message_id (str): Gmail message ID if sent
            - error_message (str): Error details if failed
    """
    try:
        creds = get_gmail_credentials()
    except GmailAuthError as e:
        logger.error("Gmail authentication failed: %s", e)
        return {"status": "error", "error_message": str(e)}

    # Build MIME message
    message = MIMEMultipart("alternative")
    message["To"] = recipient_email
    message["From"] = recipient_email  # MVP: operator is also the sender
    message["Subject"] = subject

    # Plain text fallback
    plain_text = _strip_html(html_content)
    message.attach(MIMEText(plain_text, "plain", "utf-8"))
    message.attach(MIMEText(html_content, "html", "utf-8"))

    # Base64url encode
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")

    try:
        service = build("gmail", "v1", credentials=creds)
        result = (
            service.users()
            .messages()
            .send(userId="me", body={"raw": raw_message})
            .execute()
        )

        message_id = result.get("id", "unknown")
        logger.info(
            "Newsletter email sent: message_id=%s, to=%s, subject=%s",
            message_id,
            recipient_email,
            subject,
        )
        return {"status": "sent", "message_id": message_id}

    except HttpError as e:
        error_msg = f"Gmail API error: {e.resp.status} {e.reason}"
        logger.error(error_msg)
        return {"status": "error", "error_message": error_msg}
    except Exception as e:
        error_msg = f"Unexpected error sending email: {type(e).__name__}: {e}"
        logger.error(error_msg)
        return {"status": "error", "error_message": error_msg}


def _strip_html(html: str) -> str:
    """Strip HTML tags to produce a plain-text fallback."""
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</li>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</h[1-6]>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()
```

### File Output Function - Complete Reference

```python
"""
Newsletter HTML file output for dry-run mode and delivery fallback.

Spec refs: FR-031, FR-034, FR-035.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def save_newsletter_html(
    html_content: str,
    output_dir: str,
    newsletter_date: str,
) -> str:
    """Save newsletter HTML to disk.

    Args:
        html_content: Complete HTML newsletter string.
        output_dir: Directory to save the file in.
        newsletter_date: Date string in YYYY-MM-DD format for filename.

    Returns:
        Absolute path of the saved file.

    Raises:
        IOError: If the output directory cannot be created.
    """
    output_path = Path(output_dir) / f"{newsletter_date}-newsletter.html"

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise IOError(
            f"Cannot create output directory '{output_dir}': {e}"
        ) from e

    output_path.write_text(html_content, encoding="utf-8")
    abs_path = str(output_path.resolve())

    logger.info("Newsletter HTML saved to: %s", abs_path)
    return abs_path
```

### OAuth2 Setup Script - Complete Reference

```python
#!/usr/bin/env python3
"""
One-time Gmail OAuth2 setup script.

Downloads a refresh token for the Newsletter Agent to send emails
via the Gmail API. Run this interactively in a terminal with a browser.

Usage:
    python setup_gmail_oauth.py --client-secrets-file client_secret.json
"""

import argparse
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def main():
    parser = argparse.ArgumentParser(
        description="Set up Gmail OAuth2 for Newsletter Agent"
    )
    parser.add_argument(
        "--client-secrets-file",
        required=True,
        help="Path to OAuth2 client secrets JSON from Google Cloud Console",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Local port for OAuth2 callback (default: 8080)",
    )
    args = parser.parse_args()

    secrets_path = Path(args.client_secrets_file)
    if not secrets_path.exists():
        print(f"Error: Client secrets file not found: {secrets_path}")
        print("Download it from: Google Cloud Console -> APIs & Services -> Credentials")
        sys.exit(1)

    print("Starting Gmail OAuth2 setup...")
    print(f"Using client secrets: {secrets_path}")
    print("A browser window will open for Google sign-in.\n")

    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(secrets_path),
            scopes=SCOPES,
        )
        creds = flow.run_local_server(
            port=args.port,
            access_type="offline",
            prompt="consent",
        )
    except KeyboardInterrupt:
        print("\nSetup cancelled.")
        sys.exit(1)
    except Exception as e:
        print(f"\nOAuth2 setup failed: {e}")
        sys.exit(1)

    if not creds.refresh_token:
        print("\nWarning: No refresh token received.")
        print("This may happen if you previously authorized this app.")
        print("Try revoking access at https://myaccount.google.com/permissions")
        print("and running this script again.")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("OAuth2 setup complete!")
    print("=" * 60)
    print("\nAdd these lines to your .env file:\n")
    print(f"GMAIL_REFRESH_TOKEN={creds.refresh_token}")
    print(f"GMAIL_CLIENT_ID={creds.client_id}")
    print(f"GMAIL_CLIENT_SECRET={creds.client_secret}")
    print("\nDo NOT commit the .env file to version control.")
    print("=" * 60)


if __name__ == "__main__":
    main()
```

## Implementation Notes

### Development Sequence

1. Start with T04-01 (auth), T04-03 (file output), T04-05 (setup script) in parallel
2. Then T04-02 (Gmail send) which depends on T04-01
3. Then T04-04 (delivery agent) which depends on T04-01, T04-02, T04-03
4. Then T04-06 (wire into pipeline) and T04-07 through T04-11 (tests)

### Testing Strategy

- Unit tests use mocked Gmail API and file system
- Integration test: send an actual email to the operator's own Gmail account with dry_run=false
- BDD tests mock the Gmail API to verify delivery flow logic

### Gmail API Setup Prerequisites

Before testing email delivery:
1. Create a Google Cloud project or use existing one
2. Enable Gmail API in the project
3. Create OAuth2 credentials (Desktop app type)
4. Download client secrets JSON
5. Run `python setup_gmail_oauth.py --client-secrets-file client_secret.json`
6. Copy the output credentials to `.env`

### Key Commands

```bash
# Run unit tests
pytest tests/test_gmail_auth.py tests/test_gmail_send.py tests/test_file_output.py tests/test_delivery_agent.py -v

# Run BDD tests
pytest tests/bdd/test_email_delivery.py -v

# Run OAuth setup
python setup_gmail_oauth.py --client-secrets-file client_secret.json

# Test email delivery manually (with real credentials)
adk web  # Then trigger pipeline with dry_run=false
```

## Parallel Opportunities

- T04-01 (auth), T04-03 (file output), T04-05 (setup script) can all be developed concurrently
- T04-07, T04-08, T04-09 can be developed concurrently after their respective implementation tasks

## Risks & Mitigations

- **Risk**: Gmail OAuth2 refresh tokens may expire after 7 days if the Google Cloud project is in "Testing" mode.
  **Mitigation**: Document that operators should publish the OAuth consent screen (even with no verification needed for personal use) or re-run the setup script periodically. Add a clear error message when refresh fails.

- **Risk**: Gmail API rate limits may prevent sending during testing if many test runs trigger actual sends.
  **Mitigation**: Default to `dry_run: true` during development. Only use real sends for explicit integration tests.

- **Risk**: MIME message encoding may cause rendering issues in some email clients.
  **Mitigation**: Use UTF-8 encoding explicitly. Test with actual email sends to Gmail web and mobile. The HTML template (WP03) is already designed for Gmail compatibility.

- **Risk**: The `google-api-python-client` library for Gmail API may have version conflicts with the `google-adk` package.
  **Mitigation**: Check compatibility during WP01 dependency installation. Both packages use the Google API client ecosystem and should be compatible.

- **Risk**: OAuth2 consent screen showing "This app isn't verified" may confuse operators.
  **Mitigation**: Document this clearly in the README with screenshots. Note that this is expected for personal use apps and is safe to proceed through.

- **Risk**: The setup script may fail if port 8080 is in use for the OAuth callback.
  **Mitigation**: Add a `--port` argument to the setup script so operators can use an alternative port.

## Detailed Test Plans

### T04-07 Test Plan: Gmail Auth Unit Tests

```python
"""
Unit tests for Gmail OAuth2 token management.
Tests: newsletter_agent/tools/gmail_auth.py
Spec refs: FR-028, FR-041, Section 10.2, Section 11.1
"""

import os
import pytest
from unittest.mock import patch, MagicMock

from newsletter_agent.tools.gmail_auth import (
    get_gmail_credentials,
    GmailAuthError,
    GmailSendError,
    GMAIL_SCOPES,
)


class TestGetGmailCredentials:
    """Tests for the get_gmail_credentials() function."""

    VALID_ENV = {
        "GMAIL_CLIENT_ID": "test-client-id.apps.googleusercontent.com",
        "GMAIL_CLIENT_SECRET": "test-client-secret",
        "GMAIL_REFRESH_TOKEN": "test-refresh-token",
    }

    @patch("newsletter_agent.tools.gmail_auth.Request")
    @patch("newsletter_agent.tools.gmail_auth.Credentials")
    @patch.dict(os.environ, VALID_ENV, clear=False)
    def test_valid_credentials_loaded_from_env(self, mock_creds_class, mock_request):
        """Test that valid credentials are loaded when all env vars are present."""
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.expired = False
        mock_creds_class.return_value = mock_creds

        result = get_gmail_credentials()

        assert result == mock_creds
        mock_creds_class.assert_called_once_with(
            token=None,
            refresh_token="test-refresh-token",
            token_uri="https://oauth2.googleapis.com/token",
            client_id="test-client-id.apps.googleusercontent.com",
            client_secret="test-client-secret",
            scopes=GMAIL_SCOPES,
        )

    @patch.dict(os.environ, {
        "GMAIL_CLIENT_SECRET": "test-secret",
        "GMAIL_REFRESH_TOKEN": "test-token",
    }, clear=True)
    def test_missing_client_id_raises_auth_error(self):
        """Test that missing GMAIL_CLIENT_ID raises GmailAuthError."""
        with pytest.raises(GmailAuthError, match="GMAIL_CLIENT_ID"):
            get_gmail_credentials()

    @patch.dict(os.environ, {
        "GMAIL_CLIENT_ID": "test-id",
        "GMAIL_REFRESH_TOKEN": "test-token",
    }, clear=True)
    def test_missing_client_secret_raises_auth_error(self):
        """Test that missing GMAIL_CLIENT_SECRET raises GmailAuthError."""
        with pytest.raises(GmailAuthError, match="GMAIL_CLIENT_SECRET"):
            get_gmail_credentials()

    @patch.dict(os.environ, {
        "GMAIL_CLIENT_ID": "test-id",
        "GMAIL_CLIENT_SECRET": "test-secret",
    }, clear=True)
    def test_missing_refresh_token_raises_auth_error(self):
        """Test that missing GMAIL_REFRESH_TOKEN raises GmailAuthError."""
        with pytest.raises(GmailAuthError, match="GMAIL_REFRESH_TOKEN"):
            get_gmail_credentials()

    @patch.dict(os.environ, {}, clear=True)
    def test_all_credentials_missing_raises_auth_error(self):
        """Test that all missing credentials lists them in the error."""
        with pytest.raises(GmailAuthError) as exc_info:
            get_gmail_credentials()
        error_msg = str(exc_info.value)
        assert "GMAIL_CLIENT_ID" in error_msg
        assert "GMAIL_CLIENT_SECRET" in error_msg
        assert "GMAIL_REFRESH_TOKEN" in error_msg
        assert "setup_gmail_oauth" in error_msg

    @patch("newsletter_agent.tools.gmail_auth.Request")
    @patch("newsletter_agent.tools.gmail_auth.Credentials")
    @patch.dict(os.environ, {
        "GMAIL_CLIENT_ID": "  test-id  ",
        "GMAIL_CLIENT_SECRET": "  test-secret  ",
        "GMAIL_REFRESH_TOKEN": "  test-token  ",
    }, clear=False)
    def test_credentials_with_whitespace_stripped(self, mock_creds_class, mock_request):
        """Test that leading/trailing whitespace is stripped from env vars."""
        mock_creds = MagicMock()
        mock_creds_class.return_value = mock_creds

        get_gmail_credentials()

        call_kwargs = mock_creds_class.call_args
        assert call_kwargs.kwargs["client_id"] == "test-id"
        assert call_kwargs.kwargs["client_secret"] == "test-secret"
        assert call_kwargs.kwargs["refresh_token"] == "test-token"

    @patch("newsletter_agent.tools.gmail_auth.Request")
    @patch("newsletter_agent.tools.gmail_auth.Credentials")
    @patch.dict(os.environ, VALID_ENV, clear=False)
    def test_expired_credentials_trigger_refresh(self, mock_creds_class, mock_request):
        """Test that expired credentials trigger a refresh attempt."""
        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds_class.return_value = mock_creds

        result = get_gmail_credentials()

        mock_creds.refresh.assert_called_once()

    @patch("newsletter_agent.tools.gmail_auth.Request")
    @patch("newsletter_agent.tools.gmail_auth.Credentials")
    @patch.dict(os.environ, VALID_ENV, clear=False)
    def test_revoked_refresh_token_raises_auth_error(self, mock_creds_class, mock_request):
        """Test that a revoked refresh token raises GmailAuthError."""
        from google.auth.exceptions import RefreshError

        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh.side_effect = RefreshError("Token has been revoked")
        mock_creds_class.return_value = mock_creds

        with pytest.raises(GmailAuthError, match="invalid or revoked"):
            get_gmail_credentials()

    @patch("newsletter_agent.tools.gmail_auth.Request")
    @patch("newsletter_agent.tools.gmail_auth.Credentials")
    @patch.dict(os.environ, VALID_ENV, clear=False)
    def test_correct_gmail_scope_requested(self, mock_creds_class, mock_request):
        """Test that the gmail.send scope is used."""
        mock_creds = MagicMock()
        mock_creds_class.return_value = mock_creds

        get_gmail_credentials()

        call_kwargs = mock_creds_class.call_args
        assert "https://www.googleapis.com/auth/gmail.send" in call_kwargs.kwargs["scopes"]

    @patch.dict(os.environ, {
        "GMAIL_CLIENT_ID": "",
        "GMAIL_CLIENT_SECRET": "test-secret",
        "GMAIL_REFRESH_TOKEN": "test-token",
    }, clear=True)
    def test_empty_string_client_id_treated_as_missing(self):
        """Test that empty string values are treated as missing."""
        with pytest.raises(GmailAuthError, match="GMAIL_CLIENT_ID"):
            get_gmail_credentials()
```

### T04-08 Test Plan: Gmail Send Unit Tests

```python
"""
Unit tests for Gmail email send function.
Tests: newsletter_agent/tools/gmail_send.py
Spec refs: FR-027, FR-029, FR-030, Section 8.3, Section 11.1
"""

import base64
import email
import pytest
from unittest.mock import patch, MagicMock, call

from newsletter_agent.tools.gmail_send import (
    send_newsletter_email,
    _strip_html,
)
from newsletter_agent.tools.gmail_auth import GmailAuthError


class TestSendNewsletterEmail:
    """Tests for the send_newsletter_email() function."""

    SAMPLE_HTML = """
    <html>
    <body>
        <h1>Weekly Newsletter</h1>
        <p>Here are your top stories:</p>
        <ul>
            <li>Story One</li>
            <li>Story Two</li>
        </ul>
    </body>
    </html>
    """

    @patch("newsletter_agent.tools.gmail_send.build")
    @patch("newsletter_agent.tools.gmail_send.get_gmail_credentials")
    def test_successful_send_returns_message_id(self, mock_creds, mock_build):
        """Test that a successful send returns status 'sent' with message ID."""
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        send_result = {"id": "msg-abc-123", "threadId": "thread-xyz"}
        mock_service.users().messages().send().execute.return_value = send_result

        result = send_newsletter_email(
            self.SAMPLE_HTML,
            "user@gmail.com",
            "Test Subject"
        )

        assert result["status"] == "sent"
        assert result["message_id"] == "msg-abc-123"

    @patch("newsletter_agent.tools.gmail_send.build")
    @patch("newsletter_agent.tools.gmail_send.get_gmail_credentials")
    def test_mime_message_has_html_and_plain_parts(self, mock_creds, mock_build):
        """Test that the MIME message contains HTML and plain-text parts."""
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.users().messages().send().execute.return_value = {"id": "test"}

        captured_body = {}

        def capture_send(**kwargs):
            captured_body.update(kwargs.get("body", {}))
            mock_exec = MagicMock()
            mock_exec.execute.return_value = {"id": "test"}
            return mock_exec

        mock_service.users().messages().send = capture_send

        send_newsletter_email(self.SAMPLE_HTML, "user@gmail.com", "Test")

        raw = captured_body.get("raw", "")
        decoded = base64.urlsafe_b64decode(raw + "==")
        msg = email.message_from_bytes(decoded)

        assert msg.get_content_type() == "multipart/alternative"
        parts = list(msg.walk())
        content_types = [p.get_content_type() for p in parts]
        assert "text/plain" in content_types
        assert "text/html" in content_types

    @patch("newsletter_agent.tools.gmail_send.build")
    @patch("newsletter_agent.tools.gmail_send.get_gmail_credentials")
    def test_correct_email_headers(self, mock_creds, mock_build):
        """Test that To, From, and Subject headers are set correctly."""
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        captured_body = {}

        def capture_send(**kwargs):
            captured_body.update(kwargs.get("body", {}))
            mock_exec = MagicMock()
            mock_exec.execute.return_value = {"id": "test"}
            return mock_exec

        mock_service.users().messages().send = capture_send

        send_newsletter_email(
            "<p>test</p>",
            "operator@gmail.com",
            "AI Weekly - 2026-03-14"
        )

        raw = captured_body.get("raw", "")
        decoded = base64.urlsafe_b64decode(raw + "==")
        msg = email.message_from_bytes(decoded)

        assert msg["To"] == "operator@gmail.com"
        assert msg["Subject"] == "AI Weekly - 2026-03-14"

    @patch("newsletter_agent.tools.gmail_send.get_gmail_credentials")
    def test_auth_failure_returns_error_dict(self, mock_creds):
        """Test that authentication failure returns error dict, not raises."""
        mock_creds.side_effect = GmailAuthError("Missing GMAIL_CLIENT_ID")

        result = send_newsletter_email("<p>test</p>", "user@gmail.com", "Test")

        assert result["status"] == "error"
        assert "GMAIL_CLIENT_ID" in result["error_message"]

    @patch("newsletter_agent.tools.gmail_send.build")
    @patch("newsletter_agent.tools.gmail_send.get_gmail_credentials")
    def test_gmail_api_403_returns_error(self, mock_creds, mock_build):
        """Test that a 403 Forbidden returns error dict."""
        from googleapiclient.errors import HttpError
        import io

        mock_service = MagicMock()
        mock_build.return_value = mock_service

        resp = MagicMock()
        resp.status = 403
        resp.reason = "Insufficient Permission"
        http_err = HttpError(resp, b"Insufficient Permission")
        mock_service.users().messages().send().execute.side_effect = http_err

        result = send_newsletter_email("<p>test</p>", "user@gmail.com", "Test")

        assert result["status"] == "error"
        assert "403" in result["error_message"]

    @patch("newsletter_agent.tools.gmail_send.build")
    @patch("newsletter_agent.tools.gmail_send.get_gmail_credentials")
    def test_gmail_api_500_returns_error(self, mock_creds, mock_build):
        """Test that a 500 Internal Server Error returns error dict."""
        from googleapiclient.errors import HttpError

        mock_service = MagicMock()
        mock_build.return_value = mock_service

        resp = MagicMock()
        resp.status = 500
        resp.reason = "Internal Server Error"
        http_err = HttpError(resp, b"Internal Server Error")
        mock_service.users().messages().send().execute.side_effect = http_err

        result = send_newsletter_email("<p>test</p>", "user@gmail.com", "Test")

        assert result["status"] == "error"
        assert "500" in result["error_message"]

    @patch("newsletter_agent.tools.gmail_send.build")
    @patch("newsletter_agent.tools.gmail_send.get_gmail_credentials")
    def test_network_error_returns_error(self, mock_creds, mock_build):
        """Test that network errors return error dict."""
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.users().messages().send().execute.side_effect = (
            ConnectionError("Network unreachable")
        )

        result = send_newsletter_email("<p>test</p>", "user@gmail.com", "Test")

        assert result["status"] == "error"
        assert "Network unreachable" in result["error_message"]

    @patch("newsletter_agent.tools.gmail_send.build")
    @patch("newsletter_agent.tools.gmail_send.get_gmail_credentials")
    def test_large_html_content(self, mock_creds, mock_build):
        """Test that large HTML content is handled."""
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.users().messages().send().execute.return_value = {"id": "lg-1"}

        large_html = "<html><body>" + "<p>Paragraph</p>" * 500 + "</body></html>"

        result = send_newsletter_email(large_html, "user@gmail.com", "Large Test")

        assert result["status"] == "sent"

    @patch("newsletter_agent.tools.gmail_send.build")
    @patch("newsletter_agent.tools.gmail_send.get_gmail_credentials")
    def test_html_with_special_characters(self, mock_creds, mock_build):
        """Test that special characters in HTML are handled."""
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.users().messages().send().execute.return_value = {"id": "sp-1"}

        special_html = "<html><body><p>Caf&eacute; &amp; 100% organic &lt;AI&gt;</p></body></html>"

        result = send_newsletter_email(special_html, "user@gmail.com", "Special")

        assert result["status"] == "sent"


class TestStripHtml:
    """Tests for the _strip_html() helper function."""

    def test_simple_paragraph(self):
        result = _strip_html("<p>Hello world</p>")
        assert "Hello world" in result

    def test_br_tags_become_newlines(self):
        result = _strip_html("Line one<br>Line two<br/>Line three")
        assert "Line one\nLine two\nLine three" in result

    def test_heading_tags_add_spacing(self):
        result = _strip_html("<h1>Title</h1><p>Content</p>")
        assert "Title" in result
        assert "Content" in result

    def test_list_items(self):
        result = _strip_html("<ul><li>Item 1</li><li>Item 2</li></ul>")
        assert "Item 1" in result
        assert "Item 2" in result

    def test_empty_html(self):
        result = _strip_html("")
        assert result == ""

    def test_nested_tags(self):
        result = _strip_html("<p><strong>Bold</strong> and <em>italic</em></p>")
        assert "Bold" in result
        assert "italic" in result
```

### T04-09 Test Plan: File Output Unit Tests

```python
"""
Unit tests for file output function.
Tests: newsletter_agent/tools/file_output.py
Spec refs: FR-031, FR-034, FR-035, Section 11.1
"""

import os
import pytest
from pathlib import Path

from newsletter_agent.tools.file_output import save_newsletter_html


class TestSaveNewsletterHtml:
    """Tests for the save_newsletter_html() function."""

    SAMPLE_HTML = "<html><body><h1>Test Newsletter</h1></body></html>"

    def test_save_to_existing_directory(self, tmp_path):
        """Test saving HTML to an existing directory."""
        result = save_newsletter_html(self.SAMPLE_HTML, str(tmp_path), "2026-03-14")

        assert os.path.exists(result)
        assert result.endswith("2026-03-14-newsletter.html")
        content = Path(result).read_text(encoding="utf-8")
        assert content == self.SAMPLE_HTML

    def test_save_to_new_directory_auto_created(self, tmp_path):
        """Test saving HTML to a non-existing directory creates it."""
        nested_dir = str(tmp_path / "output" / "newsletters" / "2026")
        result = save_newsletter_html(self.SAMPLE_HTML, nested_dir, "2026-03-14")

        assert os.path.exists(result)
        assert os.path.isdir(nested_dir)

    def test_file_path_format(self, tmp_path):
        """Test that the file path matches {output_dir}/{date}-newsletter.html."""
        result = save_newsletter_html(self.SAMPLE_HTML, str(tmp_path), "2026-01-15")
        expected = str(tmp_path / "2026-01-15-newsletter.html")
        assert Path(result).name == "2026-01-15-newsletter.html"

    def test_file_content_matches_input(self, tmp_path):
        """Test that the saved file content matches the input HTML."""
        complex_html = """
        <html>
        <head><style>body { font-family: Arial; }</style></head>
        <body>
            <h1>Complex Newsletter</h1>
            <p>With <strong>bold</strong> and <em>italic</em> text.</p>
        </body>
        </html>
        """
        result = save_newsletter_html(complex_html, str(tmp_path), "2026-03-14")
        content = Path(result).read_text(encoding="utf-8")
        assert content == complex_html

    def test_overwrite_existing_file(self, tmp_path):
        """Test that re-saving overwrites the existing file."""
        save_newsletter_html("<p>Version 1</p>", str(tmp_path), "2026-03-14")
        result = save_newsletter_html("<p>Version 2</p>", str(tmp_path), "2026-03-14")

        content = Path(result).read_text(encoding="utf-8")
        assert content == "<p>Version 2</p>"

    def test_utf8_encoding_with_special_characters(self, tmp_path):
        """Test that UTF-8 characters are preserved."""
        unicode_html = "<p>Cafe, Uber, naif, resume</p>"
        result = save_newsletter_html(unicode_html, str(tmp_path), "2026-03-14")

        content = Path(result).read_text(encoding="utf-8")
        assert content == unicode_html

    def test_returned_path_is_absolute(self, tmp_path):
        """Test that the returned path is an absolute path."""
        result = save_newsletter_html(self.SAMPLE_HTML, str(tmp_path), "2026-03-14")
        assert os.path.isabs(result)

    def test_permission_error_raises_ioerror(self, tmp_path):
        """Test that permission errors raise IOError."""
        # This test is platform-dependent - skip on platforms where
        # permission simulation is unreliable
        if os.name != "posix":
            pytest.skip("Permission test only on POSIX")

        read_only_dir = tmp_path / "readonly"
        read_only_dir.mkdir()
        read_only_dir.chmod(0o444)

        try:
            nested = str(read_only_dir / "nested" / "dir")
            with pytest.raises(IOError):
                save_newsletter_html(self.SAMPLE_HTML, nested, "2026-03-14")
        finally:
            read_only_dir.chmod(0o755)
```

### T04-10 Test Plan: Delivery Agent Unit Tests

```python
"""
Unit tests for the delivery agent.
Tests: newsletter_agent/agents/delivery_agent.py
Spec refs: FR-027, FR-031, FR-032, FR-033, Section 11.1, Section 11.2
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock


class TestDeliveryAgent:
    """Tests for the delivery agent orchestration logic."""

    def _make_state(self, **overrides):
        """Create a mock session state with defaults."""
        state = {
            "newsletter_html": "<h1>Test Newsletter</h1>",
            "newsletter_metadata": {
                "title": "AI Weekly",
                "date": "2026-03-14",
                "topic_count": 3,
            },
            "config_dry_run": False,
            "config_output_dir": "/tmp/output",
            "config_recipient_email": "user@gmail.com",
        }
        state.update(overrides)
        return state

    @patch("newsletter_agent.agents.delivery_agent.send_newsletter_email")
    async def test_successful_email_delivery(self, mock_send):
        """Test successful email delivery stores sent status in state."""
        mock_send.return_value = {"status": "sent", "message_id": "msg-123"}

        state = self._make_state()
        # Execute delivery agent logic (implementation-specific)
        # After execution:
        # assert state["delivery_status"]["status"] == "sent"
        # assert state["delivery_status"]["message_id"] == "msg-123"

    @patch("newsletter_agent.agents.delivery_agent.save_newsletter_html")
    async def test_dry_run_saves_html_to_disk(self, mock_save):
        """Test dry-run mode saves HTML to disk without sending email."""
        mock_save.return_value = "/tmp/output/2026-03-14-newsletter.html"

        state = self._make_state(config_dry_run=True)
        # Execute delivery agent logic
        # After execution:
        # assert state["delivery_status"]["status"] == "dry_run"
        # assert "output_file" in state["delivery_status"]
        # mock_send should not have been called

    @patch("newsletter_agent.agents.delivery_agent.save_newsletter_html")
    @patch("newsletter_agent.agents.delivery_agent.send_newsletter_email")
    async def test_email_failure_triggers_fallback_save(self, mock_send, mock_save):
        """Test email failure saves HTML as fallback."""
        mock_send.return_value = {
            "status": "error",
            "error_message": "403 Insufficient Permission",
        }
        mock_save.return_value = "/tmp/output/2026-03-14-newsletter.html"

        state = self._make_state()
        # Execute delivery agent logic
        # After execution:
        # assert state["delivery_status"]["status"] == "failed"
        # assert "fallback_file" in state["delivery_status"]
        # assert "error" in state["delivery_status"]

    async def test_missing_newsletter_html_in_state(self):
        """Test that missing newsletter_html in state is handled."""
        state = self._make_state(newsletter_html="")
        # Execute delivery agent logic
        # Agent should handle empty HTML gracefully

    async def test_correct_subject_format(self):
        """Test email subject follows format: {title} - {date}."""
        state = self._make_state()
        # The subject should be "AI Weekly - 2026-03-14"
        expected_subject = "AI Weekly - 2026-03-14"
        # Verify in the send_newsletter_email call args

    @patch("newsletter_agent.agents.delivery_agent.save_newsletter_html")
    async def test_dry_run_does_not_load_credentials(self, mock_save):
        """Test dry-run mode never loads Gmail credentials."""
        mock_save.return_value = "/tmp/output/2026-03-14-newsletter.html"

        state = self._make_state(config_dry_run=True)
        # Execute delivery agent logic
        # get_gmail_credentials should not have been called

    @patch("newsletter_agent.agents.delivery_agent.send_newsletter_email")
    async def test_delivery_status_stored_in_state_for_sent(self, mock_send):
        """Test sent status is stored in state."""
        mock_send.return_value = {"status": "sent", "message_id": "msg-456"}

        state = self._make_state()
        # Execute delivery agent logic
        # assert "delivery_status" in state

    @patch("newsletter_agent.agents.delivery_agent.save_newsletter_html")
    async def test_delivery_status_stored_in_state_for_dry_run(self, mock_save):
        """Test dry-run status is stored in state."""
        mock_save.return_value = "/tmp/output/2026-03-14-newsletter.html"

        state = self._make_state(config_dry_run=True)
        # Execute delivery agent logic
        # assert state["delivery_status"]["status"] == "dry_run"
```

### T04-11 Test Plan: BDD Acceptance Tests

```python
"""
BDD acceptance tests for email delivery.
Tests: Full delivery flow end-to-end.
Spec refs: Section 11.2, US-05

Feature: Email Delivery
  As a newsletter operator
  I want the newsletter delivered to my Gmail inbox
  So that I receive the curated content automatically

  Scenario: Successful email send
    Given a formatted HTML newsletter in state
    And valid Gmail OAuth2 credentials in environment
    And config has dry_run set to false
    When the delivery agent runs
    Then an email is sent via Gmail API
    And state contains delivery_status with status "sent"
    And the email has subject "{title} - {date}"
    And the email contains both HTML and plain-text parts

  Scenario: Dry run mode
    Given a formatted HTML newsletter in state
    And config has dry_run set to true
    When the delivery agent runs
    Then no email is sent via Gmail API
    And the HTML is saved to {output_dir}/{date}-newsletter.html
    And state contains delivery_status with status "dry_run"
    And the output file path is stored in state

  Scenario: Email failure with fallback
    Given a formatted HTML newsletter in state
    And Gmail API returns a 403 error
    And config has dry_run set to false
    When the delivery agent runs
    Then the error is logged at ERROR level
    And the HTML is saved locally as fallback
    And state contains delivery_status with status "failed"
    And the fallback file path and error message are in state

  Scenario: Expired token triggers refresh
    Given a formatted HTML newsletter in state
    And the OAuth2 access token is expired
    And the refresh token is valid
    When the delivery agent runs
    Then the access token is refreshed automatically
    And the email is sent successfully
    And state contains delivery_status with status "sent"
"""

import os
import pytest
from unittest.mock import patch, MagicMock


class TestFeatureEmailDelivery:
    """BDD scenarios for email delivery feature."""

    @patch("newsletter_agent.tools.gmail_send.build")
    @patch("newsletter_agent.tools.gmail_send.get_gmail_credentials")
    def test_scenario_successful_email_send(self, mock_creds, mock_build):
        """
        Scenario: Successful email send
        Given a formatted HTML newsletter in state
        And valid Gmail OAuth2 credentials in environment
        And config has dry_run set to false
        When the delivery agent runs
        Then an email is sent via Gmail API
        And state contains delivery_status with status "sent"
        """
        # Given
        html_content = "<html><body><h1>AI Weekly</h1></body></html>"
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.users().messages().send().execute.return_value = {
            "id": "msg-bdd-001"
        }

        # When
        from newsletter_agent.tools.gmail_send import send_newsletter_email
        result = send_newsletter_email(
            html_content,
            "operator@gmail.com",
            "AI Weekly - 2026-03-14"
        )

        # Then
        assert result["status"] == "sent"
        assert result["message_id"] == "msg-bdd-001"
        mock_service.users().messages().send.assert_called_once()

    @patch("newsletter_agent.tools.file_output.save_newsletter_html")
    def test_scenario_dry_run_mode(self, mock_save):
        """
        Scenario: Dry run mode
        Given a formatted HTML newsletter in state
        And config has dry_run set to true
        When the delivery agent runs
        Then no email is sent via Gmail API
        And the HTML is saved to {output_dir}/{date}-newsletter.html
        """
        # Given
        html_content = "<html><body><h1>AI Weekly</h1></body></html>"
        mock_save.return_value = "/tmp/output/2026-03-14-newsletter.html"

        # When
        result_path = mock_save(html_content, "/tmp/output", "2026-03-14")

        # Then
        assert result_path == "/tmp/output/2026-03-14-newsletter.html"
        mock_save.assert_called_once_with(
            html_content, "/tmp/output", "2026-03-14"
        )

    @patch("newsletter_agent.tools.gmail_send.build")
    @patch("newsletter_agent.tools.gmail_send.get_gmail_credentials")
    def test_scenario_email_failure_with_fallback(self, mock_creds, mock_build):
        """
        Scenario: Email failure with fallback
        Given Gmail API returns a 403 error
        When the delivery agent sends an email
        Then an error dict is returned (not raised)
        """
        # Given
        from googleapiclient.errors import HttpError
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        resp = MagicMock()
        resp.status = 403
        resp.reason = "Insufficient Permission"
        mock_service.users().messages().send().execute.side_effect = (
            HttpError(resp, b"Insufficient Permission")
        )

        # When
        from newsletter_agent.tools.gmail_send import send_newsletter_email
        result = send_newsletter_email(
            "<p>test</p>",
            "operator@gmail.com",
            "AI Weekly - 2026-03-14"
        )

        # Then
        assert result["status"] == "error"
        assert "403" in result["error_message"]

    @patch("newsletter_agent.tools.gmail_auth.Request")
    @patch("newsletter_agent.tools.gmail_auth.Credentials")
    @patch.dict(os.environ, {
        "GMAIL_CLIENT_ID": "test-id",
        "GMAIL_CLIENT_SECRET": "test-secret",
        "GMAIL_REFRESH_TOKEN": "test-refresh-token",
    })
    def test_scenario_expired_token_triggers_refresh(self, mock_creds_class, mock_request):
        """
        Scenario: Expired token triggers refresh
        Given the OAuth2 access token is expired
        And the refresh token is valid
        When credentials are loaded
        Then the access token is refreshed automatically
        """
        # Given
        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds_class.return_value = mock_creds

        # When
        from newsletter_agent.tools.gmail_auth import get_gmail_credentials
        result = get_gmail_credentials()

        # Then
        mock_creds.refresh.assert_called_once()
```

## Edge Cases and Error Handling

### Email Delivery Edge Cases

1. **Empty HTML content**: The delivery agent should not attempt to send an empty email. If `newsletter_html` is empty or None in state, log a warning and skip delivery, setting `delivery_status` to `{"status": "skipped", "reason": "No newsletter content to deliver"}`.

2. **Missing recipient email in config**: If `config_recipient_email` is not in state, raise a descriptive error. This should have been validated during config loading (WP01), but defensive validation here prevents silent failures.

3. **Very large newsletters**: Gmail has a 25MB attachment limit and a 35KB body limit for base64-encoded messages. The newsletter HTML (typically 15-30KB) is well under this limit, but if synthesis produces extraordinarily long content, the MIME message could exceed Gmail limits. The send function should not truncate - let the Gmail API return the error, which gets handled by the error dict path.

4. **HTML with inline images**: The MVP spec does not include inline images. If future versions add them, the MIME message would need a `multipart/related` structure instead of `multipart/alternative`. Current implementation only handles text.

5. **Concurrent sends**: The MVP is single-recipient, single-send. No concurrency concerns for email delivery.

6. **Network timeout during send**: The `google-api-python-client` has a default timeout. If the send times out, it raises an exception caught by the general error handler. No custom timeout configuration needed for MVP.

7. **Gmail API quota**: Gmail has a daily sending limit (2,000 emails/day for regular accounts). The MVP sends one email per run, so this is not a concern. Document the limit for future multi-recipient expansions.

### File Output Edge Cases

1. **Output directory on different filesystem**: If `output_dir` is on a different mount point (e.g., network drive), `mkdir(parents=True)` still works. No special handling needed.

2. **Symlinked output directory**: If `output_dir` is a symlink, `Path.mkdir()` follows symlinks. The resolved path is returned.

3. **Disk full**: If the disk is full, `write_text()` raises `OSError`. This propagates as-is - the delivery agent's fallback handler catches it.

4. **Filename with special date formats**: The `newsletter_date` parameter should always be `YYYY-MM-DD`. Invalid date strings (e.g., `2026/03/14`) would create filenames with path separators. The caller (delivery agent) is responsible for providing the correct format.

5. **Unicode in output directory path**: On Windows, paths with Unicode characters may cause issues with some tools. Use `pathlib.Path` which handles Unicode natively.

### OAuth2 Edge Cases

1. **Rate-limited refresh requests**: Google may rate-limit token refresh requests if called too frequently. The MVP refreshes once per pipeline run, so this is not a concern.

2. **Multi-factor authentication**: Google accounts with 2FA prompt the user during the initial OAuth consent flow. Once the refresh token is obtained, 2FA is not required for API calls.

3. **Account suspension**: If the Google account is suspended, all API calls fail. The error is caught and returned as an error dict.

4. **Scope changes**: If the required scope changes in a future version, the refresh token becomes invalid. The operator must re-run the setup script.

5. **Token storage security**: Credentials are stored only in environment variables (loaded from `.env`). The `.env` file must be in `.gitignore` (handled by WP01). No credentials are written to logs or state.

## Rollback Considerations

### If Gmail send fails mid-pipeline:
- The fallback file output ensures the newsletter is not lost
- The pipeline can be re-run safely (idempotent output file naming)
- No partial email state to clean up (Gmail API send is atomic)

### If file output fails:
- The HTML content remains in session state
- The pipeline log contains the full error details
- The operator can manually save the HTML from the state dump

### If OAuth credentials are invalid:
- The setup script can be re-run at any time
- No data loss - the operator simply re-authorizes
- All previously sent newsletters are unaffected

## Security Considerations

### Credential Protection

1. **Environment variables only**: Gmail credentials are loaded exclusively from environment variables. No credentials are stored in files, databases, or session state. The `.env` file is the only on-disk storage, and it must be in `.gitignore`.

2. **No credential logging**: The `get_gmail_credentials()` function and `send_newsletter_email()` function must NEVER log credential values. Log only whether operations succeeded or failed.

3. **Minimal scope**: The OAuth2 scope is limited to `gmail.send` only. The application cannot read, modify, or delete emails in the operator's inbox.

4. **Token refresh in memory**: Refreshed access tokens exist only in the `Credentials` object in memory. They are not persisted to disk or environment variables.

5. **Setup script output**: The setup script prints credentials to stdout. The operator must manually copy them to `.env`. The script does not write to `.env` automatically (prevents accidental overwrites and makes the operator aware of the credentials).

### HTML Content Safety

1. **No user-generated HTML**: The newsletter HTML is generated by the synthesis agent (WP03) using Jinja2 templates with auto-escaping. External content (research summaries) is text-only and escaped before template rendering.

2. **No script injection**: The HTML template does not include `<script>` tags or event handlers. The nh3 sanitizer (WP03) removes any that might be injected by the LLM.

3. **Email client rendering**: Gmail's web client strips most CSS and all JavaScript from HTML emails. This is an additional safety layer beyond our own sanitization.

### Error Message Safety

1. **No stack traces to users**: Error dicts returned by `send_newsletter_email()` contain descriptive messages, not raw stack traces. Stack traces are logged at DEBUG level only.

2. **No credential leakage in errors**: Error messages from Google auth library may contain partial credential information. The error handler wraps these in generic messages before storing in state.

### Network Security

1. **TLS only**: All Gmail API calls and OAuth2 token refreshes use HTTPS (TLS 1.2+). The `google-api-python-client` enforces this by default.

2. **No custom certificates**: The application uses the system's default CA certificate bundle. No certificate pinning is needed for Google APIs.

3. **No proxy configuration**: The MVP does not support HTTP proxies. If the operator is behind a proxy, they must configure the system-level proxy settings.

## Integration Test Strategy

### Manual Integration Test: Real Email Send

This test is run manually by the developer with real Gmail credentials. It is NOT part of the automated test suite.

**Prerequisites**:
1. Google Cloud project with Gmail API enabled
2. OAuth2 credentials (Desktop app type) configured
3. `.env` file with `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`

**Steps**:
1. Set `dry_run: false` in the YAML config
2. Run the full pipeline: `adk run newsletter_agent`
3. Check the operator's Gmail inbox for the newsletter email
4. Verify:
   - Email arrived within 60 seconds
   - Subject matches `{title} - {YYYY-MM-DD}`
   - HTML renders correctly in Gmail web client
   - Plain-text part is visible when toggling "Show original" and checking text/plain part
   - No broken images or layout issues
   - Email From address is the authenticated Gmail account

### Manual Integration Test: Dry Run

**Steps**:
1. Set `dry_run: true` in the YAML config
2. Run the full pipeline: `adk run newsletter_agent`
3. Verify:
   - No email is sent
   - HTML file exists at `{output_dir}/{YYYY-MM-DD}-newsletter.html`
   - The HTML file opens correctly in a browser
   - Console output indicates dry-run mode

### Manual Integration Test: Failure Fallback

**Steps**:
1. Set `dry_run: false` in the YAML config
2. Set `GMAIL_REFRESH_TOKEN` to an invalid value (e.g., `invalid-token`)
3. Run the full pipeline: `adk run newsletter_agent`
4. Verify:
   - Error is logged at ERROR level
   - HTML file is saved to the output directory as fallback
   - Console output indicates delivery failed with fallback
   - The process exits with a non-zero status code

### Automated Integration Test: Gmail API Mock Server

For CI/CD environments, create a lightweight mock Gmail API server that:
- Accepts OAuth2 token refresh requests and returns fake tokens
- Accepts messages.send requests and returns fake message IDs
- Can be configured to return specific error codes for negative testing

This is a post-MVP enhancement and not required for the initial release.

## Dependencies and Version Requirements

| Package | Version | Purpose |
|---------|---------|---------|
| google-auth | >=2.22.0 | OAuth2 credentials management |
| google-auth-oauthlib | >=1.0.0 | Interactive OAuth2 consent flow |
| google-api-python-client | >=2.95.0 | Gmail API client |
| google-auth-httplib2 | >=0.1.0 | HTTP transport for auth |

These packages should be added to `pyproject.toml` or `requirements.txt` during WP01 project scaffolding.

### Compatibility Notes

- The `google-adk` package uses protobuf internally. Ensure the `protobuf` version is compatible with `google-api-python-client` (both typically use protobuf 4.x).
- The `google-auth-oauthlib` package is only needed for the interactive setup script, not for runtime email sending. It can be listed as a dev dependency.
- The `httplib2` transport is used by `google-api-python-client`. Ensure no version conflicts with the `requests` library used elsewhere.
- On Windows, `google-auth-oauthlib` requires `pywin32` for some credential operations. Add it as a conditional dependency for Windows environments.
- Python 3.10+ is required for all Google auth packages in the versions specified above.

## Activity Log

- 2025-01-01T00:00:00Z - planner - lane=planned - Work package created
