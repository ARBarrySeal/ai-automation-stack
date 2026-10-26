"""
reauth_gmail.py — Refresh expired Gmail OAuth credentials.

Run this once whenever gmail_draft.py fails with an auth error:
  python reauth_gmail.py

Opens a browser window to re-authorize, then saves the new token to:
  $GMAIL_CREDENTIALS_DIR/credentials.json   (default ~/.gmail-mcp)

First time: create an OAuth client (Desktop app) in Google Cloud Console with the
Gmail API enabled, download it, and save it as gcp-oauth.keys.json in that folder.
"""
import json
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

from _env import env, SENDER_EMAIL

CREDS_DIR = Path(env("GMAIL_CREDENTIALS_DIR", "~/.gmail-mcp")).expanduser()
OAUTH_PATH = CREDS_DIR / "gcp-oauth.keys.json"
CREDS_PATH = CREDS_DIR / "credentials.json"
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
]


def main():
    print("Opening browser for Gmail authorization...")
    print(f"Sign in as {SENDER_EMAIL or 'the Gmail account that should own the drafts'}\n")

    flow = InstalledAppFlow.from_client_secrets_file(OAUTH_PATH, SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True)

    token_data = {
        "access_token": creds.token,
        "refresh_token": creds.refresh_token,
        "scope": " ".join(creds.scopes) if creds.scopes else "",
        "token_type": "Bearer",
        "expiry_date": int(creds.expiry.timestamp() * 1000) if creds.expiry else 0,
    }

    CREDS_DIR.mkdir(parents=True, exist_ok=True)
    with open(CREDS_PATH, "w") as f:
        json.dump(token_data, f, indent=2)

    print(f"\nCredentials saved to {CREDS_PATH}")
    print("You can now run leads_pipeline.py --draft-gmail")


if __name__ == "__main__":
    main()
