#!/usr/bin/env python3.12
"""Anthropic (claude.ai) billing source.

Anthropic emails receipts for the subscription charges but NOTHING for
usage-credit auto-recharges — those are 15 of the 22 gaps. The listing call
needs a claude.ai session; the PDF URLs it returns are Stripe secret-token URLs
that resolve with no authentication at all (verified 2026-08-01).

ANTHROPIC_ORG_UUID must be set in the environment — this module ships in an
org-wide toolkit and must never default to one specific organisation's ID.
Playwright is an optional runtime prerequisite (not a declared dependency of
this toolkit); when it's missing, this source degrades to SourceUnavailable
instead of raising ModuleNotFoundError, so a missing Playwright install only
takes out the Anthropic source, not the whole /receipts run.
"""

import datetime as dt
import hashlib
import json
import os
import urllib.request

from .base import Receipt, SourceUnavailable

LISTING = "https://claude.ai/api/stripe/{org}/invoices?limit=100&page={page}"
PROFILE = os.path.expanduser("~/.claude-receipts-profile")


class AnthropicSource:
    MERCHANTS = ("anthropic", "anthropicpbc")

    def parse_invoices(self, payload: dict) -> list[dict]:
        rows = []
        for inv in payload.get("invoices", []):
            if inv.get("status") != "paid" or not inv.get("invoice_pdf_url"):
                continue
            date = dt.datetime.fromtimestamp(inv["created_ts"], dt.UTC).date().isoformat()
            # invoice_pdf_url is unique per invoice (…/live_A/pdf vs …/live_B/pdf).
            # Fold a stable, deterministic slice of it into provenance so that
            # same-date, same-amount invoices — e.g. four $214.56 Anthropic
            # charges within six minutes — don't collide. Must be stable across
            # runs (never random/time-based): the per-upload idempotency key
            # derives from provenance, and a changing key would defeat Ramp's
            # duplicate collapsing.
            token = hashlib.sha1(inv["invoice_pdf_url"].encode()).hexdigest()[:8]
            rows.append({
                "amount_cents": int(inv["total"]),
                "date": date,
                "pdf_url": inv["invoice_pdf_url"],
                "provenance": f"anthropic:invoice {date} {inv['total']} {token}",
            })
        return rows

    def _listing(self, page: str = "") -> dict:
        org = os.environ.get("ANTHROPIC_ORG_UUID")
        if not org:
            raise SourceUnavailable(
                "ANTHROPIC_ORG_UUID is not set. Set it to your claude.ai "
                "organization UUID (Settings > Organization) before running "
                "the Anthropic source."
            )

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise SourceUnavailable(
                "Playwright is required for the Anthropic source. Install with: "
                "python3.12 -m pip install playwright && python3.12 -m playwright install chromium"
            ) from exc

        url = LISTING.format(org=org, page=page)
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(PROFILE, headless=True)
            try:
                pg = ctx.new_page()
                resp = pg.goto(url)
                if resp is None or resp.status != 200:
                    raise SourceUnavailable(
                        "claude.ai session expired. Run: python3.12 "
                        "skills/receipts/scripts/sources/anthropic.py --login"
                    )
                return json.loads(pg.inner_text("pre") or "{}")
            finally:
                ctx.close()

    @staticmethod
    def _download(url: str) -> bytes:
        with urllib.request.urlopen(url, timeout=60) as resp:
            data = resp.read()
        if not data.startswith(b"%PDF"):
            raise SourceUnavailable(f"Expected PDF from {url[:60]}…, got {data[:16]!r}")
        return data

    def fetch(self, since: str, until: str) -> list[Receipt]:
        rows, page, guard = [], "", 0
        while guard < 20:
            payload = self._listing(page)
            rows.extend(self.parse_invoices(payload))
            if not payload.get("has_more"):
                break
            page = payload.get("next_page") or ""
            guard += 1

        return [
            Receipt(
                merchant="anthropic",
                amount_cents=r["amount_cents"],
                date=r["date"],
                pdf_bytes=self._download(r["pdf_url"]),
                provenance=r["provenance"],
            )
            for r in rows
            if since <= r["date"] <= until
        ]


SOURCE = AnthropicSource()


def _login():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(PROFILE, headless=False)
        ctx.new_page().goto("https://claude.ai/login")
        input("Sign in, then press Enter here to save the session… ")
        ctx.close()


if __name__ == "__main__":
    import sys
    if "--login" in sys.argv:
        _login()
