#!/bin/bash
# NSLS Builder Toolkit — one-command installer
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/thensls/nsls-builder-toolkit/main/install.sh | bash
#   curl -fsSL .../install.sh | bash -s -- --test      # isolated "new user" test install
#
# What this does:
#   1. Installs the NSLS org skills (local plugin)
#   2. Installs superpowers + compound-engineering plugins (marketplace)
#   3. Tells you to run /setup to connect your tools

set -euo pipefail

# --- Config dir resolution -------------------------------------------------
# Claude Code respects CLAUDE_CONFIG_DIR everywhere; so does this installer, so
# everything lands in one place and stays consistent with how Claude Code is
# launched. `-t` / `--test` points that at a throwaway config dir
# ($HOME/.claude-kit-test by default, override with $CLAUDE_KIT_TEST_DIR) so you
# can install exactly like a brand-new user WITHOUT touching your real
# ~/.claude. To reset back to "new user", delete that dir. Launch a test
# install with:  CLAUDE_CONFIG_DIR="$HOME/.claude-kit-test" claude
TEST_MODE=0
for arg in "$@"; do
  case "$arg" in
    -t|--test) TEST_MODE=1 ;;
    *) ;;
  esac
done
if [ "$TEST_MODE" = "1" ] && [ -z "${CLAUDE_CONFIG_DIR:-}" ]; then
  export CLAUDE_CONFIG_DIR="${CLAUDE_KIT_TEST_DIR:-$HOME/.claude-kit-test}"
fi
CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"

PLUGIN_DIR="$CONFIG_DIR/local-plugins/nsls-builder-toolkit"
# Repo/branch are overridable for fork testing (e.g. install a feature branch
# from a fork before it merges to thensls/main). Defaults are production.
REPO_URL="${NSLS_TOOLKIT_REPO:-https://github.com/thensls/nsls-builder-toolkit.git}"
REPO_BRANCH="${NSLS_TOOLKIT_BRANCH:-main}"

echo ""
echo "=== NSLS Builder Toolkit ==="
if [ "$TEST_MODE" = "1" ]; then
  echo "  (TEST MODE — installing into $CONFIG_DIR; your real ~/.claude is untouched)"
fi
echo ""

# --- Prerequisites ---

if ! command -v git &>/dev/null; then
  echo "Error: git is not installed."
  echo "  macOS: Run 'xcode-select --install' first."
  exit 1
fi

if [ "$TEST_MODE" = "1" ]; then
  # Test config dir is fresh — create it so we install as a brand-new user.
  mkdir -p "$CONFIG_DIR"
elif [ ! -d "$CONFIG_DIR" ]; then
  echo "Error: Claude Code doesn't appear to be set up ($CONFIG_DIR not found)."
  echo "  Install Claude Code first, then re-run this script."
  exit 1
fi

# --- Step 1: Install the org toolkit ---

echo "Step 1: Installing org skills..."
mkdir -p "$CONFIG_DIR/local-plugins"

if [ -d "$PLUGIN_DIR" ]; then
  echo "  Updating existing installation..."
  git -C "$PLUGIN_DIR" fetch origin "$REPO_BRANCH" --quiet 2>/dev/null
  git -C "$PLUGIN_DIR" reset --hard "origin/$REPO_BRANCH" --quiet 2>/dev/null
else
  echo "  Cloning plugin..."
  git clone --branch "$REPO_BRANCH" "$REPO_URL" "$PLUGIN_DIR" --quiet
fi
echo "  Done."

# --- Step 2: Enable the local plugin and register the auto-update hook in settings.json ---

SETTINGS="$CONFIG_DIR/settings.json"

# A fresh test config dir has no settings.json yet (a real user already has one
# from Claude Code). Seed an empty object so the merge below runs.
if [ "$TEST_MODE" = "1" ] && [ ! -f "$SETTINGS" ]; then echo '{}' > "$SETTINGS"; fi

# In test mode, seed a +test builder email so skill events land on a separate,
# obviously-test tracker row instead of polluting your real one (skill-event.sh
# would otherwise fall back to git config user.email). The +test address still
# reaches the proxy, so you can verify end-to-end delivery in Airtable.
if [ "$TEST_MODE" = "1" ]; then
  TEST_ENV_DIR="$CONFIG_DIR/local-plugins/nsls-personal-toolkit"
  if [ ! -f "$TEST_ENV_DIR/.env" ]; then
    mkdir -p "$TEST_ENV_DIR"
    REAL_EMAIL=$(git config user.email 2>/dev/null || echo "unknown@test.local")
    echo "BUILDER_EMAIL=${REAL_EMAIL%%@*}+test@${REAL_EMAIL#*@}" > "$TEST_ENV_DIR/.env"
    echo "  Test builder email: ${REAL_EMAIL%%@*}+test@${REAL_EMAIL#*@} (keeps test events off your real tracker row)"
  fi
fi

if [ -f "$SETTINGS" ]; then
  CONFIG_DIR="$CONFIG_DIR" python3 -c "
import json, os, sys
from pathlib import Path

