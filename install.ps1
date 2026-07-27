<#
install.ps1 - NSLS Builder Toolkit installer for Windows (full native).

Windows counterpart to install.sh. Bash isn't on a stock Windows box, so this
does the whole install in PowerShell (the Windows hooks are native PowerShell).
It also provisions the runtime prerequisites the toolkit's skills need - Python
3.12 + python-docx, the gws CLI, and Node.js for the signal MCP server - and
checks for (but never installs) the MS Visual C++ x64 runtime that gws depends
on:

  0. Provision prerequisites (Python + python-docx, gws, Node); VC++ check
  1. Clone / update the org plugin
  2. Enable it + register the PowerShell hooks in settings.json
  3. Fire an install event to the Automation Tracker (platform: windows)
  4. Install the superpowers + compound-engineering marketplace plugins
  5. Register bundled MCP servers (stdio directly; http via --transport http,
     deferring token-gated servers to /signal-setup)
  6. Sync slash-command pointer skills
  7. Print next steps (desktop-first)

Self-bootstrapping - safe to run piped straight from the web:
  powershell -NoProfile -ExecutionPolicy Bypass -Command "iwr -useb https://raw.githubusercontent.com/thensls/nsls-builder-toolkit/main/install.ps1 | iex"
It clones the repo itself (Step 1) before needing any file from it, so it never
depends on $PSScriptRoot. Also runs from a local checkout.

Idempotent: re-running updates the clone and no-ops anything already in place.
  -Test   install into a throwaway $HOME\.claude-kit-test (or $env:CLAUDE_CONFIG_DIR)
#>
param([switch]$Test)
$ErrorActionPreference = 'Stop'

# TLS 1.2 for the web calls below (gws zip, VC_redist, tracker ping). Win11
# defaults already negotiate it; this is insurance for older hosts. -bor so a
# host that also speaks TLS 1.3 is never downgraded.
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch {}

# How were we launched? `-File` (the /setup re-provision path, or any wrapper)
# sets $PSCommandPath; a bare `iwr | iex` paste does not. Under -File we hand
# back real exit codes; under a bare paste we must NEVER `exit` -- that closes
# the user's interactive PowerShell window and swallows the summary/error. Each
# stop site therefore does: if ($RunningFromFile) { exit N } else { return }.
# The `return` runs at top-level script scope, which halts the script under
# `iex` without terminating the session (a function-scoped return would not).
$RunningFromFile = [bool]$PSCommandPath

# --- Config dir resolution (mirrors install.sh) ---
if ($env:CLAUDE_CONFIG_DIR) {
    $ConfigDir = $env:CLAUDE_CONFIG_DIR
} elseif ($Test) {
    $ConfigDir = if ($env:CLAUDE_KIT_TEST_DIR) { $env:CLAUDE_KIT_TEST_DIR } else { Join-Path $env:USERPROFILE '.claude-kit-test' }
} else {
    $ConfigDir = Join-Path $env:USERPROFILE '.claude'
}

$LocalDir  = Join-Path $ConfigDir 'local-plugins'
$PluginDir = Join-Path $LocalDir  'nsls-builder-toolkit'
$HooksDir  = Join-Path $PluginDir 'hooks'
$Settings  = Join-Path $ConfigDir 'settings.json'
$SkillsDir = Join-Path $ConfigDir 'skills'
# Repo/branch overridable for fork testing (install a feature branch from a fork
# before it merges to thensls/main). Defaults are production.
$RepoUrl    = if ($env:NSLS_TOOLKIT_REPO) { $env:NSLS_TOOLKIT_REPO } else { 'https://github.com/thensls/nsls-builder-toolkit.git' }
$RepoBranch = if ($env:NSLS_TOOLKIT_BRANCH) { $env:NSLS_TOOLKIT_BRANCH } else { 'main' }
$Tracker   = if ($env:NSLS_TRACKER_URL) { $env:NSLS_TRACKER_URL } else { 'https://web-production-6281e.up.railway.app' }

