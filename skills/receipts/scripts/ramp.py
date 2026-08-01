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
TIMEOUT_SECONDS = 180


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
    # Every caller catches RampError/RampAuthError and nothing else. A hung CLI
    # (TimeoutExpired) or a truncated payload (JSONDecodeError) would otherwise
    # escape as a raw traceback, skipping the controlled error path entirely —
    # and, inside the send loop, taking the run down mid-upload.
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        raise RampError(
            f"ramp {' '.join(args)} timed out after {TIMEOUT_SECONDS}s with no response. "
            f"The CLI hung — check network access to Ramp, then re-run. "
            f"Nothing was recorded for this call."
        ) from exc

    # The CLI prints a keyring banner before JSON, and reports errors as a JSON
    # object with exit code 0. Both must be handled.
    start = proc.stdout.find("{")
    if start < 0:
        raise RampError(f"No JSON from ramp {' '.join(args)}: {proc.stderr[:200]}")
    try:
        payload = json.loads(proc.stdout[start:])
    except json.JSONDecodeError as exc:
        raise RampError(
            f"Malformed JSON from ramp {' '.join(args)}: {exc}. "
            f"Output began: {proc.stdout[start:start + 200]!r}"
        ) from exc

    if payload.get("error"):
        msg = str(payload["error"].get("message", ""))
        if any(h in msg.lower() for h in AUTH_HINTS):
            raise RampAuthError(f"Ramp auth failed: {msg[:200]} — run `ramp auth login`")
        raise RampError(f"ramp {' '.join(args)}: {msg[:200]}")

    return payload.get("data", [])
