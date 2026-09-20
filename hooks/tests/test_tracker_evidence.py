#!/usr/bin/env python3
"""What counts as evidence from the tracker, and what a Windows path looks like.

Plain stdlib, no pytest: run with `python3 hooks/tests/test_tracker_evidence.py`.

Two failures this exists to prevent.

1. **Absence of proof read as proof of absence.** Gates 2 and 4 ask the tracker
   whether a build is registered. The client only ever accepted a dict with an
   `automations` key; the tracker answers `{"count", "records", "success"}`, so
   every reply parsed as None and both gates have been incapable of firing for
   as long as they have existed. Fixing that parse is only half the job: the
   endpoint honours no name, search or pagination parameter and returns the same
   first 50 of 151 rows for every query, so a name missing from a reply means
   "not on this page", not "not registered". Blocking on that would be a false
   positive on two thirds of the tracker — the failure mode these gates care
   most about. Every shape below that cannot support a confident answer must
   come back `unknown`.

2. **A Windows path is not a POSIX path.** The documentation exemption in gate 4
   tested for `/docs/`, so `C:\\repo\\docs\\example.py` was judged as executable
   product code. That gate only started reaching Windows at all with the parity
   change, which is what makes it live now.

No network: `_http_get` is replaced with a stub.
"""

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
from pathlib import Path

HOOKS = Path(__file__).resolve().parents[1]
failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        failures.append(name)


def load_gate(config_dir):
    os.environ["CLAUDE_CONFIG_DIR"] = str(config_dir)
    spec = importlib.util.spec_from_file_location(
        f"gate_{config_dir.name}", HOOKS / "guardrail-gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def lookup(body, name="my-service"):
    """One lookup against a stubbed reply, with a fresh cache each time."""
    tmp = tempfile.mkdtemp()
    gate = load_gate(Path(tmp))
    gate._http_get = lambda url: (body if isinstance(body, bytes)
                                  else json.dumps(body).encode())
    return gate.tracker_lookup(name)[0]


print("a reply has to support the answer before a gate acts on it")
rows = [{"name": "other-thing"}, {"name": "another"}]

check("a match is found",
      lookup({"success": True, "count": 2,
              "records": rows + [{"name": "my-service"}]}) == "found")
check("a complete page with no match is a real absence",
      lookup({"success": True, "count": 2, "records": rows}) == "absent")
check("success:false is unknown, whatever else it carries",
      lookup({"success": False, "count": 151, "records": []}) == "unknown")
check("a count larger than the page is unknown",
      lookup({"success": True, "count": 151, "records": rows}) == "unknown")
check("a full page is unknown even with no count",
      lookup({"records": [{"name": f"r{i}"} for i in range(50)]}) == "unknown")
check("an unrecognised shape is unknown",
      lookup({"data": rows}) == "unknown")
check("a non-dict row poisons the whole reply",
      lookup({"count": 3, "records": rows + ["temporarily unavailable"]}) == "unknown")
check("unparseable bytes are unknown", lookup(b"<html>502</html>") == "unknown")
check("a bare list still works (older shape)",
      lookup(rows + [{"name": "my-service"}]) == "found")
check("a bare list with no match is an absence", lookup(rows) == "absent")
check("a nonsense count is ignored rather than trusted",
      lookup({"count": "many", "records": rows}) == "absent")

print("\nthe live endpoint, as it actually behaves today")
with tempfile.TemporaryDirectory() as tmp:
    gate = load_gate(Path(tmp))
    # 151 rows exist; every query returns the same 50. Absence is unknowable.
    gate._http_get = lambda url: json.dumps(
        {"success": True, "count": 50,
         "records": [{"name": f"row{i}"} for i in range(50)]}).encode()
    check("a name outside the first page is unknown, never absent",
          gate.tracker_lookup("row99")[0] == "unknown")
    check("a name on the page is still found",
          gate.tracker_lookup("row7")[0] == "found")

print("\nthe cache never outlives the state a block described")
with tempfile.TemporaryDirectory() as tmp:
    gate = load_gate(Path(tmp))
    calls = []

    def stub(url):
        calls.append(url)
        return json.dumps({"success": True, "count": 1, "records": [
            {"name": "my-service", "scope": "Company-wide", "reviewer": None}]}).encode()

    gate._http_get = stub
    gate.tracker_lookup("my-service")
    gate.tracker_lookup("my-service")
    check("a repeat lookup is served from the cache", len(calls) == 1)

    # A block tells the builder to assign the reviewer. If the next attempt were
    # served the cached record, they would be blocked for having complied.
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            gate.block("test", gate="tier3_no_reviewer", automation="my-service")
        except SystemExit:
            pass
    gate.tracker_lookup("my-service")
    check("a block clears it, so the remedy is visible immediately",
          len(calls) == 2)

print("\nthe documentation exemption understands Windows paths")
with tempfile.TemporaryDirectory() as tmp:
    gate = load_gate(Path(tmp))
    gate.tracker_lookup = lambda name: (
        "found", {"name": name, "scope": "Company-wide"})
    gate.repo_root = lambda *a, **k: "/tmp/some-nsls-repo"
    gate.emit = lambda *a, **k: None
    body = "import openai\nclient = openai.OpenAI()\n"

    def blocks(path):
        # The deny JSON goes to stdout; swallow it so the run stays readable.
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                gate.gate_off_platform("Edit", {"file_path": path,
                                                "new_string": body})
            except SystemExit:
                return True
        return False

    check("a POSIX docs path is exempt", not blocks("/repo/docs/example.py"))
    check("a Windows docs path is exempt too",
          not blocks(r"C:\repo\docs\example.py"))
    check("a Windows README is exempt", not blocks(r"C:\repo\README.md"))
    check("a mixed-separator docs path is exempt",
          not blocks(r"C:\repo\docs/nested\example.py"))
    check("real Windows product code is still judged",
          blocks(r"C:\repo\src\client.py"))
    check("real POSIX product code is still judged", blocks("/repo/src/client.py"))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
