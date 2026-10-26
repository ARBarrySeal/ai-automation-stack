"""
processor.py — Ollama-based context compressor.
Reads files, calls Ollama with role-specific compression prompt,
returns a structured brief ready for claude_relay.
"""
import os
import requests

from _env import BUSINESS_NAME, BUSINESS_REGION

OLLAMA_URL = "http://localhost:11434/api/generate"

SYSTEM_PROMPTS = {
    "general": (
        "You are a context compressor. Analyze the input and produce a structured brief "
        "that gives Claude the minimum context needed to deliver a high-quality final answer.\n\n"
        "Output EXACTLY this format — no other text before or after:\n"
        "TASK: [one sentence describing what Claude must do]\n"
        "KEY FACTS:\n- [fact]\n- [fact]\n"
        "DRAFT: [your best attempt at the answer]\n"
        "CONSTRAINTS: [tone, format, length, any hard requirements]"
    ),
    "leads": (
        f"You are a B2B lead qualification engine for a CMMC consulting firm in {BUSINESS_REGION}.\n\n"
        "Output EXACTLY this format:\n"
        "TASK: write outreach email to [company name]\n"
        "KEY FACTS:\n"
        "- Company: [name]\n"
        "- NAICS: [code and description]\n"
        "- Why CMMC matters to them: [one sentence]\n"
        "- Deadline urgency: CMMC Phase 2 mandatory Nov 10 2026\n"
        "DRAFT:\n"
        "Subject: [subject line]\n\n"
        "[3-paragraph email body — opening hook, pain point, clear CTA]\n"
        "CONSTRAINTS: urgent but professional, mention Nov 2026 deadline, offer free gap "
        "assessment call, under 200 words"
    ),
    "proposal": (
        f"You are a CMMC proposal drafter for {BUSINESS_NAME} ({BUSINESS_REGION}).\n\n"
        "Output EXACTLY this format:\n"
        "TASK: finalize proposal for [client name]\n"
        "KEY FACTS:\n"
        "- Client: [name and context]\n"
        "- Scope: [what they need]\n"
        "- Pricing tier: [estimate based on company size]\n"
        "DRAFT:\n"
        "# CMMC Compliance Proposal — [Client]\n"
        "## Executive Summary\n[2 sentences]\n"
        "## Scope of Work\n[bullet list]\n"
        "## Timeline\n[phases with weeks]\n"
        "## Investment\n[price range and what's included]\n"
        "CONSTRAINTS: professional tone, specific dollar amounts, no NIST jargon, emphasize "
        "ROI and contract protection"
    ),
    "analyst": (
        "You are a business data extractor. Strip all filler. Keep only decision-relevant data.\n\n"
        "Output EXACTLY this format:\n"
        "TASK: [what analysis Claude should complete]\n"
        "KEY FACTS:\n- [number/date/name only]\n- [number/date/name only]\n"
        "DRAFT:\n[structured analysis]\n"
        "RECOMMENDATION: [one clear action item]\n"
        "CONSTRAINTS: concise, bullet-heavy, lead with the recommendation"
    ),
    "cmmc": (
        "You are a CMMC Level 2 compliance expert. Extract compliance-relevant details "
        "and structure them for a final expert review.\n\n"
        "Output EXACTLY this format:\n"
        "TASK: [compliance question or action Claude must address]\n"
        "KEY FACTS:\n- [control/domain/gap]\n- [control/domain/gap]\n"
        "DRAFT: [compliance analysis or guidance]\n"
        "CONSTRAINTS: use plain business language, map to cost/risk/timeline, "
        "target $5M-$50M DOD subcontractors"
    ),
}


def read_file(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(path)
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except ImportError:
            raise RuntimeError("pypdf not installed — run: pip install pypdf")
    elif ext == ".docx":
        try:
            import docx
            doc = docx.Document(path)
            return "\n".join(p.text for p in doc.paragraphs)
        except ImportError:
            raise RuntimeError("python-docx not installed — run: pip install python-docx")
    else:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()


def compress(task: str, context: str = "", role: str = "general", model: str = "deepseek-r1:7b") -> str:
    system = SYSTEM_PROMPTS.get(role, SYSTEM_PROMPTS["general"])

    user_content = f"Task: {task}"
    if context.strip():
        if len(context) > 12000:
            context = context[:12000] + "\n\n[...truncated for length...]"
        user_content += f"\n\nContext:\n{context}"

    payload = {
        "model": model,
        "system": system,
        "prompt": user_content,
        "stream": False,
        "options": {
            "num_ctx": 8192,
            "temperature": 0.2,
        },
    }

    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=300)
        response.raise_for_status()
        return response.json()["response"].strip()
    except requests.exceptions.ConnectionError:
        raise RuntimeError("Ollama not running — start docker compose first")
    except requests.exceptions.Timeout:
        raise RuntimeError("Ollama timed out after 300s (model may still be loading)")
    except KeyError:
        raise RuntimeError(f"Unexpected Ollama response: {response.text[:200]}")
