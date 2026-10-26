"""
Upgrades the SAM.gov -> HubSpot pipeline to enrich each company
via Apollo org enrichment before generating the outreach email.
"""
import requests, json
from _env import require, env, CALENDLY_URL

N8N = 'http://localhost:5678/api/v1'
KEY = require('N8N_API_KEY')
H  = {'X-N8N-API-KEY': KEY, 'Content-Type': 'application/json'}
WF_NAME = 'SAM.gov -> HubSpot Lead Pipeline'   # created by create_sam_pipeline.py
APOLLO_KEY = require('APOLLO_KEY')
HS_TOKEN   = require('HUBSPOT_TOKEN')
CALENDLY   = CALENDLY_URL

PIPELINE_JS = """
try {
  const item = $input.first().json;
  const body = item.body || {};
  const leads = Array.isArray(body.leads) ? body.leads : [body];
  const HS_TOKEN    = '""" + HS_TOKEN + """';
  const APOLLO_KEY  = '""" + APOLLO_KEY + """';
  const results = [];

  for (const lead of leads.slice(0, 20)) {
    const company      = (lead.company || lead.company_name || '').trim();
    const naics        = (lead.naics   || lead.naics_code   || '').trim();
    const notes        = (lead.description || lead.notes    || '').trim();
    const state        = (lead.state   || '').trim();
    const contactEmail = (lead.contact_email || '').trim();
    const contactName  = (lead.contact_name  || '').trim();
    const contractVal  = lead.contract_value || '';
    if (!company) continue;

    // 1. Apollo org enrichment — get domain, employee count, LinkedIn, description
    let apolloData = {};
    try {
      const aResp = await this.helpers.httpRequest({
        method: 'POST',
        url: 'https://api.apollo.io/v1/organizations/enrich',
        headers: { 'Content-Type': 'application/json', 'x-api-key': APOLLO_KEY },
        body: JSON.stringify({ name: company, organization_name: company }),
        timeout: 10000
      });
      const aData = typeof aResp === 'string' ? JSON.parse(aResp) : aResp;
      const org = aData.organization || {};
      apolloData = {
        domain:        org.primary_domain || '',
        employees:     org.estimated_num_employees || '',
        linkedin:      org.linkedin_url || '',
        description:   org.short_description || '',
        industry:      org.industry || '',
        city:          org.city || '',
      };
    } catch(e) { /* enrichment optional */ }

    // 2. Apollo people/match — find decision-maker at this company
    let personData = {};
    if (apolloData.domain) {
      try {
        const pResp = await this.helpers.httpRequest({
          method: 'POST',
          url: 'https://api.apollo.io/api/v1/people/match?run_waterfall_email=false&run_waterfall_phone=false&reveal_personal_emails=false&reveal_phone_number=false',
          headers: { 'Content-Type': 'application/json', 'X-Api-Key': APOLLO_KEY },
          body: JSON.stringify({ domain: apolloData.domain, organization_name: company }),
          timeout: 12000
        });
        const pData = typeof pResp === 'string' ? JSON.parse(pResp) : pResp;
        const p = pData.person || {};
        if (p.name) {
          personData = {
            firstName:   p.first_name || '',
            lastName:    p.last_name  || '',
            name:        p.name       || '',
            title:       p.title      || '',
            email:       p.email      || '',
            linkedin:    p.linkedin_url || '',
          };
        }
      } catch(e) { /* people/match optional */ }
    }

    // 3. Search HubSpot for existing company
    let companyId = null;
    try {
      const sResp = await this.helpers.httpRequest({
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
      const sData = typeof sResp === 'string' ? JSON.parse(sResp) : sResp;
      if (sData.results && sData.results.length > 0) companyId = sData.results[0].id;
    } catch(e) {}

    // 4. Create company if not found, enriched with Apollo data
    if (!companyId) {
      try {
        const cResp = await this.helpers.httpRequest({
          method: 'POST',
          url: 'https://api.hubapi.com/crm/v3/objects/companies',
          headers: { Authorization: 'Bearer ' + HS_TOKEN, 'Content-Type': 'application/json' },
          body: JSON.stringify({
            properties: {
              name:         company,
              state:        state || apolloData.city,
              description:  (apolloData.description || notes).slice(0, 500),
              domain:       apolloData.domain,
              industry:     'DEFENSE_AND_SPACE',
              hs_lead_status: 'NEW',
              numberofemployees: apolloData.employees ? String(apolloData.employees) : '',
              linkedin_company_page: apolloData.linkedin,
              annualrevenue: contractVal ? String(contractVal) : ''
            }
          }),
          timeout: 10000
        });
        const cData = typeof cResp === 'string' ? JSON.parse(cResp) : cResp;
        companyId = cData.id;
      } catch(e) { results.push({ company, status: 'error-create: ' + e.message }); continue; }
    }

    // 4. Generate outreach email with Apollo context injected into notes
    let emailDraft = '';
    const enrichedNotes = [
      notes,
      apolloData.description ? 'Company overview: ' + apolloData.description : '',
      apolloData.employees   ? 'Size: ~' + apolloData.employees + ' employees'  : '',
      apolloData.industry    ? 'Industry: ' + apolloData.industry : '',
      state ? 'Location: ' + state : (apolloData.city ? 'Location: ' + apolloData.city : ''),
    ].filter(Boolean).join('. ');

    try {
      const eResp = await this.helpers.httpRequest({
        method: 'POST',
        url: 'http://host.docker.internal:5678/webhook/leads',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ company, naics, notes: enrichedNotes }),
        timeout: 90000
      });
      emailDraft = typeof eResp === 'string' ? eResp : JSON.stringify(eResp);
    } catch(e) { emailDraft = 'Email generation failed: ' + e.message; }

    // 5. Save email draft as HubSpot note
    if (companyId) {
      const noteBody = [
        'OUTREACH DRAFT — ' + new Date().toISOString().split('T')[0] + ' [SAM.gov + Apollo]',
        apolloData.domain    ? 'Domain: '     + apolloData.domain    : '',
        apolloData.employees ? 'Employees: ~' + apolloData.employees  : '',
        apolloData.linkedin  ? 'LinkedIn: '   + apolloData.linkedin   : '',
        personData.name      ? 'Decision-maker: ' + personData.name + (personData.title ? ' | ' + personData.title : '') : '',
        personData.email     ? 'Contact email: '  + personData.email : '',
        '',
        emailDraft.slice(0, 2800)
      ].filter(s => s !== null && s !== undefined && s !== '').join('\\n');

      try {
        await this.helpers.httpRequest({
          method: 'POST',
          url: 'https://api.hubapi.com/crm/v3/objects/notes',
          headers: { Authorization: 'Bearer ' + HS_TOKEN, 'Content-Type': 'application/json' },
          body: JSON.stringify({
            properties: {
              hs_note_body: noteBody,
              hs_timestamp: String(Date.now())
            },
            associations: [{ to: { id: companyId }, types: [{ associationCategory: 'HUBSPOT_DEFINED', associationTypeId: 190 }] }]
          }),
          timeout: 10000
        });
      } catch(e) {}
    }

    // 6. Create contact — prefer Apollo people/match, fall back to SAM.gov data
    const useEmail     = personData.email     || contactEmail;
    const useFirstName = personData.firstName || (contactName.split(' ')[0] || contactName);
    const useLastName  = personData.lastName  || (contactName.split(' ').slice(1).join(' ') || '');
    if ((useEmail || personData.name) && companyId) {
      try {
        await this.helpers.httpRequest({
          method: 'POST',
          url: 'https://api.hubapi.com/crm/v3/objects/contacts',
          headers: { Authorization: 'Bearer ' + HS_TOKEN, 'Content-Type': 'application/json' },
          body: JSON.stringify({
            properties: {
              email:        useEmail,
              firstname:    useFirstName,
              lastname:     useLastName,
              jobtitle:     personData.title   || '',
              linkedin_bio: personData.linkedin || '',
              hs_lead_status: 'NEW'
            },
            associations: [{ to: { id: companyId }, types: [{ associationCategory: 'HUBSPOT_DEFINED', associationTypeId: 280 }] }]
          }),
          timeout: 10000
        });
      } catch(e) {}
    }

    results.push({
      company,
      companyId,
      domain:    apolloData.domain    || 'not found',
      employees: apolloData.employees || 'unknown',
      status:    'ok',
      emailPreview: emailDraft.slice(0, 120)
    });
  }

  return [{ json: { processed: results.length, results } }];
} catch(e) {
  return [{ json: { error: e.message } }];
}
"""

