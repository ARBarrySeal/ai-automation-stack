"""
gmail_draft.py — Create Gmail drafts using stored OAuth credentials.
Import and call create_draft() from other scripts.

If you get an auth error, run once to re-authorize:
  python reauth_gmail.py
"""
import base64
import json
import os
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from _env import env, SENDER_EMAIL

CREDS_DIR = Path(env("GMAIL_CREDENTIALS_DIR", "~/.gmail-mcp")).expanduser()
CREDS_PATH = CREDS_DIR / "credentials.json"
OAUTH_PATH = CREDS_DIR / "gcp-oauth.keys.json"
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
]


def _get_service():
    with open(CREDS_PATH) as f:
        cred_data = json.load(f)
    with open(OAUTH_PATH) as f:
        oauth_data = json.load(f)["installed"]

    creds = Credentials(
        token=cred_data.get("access_token"),
        refresh_token=cred_data.get("refresh_token"),
        token_uri=oauth_data["token_uri"],
        client_id=oauth_data["client_id"],
        client_secret=oauth_data["client_secret"],
        scopes=SCOPES,
    )

    if creds.expired or not creds.valid:
        try:
            creds.refresh(Request())
            cred_data["access_token"] = creds.token
            with open(CREDS_PATH, "w") as f:
                json.dump(cred_data, f)
        except Exception:
            raise RuntimeError(
                "Gmail credentials expired. Run once to fix:\n"
                "  python scripts/reauth_gmail.py"
            )

    return build("gmail", "v1", credentials=creds)


def create_draft(to: str = "", subject: str = "", body: str = "") -> str:
    """Create a Gmail draft. Returns draft ID. `to` defaults to SENDER_EMAIL (a draft to yourself)."""
    to = to or SENDER_EMAIL
    service = _get_service()
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["To"] = to
    msg.attach(MIMEText(body, "plain", "utf-8"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    draft = service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
    return draft["id"]
