"""
render_config.py — Render mcpo/config.json (template with ${VAR} placeholders)
into config.rendered.json using values from the repo-root .env.

Run from mcpo/:  python render_config.py
Or called automatically by start.bat / start.sh before launching mcpo.

Exits non-zero if any required ${VAR} is missing from .env so we never silently
ship an empty API key to a child process. Delete servers you don't use from
config.json rather than leaving their keys blank.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

# Load .env via shared loader.
sys.path.insert(0, str(ROOT / "scripts"))
import _env  # noqa: E402,F401 — populates os.environ

EXAMPLE = HERE / "config.example.json"
TEMPLATE = HERE / "config.json"
RENDERED = HERE / "config.rendered.json"
FS_ROOTS = "${MCP_FS_ROOTS}"

VAR_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")


def substitute(value: str) -> str:
    missing: list[str] = []

    def repl(m: re.Match[str]) -> str:
        name = m.group(1)
        val = os.environ.get(name, "")
        if not val:
            missing.append(name)
        return val

    out = VAR_RE.sub(repl, value)
    if missing:
        raise SystemExit(
            f"[render_config] Missing env vars: {', '.join(sorted(set(missing)))}.\n"
            f"  Set them in {ROOT / '.env'} (copy from .env.example)."
        )
    return out


def walk(obj):
    if isinstance(obj, dict):
        return {k: walk(v) for k, v in obj.items()}
    if isinstance(obj, list):
        out = []
        for v in obj:
            # "${MCP_FS_ROOTS}" expands to one argument per comma-separated folder.
            if v == FS_ROOTS:
                out += [str(Path(p.strip()).expanduser()) for p in substitute(v).split(",") if p.strip()]
            else:
                out.append(walk(v))
        return out
    if isinstance(obj, str):
        return substitute(obj)
    return obj


def windows_wrap(servers: dict) -> None:
    """npx is a .cmd shim on Windows, so it has to run through cmd /c."""
    if os.name != "nt":
        return
    for srv in servers.values():
        if srv.get("command") == "npx":
            srv["command"] = "cmd"
            srv["args"] = ["/c", "npx", *srv.get("args", [])]


def main() -> None:
    if not TEMPLATE.exists():
        if not EXAMPLE.exists():
            raise SystemExit(f"[render_config] Template not found: {TEMPLATE}")
        shutil.copyfile(EXAMPLE, TEMPLATE)
        print(f"[render_config] Created {TEMPLATE} from {EXAMPLE.name}")
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    rendered = walk(template)
    windows_wrap(rendered.get("mcpServers", {}))
    # Drop the _comment from the rendered output (mcpo ignores unknown keys but cleaner).
    rendered.pop("_comment", None)
    RENDERED.write_text(json.dumps(rendered, indent=2), encoding="utf-8")
    print(f"[render_config] Wrote {RENDERED} (do not commit)")


if __name__ == "__main__":
    main()