# --- Helpers ---------------------------------------------------------------
# BOM-less UTF-8 writer. PowerShell 5.1's `Set-Content -Encoding utf8` ALWAYS
# emits a BOM, and a leading BOM breaks `json.load()` for every downstream
# consumer of settings.json (confirmed live). Route every JSON/text write
# through this so nothing we write ever carries a BOM.
$Utf8NoBom = New-Object System.Text.UTF8Encoding $false
function Write-TextNoBom {
    param([string]$Path, [string]$Content)
    [System.IO.File]::WriteAllText($Path, $Content, $Utf8NoBom)
}

# Add a directory to the persistent user PATH (and this session), idempotently.
function Add-ToUserPath {
    param([string]$Dir)
    $cur = [Environment]::GetEnvironmentVariable('Path', 'User'); if (-not $cur) { $cur = '' }
    if (($cur -split ';') -notcontains $Dir) {
        $new = if ($cur) { "$cur;$Dir" } else { $Dir }
        [Environment]::SetEnvironmentVariable('Path', $new, 'User')
    }
    if (($env:Path -split ';') -notcontains $Dir) { $env:Path = "$env:Path;$Dir" }
}

# Run a native command and return combined stdout+stderr as text WITHOUT letting
# stderr trip $ErrorActionPreference='Stop' (native stderr merged via 2>&1 under
# Stop otherwise raises a terminating NativeCommandError - e.g. gws prints a
# harmless "Using keyring backend" line to stderr). Used for --version probes.
function Invoke-Native {
    param([string]$Exe, [string[]]$CmdArgs)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $out = (& $Exe @CmdArgs 2>&1 | Out-String) } catch { $out = '' }
    finally { $ErrorActionPreference = $prev }
    return $out.Trim()
}

Write-Host ""
Write-Host "=== NSLS Builder Toolkit (Windows) ==="
if ($Test) { Write-Host "  (TEST MODE - installing into $ConfigDir; your real .claude is untouched)" }
Write-Host ""

# --- Prerequisites ---
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "Git isn't installed yet - the toolkit needs it (a one-time setup)."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "  Installing Git for you via winget..."
        winget install --id Git.Git -e --source winget --accept-source-agreements --accept-package-agreements
        Write-Host ""
        Write-Host "  [ok] Git installed. Now CLOSE this PowerShell, open a NEW one, and re-run this"
        Write-Host "    installer - a fresh shell is needed so Git is on your PATH."
    } else {
        Write-Host "  Easiest path: if Claude Code offers to install Git, say YES."
        Write-Host "  Otherwise install it from https://git-scm.com/download/win (default options),"
        Write-Host "  then reopen PowerShell and re-run this installer."
    }
    if ($RunningFromFile) { exit 1 } else { return }
}

if ($Test) {
    New-Item -ItemType Directory -Path $ConfigDir -Force | Out-Null
} elseif (-not (Test-Path $ConfigDir)) {
    Write-Host "Error: Claude Code doesn't appear to be set up ($ConfigDir not found)."
    Write-Host "  Install Claude Code first, then re-run this script."
    if ($RunningFromFile) { exit 1 } else { return }
}

# --- Step 0: Provision runtime prerequisites (Python, gws, Node); VC++ check ---
# The Google-Docs skills (/gdoc-build, /gdoc-edit) need Python 3.12 + python-docx
# + gws; the signal MCP server needs Node. Provision what's missing, verify each
# with a real invocation, and DEGRADE to a warning on failure - a failed
# provision must never abort the toolkit install. Every step is idempotent: it
# skips work already done, so re-running is safe.
Write-Host ""
Write-Host "Step 0: Prerequisites (Python, gws, Node)..."
$PrereqReport = @()
$HasWinget = [bool](Get-Command winget -ErrorAction SilentlyContinue)
$PyExe  = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
$GwsDir = Join-Path $env:LOCALAPPDATA 'Programs\gws'
$GwsExe = Join-Path $GwsDir 'gws.exe'

