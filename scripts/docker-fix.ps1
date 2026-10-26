<#
  docker-fix.ps1  —  Hang-proof Docker Desktop recovery for the recurring
  "ghost engine" wedge (UI + helper procs alive, `docker info` hangs).

  The Docker Desktop UI "Restart" button does NOT fix this state. The real fix
  is to terminate the docker-desktop WSL distro and cold-start the app.

  EVERY docker/wsl call here runs inside a Start-Job with a hard timeout, so a
  dead engine can never block the script (the root cause of past session hangs).

  USAGE:
    pwsh -File docker-fix.ps1            # full recovery: kill -> terminate -> relaunch -> wait -> start stack
    pwsh -File docker-fix.ps1 -Check     # read-only health probe, no changes
    pwsh -File docker-fix.ps1 -NoStack   # recover engine only, don't start containers
#>
[CmdletBinding()]
param(
  [switch]$Check,
  [switch]$NoStack
)

$ErrorActionPreference = 'Continue'
$DOCKER = 'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
$DESKTOP = 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
$STACK = @('postgres','redis','n8n','ollama')   # container names to start; adjust as needed

function Invoke-Bounded {
  # Run a scriptblock with a hard timeout. Returns @{ Ok=$bool; Out=$string }.
  param([scriptblock]$Script, [int]$TimeoutSec = 12)
  $j = Start-Job $Script
  if (Wait-Job $j -Timeout $TimeoutSec) {
    $out = (Receive-Job $j 2>&1 | Out-String).Trim()
    Remove-Job $j -Force -EA SilentlyContinue
    return @{ Ok = $true; Out = $out }
  }
  Stop-Job $j -EA SilentlyContinue; Remove-Job $j -Force -EA SilentlyContinue
  return @{ Ok = $false; Out = "TIMEOUT (>${TimeoutSec}s)" }
}

function Get-EngineHealth {
  param([int]$TimeoutSec = 12)
  $d = $script:DOCKER
  $r = Invoke-Bounded -TimeoutSec $TimeoutSec -Script {
    & $using:d info --format '{{.ServerVersion}}|{{.ContainersRunning}}' 2>&1
  }
  if ($r.Ok -and $r.Out -match '^\d') { return @{ Healthy = $true; Detail = $r.Out } }
  return @{ Healthy = $false; Detail = $r.Out }
}

Write-Host "=== docker-fix.ps1 ===" -ForegroundColor Cyan

# --- Health probe (always runs first) ---
$h = Get-EngineHealth -TimeoutSec 12
if ($h.Healthy) {
  Write-Host "Engine HEALTHY: $($h.Detail)" -ForegroundColor Green
} else {
  Write-Host "Engine UNHEALTHY: $($h.Detail)" -ForegroundColor Yellow
}

if ($Check) {
  Write-Host "(-Check mode: no changes made)"
  return
}

if ($h.Healthy -and -not $NoStack) {
  Write-Host "Engine already healthy; ensuring stack is up..." -ForegroundColor Green
} elseif (-not $h.Healthy) {
  # --- RECOVERY SEQUENCE ---
  Write-Host "`n[1/4] Stopping Docker Desktop processes..." -ForegroundColor Cyan
  $names = 'Docker Desktop','com.docker.backend','com.docker.build',
           'com.docker.dev-envs','com.docker.extensions','com.docker.service'
  Get-Process $names -EA SilentlyContinue | Stop-Process -Force -EA SilentlyContinue
  Start-Sleep -Seconds 2

  Write-Host "[2/4] Full WSL2 shutdown (resets the shared utility VM + vpnkit networking)..." -ForegroundColor Cyan
  # NOTE: `wsl --terminate docker-desktop` is NOT enough for the hard wedge where the
  # init control API never answers ("socketforwarder-receive-fds.sock does not exist
  # yet" / "still waiting for init control API to respond"). That state lives in the
  # SHARED WSL2 utility VM, not the single distro. Only `wsl --shutdown` resets it.
  # This stops ALL distros (Ubuntu/kali), but they're independent and lose no data.
  (Invoke-Bounded -TimeoutSec 40 -Script { wsl --shutdown 2>&1 }).Out | Write-Host
  Start-Sleep -Seconds 3

  Write-Host "[3/4] Relaunching Docker Desktop..." -ForegroundColor Cyan
  Start-Process $DESKTOP

  Write-Host "[4/4] Waiting for engine to come healthy (up to ~120s)..." -ForegroundColor Cyan
  $deadline = (Get-Date).AddSeconds(120)
  do {
    Start-Sleep -Seconds 6
    $h = Get-EngineHealth -TimeoutSec 10
    Write-Host ("  ... {0}" -f ($(if($h.Healthy){"HEALTHY: $($h.Detail)"}else{$h.Detail})))
  } while (-not $h.Healthy -and (Get-Date) -lt $deadline)

  if (-not $h.Healthy) {
    Write-Host "Engine still not healthy after 120s. Open Docker Desktop UI and check for errors (disk full? update pending?)." -ForegroundColor Red
    return
  }
  Write-Host "Engine recovered: $($h.Detail)" -ForegroundColor Green
}

# --- Start the stack ---
if (-not $NoStack) {
  Write-Host "`nStarting stack containers: $($STACK -join ', ')" -ForegroundColor Cyan
  foreach ($c in $STACK) {
    $r = Invoke-Bounded -TimeoutSec 20 -Script { & $using:DOCKER start $using:c 2>&1 }
    Write-Host ("  {0}: {1}" -f $c, $r.Out)
  }
}

# --- Final report ---
Write-Host "`n=== Final state ===" -ForegroundColor Cyan
$ps = Invoke-Bounded -TimeoutSec 15 -Script { & $using:DOCKER ps --format '{{.Names}}\t{{.Status}}' 2>&1 }
Write-Host $ps.Out
