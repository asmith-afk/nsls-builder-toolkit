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
#        Windows, freezing toolkits weeks behind). ff-only never merges. ---
foreach ($dir in @($BuilderDir, $PersonalDir)) {
    if (Test-Path $dir) { & git -C $dir pull --ff-only origin main --quiet 2>$null }
}

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