# --- (a) Python 3.12 (winget installs it per-user to the path above) ---
if (-not (Test-Path $PyExe)) {
    if ($HasWinget) {
        Write-Host "  Installing Python 3.12..."
        try { winget install --id Python.Python.3.12 -e --source winget --accept-source-agreements --accept-package-agreements 2>$null | Out-Null } catch {}
    }
}
# python-docx (pip is idempotent - a no-op when already satisfied).
if (Test-Path $PyExe) {
    try { & $PyExe -m pip install --user python-docx --quiet 2>$null | Out-Null } catch {}
}

# --- (b) gws CLI - download the Windows release zip, extract gws.exe, add to PATH ---
# (Per-user OAuth stays manual: `gws auth login`, run from the gdoc skills.)
if (-not (Test-Path $GwsExe) -and -not (Get-Command gws -ErrorAction SilentlyContinue)) {
    Write-Host "  Installing gws (Google Workspace CLI)..."
    try {
        New-Item -ItemType Directory -Path $GwsDir -Force | Out-Null
        $gzip = Join-Path $env:TEMP 'gws-win.zip'
        $gtmp = Join-Path $env:TEMP 'gws-extract'
        $gurl = 'https://github.com/googleworkspace/cli/releases/latest/download/google-workspace-cli-x86_64-pc-windows-msvc.zip'
        Invoke-WebRequest -Uri $gurl -OutFile $gzip -UseBasicParsing
        if (Test-Path $gtmp) { Remove-Item $gtmp -Recurse -Force }
        Expand-Archive -Path $gzip -DestinationPath $gtmp -Force
        $gfound = Get-ChildItem $gtmp -Recurse -Filter 'gws.exe' | Select-Object -First 1
        if ($gfound) { Copy-Item $gfound.FullName $GwsExe -Force }
        Remove-Item $gzip -Force -ErrorAction SilentlyContinue
        Remove-Item $gtmp -Recurse -Force -ErrorAction SilentlyContinue
    } catch {}
}
if (Test-Path $GwsExe) { Add-ToUserPath $GwsDir }

# --- (c) Node.js LTS - the signal MCP server runs on it ---
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    if ($HasWinget) {
        Write-Host "  Installing Node.js LTS..."
        try { winget install --id OpenJS.NodeJS.LTS -e --source winget --accept-source-agreements --accept-package-agreements 2>$null | Out-Null } catch {}
        # winget writes Node onto the machine PATH; refresh this session's PATH
        # so the verify below (and Step 3.5) can see it without a reopen.
        $mp = [Environment]::GetEnvironmentVariable('Path','Machine')
        $up = [Environment]::GetEnvironmentVariable('Path','User')
        $env:Path = (@($mp, $up) | Where-Object { $_ }) -join ';'
    }
}

