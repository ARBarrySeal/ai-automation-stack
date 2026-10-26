# AI Automation Stack — Claude Code Context

## What this project is

Local AI stack on Docker plus lead-generation scripts:
- **Open WebUI** (http://localhost:3000): chat interface for local models
- **Ollama** (http://localhost:11434): model runner (default `qwen2.5:14b`)
- **n8n** (http://localhost:5678): workflow automation
- **pipelines**: routes heavy Open WebUI requests through the Claude relay
- **Postgres** / **Redis**: storage
- **ngrok** (optional): public tunnel for webhooks

## Rules

- Secrets and business details come from `.env` via `scripts/_env.py`
  (`require("KEY")` for required, `env("KEY", default)` for optional). Never hard-code them.
- Generated files go to `OUTPUT_DIR` (default `output/`, gitignored).
- Python runs from `.venv` (created by the installer).

## Common commands

```bash
docker compose up -d          # start (add -f docker-compose.gpu.yml for NVIDIA)
docker compose down           # stop
docker compose ps             # status
docker exec -it ollama ollama pull <model>
docker compose logs -f open-webui
```

## Files

| Path | Purpose |
|------|---------|
| `docker-compose.yml` | Stack definition |
| `.env` / `.env.example` | Settings and keys (`.env` is gitignored) |
| `scripts/` | Lead gen, n8n setup, SAM.gov, HubSpot, Gmail, Twilio, relay |
| `n8n/` | Importable workflows |
| `mcpo/` | MCP bridge config for Open WebUI |
| `pipeline/owui_pipeline.py` | Claude relay pipeline |
| `claude/` | Claude Code settings template and examples |
