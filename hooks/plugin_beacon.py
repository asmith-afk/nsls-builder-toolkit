#!/usr/bin/env python3
"""plugin_beacon.py — evidence that a plugin hook actually fired on this machine.

Two jobs, one file.

1. **It is the precondition for retiring a shim.** Migration stage B strips the
   installer's settings.json hooks by a single shared marker, all three at once.
   On Windows that has always been deferred, because nobody could prove the
   plugin's own hooks run there — and a stage B that guessed wrong would take
   the credit logger and the gate with it. A per-hook beacon turns the guess
   into a fact: retire the shim for a hook only once the PLUGIN copy of that
   hook has been observed running on this machine. Per hook, never per plugin,
   because "SessionStart fired" says nothing about PreToolUse.

2. **It is the denominator.** `guardrail_blocked` counts blocks and nothing
   counts evaluations, so a gate that runs ten thousand times and blocks twice
   reads exactly like a gate that never ran — which is precisely how the gates
   went dark for two weeks without anyone noticing.

A beacon is only written by a copy running from the plugin cache. Without that
check the shim could write it and authorise its own retirement: session-start.ps1
invokes the plugin's session-start.py directly, so "this code ran" and "the
plugin hook fired" are genuinely different claims.
"""

import json
import os
import time
from pathlib import Path

_CONFIG_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))
BEACON_DIR = _CONFIG_DIR / ".nsls-plugin-beacons"
_MARKETPLACE = "nsls-toolkit"
_PLUGIN = "nsls-builder-toolkit"


def _cache_prefix() -> Path:
    """Where Claude Code keeps THIS plugin's installed copies."""
    return _CONFIG_DIR / "plugins" / "cache" / _MARKETPLACE / _PLUGIN


def _installed_root() -> str:
    """The plugin copy the CLI says is installed, or "" if that is unreadable.

    This is the strongest available statement of which copy is live. Without
    it, a beacon left by a version that has since been replaced would keep
    vouching for a hook shape that no longer exists.
    """
    try:
        reg = json.loads(
            (_CONFIG_DIR / "plugins" / "installed_plugins.json")
            .read_text(encoding="utf-8")
        )
        for key, entries in (reg.get("plugins") or {}).items():
            if not str(key).startswith(_PLUGIN + "@"):
                continue
            if isinstance(entries, dict):
                entries = [entries]
            for entry in entries or []:
                path = (entry or {}).get("installPath")
                if path:
                    return str(Path(path).resolve())
    except Exception:
        pass
    return ""


def plugin_root(running_file) -> str:
    """The installed plugin root this file is running from, or "" if it is not.

    Anchored on this plugin's own cache directory, not on any path that happens
    to contain "plugins/cache". A shim living anywhere else — including the
    local clone the PowerShell hook runs session-start.py from — gets "".
    """
    try:
        prefix = _cache_prefix().resolve()
        parts = Path(running_file).resolve().parts
        for i in range(len(parts) - 1):
            root = Path(*parts[:i + 1])
            if root.parent == prefix and root.is_dir():
                return str(root)
    except Exception:
        pass
    return ""


def record(hook: str, running_file) -> bool:
    """Note that this hook ran from the plugin. Returns True if a beacon exists.

    Best-effort in every direction: a lost increment under concurrency costs a
    slightly low denominator, and a failed write costs one unproven hook. The
    alternative — a lock on a hook that runs before every tool call — costs
    more than the number is worth.
    """
    root = plugin_root(running_file)
    if not root:
        return False
    try:
        BEACON_DIR.mkdir(parents=True, exist_ok=True)
        path = BEACON_DIR / f"{hook}.json"
        now = int(time.time())
        data = {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
        runs = data.get("runs")
        data.update({
            "hook": hook,
            "root": root,
            "version": Path(root).name,
            "first": data.get("first") or now,
            "last": now,
            "runs": (runs + 1) if isinstance(runs, int) else 1,
        })
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def fired(hook: str) -> bool:
    """True when the PLUGIN copy of this hook has been seen running here.

    Every clause is a way the answer could be wrong, and each costs one more
    session of waiting rather than one wrongly retired hook:

    * the beacon must be for the hook being asked about — one hook's evidence
      says nothing about another's;
    * the root it names must still exist — a beacon from a cache directory that
      has since been removed proves nothing about today;
    * that root must sit directly under this plugin's own cache prefix — a
      forged file naming any cache-shaped path is not evidence;
    * and it must be the copy the CLI currently reports as installed, when that
      can be read, so an upgrade re-earns its evidence rather than inheriting it.
    """
    try:
        data = json.loads((BEACON_DIR / f"{hook}.json").read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("hook") != hook:
            return False
        recorded = str(data.get("root") or "")
        if not recorded:
            return False
        root = Path(recorded).resolve()
        if not root.is_dir():
            return False
        if root.parent != _cache_prefix().resolve():
            return False
        installed = _installed_root()
        if installed and str(root) != installed:
            return False
        return True
    except Exception:
        return False