# --- Verify each provision with a real invocation, and report ---
# Python + python-docx (probe the FULL path, never PATH `python` - on stock
# Win11 `python`/`python3` are Microsoft Store stubs that print a message and
# exit 0, so a naive check passes while nothing works).
if (Test-Path $PyExe) {
    $pyVer  = Invoke-Native $PyExe @('--version')
    $docxOk = (Invoke-Native $PyExe @('-c', 'import docx; print("ok")')) -match 'ok'
    if     ($pyVer -and $docxOk) { $PrereqReport += "  [ok]   Python: $pyVer (python-docx installed)" }
    elseif ($pyVer)              { $PrereqReport += "  [warn] Python: $pyVer but python-docx is missing - run: `"$PyExe`" -m pip install --user python-docx" }
    else                         { $PrereqReport += "  [warn] Python 3.12 present but not runnable - reinstall from https://www.python.org/downloads/ (3.12)" }
} else {
    $PrereqReport += "  [warn] Python 3.12 not installed - /gdoc-build needs it. Install: winget install Python.Python.3.12"
}

# Node
$NodeCmd = Get-Command node -ErrorAction SilentlyContinue
if ($NodeCmd) {
    $nodeVer = Invoke-Native $NodeCmd.Source @('--version')
    if ($nodeVer -match 'v\d') { $PrereqReport += "  [ok]   Node: $nodeVer" }
    else { $PrereqReport += "  [warn] Node present but 'node --version' failed - reopen PowerShell and retry." }
} else {
    $PrereqReport += "  [warn] Node.js not installed - the signal MCP server needs it. Install: winget install OpenJS.NodeJS.LTS"
}

# (d) MS Visual C++ x64 runtime - gws.exe (a Rust/MSVC binary) needs it or it
# exits 0xC0000135 with NO output. A silent install is impossible from a
# non-interactive shell (winget returns 1602; the UAC prompt never reaches the
# screen), so we only DETECT it and, if missing, stage the redist in Downloads
# and print the manual click-path. We never attempt to install it here.
$VcOk = Test-Path (Join-Path $env:SystemRoot 'System32\vcruntime140.dll')
if (-not $VcOk) {
    $vcDl = Join-Path $env:USERPROFILE 'Downloads\VC_redist.x64.exe'
    if (-not (Test-Path $vcDl)) {
        try { Invoke-WebRequest -Uri 'https://aka.ms/vs/17/release/vc_redist.x64.exe' -OutFile $vcDl -UseBasicParsing } catch {}
    }
    if (Test-Path $vcDl) {
        $PrereqReport += "  [ACTION NEEDED] Microsoft VC++ x64 runtime is missing - gws can't run without it."
        $PrereqReport += "                  Open File Explorer -> Downloads -> double-click VC_redist.x64.exe -> click Yes -> Install."
    } else {
        $PrereqReport += "  [ACTION NEEDED] Microsoft VC++ x64 runtime is missing (and the download failed)."
        $PrereqReport += "                  Download & install: https://aka.ms/vs/17/release/vc_redist.x64.exe"
    }
}

# gws (verified last so the message can point back at the VC++ step)
$GwsResolved = if (Test-Path $GwsExe) { $GwsExe } elseif (Get-Command gws -ErrorAction SilentlyContinue) { (Get-Command gws).Source } else { $null }
if ($GwsResolved) {
    $gwsRaw  = Invoke-Native $GwsResolved @('--version')
    $gwsLine = ($gwsRaw -split '\r?\n' | Where-Object { $_ -match 'gws' } | Select-Object -First 1)
    if ($gwsLine) { $PrereqReport += "  [ok]   gws: $($gwsLine.Trim())" }
    elseif (-not $VcOk) { $PrereqReport += "  [warn] gws installed but can't run yet - install the VC++ runtime (above), then it works." }
    else { $PrereqReport += "  [warn] gws installed but not runnable - reopen PowerShell (PATH refresh) and retry: gws --version" }
} else {
    $PrereqReport += "  [warn] gws not installed - /gdoc-build & /gdoc-edit need it (see skills/gws Windows install)."
}

# --- Step 1: Clone / update the org toolkit ---
Write-Host "Step 1: Installing org skills..."
New-Item -ItemType Directory -Path $LocalDir -Force | Out-Null
if (Test-Path (Join-Path $PluginDir '.git')) {
    Write-Host "  Updating existing installation..."
    & git -C $PluginDir fetch origin $RepoBranch --quiet 2>$null
    & git -C $PluginDir reset --hard "origin/$RepoBranch" --quiet 2>$null
} else {
    Write-Host "  Cloning plugin..."
    & git clone --branch $RepoBranch $RepoUrl $PluginDir --quiet
}
Write-Host "  Done."

# --- Find the claude CLI (best-effort; several steps need it) ---
$ClaudeBin = (Get-Command claude -ErrorAction SilentlyContinue).Source
if (-not $ClaudeBin) {
    foreach ($c in @(
        (Join-Path $env:APPDATA 'npm\claude.cmd'),
        (Join-Path $env:APPDATA 'npm\claude.ps1'),
        (Join-Path $env:USERPROFILE '.local\bin\claude.exe'),
        (Join-Path $env:USERPROFILE '.claude\bin\claude.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\claude\claude.exe')
    )) { if ($c -and (Test-Path $c)) { $ClaudeBin = $c; break } }
}
# Desktop app bundles the CLI at %APPDATA%\Claude\claude-code\<version>\claude.exe
# (confirmed on a real Windows box; also try the -vm variant). Not on PATH and
# not in the list above, which is why Steps 3 / 3.5 were silently skipping.
# Pick the highest version.
if (-not $ClaudeBin) {
    foreach ($sub in @('claude-code', 'claude-code-vm')) {
        $glob = Join-Path $env:APPDATA "Claude\$sub\*\claude.exe"
        $cand = Get-ChildItem -Path $glob -ErrorAction SilentlyContinue |
                Sort-Object -Property @{ Expression = { try { [version]$_.Directory.Name } catch { [version]'0.0.0' } } } |
                Select-Object -Last 1
        if ($cand) { $ClaudeBin = $cand.FullName; break }
    }
}

# --- Step 2: Enable plugin + register hooks in settings.json ---
Write-Host ""
Write-Host "Step 2: Enabling plugin and registering hooks..."

# Seed a fresh test config dir with an empty settings.json (BOM-less).
if ($Test -and -not (Test-Path $Settings)) { Write-TextNoBom $Settings '{}' }

$ssCmd = "powershell -NoProfile -ExecutionPolicy Bypass -File `"$HooksDir\session-start.ps1`""
$ptCmd = "powershell -NoProfile -ExecutionPolicy Bypass -File `"$HooksDir\skill-event.ps1`""

if (Test-Path $Settings) {
    $cfg = Get-Content $Settings -Raw | ConvertFrom-Json
} else {
    $cfg = [pscustomobject]@{}
}

# Enable the local plugin (merge; preserve other enabledPlugins).
if (-not ($cfg.PSObject.Properties.Name -contains 'enabledPlugins') -or $null -eq $cfg.enabledPlugins) {
    $cfg | Add-Member -NotePropertyName enabledPlugins -NotePropertyValue ([pscustomobject]@{}) -Force
}
$cfg.enabledPlugins | Add-Member -NotePropertyName 'nsls-builder-toolkit@local' -NotePropertyValue $true -Force

if (-not ($cfg.PSObject.Properties.Name -contains 'hooks') -or $null -eq $cfg.hooks) {
    $cfg | Add-Member -NotePropertyName hooks -NotePropertyValue ([pscustomobject]@{}) -Force
}

# Drop any prior NSLS entries for an event (matched by script filename) so
# re-running never duplicates and stale registrations get replaced; non-NSLS
# hooks are kept. @(...) forces an array (PS unrolls a single match to a scalar).
function Without-Matching {
    param($EventArray, [string]$Needle)
    if ($null -eq $EventArray) { return @() }
    @($EventArray | Where-Object {
        $cmds = (@($_.hooks | ForEach-Object { $_.command })) -join "`n"
        $cmds -notlike "*$Needle*"
    })
}

