#!/usr/bin/env python3
"""
run_hook_scenarios.py — run the hook half of the guardrail scenario matrix.

    python3 test/guardrail-scenarios/run_hook_scenarios.py [-v]

Feeds each `kind=hook` scenario to guardrail-gate.py as a synthetic PreToolUse
payload and asserts allow/block. Exits non-zero if any scenario fails.

TOUCHES NOTHING REAL. No network, no live APIs, no deploys, no installs, no
GitHub repos. Scenarios needing a git remote get a throwaway repo created in the
system temp dir and deleted immediately after — never inside a real project.

The suite is deliberately weighted towards allow-cases. A gate that fires when
it shouldn't teaches builders to route around the toolkit, and then it protects
nobody — so false positives are treated as the more serious failure.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOOK = HERE.parent.parent / "hooks" / "guardrail-gate.py"
SCENARIOS = HERE / "scenarios.json"
VERBOSE = "-v" in sys.argv

# Every scenario is pointed at a loopback stub, never the live NSLS tracker.
# Two reasons: the suite must not depend on (or hammer) a production service to
# pass, and several cases need responses the real proxy would never send —
# notably the malformed-200 that Codex found could turn a tracker hiccup into a
# denied deploy.
STUB_MODES = {
    "empty": (200, {"automations": []}),        # well-formed "no such automation"
    "malformed": (200, {"status": "ok"}),       # 200, unrecognised shape
}
_stub_mode = {"mode": "empty"}


class _Stub(BaseHTTPRequestHandler):
    def do_GET(self):
        code, body = STUB_MODES[_stub_mode["mode"]]
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        self.send_response(204)
        self.end_headers()

    def log_message(self, *a):
        pass


def start_stub():
    srv = HTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


def make_repo(spec: dict) -> str:
    """Throwaway git repo in the system temp dir. Never a real project."""
    d = tempfile.mkdtemp(prefix="guardrail-scenario-")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }
    run = lambda *a: subprocess.run(a, cwd=d, capture_output=True, env=env, timeout=10)
    run("git", "init", "-q", ".")
    if spec.get("origin"):
        run("git", "remote", "add", "origin", spec["origin"])
    (Path(d) / "README.md").write_text(spec.get("readme", "# scratch"))
    run("git", "add", "-A")
    run("git", "commit", "-qm", "init")
    return d


def run_scenario(sc: dict, stub_url: str):
    payload = json.dumps({"tool_name": sc.get("tool", ""), "tool_input": sc.get("input", {})})
    cwd = None
    tmp = None
    _stub_mode["mode"] = sc.get("tracker_stub", "empty")
    try:
        if sc.get("repo"):
            tmp = make_repo(sc["repo"])
            cwd = tmp
        proc = subprocess.run(
            [sys.executable, str(HOOK)],
            input=payload,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=30,
            env={**os.environ, "NSLS_TRACKER_URL": stub_url},
        )
        blocked = bool(proc.stdout.strip())
        reason = ""
        if blocked:
            try:
                reason = json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
            except Exception:
                reason = proc.stdout.strip()[:200]
        return blocked, reason, proc.stderr.strip()
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def main():
    data = json.loads(SCENARIOS.read_text())
    scenarios = data["hook"]

    srv, stub_url = start_stub()
    passed, failed = 0, []
    false_positives, false_negatives = [], []

    for sc in scenarios:
        blocked, reason, err = run_scenario(sc, stub_url)
        want_block = sc["expect"] == "block"
        ok = blocked == want_block

        if ok:
            passed += 1
            mark = "PASS"
        else:
            failed.append(sc)
            mark = "FAIL"
            (false_positives if blocked else false_negatives).append(sc)

        if VERBOSE or not ok:
            print(f"  [{mark}] {sc['id']}  expect={sc['expect']:<5} → "
                  f"{'block' if blocked else 'allow':<5}  {sc['why']}")
            if not ok and err:
                print(f"         stderr: {err[:200]}")
            if VERBOSE and blocked and reason:
                print(f"         → {reason.splitlines()[0][:100]}")

        # Every block must carry both routes. A gate with no way out is the
        # thing that makes people uninstall the toolkit.
        if blocked and want_block:
            low = reason.lower()
            if "authoriz" not in low:
                failed.append(sc)
                print(f"  [FAIL] {sc['id']} blocked with no authorization route")
            if "log it" not in low and "looks wrong" not in low:
                failed.append(sc)
                print(f"  [FAIL] {sc['id']} blocked with no dispute route")

    print(f"\n  {passed}/{len(scenarios)} scenarios passed")
    if false_positives:
        print(f"  ⚠ {len(false_positives)} FALSE POSITIVE(S) — gates firing when they "
              f"shouldn't. This is the serious kind; it teaches builders to route "
              f"around the toolkit.")
        for sc in false_positives:
            print(f"      {sc['id']}: {sc['why']}")
    if false_negatives:
        print(f"  ⚠ {len(false_negatives)} missed block(s):")
        for sc in false_negatives:
            print(f"      {sc['id']}: {sc['why']}")

    voice = data.get("voice", [])
    print(f"\n  {len(voice)} voice scenarios are NOT machine-checkable — "
          f"role-play them against RUBRIC.md before rollout.")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
