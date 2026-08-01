#!/usr/bin/env python3.12
"""Tests for the Anthropic billing source. Parsing is pure and tested offline.

Hermetic by construction: no network, no Playwright, no browser, no auth.
Playwright and ANTHROPIC_ORG_UUID absence are simulated, never required or
depended on being present/set in the test environment.
"""

import json
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


# Reproduces the live Ramp account: four separate $214.56 Anthropic charges
# within six minutes on 2026-07-23. Same date, same total — provenance must
# still be distinct per invoice, because downstream matching and the
# per-upload idempotency key both derive from it.
SAME_DAY_PAYLOAD = {
    "invoices": [
        {"total": 21456, "status": "paid", "created_ts": 1784800800,
         "invoice_pdf_url": "https://pay.stripe.com/invoice/acct_X/live_C1/pdf?s=ap"},
        {"total": 21456, "status": "paid", "created_ts": 1784800800,
         "invoice_pdf_url": "https://pay.stripe.com/invoice/acct_X/live_C2/pdf?s=ap"},
        {"total": 21456, "status": "paid", "created_ts": 1784800800,
         "invoice_pdf_url": "https://pay.stripe.com/invoice/acct_X/live_C3/pdf?s=ap"},
        {"total": 21456, "status": "paid", "created_ts": 1784800800,
         "invoice_pdf_url": "https://pay.stripe.com/invoice/acct_X/live_C4/pdf?s=ap"},
    ],
    "has_more": False,
    "next_page": None,
}


def test_provenance_is_unique_for_same_date_same_amount_invoices():
    rows = SOURCE.parse_invoices(SAME_DAY_PAYLOAD)
    assert len(rows) == 4
    assert len({r["provenance"] for r in rows}) == 4, (
        "provenance collided across same-date, same-amount invoices "
        f"— got {[r['provenance'] for r in rows]}"
    )
    # Still human-readable: date and amount stay visible.
    for r in rows:
        assert "2026-07-23" in r["provenance"]
        assert "21456" in r["provenance"]


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


def test_playwright_hint_uses_the_pep668_safe_install_command():
    # `python3.12 -m pip install playwright` fails on Homebrew Python with
    # PEP 668 "externally-managed-environment" — a hint that cannot work is
    # worse than none.
    with patch.dict(os.environ, {"ANTHROPIC_ORG_UUID": "test-org-uuid"}):
        with patch.dict(sys.modules, {"playwright": None, "playwright.sync_api": None}):
            try:
                SOURCE.fetch("2026-01-01", "2026-12-31")
            except SourceUnavailable as exc:
                assert "--break-system-packages" in str(exc), str(exc)
                return
    raise AssertionError("expected SourceUnavailable when Playwright is missing")


# ---------------------------------------------------------------------------
# Pagination — the truncation signal, and the empty-cursor spin
# ---------------------------------------------------------------------------

def _listing_pages(pages):
    """Return a fake _listing that serves `pages` in order and records calls."""
    calls = []

    def fake(page=""):
        calls.append(page)
        return pages[min(len(calls) - 1, len(pages) - 1)]

    fake.calls = calls
    return fake


def test_fetch_signals_truncation_when_the_page_guard_is_exhausted():
    # GmailSource already solved this: hit an internal cap, keep the partial
    # results, and set `truncated` so run.py can print
    # "SOURCE ANTHROPIC: TRUNCATED (...)". Exiting the loop with has_more
    # still true and no signal is a partial search that reads as a complete
    # one — receipts silently missing with no way for a user to know.
    fake = _listing_pages([{"invoices": [], "has_more": True, "next_page": "p1"},
                           {"invoices": [], "has_more": True, "next_page": "p2"},
                           {"invoices": [], "has_more": True, "next_page": "p3"}])

    def endless(page=""):
        fake.calls.append(page)
        return {"invoices": [], "has_more": True, "next_page": f"p{len(fake.calls)}"}

    with patch.object(SOURCE, "_listing", side_effect=endless):
        SOURCE.fetch("2026-01-01", "2026-12-31")

    note = getattr(SOURCE, "truncated", None)
    assert note, "exhausting the page guard with has_more still true must set `truncated`"
    assert "incomplete" in note.lower(), note
    assert len(fake.calls) <= 20, f"the guard must still cap the fetch: {len(fake.calls)}"


def test_fetch_stops_instead_of_refetching_page_one_when_next_page_is_empty():
    # has_more true with no next_page cursor left `page` at "" and re-fetched
    # the identical first page up to 20 times — 20 Playwright browser
    # launches, same results, no progress, no signal.
    calls = []

    def stuck(page=""):
        calls.append(page)
        return {"invoices": [], "has_more": True, "next_page": None}

    with patch.object(SOURCE, "_listing", side_effect=stuck):
        SOURCE.fetch("2026-01-01", "2026-12-31")

    assert len(calls) == 1, (
        f"a missing next_page cursor must stop the loop, not re-fetch page 1 "
        f"{len(calls)} times"
    )
    assert getattr(SOURCE, "truncated", None), (
        "stopping early because the cursor went missing is still a partial "
        "search and must be announced"
    )


