"""
setup_n8n_workflows.py — creates 3 Ollama->Claude workflows in n8n.
Uses Code nodes (JS) with string concatenation (no template literal issues).
"""
import sys, time, requests, json
from _env import require

N8N_BASE = "http://localhost:5678/api/v1"
N8N_API_KEY = require("N8N_API_KEY")
HEADERS = {"X-N8N-API-KEY": N8N_API_KEY, "Content-Type": "application/json"}
OLLAMA_URL = "http://ollama:11434/api/generate"
RELAY_URL = "http://host.docker.internal:7777/relay"
MODEL = "deepseek-r1:7b"


def wait_for_n8n():
    print("Waiting for n8n...")
    for _ in range(30):
        try:
            r = requests.get(f"{N8N_BASE}/workflows", headers=HEADERS, timeout=5)
            if r.ok:
                print("n8n is up.")
                return
        except Exception:
            pass
        time.sleep(2)
    sys.exit("n8n not responding")


def workflow_exists(name):
    r = requests.get(f"{N8N_BASE}/workflows", headers=HEADERS, timeout=10)
    return r.ok and any(w["name"] == name for w in r.json().get("data", []))


def create_workflow(workflow):
    name = workflow["name"]
    if workflow_exists(name):
        print(f"  Already exists: {name}")
        return
    r = requests.post(f"{N8N_BASE}/workflows", headers=HEADERS, json=workflow, timeout=15)
    if r.ok:
        wf_id = r.json().get("id")
        requests.post(f"{N8N_BASE}/workflows/{wf_id}/activate", headers=HEADERS, timeout=10)
        print(f"  Created + activated: {name} (id={wf_id})")
    else:
        print(f"  ERROR {name}: {r.status_code} {r.text[:200]}")


def build_workflow(name, path, system_prompt, prompt_js_parts, task_js, respond_expr):
    """
    prompt_js_parts: list of JS expressions that get concatenated to form the prompt string
    task_js: JS expression for the relay task string
    """
    # Escape system prompt for embedding in a JS string literal
    sys_escaped = (system_prompt
                   .replace("\\", "\\\\")
                   .replace('"', '\\"')
                   .replace("\n", "\\n"))

    prompt_concat = ' + "\\n" + '.join(prompt_js_parts)

    ollama_js = f"""const item = $input.first().json;
const body = item.body || {{}};
const prompt = {prompt_concat};
const payload = JSON.stringify({{
  model: "{MODEL}",
  system: "{sys_escaped}",
  prompt: prompt,
  stream: false
}});
const resp = await this.helpers.httpRequest({{
  method: 'POST',
  url: '{OLLAMA_URL}',
  headers: {{'Content-Type': 'application/json'}},
  body: payload,
  timeout: 120000
}});
const data = typeof resp === 'string' ? JSON.parse(resp) : resp;
return [{{json: {{...item, ollama_response: data.response || JSON.stringify(data)}}}}];"""

    relay_js = f"""const item = $input.first().json;
const body = item.body || {{}};
const payload = JSON.stringify({{
  task: {task_js},
  brief: item.ollama_response || ''
}});
const resp = await this.helpers.httpRequest({{
  method: 'POST',
  url: '{RELAY_URL}',
  headers: {{'Content-Type': 'application/json'}},
  body: payload,
  timeout: 200000
}});
const data = typeof resp === 'string' ? JSON.parse(resp) : resp;
return [{{json: {{...item, result: data.result || JSON.stringify(data)}}}}];"""

    return {
        "name": name,
        "nodes": [
            {"id": "wh", "name": "Webhook", "type": "n8n-nodes-base.webhook",
             "typeVersion": 2, "position": [240, 300],
             "parameters": {"path": path, "responseMode": "responseNode", "httpMethod": "POST"}},
            {"id": "ollama", "name": "Ollama Compress", "type": "n8n-nodes-base.code",
             "typeVersion": 2, "position": [500, 300],
             "parameters": {"jsCode": ollama_js, "mode": "runOnceForAllItems"}},
            {"id": "relay", "name": "Claude Finalize", "type": "n8n-nodes-base.code",
             "typeVersion": 2, "position": [760, 300],
             "parameters": {"jsCode": relay_js, "mode": "runOnceForAllItems"}},
            {"id": "resp", "name": "Respond", "type": "n8n-nodes-base.respondToWebhook",
             "typeVersion": 1, "position": [1020, 300],
             "parameters": {"respondWith": "json", "responseBody": respond_expr}},
        ],
        "connections": {
            "Webhook":        {"main": [[{"node": "Ollama Compress", "type": "main", "index": 0}]]},
            "Ollama Compress": {"main": [[{"node": "Claude Finalize",  "type": "main", "index": 0}]]},
            "Claude Finalize": {"main": [[{"node": "Respond",          "type": "main", "index": 0}]]},
        },
        "settings": {"executionOrder": "v1"},
    }


