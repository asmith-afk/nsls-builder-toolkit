#!/usr/bin/env python3
"""
migrate_to_plugin.py — self-migration from the shim install to a real plugin.

Executed by session-start.py on every session start (from the freshly pulled
clone, so fixes to this file take effect one session after they land on main).
Two stages, at most one per session:

Stage A — plugin not installed yet:
    Register this repo as a private marketplace and install the plugin.
    Nothing else changes: the running session keeps using the shims, and the
    plugin loads at the NEXT session start. Anyone with git access to the repo
    can install; the marketplace is not public.

Stage B — plugin installed, shims still present (mac/linux only):
    Remove exactly the shims the installer created, now that the plugin
    provides the same components:
      * pointer stubs in ~/.claude/skills whose SKILL.md points at
        local-plugins/nsls-builder-toolkit/skills/ — personal-toolkit stubs
        and user-authored skills are never touched (their SKILL.md lacks that
        marker; see the /skills/ discriminator below),
      * settings.json hook entries whose command references
        nsls-builder-toolkit/hooks/ (session-start + skill-event),
      * the user-scope `signal` MCP registration if it points into this repo
        (the plugin registers signal at plugin scope).

Safety properties:
  * fail-open — every step is wrapped; any failure leaves the machine on the
    still-working shim path and retries next session
  * idempotent — each stage checks live state, never history
  * serialized — a lockfile keeps the settings-shim copy and the plugin-hook
    copy of session-start.py from migrating concurrently during the one
    overlap session
  * announced — every state change prints a visible line (silent failure is
    the recurring bug in this pipeline)
  * reversible — settings.json is backed up to settings.json.pre-plugin-migration
    before its first edit
  * escape hatch — set NSLS_NO_PLUGIN_MIGRATION=1 to freeze migration
  * Windows — stage A runs (agents start working); stage B is deferred until
    the plugin's hooks.json has verified Windows parity, so Windows builders
    stay on shims and lose nothing
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

_CONFIG_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))
_PLUGIN_DIR = _CONFIG_DIR / "local-plugins" / "nsls-builder-toolkit"
_SKILLS_DIR = _CONFIG_DIR / "skills"
_SETTINGS = _CONFIG_DIR / "settings.json"

_MARKETPLACE = "nsls-toolkit"
_PLUGIN_ID = f"nsls-builder-toolkit@{_MARKETPLACE}"
_REPO_URL = os.environ.get(
    "NSLS_TOOLKIT_REPO", "https://github.com/thensls/nsls-builder-toolkit.git"
)
# Matches the shim hook commands install.sh/.ps1 wrote into settings.json.
_HOOK_MARKER = "nsls-builder-toolkit/hooks/"
# Matches ONLY org-toolkit pointer stubs. Personal-toolkit stubs also mention
# nsls-builder-toolkit (their credit-logging command calls this repo's
# skill-event.sh), so the discriminator must be the skills path, not the repo
# name.
_STUB_MARKER = "local-plugins/nsls-builder-toolkit/skills/"
_LOCK = _CONFIG_DIR / ".nsls-plugin-migration.lock"
_LOCK_STALE_SECS = 300
# Written once stage B has VERIFIED the machine is clean (no shim hooks, no
# org stubs, no stale user-scope signal). Stage B re-runs every session until
# then, so a partial cleanup (one stub failing to delete, a timed-out mcp
# remove) retries instead of being orphaned forever.
_DONE = _CONFIG_DIR / ".nsls-plugin-migration-done"


def _read_json(path):
    # utf-8-sig: settings.json on machines installed via PowerShell can carry
    # a UTF-8 BOM, which plain utf-8 json.loads rejects — that failure mode
    # would wedge the machine in the shim/plugin overlap state permanently.
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _find_claude():
    """Locate the claude CLI. None means retry next session."""
    found = shutil.which("claude")
    if found:
        return found
    for candidate in (
        _CONFIG_DIR / "local" / "claude",
        Path("/usr/local/bin/claude"),
        Path("/opt/homebrew/bin/claude"),
    ):
        if candidate.exists():
            return str(candidate)
    return None


# Cumulative wall-clock ceiling for this whole migration run.
#
# The per-call timeouts below bound each CLI call individually but nothing
# bounded their SUM: stage A alone is marketplace list (30) + add (60) +
# install (60) = 150s worst case, inside a SessionStart hook whose entire
# budget is 90s (install.sh). Blowing it doesn't just fail the migration — the
# hook is killed, so sync_pointers and the session ping never run either, and
# the builder silently stops getting pointer updates and credit.
#
# session-start.py injects `_NSLS_MIGRATION_DEADLINE` (a time.monotonic()
# value) into the exec globals with the slice it can spare. The fallback
# applies when the script is run directly.
#
# Running out of budget is not a failure mode here: every stage is idempotent
# and retries next session, so a partial run just makes progress and stops.
_DEADLINE = globals().get("_NSLS_MIGRATION_DEADLINE") or (time.monotonic() + 35)


def _budget_left():
    return _DEADLINE - time.monotonic()


def _claude(args, timeout):
    """Run a claude CLI subcommand. Returns (ok, stdout+stderr).

    The requested timeout is clamped to whatever remains of the run's
    cumulative budget, so no sequence of calls can overrun the hook.
    """
    claude = _find_claude()
    if not claude:
        return False, "claude CLI not found"
    remaining = _budget_left()
    if remaining <= 1:
        # Don't start work we can't finish; next session picks up here.
        return False, "migration budget exhausted; will retry next session"
    try:
        result = subprocess.run(
            [claude, *args], capture_output=True, text=True,
            timeout=min(timeout, remaining),
        )
        return result.returncode == 0, (result.stdout or "") + (result.stderr or "")
    except Exception as e:
        return False, str(e)


def _plugin_installed():
    try:
        registry = _read_json(_CONFIG_DIR / "plugins" / "installed_plugins.json")
        return any(
            key.startswith("nsls-builder-toolkit@")
            for key in registry.get("plugins", {})
        )
    except Exception:
        return False


def _plugin_disabled_by_user():
    """True if the user explicitly disabled the plugin — respect that."""
    try:
        settings = _read_json(_SETTINGS)
        for key, enabled in settings.get("enabledPlugins", {}).items():
            if key.startswith("nsls-builder-toolkit@") and enabled is False:
                return True
    except Exception:
        pass
    return False


def _shims_present():
    try:
        return _HOOK_MARKER in _SETTINGS.read_text(encoding="utf-8-sig")
    except Exception:
        return False


def _org_stubs_exist():
    """True if any org stub remains — or if we could not prove otherwise.

    Fail-CLOSED on purpose. This is the gate on writing the done-marker, and
    the marker is permanent: once written, _stage_b never runs again. An
    unreadable SKILL.md used to be swallowed by `continue` here AND by the same
    guard in _remove_org_stubs, so a stub that couldn't be deleted also
    couldn't be detected — the run looked clean, the marker was written, and
    that machine kept both the legacy shim and the plugin copy of every skill
    active forever, with no retry.

    Treating "I couldn't tell" as "something's still there" costs one extra
    retry next session; the alternative costs a permanently double-wired
    install that nothing will ever notice.
    """
    if not _SKILLS_DIR.is_dir():
        return False
    for entry in _SKILLS_DIR.iterdir():
        stub = entry / "SKILL.md"
        try:
            if (entry.is_dir() and not entry.is_symlink() and stub.exists()
                    and _STUB_MARKER in stub.read_text(encoding="utf-8-sig")):
                return True
        except Exception:
            return True  # undetermined — assume not clean, retry next session
    return False


def _announce(text):
    # Directive prefix so the message is surfaced on every Claude Code surface
    # (desktop injects hook stdout as context without printing it) — same
    # pattern as session-start.py's announcement block.
    print(
        "[NSLS Builder Toolkit — surface the following to the user verbatim "
        "at the start of your first reply, then proceed with their request:]\n\n"
        f"{text}"
    )


def _stage_a():
    """Install the plugin. The running session stays on shims."""
    ok, out = _claude(["plugin", "marketplace", "list"], timeout=30)
    if not ok:
        return
    if _MARKETPLACE not in out:
        ok, out = _claude(["plugin", "marketplace", "add", _REPO_URL], timeout=60)
        if not ok:
            print(f"toolkit migration: marketplace add failed ({out.strip()[:200]}); "
                  "will retry next session", file=sys.stderr)
            return
    # 60s, not more: the SessionStart hook budget is 90s total and a killed
    # install is safe — stage A is idempotent and retries next session.
    ok, out = _claude(["plugin", "install", _PLUGIN_ID], timeout=60)
    if not ok:
        print(f"toolkit migration: plugin install failed ({out.strip()[:200]}); "
              "will retry next session", file=sys.stderr)
        return
    _announce(
        "The NSLS Builder Toolkit installed itself as a Claude Code plugin "
        "(step 1 of 2). Starting next session, the toolkit's agents "
        "(knowledge-researcher and the two reviewers) are finally available. "
        "The old wiring will be cleaned up automatically in a later session — "
        "nothing to do."
    )


def _remove_settings_hooks():
    """Drop hook entries whose command references this repo. Returns count."""
    settings = _read_json(_SETTINGS)
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return 0

    backup = _SETTINGS.with_name("settings.json.pre-plugin-migration")
    if not backup.exists():
        shutil.copy2(_SETTINGS, backup)

    removed = 0
    for event in list(hooks.keys()):
        groups = hooks[event]
        if not isinstance(groups, list):
            continue
        kept_groups = []
        for group in groups:
            entries = group.get("hooks", []) if isinstance(group, dict) else []
            kept = [
                h for h in entries
                if _HOOK_MARKER not in str(h.get("command", ""))
            ]
            removed += len(entries) - len(kept)
            if kept:
                group["hooks"] = kept
                kept_groups.append(group)
            elif not entries:
                kept_groups.append(group)
        if kept_groups:
            hooks[event] = kept_groups
        else:
            del hooks[event]

    if removed:
        tmp = _SETTINGS.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, _SETTINGS)
    return removed


def _remove_org_stubs():
    """Delete org-toolkit pointer stubs. Returns count. Never touches
    personal-toolkit stubs or user-authored skills (marker check)."""
    removed = 0
    if not _SKILLS_DIR.is_dir():
        return 0
    for entry in sorted(_SKILLS_DIR.iterdir()):
        stub = entry / "SKILL.md"
        try:
            if not (entry.is_dir() and not entry.is_symlink() and stub.exists()):
                continue
            if _STUB_MARKER not in stub.read_text(encoding="utf-8-sig"):
                continue
            shutil.rmtree(entry)
            removed += 1
        except Exception:
            continue
    return removed


def _remove_user_scope_signal():
    """Remove the user-scope signal MCP registration if it points into this
    repo — the plugin now registers signal at plugin scope.

    Returns (changed, clean): clean means there is verifiably nothing left to
    do (absent, not ours, or removal confirmed). A failed removal returns
    clean=False so the done-marker is withheld and the next session retries.
    """
    ok, out = _claude(["mcp", "get", "signal"], timeout=15)
    if not ok or "nsls-builder-toolkit" not in out:
        return False, True  # absent or not ours — nothing to migrate
    removed, _ = _claude(["mcp", "remove", "signal", "-s", "user"], timeout=15)
    return (True, True) if removed else (False, False)


def _stage_b():
    """Retire the shims now that the plugin is live.

    Re-runs every session until the machine VERIFIES clean, then writes the
    done-marker. This is what makes partial failures (one stub that wouldn't
    delete, a timed-out mcp remove) retry instead of being orphaned once the
    settings hooks are gone.
    """
    if sys.platform == "win32":
        # The plugin's hooks.json invokes python3/bash, which is unverified on
        # Windows. Until parity is proven, Windows keeps the settings-based
        # shims (its plugin hooks fail silently, so nothing double-fires).
        return
    # CLI calls first: the claude CLI may normalize/rewrite settings.json as a
    # side effect (observed live: it rewrote a model alias during `mcp get`),
    # so our own settings edit must come after every CLI invocation.
    signal_moved, signal_clean = _remove_user_scope_signal()
    hooks_removed = _remove_settings_hooks()
    stubs_removed = _remove_org_stubs()

    clean = signal_clean and not _shims_present() and not _org_stubs_exist()
    if clean:
        _DONE.write_text("migrated\n", encoding="utf-8")

    if hooks_removed or stubs_removed or signal_moved:
        _announce(
            "NSLS Builder Toolkit plugin migration"
            + (" complete (step 2 of 2)" if clean else " progressed") + ": "
            f"removed {stubs_removed} legacy skill pointers, {hooks_removed} "
            "legacy hook entries"
            + (", and moved the signal MCP server to plugin scope"
               if signal_moved else "")
            + ". Org skills now load as nsls-builder-toolkit:<name> — if a "
            "bare skill name fails this session, use the prefixed form. "
            "Rollback, if ever needed: restore "
            "~/.claude/settings.json.pre-plugin-migration and run "
            "`claude plugin uninstall nsls-builder-toolkit@nsls-toolkit`."
        )


def _acquire_lock():
    """O_EXCL-first: never unlink before an exclusive create has failed.

    A pre-emptive stale unlink lets two contenders each remove the other's
    fresh lock (both validated against the SAME stale stat) and both proceed.
    Here a contender only reclaims after O_EXCL fails AND a fresh stat still
    shows the lock stale — and then must still win a second O_EXCL.
    """
    for _ in range(2):
        try:
            fd = os.open(str(_LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return True
        except FileExistsError:
            try:
                if time.time() - _LOCK.stat().st_mtime <= _LOCK_STALE_SECS:
                    return False  # live contender holds it
                _LOCK.unlink()
            except OSError:
                return False
        except Exception:
            return False
    return False


def run_migration():
    if os.environ.get("NSLS_NO_PLUGIN_MIGRATION"):
        return
    if not _acquire_lock():
        return
    try:
        if not _plugin_installed():
            _stage_a()
        elif _plugin_disabled_by_user():
            return
        elif not _DONE.exists():
            _stage_b()
    except Exception:
        pass  # fail-open: shims still work; retry next session
    finally:
        try:
            _LOCK.unlink()
        except OSError:
            pass


run_migration()
