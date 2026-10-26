# docker-watchdog.ps1 — auto-heals the recurring Docker "ghost engine" hang.
#
# Acts ONLY when Docker Desktop is running but the engine is wedged (the exact 500 state).
#   - Won't relaunch Docker if you deliberately quit it (checks the process is up first).
#   - Won't fire during a normal cold start (3-min grace window).
#   - Won't thrash (15-min cooldown; a fix itself takes ~2 min).
#   - Can't hang itself (health probe runs in a killable job with a hard timeout).
# Runs every 5 min via the 'DockerEngineWatchdog' scheduled task.

$ErrorActionPreference = 'SilentlyContinue'
$root     = $PSScriptRoot
$log      = Join-Path $root 'docker-watchdog.log'
$cooldown = Join-Path $root '.docker-watchdog.cooldown'
$fix      = Join-Path $root 'docker-fix.ps1'

function Log($m) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $m" | Add-Content -Path $log }

# Desktop balloon notification — no external modules. Kept short-lived but alive
# long enough for Windows to actually render the tip.
function Notify($title, $text) {
    try {
        Add-Type -AssemblyName System.Windows.Forms
        Add-Type -AssemblyName System.Drawing
        $n = New-Object System.Windows.Forms.NotifyIcon
        $n.Icon             = [System.Drawing.SystemIcons]::Information
        $n.BalloonTipTitle  = $title
        $n.BalloonTipText   = $text
        $n.Visible          = $true
        $n.ShowBalloonTip(10000)
        Start-Sleep -Seconds 8
        $n.Dispose()
    } catch {}
}

# 1) If Docker Desktop isn't running, the user quit it on purpose — do nothing.
$dd = Get-Process 'Docker Desktop' -ErrorAction SilentlyContinue | Sort-Object StartTime | Select-Object -First 1
if (-not $dd) { exit 0 }

# 2) Grace period: don't fire while the engine is still in a normal cold start (~up to 90s).
$uptime = (Get-Date) - $dd.StartTime
if ($uptime.TotalSeconds -lt 180) { exit 0 }

# 3) Cooldown: a heal does a full wsl shutdown + relaunch. Don't re-fire for 15 min.
if (Test-Path $cooldown) {
    if (((Get-Date) - (Get-Item $cooldown).LastWriteTime).TotalMinutes -lt 15) { exit 0 }
}

# 4) Bounded health probe — a dead engine can hang a bare CLI call, so run it killable.
$job = Start-Job { docker version --format '{{.Server.Version}}' 2>$null }
$healthy = $false
if (Wait-Job $job -Timeout 12) {
    $out = Receive-Job $job
    if ($out -and ($out -match '\d+\.\d+')) { $healthy = $true }
}
Remove-Job $job -Force -ErrorAction SilentlyContinue

if ($healthy) { exit 0 }   # engine fine — nothing to do

# 5) Ghost state confirmed: Docker Desktop up, engine dead. Heal it.
$mins = [int]$uptime.TotalMinutes
Log "GHOST ENGINE detected (Docker Desktop up ${mins}m, engine unhealthy) -> running docker-fix.ps1 -NoStack"
Set-Content -Path $cooldown -Value (Get-Date)
Notify 'Docker is healing itself' 'The engine wedged on startup. Auto-recovery is running now — give it ~3 minutes. Do NOT quit or restart Docker; that interrupts the fix.'
try {
    & $fix -NoStack *>> $log
    Log 'docker-fix.ps1 completed'
} catch {
    Log "docker-fix.ps1 FAILED: $_"
}
