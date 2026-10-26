# n8n Webhook Authentication Setup

Inbound webhook auth is enforced at the workflow level via a "Verify Secret" Code
node positioned immediately after each Webhook trigger. Without this, anyone who
can reach `http://localhost:5678/webhook/<path>` (and via ngrok, anyone on the
internet) can trigger billable side-effects (Apollo enrichment, HubSpot writes,
Twilio SMS, etc.).

The shared secret lives in `.env` as `N8N_WEBHOOK_SECRET`.
Callers send it as the `X-Webhook-Token` header. `leads_pipeline.py` and
`smart.py` already do this automatically.

## One-time setup per webhook workflow

For each of these workflows in the n8n UI:

| Workflow path  | Workflow name in n8n         |
|----------------|------------------------------|
| `sam-leads`    | SAM.gov → HubSpot Pipeline   |
| `leads`        | Cold Outreach Email          |
| `sms-followup` | Twilio SMS Follow-up         |
| `proposal`     | Proposal Draft               |
| `analyze`      | CMMC Gap Analysis            |

### Steps

1. Open the workflow in the n8n editor.
2. Click the **+** between the **Webhook** node and the next node.
3. Choose **Code** node (JavaScript).
4. Paste this exact code:

   ```javascript
   // Verify shared-secret header in constant time.
   const expected = $env.N8N_WEBHOOK_SECRET || '';
   const provided = $input.first().json.headers?.['x-webhook-token']
                 || $input.first().json.headers?.['X-Webhook-Token']
                 || '';

   if (!expected) {
     throw new Error('Server misconfig: N8N_WEBHOOK_SECRET not set');
   }

   // Constant-time compare so we don't leak the secret length via timing.
   const a = Buffer.from(expected, 'utf8');
   const b = Buffer.from(provided, 'utf8');
   let same = a.length === b.length;
   const len = Math.max(a.length, b.length);
   let diff = a.length ^ b.length;
   for (let i = 0; i < len; i++) {
     diff |= (a[i] || 0) ^ (b[i] || 0);
   }
   if (diff !== 0) {
     // Return a 401 by setting the Webhook node's "Respond with" mode to "Last node"
     // and producing a response item — n8n will surface this to the caller.
     return [{ json: { ok: false, error: 'unauthorized' }, _status: 401 }];
   }

   // Pass-through original webhook payload to the next node.
   return $input.all();
   ```

5. Rename the node to **Verify Secret**.
6. Save and (re-)activate the workflow.
7. To return proper 401 responses to unauthenticated callers, the Webhook node
   needs `Response Mode: Using "Respond to Webhook" Node` — or simpler, set
   **Respond → On Last Node**, and add a second branch in the Verify-Secret
   node's output that triggers a **Respond to Webhook** node with status 401.

### Verifying after setup

Once n8n is running and all five workflows have the node:

```powershell
docker start n8n          # if not already up
python scripts\verify_n8n_webhook_auth.py
```

You should see five `[OK ]` rows. Any `[FAIL]` row tells you which webhook
still needs the verify node.

## If you ever rotate the secret

1. Generate a new random string: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
2. Update `N8N_WEBHOOK_SECRET=...` in `.env`
3. Restart any process that calls the webhooks so it re-reads `.env`
   (`leads_pipeline.py`, `smart.py`, the SAM.gov scraper, etc.)
4. Restart n8n so the Code node sees the new `$env.N8N_WEBHOOK_SECRET`:
   `docker restart n8n`
5. Re-run `verify_n8n_webhook_auth.py` to confirm everything still authenticates.

## Why a Code node and not an IF node

An IF node can compare strings but it does so non-constant-time, which leaks
the secret length character-by-character to anyone who can time the response.
For a secret protecting CRM writes and Twilio sends, that's worth a few extra
lines of code.
