# docker-diag.ps1 — hang-proof Docker/WSL state probe.
# Every engine call runs inside a Start-Job with a hard timeout, so a ghost
# dockerd can never block the caller. Pure read-only. No mutations.

$cli = 'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
$out = [System.Collections.Generic.List[string]]::new()

function Bounded([scriptblock]$sb, [int]$sec, [string]$label) {
  $j = Start-Job $sb
  if (Wait-Job $j -Timeout $sec) {
    $r = Receive-Job $j 2>$null
    Remove-Job $j -Force
    return "$label OK: $($r -join ' | ')"
  }
  Stop-Job $j -EA SilentlyContinue; Remove-Job $j -Force
  return "$label TIMEOUT (>${sec}s)"
}

# 1. Drives
foreach ($d in 'C','E','G') {
  $v = Get-PSDrive $d -EA SilentlyContinue
  if ($v) { $out.Add(("DRIVE {0}: free={1:N1}GB used={2:N1}GB" -f $d,($v.Free/1GB),($v.Used/1GB))) }
}

# 2. Processes (instant, no engine call)
$dd = Get-Process 'Docker Desktop','com.docker.backend','com.docker.build' -EA SilentlyContinue
$out.Add("DOCKER PROCS: " + (($dd | Select-Object -Expand ProcessName -Unique) -join ', '))
$vm = Get-Process vmmemWSL -EA SilentlyContinue
$out.Add($(if($vm){"WSL VM: running {0:N1}GB" -f ($vm.WorkingSet64/1GB)}else{"WSL VM: not running"}))

# 3. Junction + vhdx
$jp = Join-Path $env:LOCALAPPDATA 'Docker\wsl\disk'
$j = Get-Item $jp -EA SilentlyContinue
if ($j) {
  $out.Add("JUNCTION $jp -> " + ($j.Target -join ';'))
  $vhdx = (Get-ChildItem $jp -Filter *.vhdx -EA SilentlyContinue | Select-Object -First 1).FullName
  if ($vhdx) { $out.Add(("VHDX {0} = {1:N1}GB" -f $vhdx,((Get-Item $vhdx).Length/1GB))) }
  else { $out.Add("VHDX: NOT FOUND via junction") }
} else { $out.Add("JUNCTION: missing at $jp") }

# 4. Bounded engine + wsl probes
$out.Add((Bounded { & 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' info --format '{{.ServerVersion}} containers={{.Containers}} images={{.Images}}' } 40 'docker-info'))
$out.Add((Bounded { wsl --list --verbose } 20 'wsl-list'))

$out -join "`n"
