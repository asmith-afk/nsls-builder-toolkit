#!/usr/bin/env python3
"""Beacons, the versioned done-marker, and the inert @local key.

Plain stdlib, no pytest: run with `python3 hooks/tests/test_migration_beacons.py`.

Three failures this exists to prevent:

1. **A shim certifying its own retirement.** Stage B strips all three installer
   hooks off one shared marker. Windows has never been allowed to run it
   because nobody could prove the plugin's hooks fire there — and
   session-start.ps1 calls the plugin's session-start.py directly, so "this
   code ran" is not the same claim as "the plugin hook fired". A beacon written
   from anywhere but the plugin cache would authorise retiring a working hook.

2. **A permanent marker outliving its assumptions.** Stage B writes a marker
   and never runs again. That was safe until a later installer run added
   something new to settings.json — #168 added the guardrail gate on
   2026-09-07, and any machine that re-ran install.sh after that date keeps it
   forever. Versioning the marker buys exactly one more pass per schema bump.

3. **Deleting a plugin someone actually installed.** The `@local` enablement
   key is inert and misleading, but only where no `local` marketplace exists.
"""

import importlib.util
import json
import os
import sys
import tempfile
import time
from pathlib import Path

HOOKS = Path(__file__).resolve().parents[1]
failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        failures.append(name)


