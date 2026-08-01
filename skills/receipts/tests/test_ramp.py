#!/usr/bin/env python3.12
"""Tests for ramp.py — the CLI wrapper."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import ramp
from ramp import RampAuthError, RampError, parse_amount, run


class FakeProc:
    def __init__(self, stdout, returncode=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr


def test_parse_amount_handles_thousands_and_cents():
    assert parse_amount("$1,085.00") == 108500
    assert parse_amount("$214.56") == 21456
    assert parse_amount("$50.00") == 5000


def test_parse_amount_rejects_unparseable():
    try:
        parse_amount("n/a")
    except RampError:
        return
    raise AssertionError("expected RampError on unparseable amount")


def test_run_injects_rationale():
    payload = json.dumps({"schema_version": "1.0", "data": [{"ok": True}]})
    seen = {}

    def fake(cmd, **kw):
        seen["cmd"] = cmd
        return FakeProc(payload)

    with patch("subprocess.run", side_effect=fake):
        out = run(["users", "me"], rationale="why I am calling")

    assert out == [{"ok": True}]
    assert "--rationale" in seen["cmd"]
    assert "why I am calling" in seen["cmd"]
    assert "-o" in seen["cmd"] and "json" in seen["cmd"]


def test_run_raises_on_error_object_despite_exit_zero():
    payload = json.dumps({"error": {"code": 2, "message": "Missing required flags: ID"}, "data": []})
    with patch("subprocess.run", return_value=FakeProc(payload)):
        try:
            run(["transactions", "missing"], rationale="x")
        except RampError as exc:
            assert "Missing required flags" in str(exc)
            return
    raise AssertionError("error object with exit 0 must still raise")


def test_run_raises_auth_error_distinctly():
    payload = json.dumps({"error": {"code": 2, "message": "not authenticated"}, "data": []})
    with patch("subprocess.run", return_value=FakeProc(payload)):
        try:
            run(["users", "me"], rationale="x")
        except RampAuthError:
            return
    raise AssertionError("auth failures must raise RampAuthError, not bare RampError")


def test_run_tolerates_leading_banner_before_json():
    payload = "Using keyring backend: keyring\n" + json.dumps({"data": [{"ok": 1}]})
    with patch("subprocess.run", return_value=FakeProc(payload)):
        assert run(["x"], rationale="y") == [{"ok": 1}]


if __name__ == "__main__":
    print("Running ramp wrapper tests")
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f(); print(f"  ok {n}")
    print("\nAll ramp wrapper tests passed.")
