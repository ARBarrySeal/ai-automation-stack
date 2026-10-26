# Fires on System event Tcpip 4266 (UDP ephemeral port exhaustion).
# Dumps per-process UDP socket ownership so the port hog can be identified.
$logDir = Join-Path (Split-Path $PSScriptRoot -Parent) 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$log = Join-Path $logDir 'udp_exhaustion_capture.log'

$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$udp = Get-NetUDPEndpoint -ErrorAction SilentlyContinue
$byProc = $udp | Group-Object OwningProcess | Sort-Object Count -Descending | Select-Object -First 20 | ForEach-Object {
    $p = Get-Process -Id $_.Name -ErrorAction SilentlyContinue
    '{0,6}  {1,-30} {2}' -f $_.Count, ($p.ProcessName ?? "PID $($_.Name) (gone)"), ($p.Path ?? '')
}

@(
    "==== $stamp — Event 4266 UDP port exhaustion captured ===="
    "Total UDP endpoints: $($udp.Count)"
    "Top owners:"
    $byProc
    ""
) | Add-Content -Path $log
