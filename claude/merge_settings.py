"""
merge_settings.py — add this repo's Claude Code settings to ~/.claude/settings.json.

Your existing settings always win: keys you already have are left alone, and a
timestamped backup is written before anything changes. GSD adds its own hooks
and status line when its installer runs, so they aren't in the template.

  python claude/merge_settings.py               # merge settings.template.json
  python claude/merge_settings.py --allow-shell # also auto-approve Bash/PowerShell
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "settings.template.json"
TARGET = Path.home() / ".claude" / "settings.json"


def merge(dst: dict, src: dict) -> None:
    for key, value in src.items():
        if isinstance(value, dict) and isinstance(dst.get(key), dict):
            merge(dst[key], value)
        elif key not in dst:
            dst[key] = value


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--allow-shell", action="store_true",
                   help="let Claude run shell commands without asking each time")
    args = p.parse_args()

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    current = {}
    if TARGET.exists():
        current = json.loads(TARGET.read_text(encoding="utf-8") or "{}")
        backup = TARGET.with_name(f"settings.json.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copyfile(TARGET, backup)
        print(f"[claude] Backed up settings to {backup.name}")

    merge(current, json.loads(TEMPLATE.read_text(encoding="utf-8")))

    if args.allow_shell:
        allow = current.setdefault("permissions", {}).setdefault("allow", [])
        for tool in ("Bash", "PowerShell"):
            if tool not in allow:
                allow.append(tool)

    TARGET.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    print(f"[claude] Settings merged into {TARGET}")


if __name__ == "__main__":
    main()
