"""
One-shot Open WebUI setup script.
Run after the stack is up and you have created your Open WebUI admin account
(first visit to http://localhost:3000): python setup_owui.py

Creates: a knowledge base from every file in knowledge/, model presets, and
imports every n8n workflow in n8n/. Sign-in uses OWUI_EMAIL / OWUI_PASSWORD
from .env.
"""
import os, sys, json, time, glob, requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))
from _env import require, env, BUSINESS_NAME, BUSINESS_REGION, ROOT  # noqa: E402

EMAIL = require("OWUI_EMAIL")
PASSWORD = require("OWUI_PASSWORD")
BASE = "http://localhost:3000"
HEADERS = {}

KNOWLEDGE_DIR = ROOT / "knowledge"
N8N_DIR = ROOT / "n8n"
KB_NAME = "Business Knowledge"


def check_auth():
    global HEADERS
    r = requests.post(
        f"{BASE}/api/v1/auths/signin",
        json={"email": EMAIL, "password": PASSWORD},
        timeout=10,
    )
    if not r.ok or not r.json().get("token"):
        print(f"ERROR: Sign-in failed ({r.status_code}): {r.text[:100]}")
        sys.exit(1)
    token = r.json()["token"]
    HEADERS = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    print(f"✓ Authenticated as {r.json().get('email')}")


