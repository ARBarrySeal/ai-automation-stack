"""
Lightweight .env loader (stdlib only — no python-dotenv dependency).

Usage:
    from _env import env, require
    HS_TOKEN = require("HUBSPOT_TOKEN")          # exits with clear error if missing
    APOLLO = env("APOLLO_KEY", default="")        # optional, with fallback

Loads the repo-root .env into os.environ on import. Existing os.environ values
take precedence (use `$env:VAR=...` in PowerShell or `export VAR=...` in bash
to override the .env file).

Your business details (name, region, sender, booking link) also come from .env,
so no script needs editing to make it yours. See the "Your business" block in
.env.example.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_LOADED = False


def load_env(path: Path | None = None) -> None:
    global _LOADED
    if _LOADED:
        return
    if path is None:
        path = ROOT / ".env"
    if not path.exists():
        _LOADED = True
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        os.environ.setdefault(key, value)
    _LOADED = True


def env(name: str, default: str = "") -> str:
    # Blank entries in .env (KEY=) fall back to the default too.
    return os.environ.get(name) or default


def require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(
            f"[config] Missing required env var: {name}. "
            f"Set it in .env (copy from .env.example) or export it in your shell."
        )
    return value


load_env()

# --- Your business (all optional; set in .env) ------------------------------
BUSINESS_NAME = env("BUSINESS_NAME", "Your Company")
BUSINESS_REGION = env("BUSINESS_REGION", "your region")
SENDER_NAME = env("SENDER_NAME", "Your Name")
SENDER_EMAIL = env("SENDER_EMAIL", "")
CALENDLY_URL = env("CALENDLY_URL", "https://calendly.com/your-handle")
DEFAULT_CITY = env("DEFAULT_CITY", "")
DEFAULT_STATE = env("DEFAULT_STATE", "CA")

# TLS certificate checks. Leave on. Set VERIFY_SSL=0 only if antivirus HTTPS
# scanning breaks requests with certificate errors.
VERIFY_SSL = env("VERIFY_SSL", "1") != "0"
if not VERIFY_SSL:
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Generated reports, CSVs and drafts land here (gitignored).
OUTPUT_DIR = Path(env("OUTPUT_DIR", str(ROOT / "output"))).expanduser()
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