CONFIG_DIR = os.environ['CONFIG_DIR']
SETTINGS_PATH = Path(CONFIG_DIR) / 'settings.json'
_SS = os.path.join(CONFIG_DIR, 'local-plugins/nsls-builder-toolkit/hooks/session-start.py')
HOOK_CMD = 'python3 -c \"exec(open(\'' + _SS + '\').read())\"'
HOOK_ENTRY = {
    'type': 'command',
    'command': HOOK_CMD,
    # Must exceed session-start.py's worst case: git pull (10s) + a replayed
    # ping (35s) + the live ping (35s). At 15s the hook was killed mid-delivery
    # on Railway cold starts (observed live 2026-07-03).
    'timeout': 90,
    'statusMessage': 'Syncing builder toolkit...'
}
MARKER = 'nsls-builder-toolkit/hooks/session-start.py'

# utf-8-sig tolerates a BOM: existing machines may have a BOM'd settings.json
# written by an older PowerShell installer, and plain utf-8 would choke on it.
with open(SETTINGS_PATH, encoding='utf-8-sig') as f: cfg = json.load(f)

# Enable plugin
ep = cfg.setdefault('enabledPlugins', {})
if not ep.get('nsls-builder-toolkit@local'):
    ep['nsls-builder-toolkit@local'] = True
    print('  Enabled nsls-builder-toolkit in settings.json')
else:
    print('  Plugin already enabled')

# Register auto-update hook (idempotent)
hooks = cfg.setdefault('hooks', {})
session_start = hooks.setdefault('SessionStart', [])

# Find or create the startup matcher entry
startup_entry = None
for entry in session_start:
    if entry.get('matcher', '').startswith('startup'):
        startup_entry = entry
        break
if startup_entry is None:
    startup_entry = {'matcher': 'startup', 'hooks': []}
    session_start.insert(0, startup_entry)

hook_list = startup_entry.setdefault('hooks', [])
existing = next((h for h in hook_list if MARKER in h.get('command', '')), None)
if existing is None:
    hook_list.insert(0, HOOK_ENTRY)
    print('  Registered session auto-update hook')
elif existing.get('timeout', 0) < HOOK_ENTRY['timeout']:
    # Repair installs registered when the budget was 15s — that killed the
    # hook mid-ping on cold starts.
    existing['timeout'] = HOOK_ENTRY['timeout']
    print('  Raised session hook timeout to', HOOK_ENTRY['timeout'])
else:
    print('  Auto-update hook already registered')

# Register the skill-event hook (PreToolUse:Skill) globally (idempotent).
# The plugin ships this in hooks/hooks.json, but a *locally enabled* plugin
# does not reliably load bundled hooks (especially on Claude Code desktop) —
# the same reason Step 3.5 has to register bundled MCP servers by hand. So we
# merge it into the global settings.json to make it the primary firing path.
# The server dedupes per builder/skill/day, so this is safe even on surfaces
# that also fire the plugin hook or a pointer file's inline bash.
SKILL_HOOK_CMD = 'bash ' + os.path.join(CONFIG_DIR, 'local-plugins/nsls-builder-toolkit/hooks/skill-event.sh')
SKILL_MARKER = 'nsls-builder-toolkit/hooks/skill-event.sh'
pre_tool_use = hooks.setdefault('PreToolUse', [])
skill_entry = None
for entry in pre_tool_use:
    if entry.get('matcher') == 'Skill':
        skill_entry = entry
        break
if skill_entry is None:
    skill_entry = {'matcher': 'Skill', 'hooks': []}
    pre_tool_use.append(skill_entry)
skill_hooks = skill_entry.setdefault('hooks', [])
# Friendly spinner text — without it, a new user only sees an opaque
# 'run bash skill-event.sh?' and it reads like a hidden script. This says
# plainly what it does: a one-line ping so their skill use is credited.
SKILL_STATUS = 'Logging skill use so you get NSLS credit (nothing else)…'
existing_skill = next((h for h in skill_hooks if SKILL_MARKER in h.get('command', '')), None)
if existing_skill is None:
    skill_hooks.append({'type': 'command', 'command': SKILL_HOOK_CMD,
                        'timeout': 5, 'statusMessage': SKILL_STATUS})
    print('  Registered skill-event hook (PreToolUse:Skill)')
else:
    # Backfill the friendly status message on installs that predate it.
    if existing_skill.get('statusMessage') != SKILL_STATUS:
        existing_skill['statusMessage'] = SKILL_STATUS
        print('  Updated skill-event hook status message')
    else:
        print('  Skill-event hook already registered')

# Pre-authorize the hook command so a new builder is never confronted with a
# bare 'run this script?' prompt for our own tracking ping. The command is a
# fixed, known string (the hook we just registered), so an exact allow rule is
# safe and idempotent.
perms = cfg.setdefault('permissions', {})
allow = perms.setdefault('allow', [])
skill_allow_rule = 'Bash(' + SKILL_HOOK_CMD + ')'
if skill_allow_rule not in allow:
    allow.append(skill_allow_rule)
    print('  Allowlisted the skill-event hook (no more run-script prompt)')