# SessionStart timeout 90s: must clear git pull + a replayed ping + the live ping
# on a Railway cold start (parity with install.sh, which was killed at 15s).
$ss = @(Without-Matching $cfg.hooks.SessionStart 'session-start.ps1')
$ss += , @{ matcher = 'startup'; hooks = @(@{ type = 'command'; command = $ssCmd; timeout = 90; statusMessage = 'Syncing NSLS toolkit...' }) }

$pt = @(Without-Matching $cfg.hooks.PreToolUse 'skill-event.ps1')
$pt += , @{ matcher = 'Skill'; hooks = @(@{ type = 'command'; command = $ptCmd; timeout = 5; statusMessage = 'Logging skill use so you get NSLS credit (nothing else)...' }) }

$cfg.hooks | Add-Member -NotePropertyName SessionStart -NotePropertyValue $ss -Force
$cfg.hooks | Add-Member -NotePropertyName PreToolUse  -NotePropertyValue $pt -Force

# BOM-less write: PowerShell 5.1 `Set-Content -Encoding utf8` emits a BOM that
# breaks json.load() for every downstream consumer of settings.json.
Write-TextNoBom $Settings ($cfg | ConvertTo-Json -Depth 12)
Write-Host "  Enabled plugin + registered SessionStart / PreToolUse(Skill) hooks."

