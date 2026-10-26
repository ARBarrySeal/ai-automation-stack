"""
verify_n8n_webhook_auth.py — Probe each n8n webhook with and without the shared
secret to confirm authentication is enforced.

Expected result for a properly-configured webhook:
  WITHOUT header: HTTP 401/403, OR a deliberate "rejected" response payload
  WITH header:    HTTP 2xx

Run:  python scripts/verify_n8n_webhook_auth.py

If a webhook accepts requests WITHOUT the header, that flow is unauthenticated
and needs the verify-secret Code node added at the top (see
docs/n8n-webhook-auth-setup.md).
"""
from __future__ import annotations

import json
import sys
from typing import Any

import urllib.request
import urllib.error

import _env  # noqa: F401 — loads .env
import os

SECRET = os.environ.get("N8N_WEBHOOK_SECRET", "")
BASE = "http://localhost:5678/webhook"

WEBHOOKS = [
    ("sam-leads", {"test": True, "ueiSAM": "TEST", "name": "probe"}),
    ("leads", {"test": True, "name": "probe", "company": "probe"}),
    ("sms-followup", {"test": True, "to": "+15555555555", "body": "probe"}),
    ("proposal", {"test": True, "company": "probe", "scope": "probe"}),
    ("analyze", {"test": True, "company": "probe", "controls": []}),
]


def call(path: str, body: dict[str, Any], with_secret: bool) -> tuple[int, str]:
    url = f"{BASE}/{path}"
    headers = {"Content-Type": "application/json"}
    if with_secret:
        if not SECRET:
            return 0, "N8N_WEBHOOK_SECRET missing from .env"
        headers["X-Webhook-Token"] = SECRET
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode(errors="replace")[:120]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")[:120]
    except Exception as e:
        return 0, f"connection: {e}"


def main() -> int:
    if not SECRET:
        print("ERROR: N8N_WEBHOOK_SECRET not set in .env — aborting.")
        return 2

    print(f"Probing {len(WEBHOOKS)} webhooks on {BASE}\n")
    failures = 0
    for path, body in WEBHOOKS:
        unauth_code, unauth_body = call(path, body, with_secret=False)
        auth_code, auth_body = call(path, body, with_secret=True)

        unauth_ok = unauth_code in (401, 403) or "reject" in unauth_body.lower() or "denied" in unauth_body.lower()
        auth_ok = 200 <= auth_code < 300

        marker = "OK " if unauth_ok and auth_ok else "FAIL"
        print(f"  [{marker}] /{path:<14}  without_secret={unauth_code}  with_secret={auth_code}")
        if not unauth_ok:
            print(f"         ^ UNAUTHENTICATED ACCEPTED — add verify-secret node (see docs/n8n-webhook-auth-setup.md)")
            failures += 1
        if not auth_ok and unauth_ok:
            print(f"         ^ authenticated call also failed — workflow may be inactive or test payload invalid")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
