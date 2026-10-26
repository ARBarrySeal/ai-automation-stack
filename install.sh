#!/usr/bin/env bash
# One-shot installer for the AI automation stack + Claude Code setup (macOS / Linux).
#
#   ./install.sh                      # everything
#   ./install.sh --skip-model         # skip the ~9 GB Ollama download
#   ./install.sh --non-interactive --skip-claude
#
# Steps: prerequisites, .env, Python venv, Docker stack, Ollama model,
# n8n workflow, Claude Code + GSD + plugins. Every step is safe to re-run.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

INTERACTIVE=1; SKIP_DOCKER=0; SKIP_MODEL=0; SKIP_CLAUDE=0; ALLOW_SHELL=0
MODEL="qwen2.5:14b"
while [ $# -gt 0 ]; do
  case "$1" in
    --non-interactive) INTERACTIVE=0 ;;
    --skip-docker) SKIP_DOCKER=1 ;;
    --skip-model) SKIP_MODEL=1 ;;
    --skip-claude) SKIP_CLAUDE=1 ;;
    --allow-shell) ALLOW_SHELL=1 ;;
    --model) MODEL="$2"; shift ;;
    -h|--help) sed -n 2,9p "$0"; exit 0 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
  shift
done

step() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }
OS="$(uname -s)"

# --- 1. Prerequisites -------------------------------------------------------
step "Checking prerequisites"
missing=()
for c in git python3 node docker; do have "$c" || missing+=("$c"); done

if [ ${#missing[@]} -gt 0 ]; then
  if [ "$OS" = "Darwin" ]; then
    have brew || { echo "Install Homebrew first: https://brew.sh"; exit 1; }
    for c in "${missing[@]}"; do
      case "$c" in
        python3) brew install python ;;
        docker) brew install --cask docker; echo "Open Docker.app once, then re-run."; exit 1 ;;
        *) brew install "$c" ;;
      esac
    done
  elif have apt-get; then
    pkgs=()
    for c in "${missing[@]}"; do
      case "$c" in
        python3) pkgs+=(python3 python3-venv python3-pip) ;;
        node) pkgs+=(nodejs npm) ;;
        git) pkgs+=(git) ;;
        docker) echo "Install Docker Engine + compose plugin: https://docs.docker.com/engine/install/ then re-run."; exit 1 ;;
      esac
    done
    sudo apt-get update && sudo apt-get install -y "${pkgs[@]}"
  else
    echo "Missing: ${missing[*]}. Install them with your package manager, then re-run."; exit 1
  fi
fi
have uv || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
for c in git python3 node docker; do echo "  ok  $c"; done

# --- 2. .env ------------------------------------------------------------------
step "Creating .env"
if [ "$INTERACTIVE" = 1 ]; then python3 scripts/setup_env.py --interactive; else python3 scripts/setup_env.py; fi

# --- 3. Python environment ----------------------------------------------------
step "Installing Python packages into .venv"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements.txt

[ -f mcpo/config.json ] || cp mcpo/config.example.json mcpo/config.json
[ -f mcpo/owui.env ] || cp mcpo/owui.env.example mcpo/owui.env
chmod +x mcpo/*.sh scripts/*.sh 2>/dev/null || true

# --- 4. Docker stack ------------------------------------------------------------
if [ "$SKIP_DOCKER" = 0 ]; then
  step "Starting the Docker stack"
  docker info >/dev/null 2>&1 || { echo "Docker isn't running. Start it, then re-run."; exit 1; }
  compose=(-f docker-compose.yml)
  if have nvidia-smi; then
    echo "  NVIDIA GPU found: enabling GPU for Ollama"
    compose+=(-f docker-compose.gpu.yml)
  fi
  docker compose "${compose[@]}" up -d || { echo "docker compose failed. If port 5432 is taken, set POSTGRES_PORT in .env."; exit 1; }

  # --- 5. Model + workflow --------------------------------------------------
  if [ "$SKIP_MODEL" = 0 ]; then
    step "Pulling Ollama model $MODEL (large download, one time)"
    docker exec ollama ollama pull "$MODEL"
  fi

  step "Importing the n8n workflow"
  sleep 5
  docker cp n8n/workflow_cold_email.json n8n:/tmp/workflow_cold_email.json
  docker exec n8n n8n import:workflow --input=/tmp/workflow_cold_email.json \
    || echo "  Workflow import failed. Import n8n/workflow_cold_email.json from the n8n UI instead."
fi

# --- 6. Claude Code -----------------------------------------------------------
if [ "$SKIP_CLAUDE" = 0 ]; then
  step "Setting up Claude Code"
  if ! have claude; then
    echo "  installing Claude Code..."
    curl -fsSL https://claude.ai/install.sh | bash
    export PATH="$HOME/.local/bin:$PATH"
  fi

  if [ "$ALLOW_SHELL" = 1 ]; then python3 claude/merge_settings.py --allow-shell; else python3 claude/merge_settings.py; fi

  if [ ! -f "$HOME/.claude/CLAUDE.md" ]; then
    cp claude/CLAUDE.md.example "$HOME/.claude/CLAUDE.md"
    echo "  created ~/.claude/CLAUDE.md (edit it to describe your business)"
  fi

  echo "  installing GSD (planning/execution workflows)..."
  npx -y get-shit-done-cc@latest --claude --global

  if have claude; then
    echo "  installing plugins..."
    claude plugin marketplace add anthropics/claude-plugins-official 2>/dev/null || true
    for p in chrome-devtools-mcp code-review; do
      claude plugin install "$p@claude-plugins-official" 2>/dev/null || true
    done
    claude mcp add --scope user --transport http pipeline-desktop http://localhost:7788/mcp 2>/dev/null || true
  else
    echo "  Open a new terminal and re-run with --skip-docker to finish the Claude Code plugins."
  fi
fi

step "Done"
cat <<'EOF'
  Open WebUI   http://localhost:3000
  n8n          http://localhost:5678   (login: see N8N_BASIC_AUTH_* in .env)
  Ollama       http://localhost:11434

Next:
  - Add your API keys to .env (HubSpot, Apollo, Twilio, SAM.gov, Anthropic: all optional)
  - Open WebUI admin + tool setup:   .venv/bin/python setup_owui.py
  - Claude relay:                    scripts/start_relay.sh
  - MCP bridge for Open WebUI:       mcpo/start.sh
  - Start Claude Code in this folder: claude
EOF
