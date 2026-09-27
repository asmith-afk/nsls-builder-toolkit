# session-start.ps1 - Windows SessionStart hook for the NSLS toolkits.
# Windows counterpart to session-start.py (which needs python3 that Windows
# lacks). Does the same three things:
#   1. git pull both toolkits to get latest
#   2. re-sync pointer skills into ~/.claude/skills/
#   3. fire the tracker session ping (detached, non-blocking)
# Fast and silent on failure. Registered in settings.json by install.ps1.
$ErrorActionPreference = 'SilentlyContinue'

$ClaudeDir   = Join-Path $env:USERPROFILE '.claude'
$SkillsDir   = Join-Path $ClaudeDir 'skills'
$LocalDir    = Join-Path $ClaudeDir 'local-plugins'
$BuilderDir  = Join-Path $LocalDir  'nsls-builder-toolkit'
$PersonalDir = Join-Path $LocalDir  'nsls-personal-toolkit'
$Marker      = 'local-plugins\nsls-'

# --- 1. git pull (direct call; the prior Start-Process form failed silently on
#        Windows, freezing toolkits weeks behind). ff-only never merges.
#        Bare pull (no remote/refspec) follows each checkout's configured
#        upstream, so a customized fork (NSLS_PERSONAL_REPO/BRANCH) or a pinned
#        checkout is never fast-forwarded onto a branch it doesn't track.
#        A pull refused by the checkout's own state (divergence, dirty tree) is
#        announced on stdout - SessionStart stdout reaches the model's context -
#        so a frozen toolkit is never silent. Offline failures stay quiet. ---
$env:GIT_TERMINAL_PROMPT = '0'   # credentialed remotes fail fast, never prompt-hang the hook
foreach ($dir in @($BuilderDir, $PersonalDir)) {
    if (-not (Test-Path $dir)) { continue }
    $pullOut = (& git -C $dir pull --ff-only --quiet 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0 -and $pullOut -match 'fast-forward|would be overwritten|unmerged|not concluded') {
        # Two gates, not one - matching session-start.py's `_checkout_blocks_update`.
        # The regex says git's complaint LOOKS checkout-local; this checks whether it
        # IS. Clean, up-to-date checkouts were reported FROZEN every session, sending
        # builders to back up local changes that did not exist.
        $dirty  = (& git -C $dir status --porcelain 2>$null | Out-String).Trim()
        $ahead  = (& git -C $dir rev-list --count '@{u}..HEAD' 2>$null | Out-String).Trim()
        # `@{u}`, not origin/main: a fork checkout tracks something else, and the
        # pull being diagnosed follows the same upstream.
        $commits = 0
        if ($LASTEXITCODE -eq 0 -and $ahead -match '^\d+$') { $commits = [int]$ahead }
        $blocker = $null
        if ($commits -gt 0 -and $dirty) { $blocker = "$commits local commit(s) and uncommitted edits" }
        elseif ($commits -gt 0)         { $blocker = "$commits local commit(s) not in its upstream" }
        elseif ($dirty)                 { $blocker = 'uncommitted local edits' }
        # $null means verified clean and level, or unknowable - either way NOT frozen.
        # Staying quiet costs one session's update; the next pull picks it up.
        if ($blocker) {
            # Which phrase matched, never git's raw text: everything written here
            # reaches the model's context, and git echoes attacker-controlled
            # content (`remote:` lines come verbatim from the server; branch, ref
            # and URL names appear in error text). $matched is one of OUR OWN four
            # literals, so it carries the diagnostic value with none of the surface.
            $matched = @('fast-forward','would be overwritten','unmerged','not concluded') |
                Where-Object { $pullOut -match [regex]::Escape($_) } | Select-Object -First 1
            Write-Output ("WARNING - $(Split-Path $dir -Leaf) could not self-update: the checkout at $dir has $blocker, so automatic updates are FROZEN and this toolkit is going stale. Tell the user at the first natural moment and offer the fix: preserve their local changes on a backup branch, then fast-forward the checkout to its upstream. (Skills in ~/.claude/skills are the right place for personal edits and are unaffected.) git refused with: '$matched'")
        }
    }
}

