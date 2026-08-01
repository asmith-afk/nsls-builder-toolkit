#!/usr/bin/env python3.12
"""Live smoke test — NOT part of the unit suite. Hits real endpoints.

Catches Anthropic changing the invoices endpoint shape and Ramp auth dying —
the two most likely ways this skill breaks in production, silently, between
runs.

Not every machine that runs this has every prerequisite: a live `ramp auth
login` session is required, but `ANTHROPIC_ORG_UUID` + Playwright are not
always present (e.g. a fresh laptop, CI, a colleague who only uses the Gmail
source). A missing prerequisite is reported as SKIPPED and does not fail the
run — that's an environment gap, not a code regression. Only a genuinely
unexpected failure (auth alive but rejected, a shape that changed, a PDF that
isn't a PDF) exits non-zero. Every check prints exactly what it verified, or
says plainly that it verified nothing — this script must never report "OK"
for something it didn't actually check.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from ramp import RampError, run
from sources.anthropic import SOURCE
from sources.base import SourceUnavailable


def check_ramp() -> bool:
    """The Ramp half: confirm the CLI is installed and auth is alive."""
    try:
        me = run(["users", "me"], rationale="Smoke test: confirm Ramp auth is alive")[0]
    except RampError as exc:
        print(f"FAIL     ramp auth: {exc}")
        return False
    except Exception as exc:
        print(f"FAIL     ramp auth: unexpected error — {exc}")
        return False
    print(f"OK       ramp auth: {me['users'][0]['email']}")
    return True


def check_anthropic() -> bool:
    """The Anthropic half: confirm the invoices endpoint shape and that a
    returned PDF URL still resolves to an actual PDF.

    Requires ANTHROPIC_ORG_UUID and Playwright (chromium). Either being
    absent is SourceUnavailable, which is a prerequisite gap, not a failure
    of this test — it prints the remedy and returns True (nothing to fail).
    """
    try:
        payload = SOURCE._listing()
    except SourceUnavailable as exc:
        print(f"SKIPPED  anthropic source: {exc}")
        return True
    except Exception as exc:
        print(f"FAIL     anthropic source: unexpected error — {exc}")
        return False

    invoices = payload.get("invoices")
    if not (isinstance(invoices, list) and invoices):
        print(f"FAIL     anthropic source: invoices endpoint shape changed — got {payload!r:.200}")
        return False

    rows = SOURCE.parse_invoices(payload)
    if not rows:
        print("FAIL     anthropic source: parse_invoices dropped everything — field names may have changed")
        return False

    try:
        pdf = SOURCE._download(rows[0]["pdf_url"])
    except SourceUnavailable as exc:
        print(f"FAIL     anthropic source: {exc}")
        return False

    if not pdf.startswith(b"%PDF"):
        print(f"FAIL     anthropic source: not a PDF: {pdf[:16]!r}")
        return False

    print(f"OK       anthropic source: {len(invoices)} invoices, {len(rows)} paid; "
          f"downloaded {len(pdf):,} bytes")
    return True


def main() -> int:
    results = [check_ramp(), check_anthropic()]
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