with open(SETTINGS_PATH, 'w', encoding='utf-8') as f: json.dump(cfg, f, indent=2)
" 2>/dev/null || echo "  Note: Could not update settings.json — add the hook manually"
else
  echo "  Note: No settings.json found — the plugin will be enabled on first use"
fi

# --- Step 2.5: Fire an install event to the Automation Tracker ---
#
# Records the install (and auto-registers brand-new builders — the server
# creates their row on first contact, so nobody is invisible until manually
# seeded). Email precedence matches the hooks: personal-toolkit .env →
# git config user.email → $USER@$HOSTNAME. Best-effort: a failed POST never
# blocks the install.

INSTALL_EMAIL=""
INSTALL_ENV_FILE="$CONFIG_DIR/local-plugins/nsls-personal-toolkit/.env"
if [ -f "$INSTALL_ENV_FILE" ]; then
  INSTALL_EMAIL=$(grep "^BUILDER_EMAIL=" "$INSTALL_ENV_FILE" | cut -d= -f2 | tr -d '"')
fi
[ -z "$INSTALL_EMAIL" ] && INSTALL_EMAIL=$(git config user.email 2>/dev/null || true)
[ -z "$INSTALL_EMAIL" ] && INSTALL_EMAIL="${USER:-unknown}@$(hostname -s 2>/dev/null || echo unknown)"

# Persist the EXACT provisional identity used for these early events so /setup
# Step 1.5 can reconcile them WITHOUT recomputing (parity with install.ps1).
# Written beside the toolkit, not in .env (which doesn't exist yet); gitignored.
# Idempotent — overwritten with the current value on every run.
printf '%s' "$INSTALL_EMAIL" > "$PLUGIN_DIR/.install-identity" 2>/dev/null || true

INSTALL_GH=$(gh api user --jq .login 2>/dev/null || true)