LEADS = build_workflow(
    name="Ollama->Claude: Lead Brief",
    path="leads",
    system_prompt=(
        "You are a B2B lead engine for a CMMC consulting firm.\n"
        "Output EXACTLY:\n"
        "TASK: write outreach email\n"
        "KEY FACTS:\n- Company: [name]\n- NAICS: [code]\n- Why CMMC: [one sentence]\n- Deadline: Nov 10 2026\n"
        "DRAFT:\nSubject: [subject]\n\n[3-paragraph email]\n"
        "CONSTRAINTS: urgent but professional, under 200 words, offer free gap assessment"
    ),
    prompt_js_parts=[
        '"Company: " + (body.company || "")',
        '"NAICS: " + (body.naics || "")',
        '"Notes: " + (body.notes || "")',
    ],
    task_js='"write outreach email for " + (body.company || "this company")',
    respond_expr='={{ JSON.stringify({ email: $json.result, company: $json.body.company }) }}',
)

PROPOSAL = build_workflow(
    name="Ollama->Claude: Proposal Draft",
    path="proposal",
    system_prompt=(
        "You are a CMMC proposal drafter.\n"
        "Output EXACTLY:\nTASK: finalize proposal\nKEY FACTS:\n- Client: [name]\n- Notes: [details]\n"
        "DRAFT:\n# CMMC Proposal\n## Executive Summary\n[2 sentences]\n## Scope\n[bullets]\n"
        "## Timeline\n[phases]\n## Investment\n[price range]\n"
        "CONSTRAINTS: professional, specific numbers, no NIST jargon"
    ),
    prompt_js_parts=[
        '"Client: " + (body.client || "")',
        '"Notes: " + (body.notes || "")',
    ],
    task_js='"finalize CMMC proposal for " + (body.client || "this client")',
    respond_expr='={{ JSON.stringify({ proposal: $json.result, client: $json.body.client }) }}',
)

ANALYSIS = build_workflow(
    name="Ollama->Claude: Document Analysis",
    path="analyze",
    system_prompt=(
        "You are a business data extractor.\n"
        "Output EXACTLY:\nTASK: [analysis Claude should complete]\nKEY FACTS:\n- [key fact]\n"
        "DRAFT:\n[structured analysis]\nRECOMMENDATION: [one action]\n"
        "CONSTRAINTS: concise, bullet-heavy"
    ),
    prompt_js_parts=[
        '"Question: " + (body.question || "")',
        '"Text: " + (body.text || "")',
    ],
    task_js='body.question || "analyze this"',
    respond_expr='={{ JSON.stringify({ analysis: $json.result }) }}',
)


def main():
    wait_for_n8n()
    print("\n--- Creating n8n Workflows ---")
    create_workflow(PROPOSAL)
    create_workflow(LEADS)
    create_workflow(ANALYSIS)
    print("\nOK Webhooks:")
    print("  POST http://localhost:5678/webhook/proposal   { client, notes }")
    print("  POST http://localhost:5678/webhook/leads      { company, naics, notes }")
    print("  POST http://localhost:5678/webhook/analyze    { text, question }")


if __name__ == "__main__":
    main()