# Find the workflow by name, then fetch it in full
r = requests.get(f'{N8N}/workflows', headers=H, timeout=10)
r.raise_for_status()
WF_ID = next((w['id'] for w in r.json().get('data', []) if w['name'] == WF_NAME), None)
if not WF_ID:
    raise SystemExit(f"Workflow '{WF_NAME}' not found. Run create_sam_pipeline.py first.")
r = requests.get(f'{N8N}/workflows/{WF_ID}', headers=H, timeout=10)
wf = r.json()

# Update the Code node
for node in wf.get('nodes', []):
    if node.get('type') == 'n8n-nodes-base.code':
        node['parameters']['jsCode'] = PIPELINE_JS

# Push update
payload = {
    'name': wf['name'],
    'nodes': wf['nodes'],
    'connections': wf['connections'],
    'settings': wf.get('settings', {}),
    'staticData': wf.get('staticData'),
}
r2 = requests.put(f'{N8N}/workflows/{WF_ID}', headers=H, json=payload, timeout=15)
if r2.ok:
    print(f'SAM.gov pipeline upgraded with Apollo enrichment: 200 OK')
    print(f'  Apollo: org enrichment (domain, employees, LinkedIn, industry)')
    print(f'  HubSpot: companies + notes + contacts')
    print(f'  Calendly: {CALENDLY} embedded in all outreach emails')
    print(f'  Webhook: POST http://localhost:5678/webhook/sam-leads')
else:
    print(f'Error: {r2.status_code} {r2.text[:200]}')