def test_fetch_leaves_truncated_unset_on_a_complete_pagination():
    SOURCE.truncated = "stale value from an earlier run"
    with patch.object(SOURCE, "_listing", side_effect=_listing_pages([PAYLOAD])):
        with patch.object(SOURCE, "_download", return_value=b"%PDF-1.4"):
            out = SOURCE.fetch("2026-01-01", "2026-12-31")
    assert len(out) == 2
    assert getattr(SOURCE, "truncated", None) is None, (
        "a complete run must clear the signal, not inherit the previous run's"
    )


# ---------------------------------------------------------------------------
# Per-invoice download failures
# ---------------------------------------------------------------------------

def test_one_bad_pdf_url_does_not_discard_every_other_invoice():
    # Building the whole Receipt list in one comprehension means a single
    # expired URL, non-PDF response, or network blip throws away every valid
    # invoice already gathered — the entire Anthropic source goes dark
    # because of one stale row.
    def flaky(url):
        if "live_A" in url:
            raise SourceUnavailable("Expected PDF, got b'<html>'")
        return b"%PDF-1.4"

    with patch.object(SOURCE, "_listing", side_effect=_listing_pages([PAYLOAD])):
        with patch.object(SOURCE, "_download", side_effect=flaky):
            out = SOURCE.fetch("2026-01-01", "2026-12-31")

    assert len(out) == 1, f"the good invoice must survive: {out}"
    assert out[0].amount_cents == 108500


def test_failed_downloads_are_surfaced_not_swallowed():
    def flaky(url):
        if "live_A" in url:
            raise TimeoutError("read timed out")
        return b"%PDF-1.4"

    with patch.object(SOURCE, "_listing", side_effect=_listing_pages([PAYLOAD])):
        with patch.object(SOURCE, "_download", side_effect=flaky):
            SOURCE.fetch("2026-01-01", "2026-12-31")

    note = getattr(SOURCE, "truncated", None)
    assert note, "a dropped invoice must reach the report, not vanish quietly"
    assert "1" in note and "download" in note.lower(), note


# ---------------------------------------------------------------------------
# 403 vs session expiry
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status):
        self.status = status


class _FakePage:
    def __init__(self, status, body):
        self._status, self._body = status, body

    def goto(self, url):
        return _FakeResponse(self._status)

    def inner_text(self, selector):
        return self._body


class _FakeContext:
    def __init__(self, page):
        self._page = page
        self.closed = False

    def new_page(self):
        return self._page

    def close(self):
        self.closed = True


class _FakeChromium:
    def __init__(self, ctx):
        self._ctx = ctx

    def launch_persistent_context(self, profile, headless=True):
        return self._ctx


class _FakePlaywright:
    def __init__(self, status, body="{}"):
        self.chromium = _FakeChromium(_FakeContext(_FakePage(status, body)))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _playwright_modules(status, body="{}"):
    """sys.modules stand-ins so `from playwright.sync_api import sync_playwright`
    resolves without Playwright installed and without launching a browser."""
    import types
    pkg = types.ModuleType("playwright")
    api = types.ModuleType("playwright.sync_api")
    api.sync_playwright = lambda: _FakePlaywright(status, body)
    pkg.sync_api = api
    return {"playwright": pkg, "playwright.sync_api": api}


def test_403_says_not_an_org_admin_instead_of_telling_you_to_log_in_again():
    # A non-admin org member gets 403. Telling them the session expired sends
    # them to re-run --login, which can never fix it, and buries the one
    # reason they could act on.
    with patch.dict(os.environ, {"ANTHROPIC_ORG_UUID": "test-org-uuid"}):
        with patch.dict(sys.modules, _playwright_modules(403)):
            try:
                SOURCE._listing()
            except SourceUnavailable as exc:
                msg = str(exc)
                assert "admin" in msg.lower(), f"403 must name the real cause: {msg}"
                assert "--login" not in msg, (
                    "re-authenticating cannot fix a permissions problem: " + msg
                )
                assert "expired" not in msg.lower(), msg
                return
    raise AssertionError("a 403 listing must raise SourceUnavailable")


def test_401_still_reports_an_expired_session():
    with patch.dict(os.environ, {"ANTHROPIC_ORG_UUID": "test-org-uuid"}):
        with patch.dict(sys.modules, _playwright_modules(401)):
            try:
                SOURCE._listing()
            except SourceUnavailable as exc:
                assert "--login" in str(exc), str(exc)
                return
    raise AssertionError("a 401 listing must raise SourceUnavailable")


def test_200_listing_parses_normally():
    with patch.dict(os.environ, {"ANTHROPIC_ORG_UUID": "test-org-uuid"}):
        with patch.dict(sys.modules, _playwright_modules(200, json.dumps(PAYLOAD))):
            assert SOURCE._listing()["invoices"][0]["total"] == 21456


if __name__ == "__main__":
    print("Running anthropic source tests")
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f(); print(f"  ok {n}")
    print("\nAll anthropic source tests passed.")
