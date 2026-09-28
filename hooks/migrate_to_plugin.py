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
  * Windows — NEITHER stage runs today, and this docstring used to claim
    stage A did. Nothing calls this module on Windows: session-start.ps1 is the
    hook that fires there, and its only entry into Python is
    runpy.run_path(..., run_name="__guardrails__"), which executes that block
    alone and never main(). That, not a shortage of installs, is why no PC has
    ever had the plugin — so no PC has the three agents, and stage B has never
    had anything to be deferred from. Wiring stage A into the Windows path is
    the Windows-parity change; stage B stays gated on per-hook beacon evidence
    that the plugin's own hooks actually fire on that machine.
"""

import json
import os
import shutil
import subprocess
import sys
import time
import tempfile
from pathlib import Path

def _config_dir() -> Path:
    """The Claude config directory, resolved without ever raising.

    `Path.home()` raises when neither HOME nor a password-database entry
    resolves, and at module scope that stops session start dead.
    """
    raw = os.environ.get("CLAUDE_CONFIG_DIR")
    if raw:
        return Path(raw)
    try:
        return Path.home() / ".claude"
    except Exception:
        return Path(tempfile.gettempdir()) / "nsls-claude-config"


_CONFIG_DIR = _config_dir()
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


def _norm(text) -> str:
    """Compare paths the way BOTH installers write them.

    install.sh writes POSIX separators. install.ps1 builds every path with
    Join-Path, so a Windows shim command reads
    `...\\nsls-builder-toolkit\\hooks\\session-start.ps1`. A marker spelled with
    forward slashes matched none of it: _shims_present() answered False,
    _remove_settings_hooks() removed nothing, and stage B therefore concluded
    the machine was clean and wrote the PERMANENT done marker — leaving every
    PC running the shim AND the plugin copy of every hook, for good, behind a
    marker saying the migration had finished.
    """
    return str(text).replace("\\", "/")


def _is_shim_command(command) -> bool:
    return _HOOK_MARKER in _norm(command)


def _iter_hook_commands(settings):
    """Every hook entry's command, and nothing else.

    _shims_present() used to substring-search the whole settings.json as raw
    text, so any mention of this repo anywhere in the file counted — a
    leftover `permissions.allow` rule most of all. After an otherwise clean
    stage B that left the machine reading as dirty permanently: `clean` never
    became True, the done marker was never written, and stage B re-ran every
    session for the life of the install.
    """
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return
    for groups in hooks.values():
        if not isinstance(groups, list):
            continue
        for group in groups:
            entries = group.get("hooks", []) if isinstance(group, dict) else []
            if not isinstance(entries, list):
                continue
            for h in entries:
                if isinstance(h, dict):
                    yield str(h.get("command", ""))


# ...and which shim belongs to which hook. Stage B used to strip every entry
# carrying the marker in one go, which is only safe if the plugin has replaced
# ALL of them. It has not, per hook and per machine: on Windows nothing had
# replaced any of them, and "SessionStart fired" is not evidence that PreToolUse
# does. Retiring a shim is now decided one hook at a time, against that hook's
# own beacon. The cost of getting this wrong is not abstract — skill-event is
# the credit logger, and losing it silently costs builders the record of their
# work, which is the thing NSLS measures them by.
_HOOK_SCRIPTS = {
    "session-start": ("session-start.py", "session-start.ps1"),
    "skill-event": ("skill-event.sh", "skill-event.ps1"),
    "guardrail-gate": ("guardrail-gate.py",),
}


def _beacon_fired(hook: str) -> bool:
    """Has the PLUGIN copy of this hook been seen running on this machine?"""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import plugin_beacon

        return plugin_beacon.fired(hook)
    except Exception:
        return False  # no evidence is not evidence of parity


def _proven_hooks():
    return {h for h in _HOOK_SCRIPTS if _beacon_fired(h)}


def _hook_for_command(command: str):
    normalised = _norm(command)
    for hook, scripts in _HOOK_SCRIPTS.items():
        if any(s in normalised for s in scripts):
            return hook
    return None
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
# The done-marker is permanent: once written, stage B never runs again on that
# machine. That was fine while stage B only had to remove what the installer
# wrote before the marker existed — and became a trap the moment a LATER
# installer run added something new. #168 (2026-09-07) registered the guardrail
# gate into settings.json; any machine that re-ran install.sh after that date
# with the marker already written keeps that entry for good, and once the
# plugin registers the gate too, both fire.
#
# Versioning the marker gives stage B exactly one more pass per schema bump.
# Every step it runs is idempotent and announces only when something changed,
# so a machine that is already clean sees nothing at all.
_MIGRATION_SCHEMA = 2


def _done_schema():
    """Schema of this machine's done-marker, or None if it has never run.

    Pre-versioning markers hold the literal text "migrated" and are schema 1.
    """
    try:
        raw = _DONE.read_text(encoding="utf-8-sig").strip()
    except Exception:
        return None
    try:
        return int(json.loads(raw).get("schema", 1))
    except Exception:
        return 1 if raw else None


def _stage_b_reason():
    """Why stage B should run this session: "full", "reappeared", or None.

    The done-marker is permanent, and both installers deliberately re-create any
    missing settings.json shim. So a builder who re-runs the installer after
    migrating gets every shim back, for good, silently duplicating whatever the
    plugin already registers — which is the permanent-overlap failure the marker
    versioning was meant to end, arriving by a different door. Live state
    therefore outranks the marker: if a shim or an org stub is present, stage B
    has work regardless of what the marker says.

    "reappeared" runs the cheap half only. The signal MCP check is a CLI call
    against a 15 s timeout, and it was settled the first time through; paying
    for it every session to re-confirm would be a real cost on every machine.
    """
    schema = _done_schema()
    if schema is None or schema < _MIGRATION_SCHEMA:
        return "full"
    if _shims_present() or _org_stubs_exist():
        return "reappeared"
    return None


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
    """True if a settings.json HOOK entry still points at this repo.

    Fail-CLOSED when the file cannot be read or parsed, for the same reason
    _org_stubs_exist() does: this gates the permanent done marker, and one
    extra retry next session is far cheaper than a machine wired twice forever.
    """
    try:
        raw = _SETTINGS.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return False  # no settings file at all — nothing to retire
    except Exception:
        return True
    try:
        settings = json.loads(raw)
    except Exception:
        return True
    if not isinstance(settings, dict):
        return True
    return any(_is_shim_command(c) for c in _iter_hook_commands(settings))


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
                    and _STUB_MARKER in _norm(
                        stub.read_text(encoding="utf-8-sig"))):
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


def _remove_settings_hooks(only=None):
    """Drop shim hook entries for the named hooks. Returns count.

    `only` is the set of hooks whose plugin copy has been PROVEN to run here.
    An entry for a hook outside that set is left alone, however old it is.
    """
    if only is not None and not only:
        return 0
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
            kept = []
            for h in entries:
                command = str(h.get("command", ""))
                if not _is_shim_command(command):
                    kept.append(h)
                    continue
                hook = _hook_for_command(command)
                if only is not None and hook not in only:
                    kept.append(h)  # nothing has replaced this one yet
            
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


def _remove_org_stubs(allowed=True):
    """Delete org-toolkit pointer stubs. Returns count. Never touches
    personal-toolkit stubs or user-authored skills (marker check).

    `allowed` is False until the plugin has been seen running here: the stubs
    are how skills reach a machine that has no plugin, and on Windows that has
    been every machine.
    """
    removed = 0
    if not allowed:
        return 0
    if not _SKILLS_DIR.is_dir():
        return 0
    for entry in sorted(_SKILLS_DIR.iterdir()):
        stub = entry / "SKILL.md"
        try:
            if not (entry.is_dir() and not entry.is_symlink() and stub.exists()):
                continue
            # _norm here too: detection (_org_stubs_exist) and removal must
            # agree, or a Windows stub is seen but never deleted and stage B
            # retries every session forever.
            if _STUB_MARKER not in _norm(stub.read_text(encoding="utf-8-sig")):
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
    # Windows is no longer excluded wholesale. It was, because the plugin's
    # hooks.json named `python3` — a Store alias there — and nobody could prove
    # any of it ran. Both halves of that have changed: hooks.json now goes
    # through run-hook.sh, which resolves the interpreter, and the beacons below
    # replace the guess with per-hook evidence from this machine. A hook whose
    # plugin copy has not been observed running keeps its shim, on every
    # platform, for as long as that stays true.
    #
    # Until all three are proven, a machine runs both copies of the proven ones.
    # That overlap is bounded and deliberate: the tracker dedupes session points
    # per builder per day, the gate single-flights on tool_use_id, and a second
    # git pull loses a race on index.lock and gives up. It ends on its own, one
    # hook at a time, as each beacon lands.
    proven = _proven_hooks()

    # CLI calls first: the claude CLI may normalize/rewrite settings.json as a
    # side effect (observed live: it rewrote a model alias during `mcp get`),
    # so our own settings edit must come after every CLI invocation.
    # Both passes, not just the first. A "reappeared" pass exists precisely
    # because the installer ran again, and the installer re-registers the
    # user-scope signal server alongside the shims it put back. Skipping the
    # removal there leaves signal registered at user AND plugin scope while
    # this run goes on to write the done marker, so nothing ever comes back
    # for it.
    signal_moved, signal_clean = _remove_user_scope_signal()
    hooks_removed = _remove_settings_hooks(only=proven)
    stubs_removed = _remove_org_stubs(allowed="session-start" in proven)

    local_key_removed = _remove_inert_local_enablement()

    # The done-marker is permanent, so it is withheld until every shim is gone.
    # An unproven hook therefore keeps stage B coming back each session, which
    # is exactly the retry this needs: the beacon may be one Skill call away.
    clean = signal_clean and not _shims_present() and not _org_stubs_exist()
    if clean:
        _DONE.write_text(
            json.dumps({"schema": _MIGRATION_SCHEMA, "at": int(time.time())}) + "\n",
            encoding="utf-8",
        )

    if hooks_removed or stubs_removed or signal_moved or local_key_removed:
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


def _remove_inert_local_enablement():
    """Drop `nsls-builder-toolkit@local` from enabledPlugins. Returns bool.

    Both installers write this key. It names a marketplace called `local` that
    does not exist, so Claude Code can never resolve it and it has no effect —
    but it LOOKS like a second live installation, and twice now that appearance
    has produced the wrong conclusion: an 2026-08-23 test against this key
    "proved" that bundled plugin hooks do not load, which is the belief that
    removed the guardrail gate from hooks.json on 2026-09-06 and left every
    migrated Mac unguarded for two weeks.

    Removed only when the absence of a `local` marketplace can be positively
    confirmed. If that file cannot be read, the key stays: a misleading no-op
    is cheaper than disabling a plugin someone actually installed.
    """
    try:
        known = _read_json(_CONFIG_DIR / "plugins" / "known_marketplaces.json")
    except Exception:
        return False
    names = known.get("marketplaces", known) if isinstance(known, dict) else {}
    if not isinstance(names, dict) or "local" in names:
        return False
    try:
        settings = _read_json(_SETTINGS)
    except Exception:
        return False
    plugins = settings.get("enabledPlugins")
    if not isinstance(plugins, dict) or "nsls-builder-toolkit@local" not in plugins:
        return False
    backup = _SETTINGS.with_name("settings.json.pre-plugin-migration")
    if not backup.exists():
        try:
            shutil.copy2(_SETTINGS, backup)
        except Exception:
            return False
    del plugins["nsls-builder-toolkit@local"]
    try:
        tmp = _SETTINGS.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, _SETTINGS)
        return True
    except Exception:
        return False


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
        else:
            if _stage_b_reason():
                _stage_b()
    except Exception:
        pass  # fail-open: shims still work; retry next session
    finally:
        try:
            _LOCK.unlink()
        except OSError:
            pass


run_migration()
