# collector_bootstrap.ps1 - dot-sourced by session-start.ps1.
# Windows copy of hooks/collector_bootstrap.py; same rules, same marker file.
#
# When the NSLS Claude usage collector is not installed on this PC, launch the
# same one-line installer as the self-serve link, hidden and detached, and
# return at once. Prints nothing: the collector's enrollment DMs the builder
# via Signal, and that DM is the notice.
#
#   1. NSLS_COLLECTOR_OPTOUT=1 (or true/yes) -> never install, write nothing.
#   2. Installed = %LOCALAPPDATA%\nsls-collector\config.json exists, or the
#      collector evidence file is fresh (collector_evidence.ps1).
#   3. Throttle via <CLAUDE_CONFIG_DIR or %USERPROFILE%\.claude>\.nsls-collector\
#      bootstrap.json = {attempted_at, attempts}: one attempt per 24 hours, none
#      after 5 (logged once). Written BEFORE the launch under a short
#      CreateNew lock, so two sessions starting together launch once.
#   4. Installer output -> %LOCALAPPDATA%\nsls-collector\bootstrap.log when that
#      folder exists, else the marker folder. NSLS_COLLECTOR_BASE_URL overrides
#      https://signal.nsls.org (tests); it must be a bare http(s) origin.
#
# Returns a status word (launched, installed, optout, throttled, capped, busy,
# unsupported, error). Callers must discard it: session-start stdout is
# session context. ASCII only, PowerShell 5.1 compatible, no BOM.

