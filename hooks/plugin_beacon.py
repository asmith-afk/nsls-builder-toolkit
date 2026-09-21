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
# Written only by hooks the plugin runtime launched. `${CLAUDE_PLUGIN_ROOT}` is
# exported into the process for both hook forms, and the cache path is the
# corroborating evidence when it is not.
_CACHE_PARTS = ("plugins", "cache")


def plugin_root(running_file) -> str:
    """The plugin cache root this file is running from, or "" if it is not."""
    try:
        parts = Path(running_file).resolve().parts
        for i in range(len(parts) - 1):
            if parts[i:i + 2] == _CACHE_PARTS:
                # .../plugins/cache/<marketplace>/<plugin>/<version>/...
                root = Path(*parts[:i + 5])
                return str(root) if root.is_dir() else ""
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
    """True when the PLUGIN copy of this hook has been seen running here."""
    try:
        data = json.loads((BEACON_DIR / f"{hook}.json").read_text(encoding="utf-8"))
        root = data.get("root") or ""
        parts = Path(root).parts
        return any(parts[i:i + 2] == _CACHE_PARTS for i in range(len(parts) - 1))
    except Exception:
        return False
