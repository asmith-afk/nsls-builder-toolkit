#!/usr/bin/env python3.12
"""Wrapper around the authenticated `ramp` CLI.

There are no Ramp Developer API credentials — that page is gated to admin/owner.
All access goes through the CLI, authenticated as the user via `ramp auth login`.
"""

import json
import os
import re
import shutil
import subprocess

RAMP_BIN = shutil.which("ramp") or os.path.expanduser("~/.local/bin/ramp")
AMOUNT = re.compile(r"(-?\$?\s?[0-9][0-9,]*\.[0-9]{2})")
AUTH_HINTS = ("not authenticated", "unauthorized", "401", "auth", "login")


class RampError(Exception):
    """The Ramp CLI refused or returned an error object."""


class RampAuthError(RampError):
    """Ramp auth is dead — run `ramp auth login`."""


def parse_amount(text: str) -> int:
    m = AMOUNT.search(str(text or ""))
    if not m:
        raise RampError(f"Cannot parse amount from {text!r}")
    amount_str = m.group(1).replace("$", "").replace(" ", "").replace(",", "")
    return round(float(amount_str) * 100)


def run(args: list[str], rationale: str) -> list[dict]:
    if not os.path.exists(RAMP_BIN):
        raise RampError(
            "`ramp` CLI not found. Install: curl -fsSL https://agents.ramp.com/install.sh | sh"
        )
    cmd = [RAMP_BIN, *args, "--rationale", rationale, "-o", "json"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

    # The CLI prints a keyring banner before JSON, and reports errors as a JSON
    # object with exit code 0. Both must be handled.
    start = proc.stdout.find("{")
    if start < 0:
        raise RampError(f"No JSON from ramp {' '.join(args)}: {proc.stderr[:200]}")
    payload = json.loads(proc.stdout[start:])

    if payload.get("error"):
        msg = str(payload["error"].get("message", ""))
        if any(h in msg.lower() for h in AUTH_HINTS):
            raise RampAuthError(f"Ramp auth failed: {msg[:200]} — run `ramp auth login`")
        raise RampError(f"ramp {' '.join(args)}: {msg[:200]}")

    return payload.get("data", [])
