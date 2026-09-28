#!/usr/bin/env python3
"""install.sh must register hook commands that can actually run.

Plain stdlib, no pytest: run with `python3 hooks/tests/test_installer_registration.py`.

The failure this exists to prevent, found 2026-09-20 on origin/main. The
installer writes settings.json from a Python program embedded in a shell
double-quoted string (`python3 -c "..."`). The guardrail gate's command was
built with unescaped double quotes, which closed that shell string early — so
the shell executed fragments of the Python source as words, and settings.json
received the literal text:

    python3  + os.path.join(CONFIG_DIR, local-plugins/.../guardrail-gate.py) +

as the hook command. It is not runnable. The gate therefore could not have
fired on any Mac the installer touched, even before the migration deleted the
entry, and every matching tool call would have printed a hook-error notice. The
session-start entry a few lines above escapes its quotes correctly; nobody
compared them, because nothing executed the installer's output.

This runs the real block from the real install.sh against a throwaway config
dir and then runs what it wrote.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INSTALL = REPO / "install.sh"
failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        failures.append(name)


lines = INSTALL.read_text().splitlines()
start = next(i for i, l in enumerate(lines)
             if 'python3 -c "' in l and "CONFIG_DIR=" in l)
end = next(i for i in range(start + 1, len(lines))
           if lines[i].startswith('" 2>/dev/null'))

with tempfile.TemporaryDirectory() as tmp:
    cfg = Path(tmp) / ".claude"
    cfg.mkdir()
    (cfg / "settings.json").write_text(json.dumps({"enabledPlugins": {}, "hooks": {}}))
    block = Path(tmp) / "block.sh"
    block.write_text('CONFIG_DIR="$1"\n' + "\n".join(lines[start:end + 1]) + "\n")

    proc = subprocess.run(["bash", str(block), str(cfg)],
                          capture_output=True, text=True, timeout=60)
    noise = [l for l in proc.stderr.splitlines() if l.strip()]
    check("the block runs without the shell tripping over the program",
          not noise, f"({noise[:2]})")

    written = json.loads((cfg / "settings.json").read_text())
    commands = [h["command"]
                for groups in written.get("hooks", {}).values()
                for g in groups for h in g.get("hooks", [])]
    check("three hooks registered", len(commands) == 3, f"({len(commands)})")

    gate = next((c for c in commands if "guardrail-gate" in c), None)
    check("a gate command was written", gate is not None)

    if gate:
        check("it is not mangled Python source",
              "os.path.join" not in gate and " + " not in gate, f"({gate})")
        # The real test: run what the installer wrote, exactly as a shell would.
        script = Path(tmp) / "repo" / "hooks" / "guardrail-gate.py"
        script.parent.mkdir(parents=True)
        real = (REPO / "hooks" / "guardrail-gate.py").read_text()
        script.write_text(real)
        runnable = gate.replace(
            str(cfg / "local-plugins" / "nsls-builder-toolkit" / "hooks"
                / "guardrail-gate.py"),
            str(script))
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(cfg),
                   NSLS_GUARDRAIL_EVENT_LOG=str(Path(tmp) / "ev"))
        env.pop("NSLS_GUARDRAILS_DISABLED", None)
        out = subprocess.run(runnable, shell=True, input='{"tool_name":"Bash",'
                             '"tool_input":{"command":"ls"},"tool_use_id":"t1"}',
                             capture_output=True, text=True, timeout=30, env=env)
        check("the command the installer wrote actually executes",
              out.returncode == 0, f"(exit {out.returncode}: {out.stderr[:160]})")
        check("and it is the gate that ran, not something else",
              "can't open file" not in out.stderr and "No such file" not in out.stderr,
              f"({out.stderr[:160]})")

    for c in commands:
        if "session-start" in c or "skill-event" in c:
            check(f"{'session-start' if 'session-start' in c else 'skill-event'}"
                  " command is well formed", "os.path.join" not in c, f"({c[:90]})")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
