#!/usr/bin/env python3.12
"""Tests for ramp.py — the CLI wrapper."""

import json
import subprocess
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


def test_parse_amount_handles_negative_amounts():
    assert parse_amount("-$50.00") == -5000
    assert parse_amount("-$1,085.00") == -108500
    assert parse_amount("-$214.56") == -21456


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

    with patch("os.path.exists", return_value=True):
        with patch("subprocess.run", side_effect=fake):
            out = run(["users", "me"], rationale="why I am calling")

    assert out == [{"ok": True}]
    assert "--rationale" in seen["cmd"]
    assert "why I am calling" in seen["cmd"]
    assert "-o" in seen["cmd"] and "json" in seen["cmd"]


def test_run_raises_on_error_object_despite_exit_zero():
    payload = json.dumps({"error": {"code": 2, "message": "Missing required flags: ID"}, "data": []})
    with patch("os.path.exists", return_value=True):
        with patch("subprocess.run", return_value=FakeProc(payload)):
            try:
                run(["transactions", "missing"], rationale="x")
            except RampError as exc:
                assert "Missing required flags" in str(exc)
                return
    raise AssertionError("error object with exit 0 must still raise")


def test_run_raises_auth_error_distinctly():
    payload = json.dumps({"error": {"code": 2, "message": "not authenticated"}, "data": []})
    with patch("os.path.exists", return_value=True):
        with patch("subprocess.run", return_value=FakeProc(payload)):
            try:
                run(["users", "me"], rationale="x")
            except RampAuthError:
                return
    raise AssertionError("auth failures must raise RampAuthError, not bare RampError")


def test_run_tolerates_leading_banner_before_json():
    payload = "Using keyring backend: keyring\n" + json.dumps({"data": [{"ok": 1}]})
    with patch("os.path.exists", return_value=True):
        with patch("subprocess.run", return_value=FakeProc(payload)):
            assert run(["x"], rationale="y") == [{"ok": 1}]


def test_run_wraps_a_cli_timeout_as_ramp_error():
    # subprocess.run(timeout=180) raises TimeoutExpired, which is a
    # SubprocessError — not a RampError. Every caller catches only
    # RampError/RampAuthError, so a hung CLI escapes as a raw traceback
    # instead of the controlled error path that prints a usable message.
    with patch("os.path.exists", return_value=True):
        with patch("subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="ramp", timeout=180)):
            try:
                run(["transactions", "list"], rationale="x")
            except RampError as exc:
                msg = str(exc)
                assert "timed out" in msg.lower(), f"must say it timed out: {msg}"
                assert "180" in msg, f"must say how long it waited: {msg}"
                assert "transactions list" in msg, f"must name what timed out: {msg}"
                return
    raise AssertionError("a CLI timeout must surface as RampError, not TimeoutExpired")


def test_run_wraps_malformed_json_as_ramp_error():
    # The CLI can emit a truncated or otherwise malformed payload. json.loads
    # then raises JSONDecodeError (a ValueError), which no caller catches.
    with patch("os.path.exists", return_value=True):
        with patch("subprocess.run", return_value=FakeProc('{"data": [{"ok"')):
            try:
                run(["users", "me"], rationale="x")
            except RampError as exc:
                msg = str(exc)
                assert "users me" in msg, f"must name the command: {msg}"
                assert "json" in msg.lower(), f"must say the payload was bad JSON: {msg}"
                return
    raise AssertionError("malformed JSON must surface as RampError, not JSONDecodeError")


def test_run_raises_when_binary_missing():
    with patch("os.path.exists", return_value=False):
        try:
            run(["users", "me"], rationale="x")
        except RampError as exc:
            assert "ramp` CLI not found" in str(exc)
            assert "install.sh" in str(exc)
            return
    raise AssertionError("run() must raise RampError when binary is missing")


if __name__ == "__main__":
    print("Running ramp wrapper tests")
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f(); print(f"  ok {n}")
    print("\nAll ramp wrapper tests passed.")
