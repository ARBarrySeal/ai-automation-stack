<#
.SYNOPSIS
  One-shot installer for the AI automation stack + Claude Code setup (Windows).

.DESCRIPTION
  1. Installs missing tools with winget (Git, Python, Node.js, uv, Docker Desktop)
  2. Creates .env and generates passwords/secrets
  3. Creates a Python virtual environment and installs requirements
  4. Starts the Docker stack (adds the NVIDIA GPU override when it finds one)
  5. Pulls the default Ollama model and imports the n8n workflow
  6. Installs Claude Code, GSD, plugins and settings

  Every step is safe to re-run.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install.ps1
  .\install.ps1 -SkipModel -SkipClaude
#>
param(
    [switch]$NonInteractive,   # don't ask for business details
    [switch]$SkipDocker,       # don't start containers
    [switch]$SkipModel,        # don't pull the Ollama model (~9 GB)
    [switch]$SkipClaude,       # don't touch Claude Code
    [switch]$AllowShell,       # let Claude run shell commands without asking
    [string]$Model = "qwen2.5:14b"
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Have($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}

# --- 1. Prerequisites -------------------------------------------------------
Step "Checking prerequisites"
$tools = [ordered]@{
    git    = "Git.Git"
    python = "Python.Python.3.12"
    node   = "OpenJS.NodeJS.LTS"
    uv     = "astral-sh.uv"
    docker = "Docker.DockerDesktop"
}
foreach ($cmd in $tools.Keys) {
    if (Have $cmd) { Write-Host "  ok  $cmd"; continue }
    if (-not (Have winget)) { throw "$cmd is missing and winget isn't available. Install $cmd manually, then re-run." }
    Write-Host "  installing $cmd ($($tools[$cmd]))..."
    winget install --id $tools[$cmd] -e --accept-source-agreements --accept-package-agreements --silent
    Refresh-Path
}
if (-not (Have docker)) {
    Write-Warning "Docker Desktop was just installed. Start it once (and reboot if asked), then re-run this script."
    exit 1
}

# --- 2. .env ------------------------------------------------------------------
Step "Creating .env"
$envArgs = @("scripts\setup_env.py")
if (-not $NonInteractive) { $envArgs += "--interactive" }
python @envArgs

# --- 3. Python environment ----------------------------------------------------
Step "Installing Python packages into .venv"
if (-not (Test-Path ".venv")) { python -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
& .\.venv\Scripts\python.exe -m pip install --quiet -r requirements.txt

# MCP bridge config (templates -> local, gitignored copies)
if (-not (Test-Path "mcpo\config.json")) { Copy-Item "mcpo\config.example.json" "mcpo\config.json" }
if (-not (Test-Path "mcpo\owui.env"))    { Copy-Item "mcpo\owui.env.example" "mcpo\owui.env" }

# --- 4. Docker stack ------------------------------------------------------------
if (-not $SkipDocker) {
    Step "Starting the Docker stack"
    docker info *> $null
    if ($LASTEXITCODE -ne 0) { throw "Docker isn't running. Start Docker Desktop, then re-run." }
    $compose = @("-f", "docker-compose.yml")
    if (Have nvidia-smi) {
        Write-Host "  NVIDIA GPU found: enabling GPU for Ollama"
        $compose += @("-f", "docker-compose.gpu.yml")
    }
    docker compose @compose up -d
    if ($LASTEXITCODE -ne 0) { throw "docker compose failed. If port 5432 is taken, set POSTGRES_PORT in .env." }

    # --- 5. Model + workflow --------------------------------------------------
    if (-not $SkipModel) {
        Step "Pulling Ollama model $Model (large download, one time)"
        docker exec ollama ollama pull $Model
    }

    Step "Importing the n8n workflow"
    Start-Sleep -Seconds 5
    docker cp "n8n\workflow_cold_email.json" "n8n:/tmp/workflow_cold_email.json"
    docker exec n8n n8n import:workflow --input=/tmp/workflow_cold_email.json
    if ($LASTEXITCODE -ne 0) { Write-Warning "Workflow import failed. Import n8n\workflow_cold_email.json from the n8n UI instead." }
}

# --- 6. Claude Code -----------------------------------------------------------
if (-not $SkipClaude) {
    Step "Setting up Claude Code"
    if (-not (Have claude)) {
        Write-Host "  installing Claude Code..."
        Invoke-RestMethod https://claude.ai/install.ps1 | Invoke-Expression
        Refresh-Path
        $local = Join-Path $HOME ".local\bin"
        if (Test-Path $local) { $env:Path += ";$local" }
    }

    $mergeArgs = @("claude\merge_settings.py")
    if ($AllowShell) { $mergeArgs += "--allow-shell" }
    python @mergeArgs

    $globalMd = Join-Path $HOME ".claude\CLAUDE.md"
    if (-not (Test-Path $globalMd)) {
        Copy-Item "claude\CLAUDE.md.example" $globalMd
        Write-Host "  created $globalMd (edit it to describe your business)"
    }

    Write-Host "  installing GSD (planning/execution workflows)..."
    npx -y get-shit-done-cc@latest --claude --global

    if (Have claude) {
        Write-Host "  installing plugins..."
        claude plugin marketplace add anthropics/claude-plugins-official 2>$null
        foreach ($p in "chrome-devtools-mcp", "code-review") {
            claude plugin install "$p@claude-plugins-official" 2>$null
        }
        claude mcp add --scope user --transport http pipeline-desktop http://localhost:7788/mcp 2>$null
    } else {
        Write-Warning "Open a new terminal and re-run with -SkipDocker to finish the Claude Code plugins."
    }
}

Step "Done"
Write-Host @"
  Open WebUI   http://localhost:3000
  n8n          http://localhost:5678   (login: see N8N_BASIC_AUTH_* in .env)
  Ollama       http://localhost:11434

Next:
  - Add your API keys to .env (HubSpot, Apollo, Twilio, SAM.gov, Anthropic: all optional)
  - Open WebUI admin + tool setup:   .venv\Scripts\python setup_owui.py
  - Claude relay:                    scripts\start_relay.bat
  - MCP bridge for Open WebUI:       mcpo\start.bat
  - Start Claude Code in this folder: claude
"@
