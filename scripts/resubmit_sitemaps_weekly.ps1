# Weekly sitemap resubmit for every domain in SITE_DOMAINS (.env).
# Schedule it with Task Scheduler (weekly). Logs to resubmit_sitemaps.log.
$ErrorActionPreference = "Continue"
$py = Join-Path $PSScriptRoot "resubmit_sitemap.py"
$log = Join-Path $PSScriptRoot "resubmit_sitemaps.log"
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content $log "===== $stamp ====="
try {
    $out = & python $py 2>&1 | Out-String
    Add-Content $log $out.TrimEnd()
} catch {
    Add-Content $log "ERROR: $($_.Exception.Message)"
}
Add-Content $log ""
