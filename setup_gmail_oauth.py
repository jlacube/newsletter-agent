"""
One-time Gmail OAuth2 setup script.

Runs the interactive OAuth2 consent flow in the operator's browser,
obtains a refresh token, and prints the environment variables to set.

Usage:
    python setup_gmail_oauth.py --client-secrets-file client_secret.json
"""

import argparse
import json
import sys
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def main() -> None:
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
        help="Local port for the OAuth2 callback server (default: 8080)",
    )
    args = parser.parse_args()

    secrets_path = Path(args.client_secrets_file)
    if not secrets_path.exists():
        print(f"Error: Client secrets file not found: {secrets_path}")
        sys.exit(1)

    # Validate the file is valid JSON with expected structure
    try:
        with open(secrets_path, encoding="utf-8") as f:
            data = json.load(f)
        if "installed" not in data and "web" not in data:
            print(
                "Error: Client secrets file does not contain 'installed' "
                "or 'web' credentials. Download the correct file from "
                "Google Cloud Console > APIs & Services > Credentials."
            )
            sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Client secrets file is not valid JSON: {e}")
        sys.exit(1)

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Error: google-auth-oauthlib is required. Install with:")
        print("  pip install google-auth-oauthlib")
        sys.exit(1)

    print("Opening browser for Google OAuth2 consent...")
    print("(If the browser does not open, copy the URL from the terminal.)")
    print()

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
        sys.exit(0)
    except Exception as e:
        print(f"\nOAuth2 flow failed: {e}")
        sys.exit(1)

    if not creds.refresh_token:
        print(
            "\nWarning: No refresh token received. This can happen if you "
            "previously authorized this app. Try revoking access at "
            "https://myaccount.google.com/permissions and running again."
        )
        sys.exit(1)

    print("\nOAuth2 setup complete!")
    print("\nAdd these lines to your .env file:")
    print(f"GMAIL_CLIENT_ID={creds.client_id}")
    print(f"GMAIL_CLIENT_SECRET={creds.client_secret}")
    print(f"GMAIL_REFRESH_TOKEN={creds.refresh_token}")
    print()
    print("Then run the newsletter agent with dry_run: false to test email delivery.")


if __name__ == "__main__":
    main()
