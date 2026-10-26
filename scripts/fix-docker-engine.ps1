<#
  fix-docker-engine.ps1
  ----------------------------------------------------------------------------
  Permanent recovery for the recurring Docker Desktop hang on this machine:
  the GUI stays up but dockerd is a ghost (500 errors / "engine stopped" /
  commands hang). The in-app "Restart" button does NOT fix it.

  This script does the only sequence that reliably works:
    1. Kill every Docker process + the Windows service.
    2. wsl --terminate docker-desktop   (clears the ghost WSL state)
    3. Relaunch Docker Desktop.
    4. Poll the engine until `docker ps` answers (bounded, never hangs).

  Docker's live data lives in the WSL distro on C: (verified). Nothing here
  touches your drives or the 225 GB orphan files on E:/G:.

  Usage:  double-click fix-docker.cmd   (or)   pwsh -File fix-docker-engine.ps1
#>

$ErrorActionPreference = 'SilentlyContinue'
$DockerExe = 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
$DockerCli = 'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
if (-not (Test-Path $DockerCli)) { $DockerCli = 'docker' }   # fall back to PATH

function Say($msg, $color = 'White') { Write-Host $msg -ForegroundColor $color }

Say "`n=== Docker engine recovery ===" 'Cyan'

# 1) Stop the Windows service (needs admin; ignored if not elevated) ----------
Say "[1/4] Stopping com.docker.service ..." 'Gray'
Stop-Service 'com.docker.service' -Force -ErrorAction SilentlyContinue

# 2) Kill every Docker-related process --------------------------------------
Say "[2/4] Killing Docker processes ..." 'Gray'
$names = @(
  'Docker Desktop','com.docker.backend','com.docker.build','com.docker.dev-envs',
  'com.docker.extensions','com.docker.proxy','com.docker.service','dockerd',
  'docker-agent','docker-sandbox','vpnkit','wsl-bootstrap'
)
foreach ($n in $names) {
  Get-Process -Name $n -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2

# 3) Terminate the ghost WSL distro -----------------------------------------
Say "[3/4] Terminating docker-desktop WSL distro ..." 'Gray'
wsl.exe --terminate docker-desktop      2>$null
wsl.exe --terminate docker-desktop-data 2>$null   # legacy layout, harmless if absent
Start-Sleep -Seconds 2

# 4) Relaunch + poll until the engine answers (max 120s, never hangs) -------
Say "[4/4] Relaunching Docker Desktop ..." 'Gray'
if (Test-Path $DockerExe) {
  Start-Process -FilePath $DockerExe
} else {
  Say "  ! Docker Desktop.exe not found at $DockerExe" 'Red'
}

$deadline = (Get-Date).AddSeconds(120)
$ready = $false
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 4
  & $DockerCli ps *> $null
  if ($LASTEXITCODE -eq 0) { $ready = $true; break }
  Write-Host "." -NoNewline
}
Write-Host ""

if ($ready) {
  Say "`nSUCCESS - engine is up and responding." 'Green'
  & $DockerCli info --format 'Docker root dir: {{.DockerRootDir}}' 2>$null
  & $DockerCli ps --format 'running: {{.Names}}' 2>$null
} else {
  Say "`nEngine did not answer within 120s." 'Yellow'
  Say "Open Docker Desktop manually; if still stuck, reboot is the last resort." 'Yellow'
}