def create_knowledge_base():
    print("\n--- Knowledge Base ---")
    # Check existing
    r = requests.get(f"{BASE}/api/v1/knowledge/", headers=HEADERS, timeout=10)
    items = r.json().get("items", []) if r.ok else []
    existing = {k.get("name"): k.get("id") for k in items}

    if KB_NAME in existing:
        kb_id = existing[KB_NAME]
        print(f"✓ Knowledge base already exists: {kb_id}")
    else:
        r = requests.post(
            f"{BASE}/api/v1/knowledge/create",
            headers=HEADERS,
            json={
                "name": KB_NAME,
                "description": f"Reference documents for {BUSINESS_NAME} (from the knowledge/ folder)",
                "data": {},
            },
            timeout=10,
        )
        if not r.ok:
            print(f"ERROR creating knowledge base: {r.status_code} {r.text[:100]}")
            return None
        kb_id = r.json().get("id")
        print(f"✓ Created knowledge base: {kb_id}")

    # Upload documents
    mime_for = {".md": "text/plain", ".txt": "text/plain", ".pdf": "application/pdf",
                ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
    docs = [
        (str(p), mime_for[p.suffix.lower()])
        for p in sorted(KNOWLEDGE_DIR.iterdir())
        if p.suffix.lower() in mime_for and p.name.lower() != "readme.md"
    ] if KNOWLEDGE_DIR.exists() else []
    if not docs:
        print(f"  No documents in {KNOWLEDGE_DIR} yet. Add .md/.txt/.pdf/.docx files and re-run.")

    for doc_path, mime in docs:
        if not os.path.exists(doc_path):
            print(f"  SKIP (not found): {doc_path}")
            continue
        fname = os.path.basename(doc_path)
        print(f"  Uploading {fname}...")
        with open(doc_path, "rb") as f:
            upload_r = requests.post(
                f"{BASE}/api/v1/files/",
                headers={"Authorization": HEADERS["Authorization"]},
                files={"file": (fname, f, mime)},
                timeout=60,
            )
        if not upload_r.ok:
            print(f"  ERROR uploading {fname}: {upload_r.status_code} {upload_r.text[:100]}")
            continue
        file_id = upload_r.json().get("id")
        if not file_id:
            print(f"  ERROR: no file id in response")
            continue

        # Add to knowledge base (slow — embedding generation takes 60-120s)
        add_r = requests.post(
            f"{BASE}/api/v1/knowledge/{kb_id}/file/add",
            headers=HEADERS,
            json={"file_id": file_id},
            timeout=180,
        )
        if add_r.ok:
            print(f"  ✓ {fname} added to knowledge base")
        else:
            print(f"  ERROR adding {fname} to KB: {add_r.status_code} {add_r.text[:100]}")

    return kb_id


def create_model_presets(kb_id):
    print("\n--- Model Presets ---")

    presets = [
        {
            "id": "cmmc-assistant",
            "name": "CMMC Compliance Assistant",
            "base_model_id": "qwen2.5:14b",
            "params": {
                "system": (
                    f"You are a CMMC compliance expert for {BUSINESS_NAME}, a CMMC consulting firm in {BUSINESS_REGION}. "
                    "You help DOD subcontractors understand and achieve CMMC Level 1 and Level 2 compliance.\n\n"
                    "Services we offer (edit to match yours):\n"
                    "- CMMC gap assessments and remediation\n"
                    "- Shared Responsibility Matrix (SRM) preparation\n"
                    "- vCISO retainer\n\n"
                    "Always frame answers in business terms (cost, timeline, risk), not NIST jargon. "
                    f"Target clients are small-to-mid DOD subcontractors in {BUSINESS_REGION}."
                ),
                "temperature": 0.3,
            },
            "meta": {
                "description": "CMMC compliance expert + full knowledge base + all tools",
                "knowledge": [kb_id] if kb_id else [],
            },
        },
        {
            "id": "lead-gen",
            "name": "Lead Gen Assistant",
            "base_model_id": "qwen2.5:14b",
            "params": {
                "system": (
                    f"You are a B2B lead generation specialist for {BUSINESS_NAME} in {BUSINESS_REGION}. "
                    "Your job is to find, qualify, and help engage DOD subcontractor prospects for CMMC compliance services.\n\n"
                    "Use the SAM.gov and HubSpot tools to:\n"
                    "1. Search SAM.gov for active registered contractors by NAICS code and city\n"
                    "2. Check HubSpot to avoid duplicates before adding new contacts\n"
                    "3. Create HubSpot contacts for qualified prospects\n"
                    "4. Draft outreach emails tailored to the prospect's CMMC deadlines\n\n"
                    "Best NAICS codes for CMMC prospects: 541512 (IT), 541330 (Engineering), 336611 (Shipbuilding), 236220 (Construction)."
                ),
                "temperature": 0.4,
            },
            "meta": {"description": "SAM.gov prospect finder + HubSpot CRM integration"},
        },
        {
            "id": "quick-research",
            "name": "Quick Research",
            "base_model_id": "llama3.2:3b",
            "params": {
                "system": (
                    "You are a fast research assistant. Use web search (Tavily) and Firecrawl to quickly "
                    "answer questions and summarize information. Be concise and direct."
                ),
                "temperature": 0.5,
            },
            "meta": {"description": "Fast 3B model + web search for quick lookups"},
        },
        {
            "id": "analyst",
            "name": "Business Analyst",
            "base_model_id": "phi4",
            "params": {
                "system": (
                    f"You are a sharp business analyst for {BUSINESS_NAME}. You excel at reasoning through "
                    "complex problems, drafting proposals, and analyzing business data. "
                    "You have access to Google Sheets, PostgreSQL, and file system tools. "
                    "Always structure your analysis clearly with concrete recommendations."
                ),
                "temperature": 0.2,
            },
            "meta": {"description": "phi4 reasoning model for analysis, proposals, and data work"},
        },
    ]

    r = requests.get(f"{BASE}/api/v1/models/list", headers=HEADERS, timeout=10)
    existing_ids = {m.get("id") for m in r.json().get("items", [])} if r.ok else set()

    for preset in presets:
        if preset["id"] in existing_ids:
            print(f"  ✓ Preset already exists: {preset['name']}")
            continue

        create_r = requests.post(
            f"{BASE}/api/v1/models/create",
            headers=HEADERS,
            json=preset,
            timeout=10,
        )
        if create_r.ok:
            print(f"  ✓ Created: {preset['name']}")
        else:
            print(f"  ERROR {preset['name']}: {create_r.status_code} {create_r.text[:100]}")


def import_n8n_workflows():
    print("\n--- n8n Workflows ---")
    N8N_BASE = "http://localhost:5678/api/v1"
    api_key = env("N8N_API_KEY")
    if not api_key:
        print("  SKIP: set N8N_API_KEY in .env (n8n -> Settings -> API) to import workflows")
        return
    n8n_headers = {"X-N8N-API-KEY": api_key, "Content-Type": "application/json"}

    for fpath in sorted(glob.glob(str(N8N_DIR / "*.json"))):
        fname = os.path.basename(fpath)

        with open(fpath, encoding="utf-8") as f:
            workflow = json.load(f)
        # The public API only accepts these keys on create.
        workflow = {k: workflow[k] for k in ("name", "nodes", "connections", "settings") if k in workflow}
        workflow.setdefault("settings", {})

        # Check if already imported
        r = requests.get(f"{N8N_BASE}/workflows", headers=n8n_headers, timeout=10)
        if r.ok:
            names = [w.get("name") for w in r.json().get("data", [])]
            if workflow.get("name") in names:
                print(f"  ✓ Already imported: {workflow.get('name')}")
                continue

        # Import
        create_r = requests.post(
            f"{N8N_BASE}/workflows",
            headers=n8n_headers,
            json=workflow,
            timeout=10,
        )
        if create_r.ok:
            print(f"  ✓ Imported: {workflow.get('name')}")
        else:
            print(f"  ERROR importing {fname}: {create_r.status_code} {create_r.text[:150]}")


def main():
    print("=" * 55)
    print(f"  {BUSINESS_NAME} — Open WebUI Setup")
    print("=" * 55)

    check_auth()
    kb_id = create_knowledge_base()
    create_model_presets(kb_id)
    import_n8n_workflows()

    print("\n✓ Setup complete.")
    print("  Open http://localhost:3000 and select a model preset to get started.")


if __name__ == "__main__":
    main()
