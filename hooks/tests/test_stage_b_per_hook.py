#!/usr/bin/env python3
"""Stage B retires a shim only for a hook the plugin has been proven to replace.

Plain stdlib, no pytest: run with `python3 hooks/tests/test_stage_b_per_hook.py`.

The failure this exists to prevent. Stage B strips every settings.json entry
carrying `nsls-builder-toolkit/hooks/` in one pass. That is only safe if the
plugin has replaced all of them, and on Windows it had replaced none — which is
why stage B was skipped there outright, and why Windows has kept both the shims
and no plugin for a year. Turning it on per-platform would be the same bet with
a different coin: SessionStart firing says nothing about PreToolUse, and the
entry most likely to be retired on a false assumption is skill-event, the hook
that records builders' credit.

So the unit of proof is the hook, not the platform and not the plugin. Each
scenario below runs in its own process against its own config dir, because the
beacon module reads CLAUDE_CONFIG_DIR once at import.
"""

import json
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

HOOKS = Path(__file__).resolve().parents[1]
failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        failures.append(name)


SHIM = "/Users/someone/.claude/local-plugins/nsls-builder-toolkit/hooks/"


def build(cfg: Path):
    """A machine mid-migration: three shims, one unrelated hook, one org stub."""
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "settings.json").write_text(json.dumps({
        "hooks": {
            "SessionStart": [{"matcher": "startup", "hooks": [
                {"type": "command", "command": f'python3 "{SHIM}session-start.py"'},
            ]}],
            "PreToolUse": [
                {"matcher": "Skill", "hooks": [
                    {"type": "command", "command": f'bash "{SHIM}skill-event.sh"'},
                ]},
                {"matcher": "Bash|PowerShell|Write|Edit", "hooks": [
                    {"type": "command", "command": f'python3 "{SHIM}guardrail-gate.py"'},
                ]},
                {"matcher": "Write", "hooks": [
                    {"type": "command", "command": "python3 /home/me/my-own-hook.py"},
                ]},
            ],
        },
    }, indent=2))
    skills = cfg / "skills" / "gws"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text(
        "points at local-plugins/nsls-builder-toolkit/skills/gws\n")
    cache = (cfg / "plugins" / "cache" / "nsls-toolkit"
             / "nsls-builder-toolkit" / "3.8.6" / "hooks")
    cache.mkdir(parents=True)
    return cache


SCENARIO = textwrap.dedent("""
    import importlib.util, json, os, sys
    from pathlib import Path
    hooks, cfg, cache, prove = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
    os.environ["CLAUDE_CONFIG_DIR"] = str(cfg)
    os.environ["NSLS_NO_PLUGIN_MIGRATION"] = "1"
    sys.path.insert(0, hooks)
    import plugin_beacon
    for hook in [h for h in prove.split(",") if h]:
        f = cache / f"{hook}-copy.py"
        f.write_text("# plugin copy")
        assert plugin_beacon.record(hook, f), "beacon should have been written"
    spec = importlib.util.spec_from_file_location("mig", os.path.join(hooks, "migrate_to_plugin.py"))
    mig = importlib.util.module_from_spec(spec); spec.loader.exec_module(mig)
    proven = mig._proven_hooks()
    removed = mig._remove_settings_hooks(only=proven)
    stubs = mig._remove_org_stubs(allowed="session-start" in proven)
    left = []
    for groups in json.loads((cfg / "settings.json").read_text()).get("hooks", {}).values():
        for g in groups:
            for h in g.get("hooks", []):
                left.append(h["command"])
    print(json.dumps({"proven": sorted(proven), "removed": removed,
                      "stubs": stubs, "left": left,
                      "stub_exists": (cfg / "skills" / "gws").exists()}))
""")


def run(prove):
    tmp = tempfile.mkdtemp()
    cfg = Path(tmp) / "claude"
    cache = build(cfg)
    out = subprocess.run(
        [sys.executable, "-c", SCENARIO, str(HOOKS), str(cfg), str(cache), ",".join(prove)],
        capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise AssertionError(out.stderr[-1500:])
    return json.loads(out.stdout.strip().splitlines()[-1])


def has(left, script):
    return any(script in c for c in left)


print("no beacons: nothing is retired")
r = run([])
check("no hook counts as proven", r["proven"] == [])
check("no shim removed", r["removed"] == 0)
check("session-start shim survives", has(r["left"], "session-start.py"))
check("skill-event shim survives - this is the credit logger",
      has(r["left"], "skill-event.sh"))
check("gate shim survives", has(r["left"], "guardrail-gate.py"))
check("the builder's own hook is never touched", has(r["left"], "my-own-hook.py"))
check("skill stubs survive - they are how skills reach a plugin-less machine",
      r["stub_exists"] and r["stubs"] == 0)

print("\none beacon: exactly that hook is retired")
r = run(["guardrail-gate"])
check("only the gate is proven", r["proven"] == ["guardrail-gate"])
check("one shim removed", r["removed"] == 1)
check("the gate shim is gone", not has(r["left"], "guardrail-gate.py"))
check("session-start shim survives", has(r["left"], "session-start.py"))
check("skill-event shim survives", has(r["left"], "skill-event.sh"))
check("the builder's own hook is never touched", has(r["left"], "my-own-hook.py"))
check("stubs still survive without the session-start beacon", r["stub_exists"])

print("\nall three beacons: the machine finishes migrating")
r = run(["session-start", "skill-event", "guardrail-gate"])
check("all three proven", len(r["proven"]) == 3)
check("three shims removed", r["removed"] == 3)
check("no toolkit shim remains",
      not any(x in c for c in r["left"]
              for x in ("session-start.py", "skill-event.sh", "guardrail-gate.py")))
check("the builder's own hook is STILL never touched", has(r["left"], "my-own-hook.py"))
check("and the org stubs go with them", not r["stub_exists"] and r["stubs"] == 1)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