def load(path, config_dir):
    """Import a hook module against a throwaway config dir."""
    os.environ["CLAUDE_CONFIG_DIR"] = str(config_dir)
    # migrate_to_plugin calls run_migration() at import. Never let a test
    # migrate the machine it is running on.
    os.environ["NSLS_NO_PLUGIN_MIGRATION"] = "1"
    spec = importlib.util.spec_from_file_location(f"m_{path.stem}_{time.time_ns()}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


print("beacons are written only from the plugin cache")
with tempfile.TemporaryDirectory() as tmp:
    cfg = Path(tmp) / "claude"
    cfg.mkdir()
    beacon = load(HOOKS / "plugin_beacon.py", cfg)

    cache = cfg / "plugins" / "cache" / "nsls-toolkit" / "nsls-builder-toolkit" / "3.8.5"
    (cache / "hooks").mkdir(parents=True)
    plugin_copy = cache / "hooks" / "guardrail-gate.py"
    plugin_copy.write_text("# plugin copy\n")

    clone = cfg / "local-plugins" / "nsls-builder-toolkit" / "hooks"
    clone.mkdir(parents=True)
    shim_copy = clone / "guardrail-gate.py"
    shim_copy.write_text("# shim copy\n")

    check("a shim copy writes no beacon",
          beacon.record("guardrail-gate", shim_copy) is False)
    check("and nothing claims the hook fired", beacon.fired("guardrail-gate") is False)

    check("a plugin copy writes one", beacon.record("guardrail-gate", plugin_copy) is True)
    check("which is what stage B will read", beacon.fired("guardrail-gate") is True)

    data = json.loads((beacon.BEACON_DIR / "guardrail-gate.json").read_text())
    check("it records the cache root", "plugins/cache" in data["root"].replace("\\", "/"))
    check("it records the version", data["version"] == "3.8.5")
    check("it counts runs", data["runs"] == 1)
    beacon.record("guardrail-gate", plugin_copy)
    data = json.loads((beacon.BEACON_DIR / "guardrail-gate.json").read_text())
    check("the count is the denominator the block count lacked", data["runs"] == 2)

    check("one hook's beacon says nothing about another",
          beacon.fired("skill-event") is False)

    # A forged beacon pointing outside the cache must not count.
    (beacon.BEACON_DIR / "session-start.json").write_text(
        json.dumps({"hook": "session-start", "root": str(clone)}) + "\n")
    check("a beacon naming a non-cache root is not evidence",
          beacon.fired("session-start") is False)

    # A forged beacon whose path merely LOOKS like a cache path.
    decoy = cfg / "evil" / "plugins" / "cache" / "nsls-toolkit" / "nsls-builder-toolkit" / "9.9.9"
    decoy.mkdir(parents=True)
    (beacon.BEACON_DIR / "skill-event.json").write_text(
        json.dumps({"hook": "skill-event", "root": str(decoy)}) + "\n")
    check("a cache-shaped path outside the real cache is not evidence",
          beacon.fired("skill-event") is False)

    # A beacon whose root has since been removed.
    gone = cache.parent / "3.0.0"
    gone.mkdir(parents=True)
    (beacon.BEACON_DIR / "skill-event.json").write_text(
        json.dumps({"hook": "skill-event", "root": str(gone)}) + "\n")
    check("a beacon from a directory that still exists is evidence",
          beacon.fired("skill-event") is True)
    gone.rmdir()
    check("a beacon from a directory that is gone is not",
          beacon.fired("skill-event") is False)

    # And once the CLI names an installed copy, only that copy counts, so an
    # upgrade re-earns its evidence instead of inheriting it.
    registry = cfg / "plugins" / "installed_plugins.json"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(json.dumps({"plugins": {
        "nsls-builder-toolkit@nsls-toolkit": [
            {"installPath": str(cache), "version": "3.8.5"}]}}))
    check("the current installed copy still counts",
          beacon.fired("guardrail-gate") is True)
    older = cache.parent / "3.7.0"
    (older / "hooks").mkdir(parents=True)
    (beacon.BEACON_DIR / "guardrail-gate.json").write_text(
        json.dumps({"hook": "guardrail-gate", "root": str(older)}) + "\n")
    check("a beacon from a superseded version does not",
          beacon.fired("guardrail-gate") is False)

print("\nstage B runs when the marker says done but the shims came back")
with tempfile.TemporaryDirectory() as tmp:
    cfg = Path(tmp) / "claude"
    cfg.mkdir()
    (cfg / "settings.json").write_text(json.dumps({"hooks": {}}))
    mig = load(HOOKS / "migrate_to_plugin.py", cfg)

    check("never migrated -> the full pass", mig._stage_b_reason() == "full")

    mig._DONE.write_text("migrated\n", encoding="utf-8")
    check("a pre-versioning marker reads as schema 1", mig._done_schema() == 1)
    check("and earns one more full pass, which sweeps the leftover gate",
          mig._stage_b_reason() == "full")

    mig._DONE.write_text(json.dumps({"schema": mig._MIGRATION_SCHEMA}) + "\n",
                         encoding="utf-8")
    check("a current marker on a clean machine does not re-run",
          mig._stage_b_reason() is None)

    # The regression Codex named: the marker is permanent, and both installers
    # deliberately re-create any missing shim. Re-running one after migrating
    # would otherwise leave every hook registered twice, for good.
    (cfg / "settings.json").write_text(json.dumps({"hooks": {"SessionStart": [
        {"matcher": "startup", "hooks": [{"type": "command", "command":
         'python3 "/Users/x/.claude/local-plugins/nsls-builder-toolkit/hooks/session-start.py"'}]}]}}))
    check("a shim that reappeared after the marker re-opens stage B",
          mig._stage_b_reason() == "reappeared")

    # An org stub reappearing counts too.
    (cfg / "settings.json").write_text(json.dumps({"hooks": {}}))
    stub = cfg / "skills" / "gws"
    stub.mkdir(parents=True)
    (stub / "SKILL.md").write_text(
        "points at local-plugins/nsls-builder-toolkit/skills/gws\n")
    check("a stub that reappeared after the marker re-opens stage B",
          mig._stage_b_reason() == "reappeared")

    mig._DONE.write_text("{ not json\n", encoding="utf-8")
    check("an unreadable marker is treated as old, not as done",
          mig._stage_b_reason() == "full")

print("\nthe inert @local key")


def setup_local_key(cfg, marketplaces):
    (cfg / "plugins").mkdir(parents=True, exist_ok=True)
    (cfg / "plugins" / "known_marketplaces.json").write_text(
        json.dumps({"marketplaces": marketplaces}))
    (cfg / "settings.json").write_text(json.dumps({
        "enabledPlugins": {"nsls-builder-toolkit@local": True,
                           "nsls-builder-toolkit@nsls-toolkit": True}}))


with tempfile.TemporaryDirectory() as tmp:
    cfg = Path(tmp) / "claude"
    cfg.mkdir()
    setup_local_key(cfg, {"nsls-toolkit": {}, "claude-plugins-official": {}})
    mig = load(HOOKS / "migrate_to_plugin.py", cfg)
    check("removed when no `local` marketplace exists",
          mig._remove_inert_local_enablement() is True)
    left = json.loads((cfg / "settings.json").read_text())["enabledPlugins"]
    check("the real plugin is untouched", left == {"nsls-builder-toolkit@nsls-toolkit": True})
    check("a second pass is a no-op", mig._remove_inert_local_enablement() is False)
    check("settings.json was backed up first",
          (cfg / "settings.json.pre-plugin-migration").exists())

with tempfile.TemporaryDirectory() as tmp:
    cfg = Path(tmp) / "claude"
    cfg.mkdir()
    setup_local_key(cfg, {"local": {}, "nsls-toolkit": {}})
    mig = load(HOOKS / "migrate_to_plugin.py", cfg)
    check("kept when a `local` marketplace really exists",
          mig._remove_inert_local_enablement() is False)

with tempfile.TemporaryDirectory() as tmp:
    cfg = Path(tmp) / "claude"
    cfg.mkdir()
    (cfg / "settings.json").write_text(json.dumps({
        "enabledPlugins": {"nsls-builder-toolkit@local": True}}))
    mig = load(HOOKS / "migrate_to_plugin.py", cfg)
    check("kept when the marketplace list cannot be read",
          mig._remove_inert_local_enablement() is False)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