# --- 1b. personal-toolkit forks: measured against NSLS, not against their own copy ---
# The block above speaks only when a pull FAILS. A fork's pull succeeds - the
# fork genuinely has nothing new - so a builder whose personal toolkit is their
# own GitHub fork was reported healthy every session while nothing NSLS shipped
# ever reached them (196 commits behind on a real machine, 2026-09-09).
# Windows parity with session-start.py's report_personal_fork_drift(): same
# private ref, same stamp, same lock file, same wording. NSLS is fetched by URL, so
# a fork's own remotes - whatever they are named or aimed at - are neither read
# nor changed. Python is not guaranteed on a PC, so this is the ONLY place the
# check runs on Windows - and this script self-updates from NSLS on every
# machine, which is what lets it reach a fork at all (the fork's own hook is a
# file inside the fork, so the fork can never receive it).
$PersonalUpstreamUrl     = 'https://github.com/thensls/nsls-personal-toolkit.git'
$PersonalUpstreamRef     = 'refs/nsls/upstream-main'   # a private ref of our own; this hook creates and touches NO remote
$PersonalUpstreamRefspec = "+refs/heads/main:$PersonalUpstreamRef"
$PersonalUpstreamStamp   = Join-Path $ClaudeDir '.nsls-personal-upstream-check'
$PersonalUpstreamLock    = Join-Path $ClaudeDir '.nsls-personal-upstream-check.flock'
$PersonalLegacyLock      = Join-Path $ClaudeDir '.nsls-personal-upstream-check.lock'   # the previous protocol's file: shadow-claimed (empty) while ours is held
$PersonalCheckEveryH     = 12

function Test-CanonicalOrigin {
    param([string]$Url)
    # True only for NSLS's own repository on github.com, in any spelling git
    # accepts (https, ssh://, scp-like; user info, port, www., trailing slash,
    # .git, any case). Host and path are compared exactly - a substring test
    # called a mirror on another host, or a longer-named repo under the same
    # owner, canonical, and skipped the check for it. Schemes are an allow-list.
    $u = if ($Url) { $Url.Trim() } else { '' }
    $hostName = $null
    $repoPath = $null
    $m = [regex]::Match($u, '^([A-Za-z][A-Za-z0-9+.-]*)://(?:[^@/]*@)?([^/:]+)(?::\d+)?/(.*)$')
    if ($m.Success) {
        if (@('https', 'http', 'ssh', 'git', 'git+ssh', 'ssh+git') -notcontains $m.Groups[1].Value.ToLowerInvariant()) { return $false }
        $hostName = $m.Groups[2].Value
        $repoPath = $m.Groups[3].Value
    } else {
        $m = [regex]::Match($u, '^(?:[^@/:]+@)?([^/:]+):(?!//)/?(.*)$')
        if ($m.Success) {
            $hostName = $m.Groups[1].Value
            $repoPath = $m.Groups[2].Value
        }
    }
    if ($null -eq $hostName) { return $false }
    if ($hostName -match '^www\.') { $hostName = $hostName.Substring(4) }
    $repoPath = $repoPath.Trim('/')
    if ($repoPath -match '\.git$') { $repoPath = $repoPath.Substring(0, $repoPath.Length - 4) }
    # -eq and -match are case-insensitive in PowerShell, which is what GitHub names need.
    return (($hostName -eq 'github.com') -and ($repoPath.TrimEnd('/') -eq 'thensls/nsls-personal-toolkit'))
}

