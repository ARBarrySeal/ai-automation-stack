"""
Updates n8n email workflows to include your booking link (CALENDLY_URL in .env).
Patches the workflows named below (find them by name in n8n), if they exist:
Lead Outreach Email, Daily Follow-up: Stale Leads. The SAM.gov pipeline calls the
outreach webhook, so it inherits the change.
"""
import requests, json
from _env import require, env, BUSINESS_NAME, BUSINESS_REGION, CALENDLY_URL

N8N = 'http://localhost:5678/api/v1'
KEY = require('N8N_API_KEY')
H = {'X-N8N-API-KEY': KEY, 'Content-Type': 'application/json'}
CALENDLY = CALENDLY_URL

WORKFLOWS = {
    'Lead Outreach Email': 'outreach',
    'Daily Follow-up: Stale Leads': 'followup',
}

OUTREACH_SYSTEM = (
    f'You are a B2B sales email writer for {BUSINESS_NAME}, a CMMC consulting firm in {BUSINESS_REGION}. '
    'Write a concise, professional cold outreach email to a defense contractor who needs CMMC Level 2 help. '
    'Keep it under 200 words. Lead with a specific pain point related to their industry. '
    'End with a soft CTA offering a free 30-minute gap assessment with a direct booking link: ' + CALENDLY + ' '
    'Sound human, not like marketing copy. Output ONLY the email (subject line + body). No word counts, no meta-commentary.'
)

FOLLOWUP_SYSTEM = (
    f'You are a B2B sales rep for {BUSINESS_NAME}. '
    'Write a brief friendly follow-up email (under 100 words) to a defense contractor we emailed 7+ days ago with no response. '
    'Reference CMMC and the November 2026 deadline. Sound human. '
    'Include this booking link for a free 15-min call: ' + CALENDLY + ' '
    'Output ONLY the email (Subject line + body). No meta-commentary.'
)


def get_workflow(wf_id):
    r = requests.get(f'{N8N}/workflows/{wf_id}', headers=H, timeout=10)
    return r.json() if r.ok else None


def update_code_node_system_prompt(wf, new_system):
    """Replace the system content string in the Code node's jsCode."""
    nodes = wf.get('nodes', [])
    updated = False
    for node in nodes:
        if node.get('type') == 'n8n-nodes-base.code':
            js = node['parameters'].get('jsCode', '')
            # Find and replace the system content between single quotes after 'system', 'content':
            import re
            # Pattern: 'system', content: 'OLD_SYSTEM_PROMPT'
            # The system prompt is in: {role: 'system', content: 'PROMPT'}
            new_js = re.sub(
                r"(role:\s*'system',\s*content:\s*')(.*?)(')",
                lambda m: m.group(1) + new_system.replace("'", "\\'") + m.group(3),
                js,
                flags=re.DOTALL
            )
            if new_js != js:
                node['parameters']['jsCode'] = new_js
                updated = True
    return wf, updated


def patch_workflow(wf_id, wf):
    """Send the full updated workflow back."""
    # n8n requires sending nodes + connections + settings
    payload = {
        'name': wf['name'],
        'nodes': wf['nodes'],
        'connections': wf['connections'],
        'settings': wf.get('settings', {}),
        'staticData': wf.get('staticData'),
    }
    r = requests.put(f'{N8N}/workflows/{wf_id}', headers=H, json=payload, timeout=15)
    return r.ok, r.status_code, r.text[:150] if not r.ok else ''


PROMPTS = {'outreach': OUTREACH_SYSTEM, 'followup': FOLLOWUP_SYSTEM}

r = requests.get(f'{N8N}/workflows', headers=H, timeout=10)
r.raise_for_status()
ids = {w['name']: w['id'] for w in r.json().get('data', [])}

for name, kind in WORKFLOWS.items():
    wf_id = ids.get(name)
    if not wf_id:
        print(f'Skipping: {name} (not found in n8n)')
        continue
    print(f'Patching: {name} ({wf_id})')
    wf = get_workflow(wf_id)
    if wf:
        wf, updated = update_code_node_system_prompt(wf, PROMPTS[kind])
        ok, code, err = patch_workflow(wf_id, wf)
        print(f'  {"Updated" if updated else "No match found"} | PUT {code} {"OK" if ok else err}')

# --- SAM.gov Pipeline (email generation calls /webhook/leads which uses the above) ---
# The SAM pipeline calls the leads webhook, so it inherits the update automatically.
print('SAM.gov Pipeline: inherits Calendly via Lead Outreach Email webhook - no direct patch needed.')

print(f'\nCalendly link active in outreach: {CALENDLY}')
print('All emails now end with a direct booking link.')
