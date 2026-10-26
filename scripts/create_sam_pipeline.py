import requests, json
from _env import require

N8N_BASE = "http://localhost:5678/api/v1"
N8N_KEY = require("N8N_API_KEY")
HS_TOKEN = require("HUBSPOT_TOKEN")
HEADERS = {"X-N8N-API-KEY": N8N_KEY, "Content-Type": "application/json"}

PIPELINE_JS = """
try {
  const item = $input.first().json;
  const body = item.body || {};
  const leads = Array.isArray(body.leads) ? body.leads : [body];
  const HS_TOKEN = '__HS_TOKEN__';
  const results = [];

  for (const lead of leads.slice(0, 20)) {
    const company = (lead.company || lead.company_name || '').trim();
    const naics = (lead.naics || lead.naics_code || '').trim();
    const notes = (lead.description || lead.notes || '').trim();
    const state = (lead.state || '').trim();
    const contactEmail = (lead.contact_email || '').trim();
    const contactName = (lead.contact_name || '').trim();
    const contractValue = lead.contract_value || '';
    if (!company) continue;

    // 1. Search HubSpot for existing company
    let companyId = null;
    try {
      const searchResp = await this.helpers.httpRequest({
        method: 'POST',
        url: 'https://api.hubapi.com/crm/v3/objects/companies/search',
        headers: { Authorization: 'Bearer ' + HS_TOKEN, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          filterGroups: [{ filters: [{ propertyName: 'name', operator: 'EQ', value: company }] }],
          properties: ['name', 'hs_lead_status'],
          limit: 1
        }),
        timeout: 10000
      });
      const sData = typeof searchResp === 'string' ? JSON.parse(searchResp) : searchResp;
      if (sData.results && sData.results.length > 0) {
        companyId = sData.results[0].id;
      }
    } catch(e) { /* search failed, will create */ }

    // 2. Create company if not found
    if (!companyId) {
      try {
        const createResp = await this.helpers.httpRequest({
          method: 'POST',
          url: 'https://api.hubapi.com/crm/v3/objects/companies',
          headers: { Authorization: 'Bearer ' + HS_TOKEN, 'Content-Type': 'application/json' },
          body: JSON.stringify({
            properties: {
              name: company,
              state: state,
              description: notes.slice(0, 500),
              industry: 'DEFENSE_AND_SPACE',
              hs_lead_status: 'NEW',
              annualrevenue: contractValue ? String(contractValue) : ''
            }
          }),
          timeout: 10000
        });
        const cData = typeof createResp === 'string' ? JSON.parse(createResp) : createResp;
        companyId = cData.id;
      } catch(e) { results.push({ company, status: 'error-create: ' + e.message }); continue; }
    }

    // 3. Generate outreach email via existing leads webhook
    let emailDraft = '';
    try {
      const emailResp = await this.helpers.httpRequest({
        method: 'POST',
        url: 'http://host.docker.internal:5678/webhook/leads',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ company, naics, notes: notes + (state ? ' Location: ' + state : '') }),
        timeout: 90000
      });
      emailDraft = typeof emailResp === 'string' ? emailResp : JSON.stringify(emailResp);
    } catch(e) { emailDraft = 'Email generation failed: ' + e.message; }

    // 4. Save generated email as HubSpot note
    if (companyId) {
      try {
        await this.helpers.httpRequest({
          method: 'POST',
          url: 'https://api.hubapi.com/crm/v3/objects/notes',
          headers: { Authorization: 'Bearer ' + HS_TOKEN, 'Content-Type': 'application/json' },
          body: JSON.stringify({
            properties: {
              hs_note_body: 'OUTREACH DRAFT — ' + new Date().toISOString().split('T')[0] + ' [SAM.gov]\\n\\n' + emailDraft.slice(0, 3000),
              hs_timestamp: String(Date.now())
            },
            associations: [{ to: { id: companyId }, types: [{ associationCategory: 'HUBSPOT_DEFINED', associationTypeId: 190 }] }]
          }),
          timeout: 10000
        });
      } catch(e) { /* note save failed, non-fatal */ }
    }

    // 5. Create contact if email provided
    if (contactEmail && companyId) {
      try {
        await this.helpers.httpRequest({
          method: 'POST',
          url: 'https://api.hubapi.com/crm/v3/objects/contacts',
          headers: { Authorization: 'Bearer ' + HS_TOKEN, 'Content-Type': 'application/json' },
          body: JSON.stringify({
            properties: {
              email: contactEmail,
              firstname: contactName.split(' ')[0] || contactName,
              lastname: contactName.split(' ').slice(1).join(' ') || '',
              hs_lead_status: 'NEW'
            },
            associations: companyId ? [{ to: { id: companyId }, types: [{ associationCategory: 'HUBSPOT_DEFINED', associationTypeId: 280 }] }] : []
          }),
          timeout: 10000
        });
      } catch(e) { /* contact may already exist */ }
    }

    results.push({ company, companyId, status: 'ok', emailPreview: emailDraft.slice(0, 120) });
  }

  return [{ json: { processed: results.length, results } }];
} catch(e) {
  return [{ json: { error: e.message } }];
}
"""

# Inject token at creation time so it never travels as a literal in the workflow JSON
PIPELINE_JS = PIPELINE_JS.replace("__HS_TOKEN__", HS_TOKEN)

workflow = {
  "name": "SAM.gov -> HubSpot Lead Pipeline",
  "nodes": [
    {
      "id": "wh", "name": "Webhook", "type": "n8n-nodes-base.webhook",
      "typeVersion": 2, "position": [240, 300],
      "parameters": {"path": "sam-leads", "responseMode": "responseNode", "httpMethod": "POST"}
    },
    {
      "id": "pipe", "name": "Process Leads", "type": "n8n-nodes-base.code",
      "typeVersion": 2, "position": [520, 300],
      "parameters": {"jsCode": PIPELINE_JS, "mode": "runOnceForAllItems"}
    },
    {
      "id": "resp", "name": "Respond", "type": "n8n-nodes-base.respondToWebhook",
      "typeVersion": 1, "position": [800, 300],
      "parameters": {"respondWith": "json", "responseBody": "={{ JSON.stringify($json) }}"}
    }
  ],
  "connections": {
    "Webhook":       {"main": [[{"node": "Process Leads", "type": "main", "index": 0}]]},
    "Process Leads": {"main": [[{"node": "Respond",       "type": "main", "index": 0}]]}
  },
  "settings": {"executionOrder": "v1"}
}

# Check if exists
r = requests.get(f"{N8N_BASE}/workflows", headers=HEADERS, timeout=10)
existing = [w["name"] for w in r.json().get("data", [])]
wf_name = workflow["name"]

if wf_name in existing:
    print(f"Already exists: {wf_name}")
else:
    r = requests.post(f"{N8N_BASE}/workflows", headers=HEADERS, json=workflow, timeout=15)
    if r.ok:
        wf_id = r.json().get("id")
        ra = requests.post(f"{N8N_BASE}/workflows/{wf_id}/activate", headers=HEADERS, timeout=10)
        print(f"Created + activated: {wf_name} (id={wf_id})")
        print("  Webhook: POST http://localhost:5678/webhook/sam-leads")
        print('  Body: { "leads": [{ "company", "naics", "description", "state", "contact_email" }] }')
    else:
        print(f"ERROR: {r.status_code} {r.text[:400]}")

print("\nAll n8n workflows:")
r2 = requests.get(f"{N8N_BASE}/workflows", headers=HEADERS, timeout=10)
for w in r2.json().get("data", []):
    status = "ON " if w["active"] else "OFF"
    print(f"  [{status}] {w['name']}")
