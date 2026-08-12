# skill-event.ps1 - PreToolUse(Skill) hook for Windows.
# Windows counterpart to hooks/skill-event.sh (which Windows can't run). Reads
# the Claude Code hook JSON from stdin, extracts tool_input.skill, and fires a
# non-blocking POST to the tracker /skill-event. Never blocks tool execution.
$ErrorActionPreference = 'SilentlyContinue'

try { $raw = [Console]::In.ReadToEnd() } catch { $raw = '' }
$skill = $null
try { $skill = ($raw | ConvertFrom-Json).tool_input.skill } catch {}
if ([string]::IsNullOrWhiteSpace($skill)) { exit 0 }

# Mirror of skill-event.sh: strip OUR plugin prefixes only, so tracker credit
# rows stay continuous with the bare-name history. Third-party prefixes
# (compound-engineering:...) are real distinct names and pass through.
$skill = $skill -replace '^nsls-builder-toolkit:', '' -replace '^nsls-personal-toolkit:', ''

# Builder email - same precedence as session-ping.ps1 / session-start.py.
$email = ''
$envFile = Join-Path $env:USERPROFILE '.claude\local-plugins\nsls-personal-toolkit\.env'
if (Test-Path $envFile) {
  foreach ($l in Get-Content $envFile -Encoding UTF8) {
    if ($l -match '^BUILDER_EMAIL=(.*)$') { $email = $Matches[1].Trim().Trim('"') }
  }
}
if (-not $email) { try { $email = (& git config user.email) } catch {} }
$email = "$email".Trim()
if ([string]::IsNullOrWhiteSpace($email)) { exit 0 }

# Fire-and-forget: detached poster (args passed cleanly, no JSON-in-string
# escaping) so the POST's latency never delays the Skill tool.
$poster = Join-Path $PSScriptRoot 'skill-post.ps1'
if (Test-Path $poster) {
  Start-Process powershell -WindowStyle Hidden -ArgumentList @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $poster,
    '-Email', $email, '-Skill', $skill
  ) | Out-Null
}
exit 0
