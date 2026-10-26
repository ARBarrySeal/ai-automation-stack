"""
pipeline_mcp_server.py — MCP server exposing desktop AI stack as tools.
Runs on port 7788 (streamable HTTP), bound to 127.0.0.1.

Tools available in Claude mobile app:
  ask_ollama        — chat directly with local Ollama (free, no API tokens)
  run_leads_pipeline — trigger CMMC lead generation on desktop
  service_status    — check if relay/n8n/ollama are up
  get_hubspot_leads — list recent CRM leads
  generate_followup — write a follow-up email for a specific company

Start:
  python pipeline_mcp_server.py

Connect Claude Code on the same machine:
  claude mcp add --transport http pipeline-desktop http://localhost:7788/mcp

WARNING: this server has no authentication and can write to your CRM and run
scripts. Do not expose it with a public tunnel (cloudflared/ngrok) unless you
put an authenticating proxy in front of it.
"""
import os
import subprocess
import sys
import time

import httpx
import requests
from fastmcp import FastMCP

from _env import DEFAULT_CITY, DEFAULT_STATE  # also loads .env

RELAY_URL = "http://localhost:7777/v1/chat/completions"
OLLAMA_DEFAULT = "qwen2.5:14b"
HUBSPOT_BASE = "https://api.hubapi.com"
HUBSPOT_TOKEN = os.environ.get("HUBSPOT_TOKEN") or os.environ.get("HUBSPOT_ACCESS_TOKEN") or ""
if not HUBSPOT_TOKEN:
    raise SystemExit("[config] HUBSPOT_TOKEN not set — add it to .env")
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))

mcp = FastMCP("Desktop AI Stack")


@mcp.tool()
def ask_ollama(prompt: str, model: str = OLLAMA_DEFAULT) -> str:
    """
    Send a question or task to local Ollama on your desktop. Free — uses no Claude API tokens.
    Supports: qwen2.5:14b (default), qwen2.5-coder:7b, llama3.2:3b, phi4:latest, gemma3:12b, deepseek-r1:7b
    """
    try:
        r = requests.post(
            RELAY_URL,
            json={"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 1024},
            timeout=120,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Error calling Ollama: {e}"


@mcp.tool()
def run_leads_pipeline(
    naics: str = "541512",
    count: int = 3,
    city: str = DEFAULT_CITY,
    state: str = DEFAULT_STATE,
    nationwide: bool = False,
) -> str:
    """
    Run the CMMC lead generation pipeline on the desktop. Finds DoD contractors and writes outreach emails.
    naics options: 541512 (IT/cyber), 541330 (engineering), 336411 (aircraft), 541715 (R&D), 332994 (ordnance)
    Returns a summary of companies found and whether emails were generated.
    """
    script = os.path.join(SCRIPTS_DIR, "leads_pipeline.py")
    cmd = [sys.executable, script, "--naics", naics, "--count", str(count)]
    if nationwide:
        cmd.append("--nationwide")
    else:
        cmd += ["--city", city, "--state", state]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180, cwd=SCRIPTS_DIR)
        output = result.stdout + result.stderr
        # Return last 2000 chars to keep response manageable
        return output[-2000:] if len(output) > 2000 else output
    except subprocess.TimeoutExpired:
        return "Pipeline timed out after 3 minutes."
    except Exception as e:
        return f"Error running pipeline: {e}"


@mcp.tool()
def service_status() -> str:
    """Check whether the AI stack services (relay, n8n, Ollama, Open WebUI) are running on the desktop."""
    checks = [
        ("claude-relay", "http://localhost:7777/health"),
        ("n8n", "http://localhost:5678"),
        ("ollama", "http://localhost:11434/api/tags"),
        ("open-webui", "http://localhost:3000"),
    ]
    lines = []
    for name, url in checks:
        try:
            r = httpx.get(url, timeout=4)
            status = "UP" if r.status_code < 500 else f"ERROR {r.status_code}"
        except Exception:
            status = "DOWN"
        lines.append(f"  {name:<15} {status}")
    return "Desktop AI Stack Status:\n" + "\n".join(lines)


@mcp.tool()
def get_hubspot_leads(limit: int = 10, status: str = "NEW") -> str:
    """
    List recent leads from HubSpot CRM.
    status options: NEW, OPEN, IN_PROGRESS, CONNECTED
    Returns company names, location, award amount, and last activity date.
    """
    try:
        r = requests.post(
            f"{HUBSPOT_BASE}/crm/v3/objects/companies/search",
            headers={"Authorization": f"Bearer {HUBSPOT_TOKEN}", "Content-Type": "application/json"},
            json={
                "filterGroups": [{"filters": [
                    {"propertyName": "hs_lead_status", "operator": "EQ", "value": status}
                ]}],
                "properties": ["name", "city", "state", "description", "notes_last_updated", "hs_lead_status"],
                "limit": limit,
                "sorts": [{"propertyName": "createdate", "direction": "DESCENDING"}],
            },
            timeout=10,
        )
        r.raise_for_status()
        results = r.json().get("results", [])
        if not results:
            return f"No leads with status '{status}' in HubSpot."
        lines = [f"HubSpot leads (status={status}, {len(results)} found):\n"]
        for co in results:
            p = co["properties"]
            last = p.get("notes_last_updated", "")
            last_str = last[:10] if last else "never"
            lines.append(f"  {p.get('name','?'):<40} {p.get('city','?')}, {p.get('state','?')}  last activity: {last_str}")
        return "\n".join(lines)
    except Exception as e:
        return f"HubSpot error: {e}"


@mcp.tool()
def generate_followup(company_name: str, context: str = "") -> str:
    """
    Write a follow-up CMMC outreach email for a specific company that hasn't responded.
    company_name: exact company name as it appears in HubSpot
    context: optional extra context (e.g. 'they make aircraft parts')
    Returns a ready-to-send follow-up email.
    """
    prompt = (
        f"Write a brief, friendly follow-up email (under 120 words) to {company_name}, "
        f"a defense contractor we emailed 7+ days ago about CMMC compliance with no response. "
        f"Reference that CMMC Level 2 is required for continued DoD contract eligibility. "
        f"Sound human, not spammy. Output ONLY Subject line + email body. "
        + (f"Context: {context}" if context else "")
    )
    try:
        r = requests.post(
            RELAY_URL,
            json={"model": OLLAMA_DEFAULT, "messages": [{"role": "user", "content": prompt}], "max_tokens": 400},
            timeout=120,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Error generating follow-up: {e}"


if __name__ == "__main__":
    print("Starting Desktop AI Stack MCP server on http://127.0.0.1:7788/mcp ...")
    mcp.run(transport="streamable-http", host="127.0.0.1", port=7788)
