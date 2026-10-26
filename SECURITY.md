# Security Notes

## Where secrets live

All API keys, tokens and passwords live in **`.env`** (gitignored). The installer
creates it from `.env.example` and generates the passwords marked `auto`.
Never commit, paste or screenshot it.

- Python scripts read it through `scripts/_env.py` (`require` / `env`).
- `docker-compose.yml` reads it for container settings.
- `mcpo/config.json` uses `${VAR}` placeholders; `mcpo/render_config.py` fills them
  in from `.env` at launch, writing the gitignored `config.rendered.json`.

## Network exposure

All container ports bind to `127.0.0.1`. The Claude relay (7777) binds to all
interfaces so containers can reach it through `host.docker.internal`. It has no
login, so keep it behind your firewall and never forward the port.

## Webhook security

Inbound n8n webhooks require a shared-secret header:

```
X-Webhook-Token: <N8N_WEBHOOK_SECRET from .env>
```

The installer generates the secret. See `docs/n8n-webhook-auth-setup.md`, and run
`scripts/verify_n8n_webhook_auth.py` to confirm unauthenticated calls are rejected.

## Rotating keys

| Service | Where |
|---|---|
| Anthropic | console.anthropic.com → API Keys |
| HubSpot | Settings → Integrations → Private Apps |
| Apollo | Settings → Integrations → API |
| Twilio | console.twilio.com → API keys & tokens |
| n8n API key | http://localhost:5678 → Settings → API |
| n8n login | change `N8N_BASIC_AUTH_PASSWORD` in `.env`, then `docker compose up -d n8n` |
| Google OAuth | console.cloud.google.com → APIs & Services → Credentials |

## Reporting a problem

Please open a GitHub issue without including any secrets, or use GitHub's private
vulnerability reporting on this repo.