function Invoke-GitBounded {
    param([string]$Dir, [string[]]$GitArgs, [int]$TimeoutMs = 3000)
    # EVERY git call in this block runs through here: a hard time limit (the
    # direct `& git` form has none, and a fetch can hang for a minute on a captive
    # portal; a rev-list walk has no natural bound either), the whole process
    # TREE killed on timeout (git's HTTPS remote helper is a child that
    # Process.Kill() alone leaves running the fetch after we release the lock),
    # and output captured only for our own parsing. Everything this hook prints
    # is the model's context and git echoes server-controlled text, so nothing
    # captured here is ever surfaced - only our literals and a verified integer.
    # Returns @{ Code = exit code (-1 on timeout or failure to start); Out = stdout }.
    $result = @{ Code = -1; Out = '' }
    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = 'git'
        $parts = @('-C', $Dir) + $GitArgs
        $psi.Arguments = (($parts | ForEach-Object { if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ } }) -join ' ')
        $psi.UseShellExecute = $false
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.CreateNoWindow = $true
        $psi.EnvironmentVariables['GIT_TERMINAL_PROMPT'] = '0'
        $p = [System.Diagnostics.Process]::Start($psi)
        # Drain both pipes while waiting - a chatty child deadlocks on a full pipe
        # otherwise. stdout is kept (for the count); stderr is discarded.
        $outTask = $p.StandardOutput.ReadToEndAsync()
        $p.BeginErrorReadLine()
        if (-not $p.WaitForExit($TimeoutMs)) {
            try { & taskkill /T /F /PID $p.Id 2>$null | Out-Null } catch { }
            try { $p.WaitForExit(3000) | Out-Null } catch { }
            return $result
        }
        $p.WaitForExit()   # lets the async readers finish after a timed wait
        $result.Code = $p.ExitCode
        $result.Out = $outTask.Result.Trim()
        return $result
    } catch {
        return $result
    }
}

function Get-PullSourceUrl {
    param([string]$Dir)
    # The remote this checkout's branch actually pulls from - the same source a
    # bare `git pull` uses - falling back to origin. A canonical origin beside a
    # branch that tracks a personal fork is a fork in every way that matters; a
    # fork whose remote is not called origin is still a fork. Empty when neither
    # resolves. Read from config rather than by splitting the tracking ref on
    # "/": a remote may itself be named with a slash (personal/fork).
    $remote = 'origin'
    $r = Invoke-GitBounded -Dir $Dir -GitArgs @('symbolic-ref', '--short', 'HEAD')   # fails when detached
    $branch = if ($r.Code -eq 0) { $r.Out } else { '' }
    $seen = @()
    while ($branch -and ($seen -cnotcontains $branch)) {
        $seen += $branch   # stop only on a cycle, not at an arbitrary hop count
        # $($branch) - a bare "$branch.remote" would read .remote as a property.
        $r = Invoke-GitBounded -Dir $Dir -GitArgs @('config', '--get', "branch.$($branch).remote")
        if ($r.Code -ne 0 -or -not $r.Out) { break }
        if ($r.Out -ne '.') { $remote = $r.Out; break }
        # '.' means the branch pulls from a LOCAL branch, not a remote. Follow that
        # chain to the remote it ends at, rather than pretending it is origin - but
        # never give up on the checkout: its remote of record is still the honest
        # fallback, and silence on a fork is the failure here.
        $r = Invoke-GitBounded -Dir $Dir -GitArgs @('config', '--get', "branch.$($branch).merge")
        if ($r.Code -ne 0 -or $r.Out -notlike 'refs/heads/*') { break }
        $branch = $r.Out.Substring(11)
    }
    $r = Invoke-GitBounded -Dir $Dir -GitArgs @('remote', 'get-url', $remote)
    if (($r.Code -ne 0 -or -not $r.Out) -and $remote -ne 'origin') {
        $r = Invoke-GitBounded -Dir $Dir -GitArgs @('remote', 'get-url', 'origin')
    }
    if ($r.Code -ne 0) { return '' }
    return $r.Out
}

function Test-StampFresh {
    # Bounded at BOTH ends: a stamp dated in the future (clock skew, a restored
    # backup) would otherwise read as fresh forever.
    $ageH = $null
    try {
        if (Test-Path $PersonalUpstreamStamp) {
            $ageH = ((Get-Date) - (Get-Item $PersonalUpstreamStamp).LastWriteTime).TotalHours
        }
    } catch { }
    return ($null -ne $ageH -and $ageH -ge 0 -and $ageH -lt $PersonalCheckEveryH)
}