# --- Step 2.5: Fire an install event to the Automation Tracker (best-effort) ---
$InstallEmail = ""
$EnvFile = Join-Path $LocalDir 'nsls-personal-toolkit\.env'
if (Test-Path $EnvFile) {
    $line = (Get-Content $EnvFile | Where-Object { $_ -match '^BUILDER_EMAIL=' } | Select-Object -First 1)
    if ($line) { $InstallEmail = ($line -replace '^BUILDER_EMAIL=', '').Trim('"') }
}
if (-not $InstallEmail) { $InstallEmail = (& git config user.email 2>$null) }
if (-not $InstallEmail) { $InstallEmail = "$($env:USERNAME)@$($env:COMPUTERNAME)" }

# Persist the EXACT provisional identity used for the install/skill events so
# /setup Step 1.5 can reconcile early events WITHOUT recomputing. On Windows Git
# Bash the old recompute (`${USER:-unknown}@$(hostname -s)`) yields
# `unknown@unknown` and could never match this. Written beside the toolkit (NOT
# .env, which doesn't exist yet); untracked (see .gitignore). Idempotent.
try { Write-TextNoBom (Join-Path $PluginDir '.install-identity') $InstallEmail } catch {}

# gh is fully optional and only feeds github_username. Guard the probe: a MISSING
# `gh` raises a PowerShell-engine error that `2>$null` does NOT suppress, which
# under $ErrorActionPreference='Stop' would kill everything after this point.
$InstallGh = ""
if (Get-Command gh -ErrorAction SilentlyContinue) {
    try { $InstallGh = (& gh api user --jq .login 2>$null) } catch { $InstallGh = "" }
}
try {
    $body = @{ builder_email = $InstallEmail; github_username = $InstallGh;
               platform = 'windows'; install_source = 'cc-builder-kit' } | ConvertTo-Json -Compress
    Invoke-RestMethod -Uri "$Tracker/install-event" -Method Post -Body $body `
        -ContentType 'application/json' -TimeoutSec 40 | Out-Null
} catch { }  # a failed ping never blocks the install

# --- Step 3: Install marketplace plugins ---
Write-Host ""
Write-Host "Step 3: Installing recommended plugins..."
if ($ClaudeBin) {
    function Install-Plugin {
        param([string]$Name, [string]$Spec, [string]$Market)
        $installed = (& $ClaudeBin plugin list 2>$null | Out-String)
        if ($installed -match [regex]::Escape($Name)) { Write-Host "  ${Name}: already installed"; return }
        # A native command's non-zero exit does NOT trip try/catch, so we check
        # $LASTEXITCODE and warn explicitly. Redirect stderr to $null (NOT `2>&1`):
        # merging stderr into the pipeline under $ErrorActionPreference='Stop'
        # raises a terminating NativeCommandError before the warning below runs.
        if ($Market) {
            & $ClaudeBin plugin marketplace add $Market 2>$null | Out-Null
            if ($LASTEXITCODE -ne 0) { Write-Host "  Warning: failed to add $Name marketplace. Retry: claude plugin marketplace add $Market"; return }
        }
        Write-Host "  Installing $Name..."
        & $ClaudeBin plugin install $Spec 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { Write-Host "  Warning: '$Name' install failed. Retry: claude plugin install $Spec" }
    }
    # Migrate compound off the renamed 'every-marketplace' (parity with install.sh).
    if ((& $ClaudeBin plugin marketplace list 2>$null | Out-String) -match 'every-marketplace') {
        Write-Host "  Migrating compound-engineering off 'every-marketplace'..."
        foreach ($scope in 'local','project','user') {
            & $ClaudeBin plugin disable compound-engineering@every-marketplace --scope $scope 2>$null | Out-Null
        }
        & $ClaudeBin plugin uninstall compound-engineering@every-marketplace 2>$null | Out-Null
        & $ClaudeBin plugin uninstall compound-engineering 2>$null | Out-Null
        & $ClaudeBin plugin marketplace remove every-marketplace 2>$null | Out-Null
    }
    # superpowers needs its marketplace registered first - a bare install spec
    # with no marketplace can never resolve on a fresh machine.
    Install-Plugin 'superpowers' 'superpowers@superpowers-marketplace' `
        'https://github.com/obra/superpowers-marketplace.git'
    Install-Plugin 'compound-engineering' 'compound-engineering@compound-engineering-plugin' `
        'https://github.com/EveryInc/compound-engineering-plugin.git'
} else {
    Write-Host "  Could not find the 'claude' CLI. After your next Claude Code session, run /setup."
}

# --- Step 3.5: Register bundled MCP servers (A1 parity: stdio + http) ---
Write-Host ""
Write-Host "Step 3.5: Registering bundled MCP servers..."
$McpJson = Join-Path $PluginDir '.mcp.json'
if ($ClaudeBin -and (Test-Path $McpJson)) {
    function Expand-Vars {
        param([string]$v)
        if ($null -eq $v) { return $v }
        $v = $v -replace [regex]::Escape('${CLAUDE_PLUGIN_ROOT}'), $PluginDir
        [regex]::Replace($v, '\$\{([A-Z0-9_]+)\}', {
            param($m) $val = [Environment]::GetEnvironmentVariable($m.Groups[1].Value)
            if ($val) { $val } else { $m.Value }
        })
    }
    function Has-Unresolved { param([string]$v) $v -match '\$\{[A-Z0-9_]+\}' }

    $servers = (Get-Content $McpJson -Raw | ConvertFrom-Json).mcpServers
    $new = 0; $skipped = @()
    foreach ($p in $servers.PSObject.Properties) {
        $name = $p.Name; $s = $p.Value
        $stype = if ($s.PSObject.Properties.Name -contains 'type') { $s.type } else { 'stdio' }
        if ($stype -eq 'http') {
            # http servers take a URL + auth header, NOT a command. The bearer
            # tokens don't exist on a fresh machine - defer to /signal-setup
            # rather than register a server that 401s silently.
            $url = Expand-Vars $s.url
            $headerArgs = @(); $blocked = (Has-Unresolved $url)
            if ($s.PSObject.Properties.Name -contains 'headers') {
                foreach ($h in $s.headers.PSObject.Properties) {
                    $hv = Expand-Vars $h.Value
                    if (Has-Unresolved $hv) { $blocked = $true }
                    $headerArgs += @('--header', "$($h.Name): $hv")
                }
            }
            if ($blocked) { $skipped += $name; continue }
            $mcpArgs = @('mcp','add','--transport','http',$name,$url,'--scope','user') + $headerArgs
        } else {
            $cmd = Expand-Vars $s.command
            $sargs = @(); if ($s.PSObject.Properties.Name -contains 'args') { $sargs = @($s.args | ForEach-Object { Expand-Vars $_ }) }
            $mcpArgs = @('mcp','add',$name,'--scope','user','--env',"CLAUDE_PLUGIN_ROOT=$PluginDir")
            if ($s.PSObject.Properties.Name -contains 'env') {
                foreach ($e in $s.env.PSObject.Properties) { $mcpArgs += @('--env', "$($e.Name)=$(Expand-Vars $e.Value)") }
            }
            $mcpArgs += @('--', $cmd) + $sargs
        }
        # Capture via Invoke-Native so `claude`'s stderr can't raise a terminating
        # NativeCommandError under $ErrorActionPreference='Stop'.
        $out = Invoke-Native $ClaudeBin $mcpArgs
        if ($out -match 'already exists') { Write-Host "  ${name}: already registered" }
        elseif ($out -match 'Added') { Write-Host "  ${name}: registered (user scope)"; $new++ }
        else { Write-Host "  ${name}: registration failed - $out" }
    }
    Write-Host "  $new MCP server(s) newly registered (restart Claude Code to load)"
    if ($skipped.Count) { Write-Host "  Deferred (needs an access token): $($skipped -join ', ') - run /signal-setup to connect these." }
    # signal is a stdio server that runs on Node. Registration succeeds either
    # way, but without Node the server reports "Failed to connect" on restart -
    # so say what to do rather than leave a bare failed server.
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
        Write-Host "  Note: 'signal' needs Node.js, which isn't installed - install Node, then run /signal-setup."
    }
} else {
    Write-Host "  Skipped - 'claude' CLI or .mcp.json not found."
}

# --- Step 4: Sync slash-command pointer skills ---
Write-Host ""
Write-Host "Step 4: Creating slash-command pointers..."
New-Item -ItemType Directory -Path $SkillsDir -Force | Out-Null
$count = 0
foreach ($skillFolder in Get-ChildItem (Join-Path $PluginDir 'skills') -Directory) {
    $src = Join-Path $skillFolder.FullName 'SKILL.md'
    if (-not (Test-Path $src)) { continue }
    $content = Get-Content $src -Raw -Encoding UTF8
    $fmName = [regex]::Match($content, '(?m)^name:\s*(.+)$')
    if (-not $fmName.Success) { continue }
    $name = $fmName.Groups[1].Value.Trim()
    $destDir = Join-Path $SkillsDir $skillFolder.Name
    $destMd  = Join-Path $destDir 'SKILL.md'
    if (Test-Path $destMd) {
        $existing = Get-Content $destMd -Raw -Encoding UTF8
        if ($existing -notmatch 'local-plugins[\\/]nsls-builder-toolkit') { continue }
    }
    if (-not (Test-Path $destDir)) { New-Item -ItemType Directory -Path $destDir | Out-Null }
    $ptr = "~/.claude/local-plugins/nsls-builder-toolkit/skills/$($skillFolder.Name)/SKILL.md"
    $pointer = @"
---
name: $name
description: >-
  NSLS Builder Toolkit skill: $($skillFolder.Name)
---

Read and follow the full skill at ``$ptr``.
"@
    Write-TextNoBom $destMd ($pointer + "`r`n")
    $count++
}
Write-Host "  $count skill pointers synced"

# --- Done ---
$skillTotal = (Get-ChildItem (Join-Path $PluginDir 'skills') -Directory).Count
if ($PrereqReport.Count) {
    Write-Host ""
    Write-Host "Prerequisite check:"
    $PrereqReport | ForEach-Object { Write-Host $_ }
}
Write-Host ""
Write-Host "==============================="
Write-Host "  NSLS Builder Toolkit installed!"
Write-Host "==============================="
Write-Host ""
if ($ClaudeBin) {
    Write-Host "  ORG SKILLS ($skillTotal skills), plus superpowers + compound-engineering."
} else {
    # Honest banner: without the CLI, Steps 3 and 3.5 were skipped - don't imply
    # a clean install. Name exactly what didn't happen and how to finish it.
    Write-Host "  ORG SKILLS ($skillTotal skills) installed and enabled."
    Write-Host ""
    Write-Host "  NOTE: the 'claude' CLI wasn't found, so these steps were SKIPPED:"
    Write-Host "    - Step 3:   plugins (superpowers, compound-engineering) - NOT installed"
    Write-Host "    - Step 3.5: bundled MCP servers (e.g. signal) - NOT registered"
    Write-Host "  Finish them after your first Claude Code session by running:  /setup"
    Write-Host "  (or re-run this installer from a shell where 'claude' is on PATH)."
}
Write-Host ""
if ($Test) {
    Write-Host "=== TEST INSTALL ==="
    Write-Host "  Everything went into: $ConfigDir (your real .claude was NOT touched)."
    Write-Host "  NOTE: -Test is only usable from the terminal via CLAUDE_CONFIG_DIR; the"
    Write-Host "  desktop app always launches against your real .claude."
    Write-Host "  Reset with:  Remove-Item -Recurse -Force `"$ConfigDir`""
} else {
    Write-Host "=== NEXT STEP ==="
    Write-Host "  1. Restart Claude Code (quit and reopen - a restart loads the MCP servers"
    Write-Host "     and hooks). In the desktop app, click Code (top left) when it reopens."
    Write-Host "  2. Say:  /setup"
    Write-Host "     It connects your tools (Slack, Google Drive, Calendar, Gmail, Fathom -"
    Write-Host "     one at a time, with you) and offers the personal productivity skills."
}
Write-Host ""
# Explicit success exit under -File: native calls above leak their code into
# $LASTEXITCODE, so a good install would otherwise return non-zero and any
# wrapper checking the code (or /setup's re-provision) would treat it as failed.
# Under a bare `iwr | iex` paste there's no wrapper to see a code and `exit`
# would close the user's window, so just return.
if ($RunningFromFile) { exit 0 } else { return }
