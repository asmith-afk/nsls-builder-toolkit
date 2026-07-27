param(
  [Parameter(Mandatory = $true)][string]$Email,
  [Parameter(Mandatory = $true)][string]$Skill
)
# Detached POST to the tracker /skill-event (deduped per builder/skill/day).
# Launched fire-and-forget by skill-event.ps1 so it never blocks tool use.
$ErrorActionPreference = 'SilentlyContinue'
try {
  $body = @{ builder_email = $Email; skill_name = $Skill } | ConvertTo-Json -Compress
  $tracker = if ($env:NSLS_TRACKER_URL) { $env:NSLS_TRACKER_URL } else { 'https://web-production-6281e.up.railway.app' }
  Invoke-RestMethod -Uri "$tracker/skill-event" `
    -Method Post -Body $body -ContentType 'application/json' -TimeoutSec 20 | Out-Null
} catch {}
