"""
Creates an n8n SMS follow-up workflow (webhook: sms-followup).
Send one contact or a list; each gets a short AI-written text after a networking
event, signed with SENDER_NAME / BUSINESS_NAME and your booking link.
Twilio trial accounts can only text numbers you have verified in the console.
"""
import requests, json
from _env import require, env, SENDER_NAME, BUSINESS_NAME, CALENDLY_URL

N8N = 'http://localhost:5678/api/v1'
KEY = require('N8N_API_KEY')
H = {'X-N8N-API-KEY': KEY, 'Content-Type': 'application/json'}

TWILIO_SID   = require('TWILIO_SID')
TWILIO_TOKEN = require('TWILIO_AUTH_TOKEN')
FROM_NUMBER  = require('TWILIO_FROM')
CALENDLY     = CALENDLY_URL
SENDER       = f'{SENDER_NAME} at {BUSINESS_NAME}'

SMS_JS = f"""
try {{
  const item = $input.first().json;
  const body = item.body || {{}};

  // Support single contact or array
  const contacts = Array.isArray(body.contacts) ? body.contacts : [{{
    phone: body.phone || body.to,
    name:  body.name  || 'there',
    context: body.context || ''
  }}];

  const TWILIO_SID   = '{TWILIO_SID}';
  const TWILIO_TOKEN = '{TWILIO_TOKEN}';
  const FROM         = '{FROM_NUMBER}';
  const CALENDLY     = '{CALENDLY}';
  const results = [];

  for (const contact of contacts.slice(0, 50)) {{
    const phone   = (contact.phone || '').trim();
    const name    = (contact.name  || 'there').split(' ')[0];
    const context = (contact.context || '').trim();

    if (!phone) continue;

    // Generate a short personalized SMS via local AI
    let msgText = '';
    try {{
      const aiResp = await this.helpers.httpRequest({{
        method: 'POST',
        url: 'http://host.docker.internal:7777/v1/chat/completions',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{
          model: 'qwen2.5:14b',
          max_tokens: 80,
          messages: [
            {{ role: 'system', content: 'Write a single SMS (under 160 chars) from {SENDER} following up after a networking event. Be warm and personal. Include the booking link at the end. No hashtags. Output ONLY the message text.' }},
            {{ role: 'user', content: 'To: ' + name + (context ? '. Context: ' + context : '') + '. Booking link: ' + CALENDLY }}
          ]
        }}),
        timeout: 30000
      }});
      const aiData = typeof aiResp === 'string' ? JSON.parse(aiResp) : aiResp;
      msgText = (aiData?.choices?.[0]?.message?.content || '').trim().slice(0, 160);
    }} catch(e) {{
      msgText = 'Hey ' + name + ', great meeting you! This is {SENDER}. Happy to chat anytime: ' + CALENDLY;
    }}

    // Send via Twilio
    const formData = 'To=' + encodeURIComponent(phone) +
                     '&From=' + encodeURIComponent(FROM) +
                     '&Body=' + encodeURIComponent(msgText);

    const twilioResp = await this.helpers.httpRequest({{
      method: 'POST',
      url: 'https://api.twilio.com/2010-04-01/Accounts/' + TWILIO_SID + '/Messages.json',
      headers: {{
        'Content-Type': 'application/x-www-form-urlencoded',
        'Authorization': 'Basic ' + Buffer.from(TWILIO_SID + ':' + TWILIO_TOKEN).toString('base64')
      }},
      body: formData,
      timeout: 15000
    }});

    const tData = typeof twilioResp === 'string' ? JSON.parse(twilioResp) : twilioResp;
    results.push({{
      phone,
      name,
      status: tData.status || 'sent',
      sid: tData.sid || '',
      preview: msgText.slice(0, 80)
    }});
  }}

  return [{{ json: {{ sent: results.length, results }} }}];
}} catch(e) {{
  return [{{ json: {{ error: e.message }} }}];
}}
"""

workflow = {
    "name": "SMS Follow-up (Events)",
    "nodes": [
        {
            "id": "wh", "name": "Webhook", "type": "n8n-nodes-base.webhook",
            "typeVersion": 2, "position": [240, 300],
            "parameters": {
                "path": "sms-followup",
                "responseMode": "responseNode",
                "httpMethod": "POST"
            }
        },
        {
            "id": "sms", "name": "Send SMS", "type": "n8n-nodes-base.code",
            "typeVersion": 2, "position": [520, 300],
            "parameters": {"jsCode": SMS_JS, "mode": "runOnceForAllItems"}
        },
        {
            "id": "resp", "name": "Respond", "type": "n8n-nodes-base.respondToWebhook",
            "typeVersion": 1, "position": [800, 300],
            "parameters": {"respondWith": "json", "responseBody": "={{ JSON.stringify($json) }}"}
        }
    ],
    "connections": {
        "Webhook":  {"main": [[{"node": "Send SMS", "type": "main", "index": 0}]]},
        "Send SMS": {"main": [[{"node": "Respond",  "type": "main", "index": 0}]]}
    },
    "settings": {"executionOrder": "v1"}
}

# Check if exists
r = requests.get(f'{N8N}/workflows', headers=H, timeout=10)
existing = [w['name'] for w in r.json().get('data', [])]

if workflow['name'] in existing:
    print(f'Already exists: {workflow["name"]}')
else:
    r = requests.post(f'{N8N}/workflows', headers=H, json=workflow, timeout=15)
    if r.ok:
        wf_id = r.json().get('id')
        requests.post(f'{N8N}/workflows/{wf_id}/activate', headers=H, timeout=10)
        print(f'Created + activated: {workflow["name"]} (id={wf_id})')
    else:
        print(f'ERROR: {r.status_code} {r.text[:300]}')

print('\nAll workflows:')
r2 = requests.get(f'{N8N}/workflows', headers=H, timeout=10)
for w in r2.json().get('data', []):
    status = 'ON ' if w['active'] else 'OFF'
    print(f'  [{status}] {w["name"]}')

print(f'\nTwilio number: {FROM_NUMBER}')
print(f'Webhook: POST http://localhost:5678/webhook/sms-followup')
print('Single: { "phone": "+15555550100", "name": "Alex", "context": "met at the industry lunch" }')
print('Bulk:   { "contacts": [{ "phone": "...", "name": "...", "context": "..." }] }')
