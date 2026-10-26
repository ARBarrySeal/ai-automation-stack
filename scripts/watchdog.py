"""
watchdog.py — Monitor AI stack services and restart any that are down.
Run every 5 minutes via Task Scheduler (Windows) or cron (Mac/Linux).
"""
import io
import os
import subprocess
import sys
import time

import requests

import _env  # noqa: F401 — loads .env into os.environ on import

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

CHECKS = [
    {
        "name": "claude-relay",
        "url": "http://localhost:7777/health",
        "restart_cmd": [sys.executable, "-m", "uvicorn", "claude_relay:app", "--host", "0.0.0.0", "--port", "7777", "--log-level", "warning"],
        "cwd": SCRIPTS_DIR,
        "type": "process",
    },
    {
        "name": "n8n",
        "url": "http://localhost:5678",
        "restart_cmd": ["docker", "start", "n8n"],
        "type": "docker",
    },
    {
        "name": "ollama",
        "url": "http://localhost:11434/api/tags",
        "restart_cmd": ["docker", "start", "ollama"],
        "type": "docker",
    },
    {
        "name": "open-webui",
        "url": "http://localhost:3000",
        "restart_cmd": ["docker", "start", "open-webui"],
        "type": "docker",
    },
    {
        "name": "pipeline-mcp",
        "url": "http://localhost:7788/mcp",
        "restart_cmd": [sys.executable, "pipeline_mcp_server.py"],
        "cwd": SCRIPTS_DIR,
        "type": "process",
    },
]


def is_up(url: str) -> bool:
    try:
        r = requests.get(url, timeout=5)
        return r.status_code < 500
    except Exception:
        return False


def restart_service(check: dict):
    name = check["name"]
    if check["type"] == "docker":
        result = subprocess.run(check["restart_cmd"], capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            print(f"  [{name}] restarted via docker start")
        else:
            print(f"  [{name}] docker restart failed: {result.stderr[:100]}")
    elif check["type"] == "process":
        # Inherit current process env (which already has .env loaded via _env)
        subprocess.Popen(
            check["restart_cmd"],
            cwd=check["cwd"],
            env=os.environ.copy(),
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        print(f"  [{name}] process restarted")


def main():
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    any_down = False

    for check in CHECKS:
        if is_up(check["url"]):
            continue
        any_down = True
        print(f"[{ts}] {check['name']} is DOWN — restarting...")
        restart_service(check)
        time.sleep(5)
        if is_up(check["url"]):
            print(f"  [{check['name']}] back UP")
        else:
            print(f"  [{check['name']}] still down after restart")

    if not any_down:
        print(f"[{ts}] All services OK")


if __name__ == "__main__":
    main()
