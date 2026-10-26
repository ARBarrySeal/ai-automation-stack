"""
setup_env.py — create .env from .env.example and fill in the generated values.

Called by install.ps1 / install.sh. Safe to re-run: an existing .env is kept and
only values still set to "auto" are generated. With --interactive it also asks
for your business details (press Enter to keep the current value).

  python scripts/setup_env.py               # generate secrets only
  python scripts/setup_env.py --interactive # also ask for name, region, etc.
"""
from __future__ import annotations

import argparse
import re
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / ".env.example"
ENV = ROOT / ".env"

PROMPTS = [
    ("BUSINESS_NAME", "Business name"),
    ("BUSINESS_REGION", "City or region you serve"),
    ("SENDER_NAME", "Your name (used to sign emails)"),
    ("SENDER_EMAIL", "Your email"),
    ("CALENDLY_URL", "Booking link"),
    ("DEFAULT_STATE", "Default US state for lead searches (e.g. CA)"),
    ("OWUI_EMAIL", "Open WebUI admin email"),
    ("ANTHROPIC_API_KEY", "Anthropic API key (optional, Enter to skip)"),
]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--interactive", action="store_true")
    args = p.parse_args()

    if not ENV.exists():
        ENV.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"[setup_env] Created {ENV.name} from {EXAMPLE.name}")
    text = ENV.read_text(encoding="utf-8")

    def get(key: str) -> str:
        m = re.search(rf"^{key}=(.*)$", text, re.M)
        return m.group(1).strip() if m else ""

    def put(key: str, value: str) -> None:
        nonlocal text
        if re.search(rf"^{key}=", text, re.M):
            text = re.sub(rf"^{key}=.*$", lambda _: f"{key}={value}", text, flags=re.M)
        else:
            text += f"\n{key}={value}\n"

    generated = 0
    for m in re.finditer(r"^([A-Z0-9_]+)=auto\s*$", text, re.M):
        put(m.group(1), secrets.token_urlsafe(32))
        generated += 1

    # Open WebUI admin password: generate one if blank so setup_owui.py can log in.
    if not get("OWUI_PASSWORD"):
        put("OWUI_PASSWORD", secrets.token_urlsafe(18))
        generated += 1

    if args.interactive:
        print("\nYour details (Enter keeps the value in brackets):")
        for key, label in PROMPTS:
            current = get(key)
            shown = "set" if key.endswith("KEY") and current else current
            answer = input(f"  {label} [{shown}]: ").strip()
            if answer:
                put(key, answer)

    ENV.write_text(text, encoding="utf-8")
    print(f"[setup_env] {generated} secret(s) generated. Edit .env any time to add API keys.")


if __name__ == "__main__":
    main()
