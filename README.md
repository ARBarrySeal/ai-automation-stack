# AI Automation Stack

A local AI stack for sales and lead-generation automation, plus a ready-to-use
Claude Code setup. One installer sets up everything on Windows, macOS or Linux.

**What you get**

| Piece | What it does |
|---|---|
| **Ollama** + **Open WebUI** | Private ChatGPT-style chat on your own machine (http://localhost:3000) |
| **n8n** | Workflow automation, with a cold-outreach email workflow pre-loaded (http://localhost:5678) |
| **Claude relay** | Routes heavy requests to Claude and light ones to the local model (port 7777) |
| **MCP bridge (mcpo)** | Gives Open WebUI tools: memory, files, web search, CRM, Google Sheets, browser |
| **Postgres** + **Redis** | Storage for workflows and scripts |
| **Lead scripts** | SAM.gov and USASpending.gov contractor search, Apollo enrichment, HubSpot sync, Gmail drafts, Twilio SMS, Word reports |
| **Claude Code setup** | Settings, the [GSD](https://www.npmjs.com/package/get-shit-done-cc) planning workflows, browser and code-review plugins, a `CLAUDE.md` template |

## Install

You need about 20 GB of free disk space (most of it is the AI model). An NVIDIA GPU is
used automatically if you have one. Without one, everything still runs, just more slowly.

**Windows** (PowerShell):

```powershell
git clone https://github.com/ARBarrySeal/ai-automation-stack.git
cd ai-automation-stack
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

**macOS / Linux**:

```bash
git clone https://github.com/ARBarrySeal/ai-automation-stack.git
cd ai-automation-stack
chmod +x install.sh && ./install.sh
```

The installer:

1. Installs whatever is missing: Git, Python, Node.js, uv and Docker (winget on Windows, Homebrew on Mac, apt on Debian/Ubuntu)
2. Creates `.env`, generates strong passwords and asks for your business name, region and booking link
3. Installs the Python packages into `.venv`
4. Starts the Docker stack and downloads the `qwen2.5:14b` model (~9 GB)
5. Imports the n8n workflow
6. Installs Claude Code, GSD and the plugins, and merges the settings into yours (your existing settings are backed up and never overwritten)

Run it again any time: every step skips what's already done.

| Option (Windows / Mac-Linux) | Effect |
|---|---|
| `-NonInteractive` / `--non-interactive` | Don't ask questions |
| `-SkipModel` / `--skip-model` | Skip the model download |
| `-Model llama3.2` / `--model llama3.2` | Use a different (e.g. smaller) model |
| `-SkipDocker` / `--skip-docker` | Don't start containers |
| `-SkipClaude` / `--skip-claude` | Don't change Claude Code |
| `-AllowShell` / `--allow-shell` | Let Claude Code run shell commands without asking each time |

## After installing

1. **Add API keys** to `.env`. All of them are optional, so add only the services you use:
   Anthropic, HubSpot, Apollo, Twilio, SAM.gov (free), Tavily, Firecrawl, Google.
2. **Open WebUI**: run `.venv/bin/python setup_owui.py` (Windows: `.venv\Scripts\python setup_owui.py`)
   to create the admin account and register the tools.
3. **Optional background services**:
   - Claude relay: `scripts/start_relay.sh` (Windows: `scripts\start_relay.bat`; `install-relay-autostart.bat` runs it at login)
   - MCP bridge: `mcpo/start.sh` (Windows: `mcpo\start.bat`; `install-autostart.bat` runs it at login)
   - Claude Code MCP server: `.venv/bin/python scripts/pipeline_mcp_server.py`
4. **Edit `~/.claude/CLAUDE.md`** to describe your business, so Claude Code knows your context.

## Everyday commands

```bash
docker compose up -d                 # start the stack
docker compose down                  # stop it
docker compose logs -f n8n           # watch a service
docker exec ollama ollama pull phi4  # add another model

scripts/leads_pipeline.sh --state TX --naics 541512 --count 5   # find contractors + draft emails
.venv/bin/python scripts/upgrade_sam_pipeline.py                # SAM.gov -> n8n -> HubSpot
.venv/bin/python scripts/build_report.py --input examples/report_data.example.json
```

Reports, CSVs and drafts are written to `output/`.

## Layout

```
install.ps1 / install.sh    one-shot installers
.env.example                every setting, with comments
docker-compose.yml          the stack (+ docker-compose.gpu.yml for NVIDIA)
scripts/                    lead gen, CRM, email/SMS, relay, Docker helpers (Windows .ps1)
n8n/                        importable n8n workflow
mcpo/                       MCP bridge config for Open WebUI
pipeline/                   Open WebUI pipeline that routes to the Claude relay
claude/                     Claude Code settings template, CLAUDE.md and memory examples
examples/                   sample input files
docs/                       extra setup guides
```

## Security

- Everything listens on `127.0.0.1` only. The Claude relay binds to all interfaces so Docker
  can reach it. Don't forward port 7777 on your router, because it has no login.
- Secrets live only in `.env`, which git ignores. See [SECURITY.md](SECURITY.md).
- TLS certificate checks are on. If antivirus HTTPS scanning breaks requests, set `VERIFY_SSL=0` in `.env`.

## License

MIT. See [LICENSE](LICENSE).
