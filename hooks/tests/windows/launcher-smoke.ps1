# launcher-smoke.ps1 — prove run-hook.sh works on a real Windows machine.
#
# Add to the windows-latest hooks job (the one that parses the .ps1 files) as:
#     - name: Hook launcher resolves a Python and decides
#       run: pwsh -File hooks/tests/windows/launcher-smoke.ps1
#
# What this is for. hooks.json has no OS conditional, so every hook entry names
# one launch shape for every machine. The last time that was decided from a Mac,
# the entry named `python3` — a Store alias on Windows that exits without
# running — the error notice it produced got the gate deleted from hooks.json,
# and every migrated Mac then went unguarded for two weeks. The replacement
# resolves the interpreter inside a bash launcher. This is the check that it
# does so on Windows, rather than on the assumption of someone without a PC.

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path "$PSScriptRoot/../../..").Path
$failures = @()

function Check($name, $ok, $detail = '') {
    if ($ok) { Write-Host "  ok   $name" }
    else { Write-Host "  FAIL $name $detail"; $script:failures += $name }
}

$bash = (Get-Command bash -ErrorAction SilentlyContinue)
Check 'Git Bash is on PATH (install.ps1 requires Git for Windows)' ($null -ne $bash)
if (-not $bash) { Write-Host 'cannot continue'; exit 1 }

$work = Join-Path $env:RUNNER_TEMP "launcher-smoke-$([guid]::NewGuid())"
New-Item -ItemType Directory -Path "$work/cfg" -Force | Out-Null
New-Item -ItemType Directory -Path "$work/repo" -Force | Out-Null
Set-Content -Path "$work/repo/README.md" -Value "# NSLS tool`nInternal NSLS." -NoNewline
Push-Location "$work/repo"
git init -q .
git remote add origin https://github.com/someones-personal-account/nsls-thing.git
Pop-Location

$env:CLAUDE_CONFIG_DIR = "$work/cfg"
$env:CLAUDE_PLUGIN_ROOT = $repo
$env:NSLS_GUARDRAIL_EVENT_LOG = "$work/events.jsonl"

$payload = '{"tool_name":"Bash","tool_input":{"command":"git push origin main"},"tool_use_id":"toolu_ci"}'
$launcher = "$repo/hooks/run-hook.sh" -replace '\\', '/'

Push-Location "$work/repo"
$out = $payload | & bash $launcher gate 2>&1 | Out-String
$code = $LASTEXITCODE
Pop-Location

Check 'the launcher exits 0 (a non-zero exit prints a hook-error notice on every tool call)' ($code -eq 0) "(exit $code)"
Check 'it resolved a Python and the gate decided' ($out -match '"permissionDecision"\s*:\s*"deny"') "(output: $out)"
Check 'it cached the interpreter it chose' (Test-Path "$work/cfg/.nsls-hook-python")
if (Test-Path "$work/cfg/.nsls-hook-python") {
    $chosen = (Get-Content "$work/cfg/.nsls-hook-python" -Raw).Trim()
    Write-Host "       chose: $chosen"
    Check 'it did not select the Store alias' ($chosen -notmatch '^python3\|$') "($chosen)"
}

# A second call must not pay for the probe again, and must still decide.
Push-Location "$work/repo"
$out2 = '{"tool_name":"Bash","tool_input":{"command":"git push origin main"},"tool_use_id":"toolu_ci2"}' |
    & bash $launcher gate 2>&1 | Out-String
Pop-Location
Check 'a cached run still decides' ($out2 -match '"deny"')

# An unknown subcommand is silence, never an error.
$out3 = '{}' | & bash $launcher not-a-hook 2>&1 | Out-String
Check 'an unknown hook name exits 0 silently' (($LASTEXITCODE -eq 0) -and ($out3.Trim() -eq '')) "($out3)"

# The failure mode this launcher exists to prevent: an interpreter that exits 0
# having run nothing. The Windows App Execution Aliases for python/python3 do
# exactly that when the Store package is absent, and a probe that accepted exit
# 0 would cache one and silently disable every hook on the machine.
$aliasDir = Join-Path $work 'aliasbin'
New-Item -ItemType Directory -Path $aliasDir -Force | Out-Null
foreach ($n in 'python', 'python3') {
    Set-Content -Path (Join-Path $aliasDir "$n.bat") -Value "@exit /b 0" -Encoding ascii
}
$aliasCfg = Join-Path $work 'aliascfg'
New-Item -ItemType Directory -Path $aliasCfg -Force | Out-Null
$savedPath = $env:PATH
$savedCfg = $env:CLAUDE_CONFIG_DIR
$env:PATH = "$aliasDir;$savedPath"
$env:CLAUDE_CONFIG_DIR = $aliasCfg
Push-Location "$work/repo"
$aliasOut = $payload | & bash $launcher gate 2>&1 | Out-String
$aliasCode = $LASTEXITCODE
Pop-Location
$env:PATH = $savedPath
$env:CLAUDE_CONFIG_DIR = $savedCfg

Check 'with stub aliases ahead on PATH the launcher still exits 0' ($aliasCode -eq 0) "(exit $aliasCode)"
Check 'and it looked past them to a real interpreter' ($aliasOut -match '"deny"') "(output: $aliasOut)"
$aliasCache = Join-Path $aliasCfg '.nsls-hook-python'
if (Test-Path $aliasCache) {
    $aliasChosen = (Get-Content $aliasCache -Raw).Trim()
    Check 'it did not cache a stub alias' ($aliasChosen -notlike "*aliasbin*") "($aliasChosen)"
}

# And if bash itself is missing, nothing here can run - which is what the
# installer's own check is for. Recorded rather than asserted: the runner always
# has bash, so this only reports what the machine actually had.
Write-Host "       bash: $((Get-Command bash -ErrorAction SilentlyContinue).Source)"

Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
if ($failures.Count) { Write-Host "`nFAILED: $($failures -join ', ')"; exit 1 }
Write-Host "`nall checks passed"
