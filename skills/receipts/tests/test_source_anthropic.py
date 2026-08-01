#!/usr/bin/env python3.12
"""Tests for the Anthropic billing source. Parsing is pure and tested offline.

Hermetic by construction: no network, no Playwright, no browser, no auth.
Playwright and ANTHROPIC_ORG_UUID absence are simulated, never required or
depended on being present/set in the test environment.
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from sources.anthropic import SOURCE
from sources.base import SourceUnavailable

# Shape captured live from GET /api/stripe/{org}/invoices on 2026-08-01.
PAYLOAD = {
    "invoices": [
        {"total": 21456, "status": "paid", "created_ts": 1784806673,
         "invoice_pdf_url": "https://pay.stripe.com/invoice/acct_X/live_A/pdf?s=ap"},
        {"total": 108500, "status": "paid", "created_ts": 1784501642,
         "invoice_pdf_url": "https://pay.stripe.com/invoice/acct_X/live_B/pdf?s=ap"},
        {"total": 9999, "status": "draft", "created_ts": 1784501000,
         "invoice_pdf_url": None},
    ],
    "has_more": False,
    "next_page": None,
}


def test_amounts_stay_integer_cents():
    rows = SOURCE.parse_invoices(PAYLOAD)
    assert rows[0]["amount_cents"] == 21456
    assert rows[1]["amount_cents"] == 108500


def test_created_ts_becomes_iso_date():
    rows = SOURCE.parse_invoices(PAYLOAD)
    assert rows[1]["date"] == "2026-07-19", rows[1]["date"]


def test_unpaid_or_pdfless_invoices_dropped():
    rows = SOURCE.parse_invoices(PAYLOAD)
    assert len(rows) == 2
    assert all(r["pdf_url"] for r in rows)


def test_provenance_is_unique_per_invoice():
    rows = SOURCE.parse_invoices(PAYLOAD)
    assert rows[0]["provenance"] != rows[1]["provenance"]
    assert "anthropic" in rows[0]["provenance"]


def test_merchants_declared():
    assert "anthropic" in SOURCE.MERCHANTS


def test_fetch_raises_source_unavailable_when_org_uuid_unset():
    # No network call should ever be reached: the org-uuid check must come
    # before anything that touches Playwright or the network.
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("ANTHROPIC_ORG_UUID", None)
        try:
            SOURCE.fetch("2026-01-01", "2026-12-31")
        except SourceUnavailable as exc:
            assert "ANTHROPIC_ORG_UUID" in str(exc)
            return
    raise AssertionError("fetch() must raise SourceUnavailable when ANTHROPIC_ORG_UUID is unset")


def test_fetch_raises_source_unavailable_not_module_not_found_when_playwright_missing():
    # Simulate Playwright being absent regardless of whether it's actually
    # installed on the machine running this test, per hermeticity rules.
    with patch.dict(os.environ, {"ANTHROPIC_ORG_UUID": "test-org-uuid"}):
        with patch.dict(sys.modules, {"playwright": None, "playwright.sync_api": None}):
            try:
                SOURCE.fetch("2026-01-01", "2026-12-31")
            except ModuleNotFoundError:
                raise AssertionError(
                    "fetch() must raise SourceUnavailable, not let "
                    "ModuleNotFoundError propagate and kill the whole run"
                )
            except SourceUnavailable as exc:
                assert "playwright" in str(exc).lower() or "Playwright" in str(exc)
                return
    raise AssertionError("fetch() must raise SourceUnavailable when Playwright is unavailable")


if __name__ == "__main__":
    print("Running anthropic source tests")
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f(); print(f"  ok {n}")
    print("\nAll anthropic source tests passed.")