function Claim-Lock {
    param([string]$Path, [string]$LegacyPath = '')
    # An exclusive OS-level open on a file that is never deleted: the open handle
    # when we hold the lock, $null when another hook does. The stamp is only a
    # throttle - two hooks can both read it as stale before either writes it - so
    # this is the claim. FileShare.None makes every other open of the file fail
    # while ours is live (session-start.py's copy of this check, when a PC runs
    # it, opens this same file with the default share mode, so whichever opens
    # first holds it), and Windows drops the handle the instant the process
    # exits - so a hook that dies mid-check leaves nothing to reclaim: no stale
    # threshold, no token, no move-aside, and no step at which a third hook could
    # be handed a lock still in use.
    try {
        $fs = [System.IO.File]::Open($Path, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
    } catch {
        return $null
    }
    # Belt and braces: FileShare.None already refuses any other open handle, and
    # that is what excludes the Python copy (its descriptor stays open for as long
    # as it holds; proven on windows-latest, "PS: refused while Python holds").
    # Take the same one-byte lock Python takes as well, so both languages hold
    # one visible primitive; if even that is refused, someone else holds it.
    try {
        $fs.Lock(0, 1)
    } catch {
        $fs.Dispose()
        return $null
    }
    # A machine may briefly run one old copy of this check beside one new. The old
    # copy claims by creating ITS OWN lock file exclusively with a token inside,
    # and treats it as stale after 120 s. So, while holding the lock above, also
    # claim under that protocol: create the old file exclusively and leave it
    # EMPTY. An old hook arriving now sees a live lock and yields; an old hook
    # already mid-check (a fresh, non-empty token) makes this one yield. Only ever
    # done while holding $fs, so no two new hooks touch the old file at once. Our
    # empty shadow is never deleted by us - old tokens are never empty, so a later
    # new hook does not mistake it for a live old hook, and an old hook's release
    # only deletes a file that still carries its own token.
    if ($LegacyPath) {
        foreach ($attempt in 1, 2) {
            try {
                $shadow = [System.IO.File]::Open($LegacyPath, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
                $shadow.Dispose()
                break
            } catch {
                $old = $null
                try { $old = Get-Item -LiteralPath $LegacyPath -ErrorAction Stop } catch { }
                if ($null -eq $old) { break }                        # cannot create or read it: the stamp arbitrates
                $ageS = ((Get-Date) - $old.LastWriteTime).TotalSeconds
                if ($old.Length -gt 0 -and $ageS -ge 0 -and $ageS -le 120) {
                    $fs.Dispose()
                    return $null                                    # an old hook is mid-check right now
                }
                if ($attempt -eq 2) { break }
                try { [System.IO.File]::Delete($LegacyPath) } catch { break }   # a dead old hook's token, or our own empty shadow
            }
        }
    }
    return $fs
}

function Release-Lock {
    param($Handle)
    # Closing the handle drops the lock; the file itself stays.
    try { if ($null -ne $Handle) { $Handle.Dispose() } } catch { }
}

function Report-PersonalForkDrift {
    param([string]$Dir)
    if (-not (Test-Path (Join-Path $Dir '.git'))) { return }
    $url = Get-PullSourceUrl -Dir $Dir
    if (-not $url) { return }                        # nothing to measure against
    if (Test-CanonicalOrigin $url) { return }        # NSLS's own repo: the freeze check above owns it
    if (Test-StampFresh) { return }
    $lock = Claim-Lock -Path $PersonalUpstreamLock -LegacyPath $PersonalLegacyLock
    if ($null -eq $lock) { return }                  # another hook is mid-check this very second; it will speak
    try {
        if (Test-StampFresh) { return }              # it finished between our two looks
        try { [System.IO.File]::WriteAllText($PersonalUpstreamStamp, '') } catch { }
        # Bounded, best-effort: offline, blocked or slow all mean "say nothing this
        # session". '+' so our own ref always follows NSLS's main, even across a
        # force-push there; refs/heads/main so a tag called main cannot stand in;
        # --no-tags so NSLS's tags are not written into the builder's checkout.
        $r = Invoke-GitBounded -Dir $Dir -GitArgs @('fetch', '--quiet', '--no-tags', $PersonalUpstreamUrl, $PersonalUpstreamRefspec) -TimeoutMs 8000
        if ($r.Code -ne 0) { return }
        # A fork shares history with NSLS. A repository that does not - some
        # unrelated project sitting at this path - is not a fork, and telling
        # Claude to merge NSLS's main into it would be an instruction to merge two
        # unrelated histories. Nothing to say about such a checkout.
        $r = Invoke-GitBounded -Dir $Dir -GitArgs @('merge-base', 'HEAD', $PersonalUpstreamRef)
        if ($r.Code -ne 0) { return }
        $r = Invoke-GitBounded -Dir $Dir -GitArgs @('rev-list', '--count', "HEAD..$PersonalUpstreamRef")
        if ($r.Code -ne 0 -or $r.Out -notmatch '^\d+$') { return }
        $behind = [int]$r.Out
        if ($behind -eq 0) { return }
        # The path is text someone else can choose: printable ASCII only, bounded.
        $safeDir = ($Dir -replace '[^\x20-\x7e]', '?')
        if ($safeDir.Length -gt 200) { $safeDir = $safeDir.Substring(0, 200) }
        # Same prefix and wording as the personal toolkit's own hook, so Claude
        # sees one identical line whichever of the two spoke first.
        Write-Output ("[NSLS Personal Toolkit] This builder's toolkit is their OWN FORK and is $behind commit(s) behind NSLS - nothing shipped upstream has reached them, and their auto-update never will, because it follows their fork. Tell them in ONE plain sentence at the start of your first reply - e.g. `"Your toolkit is your own copy, so NSLS updates haven't been reaching you - want me to catch it up?`" - and if they agree: run /update-personal-productivity if this machine has it; otherwise, in $safeDir, merge $PersonalUpstreamRef (NSLS's main, fetched from $PersonalUpstreamUrl moments ago) yourself, preserving their own commits and setting aside any uncommitted edits first, then read and follow skills/update-personal-productivity/SKILL.md from the freshly merged checkout to walk them through what's new (the slash command itself appears after their next restart). NEVER hand them a git command.")
    } finally {
        Release-Lock -Handle $lock
    }
}
Report-PersonalForkDrift -Dir $PersonalDir

function Parse-Frontmatter {
    param([string]$Path)
    $content = Get-Content $Path -Raw -Encoding UTF8
    $m = [regex]::Match($content, '^---\r?\n(.*?)\r?\n---', 'Singleline')
    if (-not $m.Success) { return @{ name = $null; desc = $null } }
    $block = $m.Groups[1].Value
    $nameMatch = [regex]::Match($block, '^name:\s*(.+)$', 'Multiline')
    $name = if ($nameMatch.Success) { $nameMatch.Groups[1].Value.Trim() } else { $null }
    # '*' not '+': an empty folded block still belongs to the folded branch.
    # With '+' it fell through to the plain branch, which then captured the
    # literal '>-' and used it as the description.
    $folded = [regex]::Match($block, 'description:\s*>-?\s*\r?\n((?:[ \t]+.+\r?\n?)*)')
    if ($folded.Success) {
        $lines = $folded.Groups[1].Value -split "\r?\n" | ForEach-Object { $_.Trim() } | Where-Object { $_ }
        $d = ($lines -join ' ')
    } else {
        # Single-line scalar: reject a bare block indicator, then strip YAML
        # quotes and decode double-quoted escapes in ONE left-to-right pass.
        # Parity with the .py / .sh extractors.
        $plain = [regex]::Match($block, '^description:[ \t]*(.+)$', 'Multiline')
        $d = if ($plain.Success) { $plain.Groups[1].Value.Trim() } else { '' }
        if (@('>', '>-', '>+', '|', '|-', '|+') -contains $d) {
            $d = ''
        } elseif ($d.Length -gt 1) {
            $q = $d[0]
            if ($d[$d.Length - 1] -eq $q -and ($q -eq '"' -or $q -eq "'")) {
                $inner = $d.Substring(1, $d.Length - 2)
                if ($q -eq '"') {
                    $inner = [regex]::Replace($inner,
                        '\\x([0-9a-fA-F]{2})|\\u([0-9a-fA-F]{4})|\\U([0-9a-fA-F]{8})|\\(.)',
                        {
                            param($mm)
                            foreach ($g in 1, 2, 3) {
                                if ($mm.Groups[$g].Success) {
                                    # ConvertFromUtf32, not [char]: a valid \U
                                    # escape above U+FFFF (e.g. \U0001F600)
                                    # overflows System.Char and would throw,
                                    # killing the whole pointer sync. This
                                    # returns the surrogate pair instead.
                                    return [char]::ConvertFromUtf32([Convert]::ToInt32($mm.Groups[$g].Value, 16))
                                }
                            }
                            # switch -CaseSensitive, NOT a hashtable: PowerShell
                            # hashtable keys are case-INsensitive, so 'n' and 'N'
                            # collide and @{...} fails to parse outright. YAML
                            # needs both (\n = newline, \N = next-line), and the
                            # same applies to the \L / \P pair.
                            # [char] codes, not backtick escapes: `e and `v don't
                            # exist in Windows PowerShell 5.1, which runs this.
                            $c = $mm.Groups[4].Value
                            switch -CaseSensitive ($c) {
                                '0' { return [char]0 }
                                'a' { return [char]7 }
                                'b' { return [char]8 }
                                't' { return [char]9 }
                                'n' { return [char]10 }
                                'v' { return [char]11 }
                                'f' { return [char]12 }
                                'r' { return [char]13 }
                                'e' { return [char]27 }
                                'N' { return [char]133 }
                                '_' { return [char]160 }
                                'L' { return [char]8232 }
                                'P' { return [char]8233 }
                            }
                            # Anything else (\" \\ \/ \space) stands for itself.
                            return $c
                        })
                } else {
                    $inner = $inner.Replace("''", "'")
                }
                $d = $inner
            }
        }
    }
    # Map decoded control chars (NUL, BEL, ESC) to spaces - they would make the
    # generated pointer unparseable - then collapse whitespace, because the
    # caller embeds this as one indented line under description: >-.
    # Blank means "no description" so the caller's default stands.
    $d = [regex]::Replace($d, '[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', ' ')
    $d = ($d -split '\s+' | Where-Object { $_ }) -join ' '
    $desc = if ([string]::IsNullOrWhiteSpace($d)) { $null } else { $d }
    return @{ name = $name; desc = $desc }
}

function Sync-Pointers {
    param([string]$PluginDir)
    $skillsRoot = Join-Path $PluginDir 'skills'
    if (-not (Test-Path $skillsRoot)) { return 0 }
    $count = 0
    $pluginName = [System.IO.Path]::GetFileName($PluginDir)
    foreach ($skillFolder in Get-ChildItem $skillsRoot -Directory) {
        $src = Join-Path $skillFolder.FullName 'SKILL.md'
        if (-not (Test-Path $src)) { continue }
        $fm = Parse-Frontmatter -Path $src
        if (-not $fm.name) { continue }
        $desc = if ($fm.desc) { $fm.desc } else { "NSLS toolkit skill: $($skillFolder.Name)" }
        $destDir = Join-Path $SkillsDir $skillFolder.Name
        $destMd  = Join-Path $destDir   'SKILL.md'
        if (Test-Path $destMd) {
            $existing = Get-Content $destMd -Raw -Encoding UTF8
            if ($existing -notmatch [regex]::Escape($Marker)) { continue }
        }
        if (-not (Test-Path $destDir)) { New-Item -ItemType Directory -Path $destDir | Out-Null }
        $pointerPath = "~/.claude/local-plugins/$pluginName/skills/$($skillFolder.Name)/SKILL.md"
        $pointer = @"
---
name: $($fm.name)
description: >-
  $desc
---

Read and follow the full skill at ``$pointerPath``.
"@
        # BOM-less write (matches install.ps1): PS 5.1 `Set-Content -Encoding
        # utf8` prepends a BOM. Harmless-looking on a pointer, but this hook runs
        # every session, so a BOM here would silently re-introduce one on files
        # install.ps1 just wrote clean.
        [System.IO.File]::WriteAllText($destMd, ($pointer + "`r`n"), (New-Object System.Text.UTF8Encoding $false))
        $count++
    }
    return $count
}

# --- 2. sync pointer skills ---
if (-not (Test-Path $SkillsDir)) { New-Item -ItemType Directory -Path $SkillsDir -Force | Out-Null }
$null = Sync-Pointers -PluginDir $BuilderDir
$null = Sync-Pointers -PluginDir $PersonalDir

# --- 2b. surface announcements stashed by the previous detached ping ---
# session-ping.ps1 runs detached, so it can't print to session context itself;
# it dismisses announcements and writes their text here. We read + print it
# synchronously (this hook's stdout IS session context on every surface),
# wrapped in the same directive prefix session-start.py uses so it shows on the
# desktop app too, then delete the file. One session's lag, but it surfaces.
$AnnounceFile = if (Test-Path $BuilderDir) {
    Join-Path $BuilderDir '.pending-announcements'
} else {
    Join-Path $ClaudeDir '.pending-announcements'
}
if (Test-Path $AnnounceFile) {
    $block = (Get-Content $AnnounceFile -Raw -Encoding UTF8).Trim()
    Remove-Item $AnnounceFile -Force -ErrorAction SilentlyContinue
    if ($block) {
        Write-Output "[NSLS Builder Toolkit - surface the following to the user verbatim at the start of your first reply, then proceed with their request:]`n`n$block"
    }
}

# --- 3. session ping (detached, non-blocking) ---
# The proxy is idempotent, so repeated pings never duplicate. Detached so its
# cold-start latency never delays session start; output -> nsls-session-ping.log.
$pingScript = Join-Path $PSScriptRoot 'session-ping.ps1'
if (Test-Path $pingScript) {
    Start-Process powershell -WindowStyle Hidden -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $pingScript
    ) | Out-Null
}

# --- 3b. NSLS Claude usage collector bootstrap (detached, silent) ---
# If the collector is not installed, launch the self-serve installer hidden in
# the background, at most once a day and five times ever. Silent by design:
# enrollment DMs the builder via Signal. Opt out: NSLS_COLLECTOR_OPTOUT=1.
# Output discarded - this hook's stdout is session context. See
# collector_bootstrap.ps1.
$bootstrapScript = Join-Path $PSScriptRoot 'collector_bootstrap.ps1'
if (Test-Path $bootstrapScript) {
    try {
        . $bootstrapScript
        $null = Invoke-CollectorBootstrap
    } catch { }
}

# --- 4. Builder Guardrails context + plugin freshness ---
# Windows parity with session-start.py's emit_guardrails_context(). Without
# this, Windows builders got the four hard gates (the hook is registered for
# them) but none of the conversational half - tiers, escalation triggers, the
# voice guide, remembered declines - which is the same
# configuration-present-but-not-loaded failure this project has hit three times.
# Delegated to the Python emitter rather than reimplemented: one copy of the
# section-extraction and path-resolution logic, not two that can drift.
# The same Python entry point also runs ensure_plugin_fresh(): the daily
# `claude plugin update` plus the commit-level drift check and self-heal. The
# plugin's own hooks.json hook invokes `python3`, which on stock Windows is a
# Store alias that exits without running, so THIS script is the only place the
# freshness step reliably fires on Windows. It is a no-op unless the plugin is
# installed and enabled; clone-only machines stay fresh via the git pull above.
# Interpreter: the stock Windows `python3` is a Store alias that exits without
# running anything, so falling back to it emitted nothing at all - worse than
# failing loudly. Prefer the launcher, then the toolkit-provisioned runtime,
# and give up quietly only when there is genuinely no Python.
$pyExe = $null
if (Get-Command py -ErrorAction SilentlyContinue) { $pyExe = 'py' }
elseif (Test-Path (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe')) {
    $pyExe = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
}
elseif (Get-Command python -ErrorAction SilentlyContinue) { $pyExe = 'python' }

$startPy = Join-Path $PSScriptRoot 'session-start.py'
if ($pyExe -and (Test-Path $startPy)) {
    # The path goes in as an ARGUMENT, never interpolated into Python source:
    # a Windows profile containing an apostrophe (O'Brien) made the inline
    # program a SyntaxError, and the empty catch swallowed it - the guardrail
    # context just silently vanished for that person.
    $emitter = @'
import runpy, sys
runpy.run_path(sys.argv[1], run_name="__guardrails__")
'@
    try {
        if ($pyExe -eq 'py') { & $pyExe -3 -c $emitter $startPy 2>$null }
        else { & $pyExe -c $emitter $startPy 2>$null }
    } catch { }
}