INSTALL_EMAIL_SAFE=$(printf '%s' "$INSTALL_EMAIL" | tr -d '"\\')
INSTALL_GH_SAFE=$(printf '%s' "$INSTALL_GH" | tr -d '"\\')
# --max-time must clear a Railway cold start (~35s, per session-start.py's own
# measurement); at 10s the very first install of the day — the one most worth
# recording — was silently dropped.
curl -s --max-time 40 -X POST \
  ${NSLS_TRACKER_URL:-https://web-production-6281e.up.railway.app}/install-event \
  -H 'Content-Type: application/json' \
  -d "{\"builder_email\":\"$INSTALL_EMAIL_SAFE\",\"github_username\":\"$INSTALL_GH_SAFE\",\"platform\":\"mac\",\"install_source\":\"cc-builder-kit\"}" \
  >/dev/null 2>&1 || true

# --- Step 3: Install marketplace plugins ---

echo ""
echo "Step 2: Installing recommended plugins..."

# Find the claude CLI — curl|bash may not inherit the full PATH
CLAUDE_BIN=""
for candidate in \
  "$(command -v claude 2>/dev/null)" \
  "$HOME/.local/bin/claude" \
  "$HOME/.claude/bin/claude" \
  "/usr/local/bin/claude" \
  "/opt/homebrew/bin/claude" \
  "$HOME/.npm-global/bin/claude" \
  "$HOME/.nvm/versions/node/*/bin/claude"; do
  if [ -n "$candidate" ] && [ -x "$candidate" ]; then
    CLAUDE_BIN="$candidate"
    break
  fi
done

# Retry with PATH refresh if not found (native installer may need a moment).
# The `|| true` is load-bearing: a bare VAR="$(failing command)" assignment
# carries the substitution's exit status, and under `set -e` that killed the
# whole install right here on every CLI-less Mac Desktop machine — before the
# desktop-app probe below ever ran (Mac round-2 finding C1).
if [ -z "$CLAUDE_BIN" ]; then
  eval "$(cat ~/.zshrc 2>/dev/null | grep -E 'export PATH|path=')" 2>/dev/null || true
  eval "$(cat ~/.bashrc 2>/dev/null | grep -E 'export PATH|path=')" 2>/dev/null || true
  CLAUDE_BIN="$(command -v claude 2>/dev/null || true)"
fi

# Desktop-app bundled CLI (no separate CLI install). macOS ships it under
# ~/Library/Application Support/Claude/claude-code[-vm]/<version>/claude.
# NOTE: on Apple Silicon that binary is a Linux build that runs inside the app's
# VM and is NOT executable from the host shell (verified: `exec format error`),
# so accept it ONLY if it actually runs. Otherwise fall through to the honest
# "no claude" path rather than selecting a binary that exec-fails on every call.
if [ -z "$CLAUDE_BIN" ]; then
  for base in \
    "$HOME/Library/Application Support/Claude/claude-code" \
    "$HOME/Library/Application Support/Claude/claude-code-vm"; do
    [ -d "$base" ] || continue
    # sort -V => highest version last (falls back gracefully if -V is unsupported).
    cand=$(ls -1d "$base"/*/claude 2>/dev/null | sort -V | tail -1) || true
    if [ -n "$cand" ] && [ -x "$cand" ] && "$cand" --version >/dev/null 2>&1; then
      CLAUDE_BIN="$cand"
      break
    fi
  done
fi

install_plugin() {
  local name="$1"
  local install_cmd="$2"
  local marketplace_url="$3"

  if "$CLAUDE_BIN" plugin list 2>/dev/null | grep -q "$name"; then
    echo "  $name: already installed"
  else
    if [ -n "$marketplace_url" ]; then
      echo "  Adding $name marketplace..."
      "$CLAUDE_BIN" plugin marketplace add "$marketplace_url" 2>&1 | tail -1 || true
    fi
    echo "  Installing $name..."
    "$CLAUDE_BIN" plugin install "$install_cmd" 2>&1 | tail -1 || true
  fi
}

# Every renamed their marketplace from "every-marketplace" to
# "compound-engineering-plugin" (and bumped the plugin to 3.x). Builders who
# installed before the rename are pinned to the stale "every-marketplace"
# registration: install_plugin's name-only grep sees "compound-engineering"
# already in the list and never migrates them. This detects the old
# registration and clears it so the install below pulls the current plugin.
migrate_compound_marketplace() {
  "$CLAUDE_BIN" plugin marketplace list 2>/dev/null | grep -q "every-marketplace" || return 0
  echo "  Migrating compound-engineering off the renamed 'every-marketplace'..."

  # Disable across every scope first so nothing keeps the stale install pinned
  # (a shared project-scope enablement otherwise blocks uninstall).
  for scope in local project user; do
    "$CLAUDE_BIN" plugin disable compound-engineering@every-marketplace --scope "$scope" 2>/dev/null || true
  done

  # Uninstall the old plugin. Different CLI versions accept either the
  # marketplace-qualified spec or the bare manifest name, so try both — each is
  # idempotent and a no-op if the other already worked.
  "$CLAUDE_BIN" plugin uninstall compound-engineering@every-marketplace 2>/dev/null || true
  "$CLAUDE_BIN" plugin uninstall compound-engineering 2>/dev/null || true

  # Removing the marketplace is the reliable cleanup: it cascades and drops any
  # plugin still registered against it, so the migration completes even if the
  # uninstall calls above were no-ops.
  "$CLAUDE_BIN" plugin marketplace remove every-marketplace 2>/dev/null || true

  # Confirm the stale registration is actually gone before we reinstall.
  if "$CLAUDE_BIN" plugin marketplace list 2>/dev/null | grep -q "every-marketplace"; then
    echo "  Warning: could not fully remove 'every-marketplace'. Run manually:"
    echo "    claude plugin uninstall compound-engineering && claude plugin marketplace remove every-marketplace"
  fi
}

if [ -n "$CLAUDE_BIN" ]; then
  # superpowers needs its marketplace registered first — a bare install spec
  # with no marketplace can never resolve on a fresh machine.
  install_plugin "superpowers" "superpowers@superpowers-marketplace" \
    "https://github.com/obra/superpowers-marketplace.git"
  migrate_compound_marketplace
  # Grep key is the bare plugin id (what `plugin list` prints); migrate_* above
  # has already cleared the stale every-marketplace install, so a bare-name
  # match here can only be the current compound-engineering-plugin one.
  install_plugin "compound-engineering" \
    "compound-engineering@compound-engineering-plugin" \
    "https://github.com/EveryInc/compound-engineering-plugin.git"
else
  echo ""
  echo "  Could not find the 'claude' CLI in PATH."
  echo "  After your next Claude Code session, run /setup — it will detect"
  echo "  missing plugins and give you the install commands."
  echo ""
  echo "  Or run these manually:"
  echo "    claude plugin install superpowers"
  echo "    claude plugin marketplace add https://github.com/EveryInc/compound-engineering-plugin.git"
  echo "    claude plugin install compound-engineering@compound-engineering-plugin"
fi

# --- Step 3.5: Register bundled MCP servers (signal, etc.) ---
#
# This plugin is *locally enabled* (enabledPlugins in settings.json), not
# marketplace-installed. Local enable loads skills/commands/hooks, but it does
# NOT register a plugin's bundled .mcp.json MCP servers — only marketplace
# installs do. So the signal_* tools silently never appear.
#
# Fix: register each server from .mcp.json explicitly at user scope, pointing at
# the absolute install path. That path is the same local-plugins dir the
# auto-update hook git-pulls, so server updates still flow through on the next
# session. `claude mcp add` is idempotent — it no-ops if the server already
# exists, so re-running the installer is safe.

echo ""
echo "Step 3: Registering bundled MCP servers..."

if [ -n "$CLAUDE_BIN" ] && [ -f "$PLUGIN_DIR/.mcp.json" ]; then
  # Guard against set -e: a Python exception here (bad CLAUDE_BIN, malformed
  # .mcp.json) must not abort the installer and skip Steps 4-5, which don't
  # depend on MCP registration. Matches the || pattern used in Step 2.
  CLAUDE_BIN="$CLAUDE_BIN" PLUGIN_DIR="$PLUGIN_DIR" python3 - << 'PYEOF' || echo "  Note: MCP registration step failed — run /signal-setup later to register the server"
import json, os, re, subprocess, sys

claude = os.environ["CLAUDE_BIN"]
root = os.environ["PLUGIN_DIR"]

try:
    with open(os.path.join(root, ".mcp.json"), encoding="utf-8") as f:
        servers = json.load(f).get("mcpServers", {})
except Exception as e:
    print(f"  Could not read .mcp.json ({e}) — skipping MCP registration")
    sys.exit(0)

_VAR = re.compile(r"\$\{([A-Z0-9_]+)\}")

def sub(v):
    # The bundled config uses ${CLAUDE_PLUGIN_ROOT}; user-scope config doesn't
    # expand it, so substitute the real absolute path here. Also expand any
    # other ${ENV_VAR} that happens to be set in this shell (e.g. a pre-exported
    # studio token) — anything unset is left as a literal ${VAR} and caught by
    # unresolved() below.
    if not isinstance(v, str):
        return v
    v = v.replace("${CLAUDE_PLUGIN_ROOT}", root)
    return _VAR.sub(lambda m: os.environ.get(m.group(1), m.group(0)), v)

def unresolved(v):
    return isinstance(v, str) and bool(_VAR.search(v))

new = 0
skipped = []
for name, cfg in servers.items():
    stype = cfg.get("type", "stdio")

    if stype == "http":
        # http servers (society-studio, strategy-studio) take a URL + auth
        # header, NOT a command. The old code built `claude mcp add <name> --`
        # with an empty command, which the CLI rejects ("Command is required").
        # Correct form: `claude mcp add --transport http <name> <url> --header`.
        url = sub(cfg.get("url", ""))
        headers = {k: sub(val) for k, val in cfg.get("headers", {}).items()}
        # The bearer tokens (${STUDIO_MCP_TOKEN}, ${STRATEGY_MCP_TOKEN}) don't
        # exist on a fresh machine. Registering with an unexpanded token yields
        # a server that 401s silently — worse than not registering. Defer to
        # /signal-setup, which owns the studio token flow.
        if unresolved(url) or any(unresolved(h) for h in headers.values()):
            skipped.append(name)
            continue
        cmd = [claude, "mcp", "add", "--transport", "http", name, url,
               "--scope", "user"]
        for hk, hv in headers.items():
            cmd += ["--header", f"{hk}: {hv}"]
    else:
        command = sub(cfg.get("command", ""))
        args = [sub(a) for a in cfg.get("args", [])]
        cmd = [claude, "mcp", "add", name, "--scope", "user",
               "--env", f"CLAUDE_PLUGIN_ROOT={root}"]
        for k, val in cfg.get("env", {}).items():
            cmd += ["--env", f"{k}={sub(val)}"]
        cmd += ["--", command] + args

    res = subprocess.run(cmd, capture_output=True, text=True)
    out = (res.stdout + res.stderr).strip()
    if "already exists" in out:
        print(f"  {name}: already registered")
    elif res.returncode == 0 and "Added" in out:
        print(f"  {name}: registered (user scope)")
        new += 1
    else:
        print(f"  {name}: registration failed — {out or 'unknown error'}")

print(f"  {new} MCP server(s) newly registered (restart Claude Code to load)")
if skipped:
    print(f"  Deferred (needs an access token): {', '.join(skipped)} — run /signal-setup to connect these.")
PYEOF
else
  if [ -z "$CLAUDE_BIN" ]; then
    echo "  Skipped — 'claude' CLI not found in PATH. Run /signal-setup later to register."
  else
    echo "  No .mcp.json found — nothing to register"
  fi
fi

# --- Step 3.7: Install the gws CLI (Google Workspace) ---
#
# Two flagship skills — /gdoc-build and /gdoc-edit — shell out to `gws` and are
# dead on arrival without it. (Per-user OAUTH stays manual: `gws auth login`,
# run from those skills' setup.) Idempotent: skips if gws is already on PATH.
# Best-effort — a failed install must never abort the toolkit install.

echo ""
echo "Installing gws (Google Workspace CLI)..."
GWS_OK=0
if command -v gws &>/dev/null; then
  echo "  gws: already installed ($(gws --version 2>/dev/null | head -1))"
elif [ -x "$HOME/.local/bin/gws" ] && "$HOME/.local/bin/gws" --version >/dev/null 2>&1; then
  # A working gws already sits at the install target but ~/.local/bin isn't on
  # PATH, so `command -v` missed it. Do NOT re-download over it — the old code
  # overwrote this binary and then deleted it if the fresh download failed its
  # version check, destroying a working install. Just fix the PATH below.
  echo "  gws: already installed at ~/.local/bin (not on PATH — fixing that below)"
  GWS_OK=1
else
  # Upstream retired their installer script (the old
  # google-workspace-cli-installer.sh URL 404s — every fresh Mac install hit
  # it). Releases now ship per-arch tarballs with .sha256 sidecars: download
  # the right one, verify the checksum, install to ~/.local/bin (no sudo).
  GWS_OK=0
  case "$(uname -s)-$(uname -m)" in
    Darwin-arm64)              GWS_TARGET="aarch64-apple-darwin" ;;
    Darwin-x86_64)             GWS_TARGET="x86_64-apple-darwin" ;;
    Linux-aarch64|Linux-arm64) GWS_TARGET="aarch64-unknown-linux-gnu" ;;
    Linux-x86_64)              GWS_TARGET="x86_64-unknown-linux-gnu" ;;
    *)                         GWS_TARGET="" ;;
  esac
  if [ -n "$GWS_TARGET" ]; then
    GWS_TMP=$(mktemp -d)
    GWS_TAR="google-workspace-cli-$GWS_TARGET.tar.gz"
    GWS_BASE="https://github.com/googleworkspace/cli/releases/latest/download"
    if curl --proto '=https' --tlsv1.2 -fsSL "$GWS_BASE/$GWS_TAR" -o "$GWS_TMP/$GWS_TAR" 2>/dev/null \
      && curl --proto '=https' --tlsv1.2 -fsSL "$GWS_BASE/$GWS_TAR.sha256" -o "$GWS_TMP/$GWS_TAR.sha256" 2>/dev/null; then
      # Tolerate both checksum-file formats ("<hex>" and "<hex>  <name>").
      GWS_EXPECTED=$(awk '{print $1}' "$GWS_TMP/$GWS_TAR.sha256" 2>/dev/null || true)
      if command -v shasum &>/dev/null; then
        GWS_ACTUAL=$(shasum -a 256 "$GWS_TMP/$GWS_TAR" | awk '{print $1}')
      else
        GWS_ACTUAL=$(sha256sum "$GWS_TMP/$GWS_TAR" | awk '{print $1}')
      fi
      if [ -n "$GWS_EXPECTED" ] && [ "$GWS_EXPECTED" = "$GWS_ACTUAL" ]; then
        if tar -xzf "$GWS_TMP/$GWS_TAR" -C "$GWS_TMP" 2>/dev/null; then
          GWS_BIN=$(find "$GWS_TMP" -type f -name gws 2>/dev/null | head -1)
          if [ -n "$GWS_BIN" ]; then
            mkdir -p "$HOME/.local/bin"
            mv "$GWS_BIN" "$HOME/.local/bin/gws" && chmod +x "$HOME/.local/bin/gws" && GWS_OK=1
            # Gate success on the binary actually running — a wrong-libc
            # artifact (e.g. the gnu build on musl/Alpine) exec-fails here,
            # and reporting it "installed" would be a lie.
            if [ "$GWS_OK" = "1" ] && ! "$HOME/.local/bin/gws" --version >/dev/null 2>&1; then
              GWS_OK=0
              echo "  Note: gws downloaded but won't run on this system (libc mismatch?) — removing it."
              rm -f "$HOME/.local/bin/gws"
            fi
          fi
        fi
      else
        echo "  Note: gws checksum verification failed — not installing this download."
      fi
    fi
    rm -rf "$GWS_TMP"
  fi
  if [ "$GWS_OK" = "1" ]; then
    echo "  gws installed to ~/.local/bin ($("$HOME/.local/bin/gws" --version 2>/dev/null | head -1)). Authenticate later with: gws auth login"
  else
    echo "  Note: gws install failed — /gdoc-build and /gdoc-edit will prompt you to install it."
  fi
fi

# PATH fix-up, outside the install branch so it also runs for a gws we FOUND at
# ~/.local/bin rather than downloaded (that's the whole point of the elif above).
if [ "$GWS_OK" = "1" ]; then
  case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *)
      if [ "$TEST_MODE" = "1" ]; then
        echo "  Note: ~/.local/bin isn't on your PATH — add it to use gws (test mode won't touch your shell profile)."
      else
        # Pick the rc file the user's LOGIN SHELL actually reads. Selecting by
        # file-existence order (zshrc, then bashrc, then bash_profile) wrote the
        # export into ~/.bashrc for any zsh user who merely happened to have
        # one — and zsh never sources it, so gws stayed missing while the
        # installer reported PATH configured.
        GWS_SHELL=$(basename "${SHELL:-}" 2>/dev/null || true)
        if [ -z "$GWS_SHELL" ] || [ "$GWS_SHELL" = "sh" ]; then
          case "$(uname -s)" in
            Darwin) GWS_SHELL="zsh" ;;
            *)      GWS_SHELL="bash" ;;
          esac
        fi
        GWS_RC=""
        case "$GWS_SHELL" in
          zsh) GWS_RC="${ZDOTDIR:-$HOME}/.zshrc" ;;
          bash)
            # bash reads .bashrc for interactive non-login shells, but macOS
            # Terminal starts login shells, which read .bash_profile instead.
            if [ -f "$HOME/.bashrc" ]; then GWS_RC="$HOME/.bashrc"
            elif [ -f "$HOME/.bash_profile" ]; then GWS_RC="$HOME/.bash_profile"
            else
              case "$(uname -s)" in
                Darwin) GWS_RC="$HOME/.bash_profile" ;;
                *)      GWS_RC="$HOME/.bashrc" ;;
              esac
            fi
            ;;
          *) GWS_RC="" ;;  # fish/nu/etc: different syntax — instruct, don't corrupt
        esac
        if [ -z "$GWS_RC" ]; then
          echo "  Note: ~/.local/bin isn't on your PATH, and $GWS_SHELL needs a syntax this installer doesn't write."
          echo "        Add ~/.local/bin to your PATH manually to use gws."
        else
          [ -f "$GWS_RC" ] || touch "$GWS_RC"
          # Match the exact export line, not the bare substring: a commented-out
          # export, or an unrelated path that merely contains ".local/bin"
          # (/opt/app/.local/bin), would satisfy a substring grep and we'd skip
          # appending — leaving gws off PATH while reporting it configured.
          if ! grep -qE '^[[:space:]]*export PATH="\$HOME/\.local/bin' "$GWS_RC" 2>/dev/null; then
            { echo ""; echo "# gws (NSLS Builder Toolkit)"; echo 'export PATH="$HOME/.local/bin:$PATH"'; } >> "$GWS_RC"
            echo "  Added ~/.local/bin to PATH in $(basename "$GWS_RC") (takes effect in new terminals)."
          fi
        fi
      fi
      ;;
  esac
fi

# --- Step 3.8: Node.js check (the signal MCP server needs it) ---
# Instruct + degrade (matches this script's style); don't auto-install Node.
echo ""
if command -v node &>/dev/null; then
  echo "Node.js: $(node --version 2>/dev/null) — the signal MCP server can run."
else
  echo "Node.js not found — the 'signal' MCP server needs it to connect."
  if command -v brew &>/dev/null; then
    echo "  Install it:  brew install node   (then restart Claude Code and run /signal-setup)"
  else
    echo "  Install Node LTS from https://nodejs.org, then restart Claude Code and run /signal-setup."
  fi
fi

# --- Step 4: Create slash-command pointer skills ---

echo ""
echo "Step 4: Creating slash-command pointers..."
SKILLS_DIR="$CONFIG_DIR/skills"
mkdir -p "$SKILLS_DIR"

count=0
for skill_dir in "$PLUGIN_DIR/skills"/*/; do
  skill=$(basename "$skill_dir")
  dest="$SKILLS_DIR/$skill"
  src="$skill_dir/SKILL.md"
  [ -f "$src" ] || continue

  # Skip if user already has a custom (non-pointer) skill with this name
  if [ -d "$dest" ] && [ -f "$dest/SKILL.md" ]; then
    grep -q "local-plugins/nsls-builder-toolkit" "$dest/SKILL.md" 2>/dev/null || continue
  fi

  # Extract name from frontmatter
  name=$(grep "^name:" "$src" | head -1 | sed 's/name: *//')
  [ -z "$name" ] && continue

  # Extract description (handles >- multiline format)
  desc=$(python3 -c "
import re, sys
with open('$src', encoding='utf-8') as f: content = f.read()
fm = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
if not fm: sys.exit(0)
m = re.search(r'description:\s*>-?\s*\n((?:[ \t]+.+\n?)*)', fm.group(1))
if m: d = ' '.join(m.group(1).split())
else:
    m = re.search(r'description:[ \t]*(.+)', fm.group(1), re.MULTILINE)
    d = m.group(1).strip() if m else ''
    # A bare block indicator is not a description; and strip YAML quotes off a
    # single-line scalar, decoding double-quoted escapes in ONE left-to-right
    # pass (chained replaces would re-decode their own output). chr(34)/chr(39)
    # /chr(92) are a double-quote, single-quote and backslash: this Python is
    # embedded in a double-quoted shell string, where a literal double-quote
    # would end it early.
    if d in ('>', '>-', '>+', chr(124), chr(124) + '-', chr(124) + '+'):
        d = ''
    else:
        q = d[:1]
        if len(d) > 1 and d[-1:] == q and q in (chr(34), chr(39)):
            inner = d[1:-1]
            if q == chr(34):
                # Includes YAML's four named Unicode escapes (N _ L P);
                # the whitespace collapse folds all four to spaces.
                simple = {'0': chr(0), 'a': chr(7), 'b': chr(8), 't': chr(9),
                          'n': chr(10), 'v': chr(11), 'f': chr(12), 'r': chr(13),
                          'e': chr(27), 'N': chr(133), '_': chr(160),
                          'L': chr(8232), 'P': chr(8233)}
                esc = re.compile(chr(92) * 2 + 'x([0-9a-fA-F]{2})|' + chr(92) * 2
                                 + 'u([0-9a-fA-F]{4})|' + chr(92) * 2
                                 + 'U([0-9a-fA-F]{8})|' + chr(92) * 2 + '(.)')
                def rep(mm):
                    for g in (1, 2, 3):
                        if mm.group(g): return chr(int(mm.group(g), 16))
                    return simple.get(mm.group(4), mm.group(4))
                inner = esc.sub(rep, inner)
            else:
                inner = inner.replace(chr(39) * 2, chr(39))
            d = inner
    # Map decoded control chars (NUL, BEL, ESC) to spaces -- they would make the
    # generated pointer unparseable -- then collapse whitespace, because the
    # caller embeds this as one indented line under description: >-.
    d = re.sub('[' + chr(92) + 'x00-' + chr(92) + 'x08' + chr(92) + 'x0b' + chr(92) + 'x0c' + chr(92) + 'x0e-' + chr(92) + 'x1f' + chr(92) + 'x7f-' + chr(92) + 'x9f]', ' ', d)
    d = ' '.join(d.split())
if d: print(d)
" 2>/dev/null)
  [ -z "$desc" ] && desc="NSLS Builder Toolkit skill: $skill"

  mkdir -p "$dest"
  cat > "$dest/SKILL.md" << POINTER
---
name: $name
description: >-
  $desc
---

Read and follow the full skill at \`$PLUGIN_DIR/skills/$skill/SKILL.md\`.
POINTER
  count=$((count + 1))
done

echo "  $count skill pointers synced"

# --- Step 5: Add 'cc' shortcut ---

echo ""
echo "Step 5: Adding 'cc' shortcut..."

if [ "$TEST_MODE" = "1" ]; then
  # Never touch the real shell profile in test mode — the test install must be
  # fully contained in $CONFIG_DIR and leave no trace outside it.
  echo "  Skipped in test mode (won't modify your shell profile)."
else
  # Detect shell config file
  SHELL_RC=""
  if [ -f "$HOME/.zshrc" ]; then
    SHELL_RC="$HOME/.zshrc"
  elif [ -f "$HOME/.bashrc" ]; then
    SHELL_RC="$HOME/.bashrc"
  elif [ -f "$HOME/.bash_profile" ]; then
    SHELL_RC="$HOME/.bash_profile"
  fi

  if [ -n "$SHELL_RC" ]; then
    if grep -q "alias cc=" "$SHELL_RC" 2>/dev/null; then
      echo "  cc shortcut: already configured"
    else
      echo "" >> "$SHELL_RC"
      echo "# Claude Code shortcut" >> "$SHELL_RC"
      echo "alias cc='claude'" >> "$SHELL_RC"
      echo "  Added 'cc' shortcut to $(basename "$SHELL_RC") — type cc to launch Claude Code"
      echo "  (takes effect in new terminal windows, or run: source $SHELL_RC)"
    fi
  else
    echo "  Could not find shell config (.zshrc, .bashrc, .bash_profile)"
    echo "  Add this manually: alias cc='claude'"
  fi
fi

# --- Done ---

echo ""
echo "==============================="
echo "  NSLS Builder Toolkit installed!"
echo "==============================="
echo ""
echo "What you got:"
echo ""
SKILL_COUNT=$(ls "$PLUGIN_DIR/skills/" 2>/dev/null | wc -l | tr -d ' ')
echo "  ORG SKILLS ($SKILL_COUNT skills for building, tracking, deploying):"
ls "$PLUGIN_DIR/skills/" | sed 's/^/    \//'
echo ""
if [ -n "$CLAUDE_BIN" ]; then
  echo "  PLUGINS:"
  echo "    superpowers              — planning, debugging, verification workflows"
  echo "    compound-engineering     — brainstorm, plan, build, review pipeline"
  echo ""
else
  # Honest banner: without the CLI, plugins + MCP registration were skipped —
  # don't imply they landed. Name what's missing and how to finish.
  echo "  NOTE: the 'claude' CLI wasn't found, so these were SKIPPED:"
  echo "    - plugins (superpowers, compound-engineering) — NOT installed"
  echo "    - bundled MCP servers (e.g. signal) — NOT registered"
  echo "  Finish them after your first Claude Code session by running:  /setup"
  echo ""
fi
if [ "$TEST_MODE" != "1" ]; then
  echo "  SHORTCUT:"
  echo "    cc                       — type 'cc' in any terminal to launch Claude Code"
  echo ""
fi

if [ "$TEST_MODE" = "1" ]; then
  echo "=== TEST INSTALL — how to run and reset ==="
  echo ""
  echo "  Everything went into:  $CONFIG_DIR"
  echo "  Your real ~/.claude was NOT touched."
  echo ""
  echo "  NOTE: --test is terminal-only. The desktop app always launches"
  echo "  against your real ~/.claude and cannot open this isolated config,"
  echo "  so a test install can only be exercised from the terminal as below."
  echo ""
  echo "  1. Launch Claude Code against this test install:"
  echo ""
  echo "       CLAUDE_CONFIG_DIR=\"$CONFIG_DIR\" claude"
  echo ""
  echo "  2. Try it: say  /setup  (or  open day )  as a first-time user would."
  echo ""
  echo "  3. Reset back to a brand-new user (wipes the test install only):"
  echo ""
  echo "       rm -rf \"$CONFIG_DIR\""
  echo ""
  echo "     Then re-run this installer with --test to start clean again."
  echo ""
else
  echo "=== NEXT STEP ==="
  echo ""
  echo "  1. Restart Claude Code"
  echo "       Desktop app: quit and reopen it, then click Code (top left)."
  echo "       Terminal:    open a new window and type  cc"
  echo "     (A restart is required to load the MCP servers and hooks.)"
  echo ""
  echo "  2. Say:  /setup"
  echo "     This connects your tools (Slack, Google Drive, Calendar, Gmail,"
  echo "     Fathom — one at a time, with you) and optionally installs personal"
  echo "     productivity skills (daily planning, weekly reviews, project logging)."
  echo ""
fi
