#!/usr/bin/env python3.12
"""Executes every documented auth invocation as a real subprocess.

`--login` became `--set-session` when the browser was removed from the
Anthropic source. Both names are exercised here: the new one because it is
what the docs now say, the old one because it is in shipped docs, in old
error strings, and in muscle memory, and must still land somewhere useful
instead of dying on "unrecognized arguments".

The bug this file exists to catch: `sources/anthropic.py` used a bare
relative import (`from .base import ...`), so running it directly —
`python3.12 skills/receipts/scripts/sources/anthropic.py --login` — crashed
with `ImportError: attempted relative import with no known parent package`
before argument parsing ever ran. That exact command was (and, for the
direct-script fallback, still is) printed by SKILL.md and by the
SourceUnavailable message a dead claude.ai session raises — the fix for the
failure was unreachable through the instructions telling a user how to fix
it.

A test that only checks the *string* of the command appearing in a doc or a
--help message would not have caught this — the string was always right
there; the process behind it was what was broken. This test actually
launches each documented form as a subprocess and checks the process comes
up alive: import succeeds, argument dispatch reaches _login(), and it exits
0 — not that a real browser opens.

Hermetic: RECEIPTS_LOGIN_TEST_NOOP=1 makes `_set_session()` a no-op before it
prompts for a credential or touches the network. No network, no auth, no
credential prompt, no writes outside a throwaway temp cwd used only as a
working directory.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent.parent.parent  # tests -> receipts -> skills -> repo root
SCRIPTS = REPO_ROOT / "skills" / "receipts" / "scripts"
RUN_PY = SCRIPTS / "run.py"
ANTHROPIC_PY = SCRIPTS / "sources" / "anthropic.py"

assert RUN_PY.is_file(), f"expected {RUN_PY} to exist"
assert ANTHROPIC_PY.is_file(), f"expected {ANTHROPIC_PY} to exist"


def _clean_env(**extra) -> dict:
    """A minimal environment: just enough PATH for the interpreter and its
    shared libraries to resolve, plus whatever the caller adds. Deliberately
    does not inherit ANTHROPIC_ORG_UUID, Ramp auth, or gws auth — --login
    must not need any of that to reach _login()."""
    env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")}
    env.update(extra)
    return env


def _run(args, cwd) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, *args],
        cwd=str(cwd),
        env=_clean_env(RECEIPTS_LOGIN_TEST_NOOP="1"),
        capture_output=True,
        text=True,
        timeout=30,
    )


def _assert_clean_dispatch(proc: subprocess.CompletedProcess, label: str):
    combined = proc.stdout + proc.stderr
    assert "Traceback" not in combined, f"{label}: unexpected traceback:\n{combined}"
    assert "ImportError" not in combined, f"{label}: import failed:\n{combined}"
    assert "relative import" not in combined, f"{label}: relative import failure:\n{combined}"
    assert proc.returncode == 0, f"{label}: exited {proc.returncode}:\n{combined}"
    assert "RECEIPTS_LOGIN_TEST_NOOP set" in combined, (
        f"{label}: the no-op marker never printed — dispatch never reached "
        f"_login():\n{combined}"
    )


def test_run_py_set_session_works_from_the_repo_root():
    # The documented form: `python3.12 skills/receipts/scripts/run.py --set-session`
    proc = _run(["skills/receipts/scripts/run.py", "--set-session"], cwd=REPO_ROOT)
    _assert_clean_dispatch(proc, "run.py --set-session (repo root)")


def test_run_py_set_session_works_from_anywhere():
    proc = _run([str(RUN_PY), "--set-session"], cwd=tempfile.mkdtemp())
    _assert_clean_dispatch(proc, "run.py --set-session (arbitrary cwd)")


def test_anthropic_py_direct_script_set_session_works():
    proc = _run([str(ANTHROPIC_PY), "--set-session"], cwd=tempfile.mkdtemp())
    _assert_clean_dispatch(proc, "sources/anthropic.py --set-session (direct script)")


def test_dash_m_set_session_works_from_the_scripts_dir():
    proc = _run(["-m", "sources.anthropic", "--set-session"], cwd=SCRIPTS)
    _assert_clean_dispatch(proc, "-m sources.anthropic --set-session")


def test_run_py_login_alias_still_dispatches_and_explains_itself():
    # The old name must not become a dead end for anyone following an older
    # doc or an older error message.
    proc = _run(["skills/receipts/scripts/run.py", "--login"], cwd=REPO_ROOT)
    _assert_clean_dispatch(proc, "run.py --login (repo root)")
    combined = proc.stdout + proc.stderr
    assert "--set-session" in combined, (
        "the alias must tell the user what it is now called: " + combined
    )


def test_anthropic_py_login_alias_still_dispatches():
    proc = _run([str(ANTHROPIC_PY), "--login"], cwd=tempfile.mkdtemp())
    _assert_clean_dispatch(proc, "sources/anthropic.py --login (direct script)")


def test_run_py_login_works_from_anywhere():
    # run.py's own imports (match, txn_queue, sources.*) resolve off the
    # script's own directory, not CWD — an absolute path must work regardless
    # of where the caller's shell happens to be sitting.
    proc = _run([str(RUN_PY), "--login"], cwd=tempfile.mkdtemp())
    _assert_clean_dispatch(proc, "run.py --login (arbitrary cwd)")


def test_anthropic_py_direct_script_login_works():
    # The exact command this bug report is about. Previously crashed with
    # "ImportError: attempted relative import with no known parent package"
    # before reaching argument dispatch — must not regress, since it's still
    # printed as a fallback in the SourceUnavailable message history, and may
    # already be sitting in a colleague's notes.
    proc = _run([str(ANTHROPIC_PY), "--login"], cwd=tempfile.mkdtemp())
    _assert_clean_dispatch(proc, "sources/anthropic.py --login (direct script)")


def test_dash_m_form_still_works_from_the_scripts_dir():
    # `python3.12 -m sources.anthropic --login` already worked before this
    # fix and must keep working. -m resolves the module off CWD, so this one
    # genuinely requires running from the scripts/ directory.
    proc = _run(["-m", "sources.anthropic", "--login"], cwd=SCRIPTS)
    _assert_clean_dispatch(proc, "-m sources.anthropic --login")


if __name__ == "__main__":
    print("Running --login invocation subprocess tests")
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f(); print(f"  ok {n}")
    print("\nAll --login invocation tests passed.")