function Invoke-CollectorBootstrap {
    param([object]$Now = $null)
    $ErrorActionPreference = 'Stop'
    try {
        $optout = "$env:NSLS_COLLECTOR_OPTOUT".Trim().ToLowerInvariant()
        if (@('1', 'true', 'yes') -contains $optout) { return 'optout' }
        if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { return 'unsupported' }
        $home_ = Join-Path $env:LOCALAPPDATA 'nsls-collector'
        if (Test-Path -LiteralPath (Join-Path $home_ 'config.json') -PathType Leaf) { return 'installed' }
        $evidence = Join-Path $PSScriptRoot 'collector_evidence.ps1'
        if (Test-Path -LiteralPath $evidence) {
            . $evidence
            if (Test-CollectorEvidenceFresh) { return 'installed' }
        }

        $base = "$env:NSLS_COLLECTOR_BASE_URL".Trim()
        if (-not $base) { $base = 'https://signal.nsls.org' }
        if ($base.EndsWith('/')) { $base = $base.Substring(0, $base.Length - 1) }
        if ($base -notmatch '\Ahttps?://[A-Za-z0-9.-]+(:[0-9]{1,5})?\z') { return 'error' }

        $clock = if ($null -ne $Now) { ([DateTime]$Now).ToUniversalTime() } else { [DateTime]::UtcNow }
        $cfg = $env:CLAUDE_CONFIG_DIR
        if ([string]::IsNullOrWhiteSpace($cfg)) { $cfg = Join-Path $env:USERPROFILE '.claude' }
        $dir = Join-Path $cfg '.nsls-collector'
        if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        $marker = Join-Path $dir 'bootstrap.json'
        $lock = Join-Path $dir 'bootstrap.lock'
        $log = if (Test-Path -LiteralPath $home_ -PathType Container) { Join-Path $home_ 'bootstrap.log' } else { Join-Path $dir 'bootstrap.log' }
        $utf8 = New-Object System.Text.UTF8Encoding $false
        $inv = [System.Globalization.CultureInfo]::InvariantCulture
        $stamp = $clock.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", $inv)

        # Lock: CreateNew fails if another session holds it. One older than 10
        # minutes (or dated in the future) is abandoned and taken over once.
        $held = $false
        for ($try = 0; $try -lt 2 -and -not $held; $try++) {
            try {
                ([System.IO.File]::Open($lock, [System.IO.FileMode]::CreateNew)).Dispose()
                $held = $true
            } catch {
                $age = ([DateTime]::UtcNow - (Get-Item -LiteralPath $lock -Force).LastWriteTimeUtc).TotalSeconds
                if ($age -le 600 -and $age -ge -60) { return 'busy' }
                # Take over atomically: rename wins for exactly one session. If
                # what we renamed turns out to be live (another session already
                # replaced the stale lock), put it back and stand down.
                $quarantine = "$lock.stale.$PID." + [guid]::NewGuid().ToString('N')
                try { [System.IO.File]::Move($lock, $quarantine) } catch { continue }
                $qAge = ([DateTime]::UtcNow - (Get-Item -LiteralPath $quarantine -Force).LastWriteTimeUtc).TotalSeconds
                if ($qAge -le 600 -and $qAge -ge -60) {
                    try { [System.IO.File]::Move($quarantine, $lock) } catch { }
                    return 'busy'
                }
                Remove-Item -LiteralPath $quarantine -Force
            }
        }
        if (-not $held) { return 'busy' }

        try {
            $attempts = 0; $last = $null; $gaveUp = $false
            if (Test-Path -LiteralPath $marker -PathType Leaf) {
                $item = Get-Item -LiteralPath $marker -Force
                if ($item.Length -le 4096) {
                    $raw = [System.IO.File]::ReadAllText($marker)
                    $m = [regex]::Match($raw, '"attempts"\s*:\s*([0-9]{1,6})\b')
                    if ($m.Success) { $attempts = [int]$m.Groups[1].Value }
                    $m = [regex]::Match($raw, '"attempted_at"\s*:\s*"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})Z"')
                    if ($m.Success) {
                        try {
                            $g = $m.Groups
                            $last = [DateTime]::new([int]$g[1].Value, [int]$g[2].Value, [int]$g[3].Value,
                                                    [int]$g[4].Value, [int]$g[5].Value, [int]$g[6].Value,
                                                    [DateTimeKind]::Utc)
                        } catch { $last = $null }
                    }
                    $gaveUp = $raw -match '"gave_up"\s*:\s*true'
                }
            }
            if ($attempts -ge 5) {
                if (-not $gaveUp) {
                    [System.IO.File]::AppendAllText($log, "[$stamp] collector bootstrap: $attempts attempts without an install; giving up. Run the installer by hand from signal.nsls.org/me/machines.`r`n", $utf8)
                    $lastStamp = if ($null -ne $last) { $last.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", $inv) } else { $stamp }
                    [System.IO.File]::WriteAllText($marker, ('{"attempted_at":"' + $lastStamp + '","attempts":' + $attempts + ',"gave_up":true}'), $utf8)
                }
                return 'capped'
            }
            if ($null -ne $last) {
                $since = ($clock - $last).TotalHours
                if ($since -ge 0 -and $since -lt 24) { return 'throttled' }
            }
            # Record the attempt BEFORE launching (see collector_bootstrap.py).
            $attempts += 1
            $tmp = "$marker.$PID.tmp"
            [System.IO.File]::WriteAllText($tmp, ('{"attempted_at":"' + $stamp + '","attempts":' + $attempts + '}'), $utf8)
            Move-Item -LiteralPath $tmp -Destination $marker -Force
        } finally {
            Remove-Item -LiteralPath $lock -Force -ErrorAction SilentlyContinue
        }

        [System.IO.File]::AppendAllText($log, "[$stamp] collector bootstrap: attempt $attempts from $base`r`n", $utf8)
        # The self-serve one-liner, verbatim, with its output appended to the log
        # as ASCII (PS 5.1's >> would write UTF-16 into a UTF-8 file).
        $logArg = $log.Replace("'", "''")
        $cmd = "& { iwr -UseBasicParsing $base/api/collector/dist/install.ps1 | iex } *>&1 | Out-File -FilePath '$logArg' -Append -Encoding ascii"
        Start-Process powershell -WindowStyle Hidden -ArgumentList @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', $cmd
        ) | Out-Null
        return 'launched'
    } catch {
        return 'error'
    }
}
