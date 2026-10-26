"""
smart — direct-to-Claude CLI for your business.

Usage:
  smart "draft a CMMC proposal for Acme Corp"
  smart "analyze this gap assessment" --file report.pdf
  smart "write outreach to Example Defense" --role leads
  smart "what are the top gaps?" --paste --role cmmc
  smart "outreach to Example Defense" --role leads --webhook
"""
import argparse
import os
import sys
import io
import requests
from _env import env, BUSINESS_NAME, BUSINESS_REGION

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

RELAY_URL = "http://localhost:7777/v1/chat/completions"
N8N_BASE = "http://localhost:5678/webhook"
WEBHOOK_SECRET = env("N8N_WEBHOOK_SECRET", "")
CLAUDE_MODEL = env("CLAUDE_MODEL", "claude-sonnet-5-5")
FIRM = f"{BUSINESS_NAME}, a CMMC consulting firm in {BUSINESS_REGION}"

SYSTEM_PROMPTS = {
    "general": (
        f"You are a smart assistant for {FIRM}. "
        "Answer clearly and concisely. Be direct and actionable."
    ),
    "leads": (
        f"You are a B2B sales email writer for {FIRM}. "
        "Write concise, professional cold outreach emails to defense contractors who need CMMC Level 2 compliance help. "
        "Keep emails under 200 words. Lead with a specific pain point. "
        "End with a soft CTA for a free gap assessment. Sound human, not like marketing copy."
    ),
    "proposal": (
        f"You are a proposal writer for {BUSINESS_NAME}. Write professional CMMC compliance consulting proposals. "
        "Structure: Executive Summary, Scope of Work, Our Approach, Timeline, Investment. "
        "Be specific about deliverables. Tone: expert, confident, partner-oriented."
    ),
    "analyst": (
        f"You are a business data analyst for {BUSINESS_NAME}. "
        "Strip all filler. Keep only decision-relevant data. Lead with the recommendation. "
        "Use bullet points. Be concise."
    ),
    "cmmc": (
        "You are a CMMC Level 2 compliance expert. Reference specific NIST SP 800-171 Rev 2 control IDs "
        "(e.g., IA.3.083, SC.3.177) where relevant. Use plain business language. "
        "Map findings to cost, risk, and timeline. Target $5M-$50M DOD subcontractors."
    ),
}

WEBHOOK_ROUTES = {
    "leads": ("leads", lambda task, ctx: {"company": task, "notes": ctx}),
    "proposal": ("proposal", lambda task, ctx: {"client": task, "notes": ctx}),
    "cmmc": ("analyze", lambda task, ctx: {"question": task, "text": ctx}),
}


def get_clipboard() -> str:
    import subprocess
    if sys.platform == "win32":
        cmd = ["powershell", "-command", "Get-Clipboard"]
    elif sys.platform == "darwin":
        cmd = ["pbpaste"]
    else:
        cmd = ["xclip", "-selection", "clipboard", "-o"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout.strip()


def read_file(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(path)
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except ImportError:
            raise RuntimeError("pip install pypdf")
    elif ext == ".docx":
        try:
            import docx
            return "\n".join(p.text for p in docx.Document(path).paragraphs)
        except ImportError:
            raise RuntimeError("pip install python-docx")
    else:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()


def call_claude(system: str, user: str) -> str:
    r = requests.post(
        RELAY_URL,
        json={
            "model": CLAUDE_MODEL,
            "max_tokens": 2000,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        timeout=120,
    )
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"]


def call_webhook(route: str, payload: dict) -> str:
    headers = {"X-Webhook-Token": WEBHOOK_SECRET} if WEBHOOK_SECRET else {}
    r = requests.post(f"{N8N_BASE}/{route}", json=payload, headers=headers, timeout=120)
    r.raise_for_status()
    return r.text


def main():
    parser = argparse.ArgumentParser(
        description="smart: direct-to-Claude CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("task", help="What you want done")
    parser.add_argument("--file", metavar="PATH", help="File to include as context")
    parser.add_argument(
        "--role",
        default="general",
        choices=list(SYSTEM_PROMPTS.keys()),
        help="Role/persona (default: general)",
    )
    parser.add_argument("--paste", action="store_true", help="Include clipboard as context")
    parser.add_argument("--webhook", action="store_true", help="Route through n8n webhook instead")
    args = parser.parse_args()

    context = ""
    if args.file:
        if not os.path.exists(args.file):
            print(f"ERROR: File not found: {args.file}", file=sys.stderr)
            sys.exit(1)
        print(f"  Reading {args.file}...")
        context = read_file(args.file)
        print(f"  {len(context):,} chars loaded\n")

    if args.paste:
        clip = get_clipboard()
        if clip:
            context += ("\n\n" if context else "") + clip
            print(f"  Clipboard: {len(clip):,} chars added\n")

    if args.webhook and args.role in WEBHOOK_ROUTES:
        route, build_payload = WEBHOOK_ROUTES[args.role]
        payload = build_payload(args.task, context)
        print(f"[n8n /{route}] Generating...\n")
        try:
            result = call_webhook(route, payload)
            print(result)
        except requests.exceptions.ConnectionError:
            print("ERROR: n8n not running (http://localhost:5678)", file=sys.stderr)
            sys.exit(1)
    else:
        system = SYSTEM_PROMPTS[args.role]
        user = args.task
        if context:
            user += f"\n\nContext:\n{context[:15000]}"
        print(f"[Claude / {args.role}] Generating...\n")
        try:
            result = call_claude(system, user)
            print(result)
        except requests.exceptions.ConnectionError:
            print("ERROR: Claude relay not running (http://localhost:7777)", file=sys.stderr)
            sys.exit(1)
        except requests.exceptions.HTTPError as e:
            print(f"ERROR: {e.response.status_code}: {e.response.text[:200]}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
