#!/usr/bin/env python3.12
"""Tests for the Neon billing source. Parsing is pure and tested offline.

Neon Tech is the largest unautomated vendor in the receipt queue and sends
NO invoice email at all — only product updates and usage recaps. The portal
API is therefore the only source, and it takes a plain long-lived API key
(no cookie, no browser):

    GET https://console.neon.tech/api/v2/organizations/{org_id}/billing/invoices
    Authorization: Bearer $NEON_API_KEY

Everything about the API key — where it comes from, how it is protected, and
how each authentication failure is reported — lives in test_neon_key.py.
Parsing, the date rule, truncation and per-invoice download behaviour live
here.

The two shape facts this file exists to pin, both different from Anthropic's:

* `total` is a decimal STRING ("550.76"), not integer cents. Converting it
  through float() is wrong for a whole class of ordinary amounts —
  int(float("1.15") * 100) is 114, not 115 — and this is a financial record.
* The charge date is `paid_at`, falling back to `issued_at`. The card charge
  follows payment, which is what Ramp's transaction date reflects.

Hermetic by construction: no network, no auth, no browser. Every payload
below is a fixture; no real API key and no real Orb token appears anywhere.
"""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from match import BALANCED, CONFIDENT, match
from sources.base import Receipt, SourceUnavailable
from sources.neon import SOURCE
from txn_queue import Transaction

# Shape captured live from
# GET /api/v2/organizations/{org_id}/billing/invoices on 2026-08-01.
# The pdf_url token is a placeholder — no real Orb token is ever committed.
PAYLOAD = {
    "invoices": [
        {"invoice_number": "NLPHVL-00016", "issued_at": "2026-08-01T14:22:13Z",
         "paid_at": "2026-08-01T14:22:23Z", "invoice_id": "FWYWREQERmfytC4w",
         "pdf_url": "https://assets.withorb.com/invoice/16?token=PLACEHOLDER-NOT-A-TOKEN",
         "hosted_invoice_url": "https://billing.withorb.com/view/16",
         "status": "paid", "due_date": "2026-08-01T00:00:00Z",
         "total": "550.76", "currency": "USD"},
        {"invoice_number": "NLPHVL-00015", "issued_at": "2026-07-01T14:19:02Z",
         "paid_at": "2026-07-01T14:19:11Z", "invoice_id": "FWYWREQERmfytC4v",
         "pdf_url": "https://assets.withorb.com/invoice/15?token=PLACEHOLDER-NOT-A-TOKEN",
         "status": "paid", "due_date": "2026-07-01T00:00:00Z",
         "total": "425.36", "currency": "USD"},
        {"invoice_number": "NLPHVL-00014", "issued_at": "2026-06-01T14:11:44Z",
         "paid_at": "2026-06-01T14:11:50Z", "invoice_id": "FWYWREQERmfytC4u",
         "pdf_url": "https://assets.withorb.com/invoice/14?token=PLACEHOLDER-NOT-A-TOKEN",
         "status": "paid", "due_date": "2026-06-01T00:00:00Z",
         "total": "317.61", "currency": "USD"},
        # Issued but not yet paid — no card charge exists, so no receipt.
        {"invoice_number": "NLPHVL-00017", "issued_at": "2026-09-01T14:00:00Z",
         "paid_at": None, "invoice_id": "FWYWREQERmfytC4x",
         "pdf_url": "https://assets.withorb.com/invoice/17?token=PLACEHOLDER-NOT-A-TOKEN",
         "status": "issued", "due_date": "2026-09-01T00:00:00Z",
         "total": "612.40", "currency": "USD"},
    ],
}


# ---------------------------------------------------------------------------
# The money. `total` is a decimal string, and float() is not allowed near it.
# ---------------------------------------------------------------------------

def test_decimal_string_total_becomes_exact_integer_cents():
    rows = SOURCE.parse_invoices(PAYLOAD)
    by_number = {r["provenance"].split()[-1]: r for r in rows}
    assert by_number["NLPHVL-00016"]["amount_cents"] == 55076
    assert by_number["NLPHVL-00015"]["amount_cents"] == 42536
    assert by_number["NLPHVL-00014"]["amount_cents"] == 31761
    for r in rows:
        assert isinstance(r["amount_cents"], int), (
            f"amount_cents must be an int, got {type(r['amount_cents'])}"
        )


def test_float_rounding_can_never_reach_the_amount():
    # The failure this guards against, spelled out: for a whole class of
    # ordinary amounts the float round-trip lands a cent low, and this value
    # is uploaded against a real financial record and matched on exact cents.
    #   int(float("1.15")   * 100) == 114     (not 115)
    #   int(float("300.15") * 100) == 30014   (not 30015)
    assert int(float("1.15") * 100) == 114, "the premise of this test changed"
    assert int(float("300.15") * 100) == 30014, "the premise of this test changed"

    payload = {"invoices": [
        {"invoice_number": "NLPHVL-90001", "issued_at": "2026-03-01T00:00:00Z",
         "paid_at": "2026-03-01T00:00:00Z", "status": "paid",
         "pdf_url": "https://assets.withorb.com/invoice/90001?token=PLACEHOLDER",
         "total": "1.15", "currency": "USD"},
        {"invoice_number": "NLPHVL-90002", "issued_at": "2026-03-02T00:00:00Z",
         "paid_at": "2026-03-02T00:00:00Z", "status": "paid",
         "pdf_url": "https://assets.withorb.com/invoice/90002?token=PLACEHOLDER",
         "total": "300.15", "currency": "USD"},
    ]}
    rows = SOURCE.parse_invoices(payload)
    assert [r["amount_cents"] for r in rows] == [115, 30015], (
        f"decimal-string totals must convert exactly, got "
        f"{[r['amount_cents'] for r in rows]}"
    )


def test_a_whole_dollar_total_still_converts():
    payload = {"invoices": [
        {"invoice_number": "NLPHVL-90003", "issued_at": "2026-03-03T00:00:00Z",
         "paid_at": "2026-03-03T00:00:00Z", "status": "paid",
         "pdf_url": "https://assets.withorb.com/invoice/90003?token=PLACEHOLDER",
         "total": "600", "currency": "USD"},
    ]}
    assert SOURCE.parse_invoices(payload)[0]["amount_cents"] == 60000


# ---------------------------------------------------------------------------
# The date. paid_at, falling back to issued_at.
# ---------------------------------------------------------------------------

def test_iso_timestamps_become_iso_dates():
    rows = SOURCE.parse_invoices(PAYLOAD)
    assert [r["date"] for r in rows] == ["2026-08-01", "2026-07-01", "2026-06-01"]


def test_paid_at_is_preferred_over_issued_at():
    # The card charge follows payment, and Ramp's transaction date reflects
    # the charge. An invoice issued just before midnight and paid just after
    # must bind on the payment date, or it lands a day out — enough to fall
    # outside the match window at the edge.
    payload = {"invoices": [
        {"invoice_number": "NLPHVL-90004", "issued_at": "2026-04-30T23:52:00Z",
         "paid_at": "2026-05-01T00:04:00Z", "status": "paid",
         "pdf_url": "https://assets.withorb.com/invoice/90004?token=PLACEHOLDER",
         "total": "10.00", "currency": "USD"},
    ]}
    assert SOURCE.parse_invoices(payload)[0]["date"] == "2026-05-01"


def test_issued_at_is_the_fallback_when_paid_at_is_absent():
    for missing in ({}, {"paid_at": None}, {"paid_at": ""}):
        payload = {"invoices": [
            {"invoice_number": "NLPHVL-90005", "issued_at": "2026-04-30T23:52:00Z",
             "status": "paid",
             "pdf_url": "https://assets.withorb.com/invoice/90005?token=PLACEHOLDER",
             "total": "10.00", "currency": "USD", **missing},
        ]}
        rows = SOURCE.parse_invoices(payload)
        assert rows and rows[0]["date"] == "2026-04-30", (missing, rows)


# ---------------------------------------------------------------------------
# What gets dropped
# ---------------------------------------------------------------------------

def test_only_paid_invoices_yield_receipts():
    rows = SOURCE.parse_invoices(PAYLOAD)
    assert len(rows) == 3, f"the unpaid invoice must be dropped: {rows}"
    assert all("NLPHVL-00017" not in r["provenance"] for r in rows)


def test_invoices_with_no_pdf_url_are_dropped():
    for bad in (None, ""):
        payload = {"invoices": [
            {"invoice_number": "NLPHVL-90006", "issued_at": "2026-04-01T00:00:00Z",
             "paid_at": "2026-04-01T00:00:00Z", "status": "paid",
             "pdf_url": bad, "total": "10.00", "currency": "USD"},
        ]}
        assert SOURCE.parse_invoices(payload) == [], bad


def test_an_empty_or_shapeless_payload_is_not_a_crash():
    assert SOURCE.parse_invoices({}) == []
    assert SOURCE.parse_invoices({"invoices": []}) == []
    assert SOURCE.parse_invoices({"invoices": None}) == []


# ---------------------------------------------------------------------------
# Provenance — the upload idempotency key and match.py's dedupe key
# ---------------------------------------------------------------------------

def test_provenance_is_the_invoice_number_and_namespaced_to_neon():
    rows = SOURCE.parse_invoices(PAYLOAD)
    assert rows[0]["provenance"] == "neon:invoice NLPHVL-00016", rows[0]["provenance"]
    for r in rows:
        assert r["provenance"].startswith("neon:"), r["provenance"]


def test_provenance_is_unique_per_invoice():
    rows = SOURCE.parse_invoices(PAYLOAD)
    assert len({r["provenance"] for r in rows}) == len(rows)


def test_provenance_is_stable_across_runs():
    # The per-upload idempotency key derives from provenance. Anything
    # random, hashed-from-bytes, or time-based here would mint a new key on
    # every run and defeat Ramp's duplicate collapsing.
    first = [r["provenance"] for r in SOURCE.parse_invoices(PAYLOAD)]
    second = [r["provenance"] for r in SOURCE.parse_invoices(PAYLOAD)]
    assert first == second


def test_provenance_stays_distinct_for_same_day_same_amount_invoices():
    payload = {"invoices": [
        {"invoice_number": "NLPHVL-90007", "issued_at": "2026-05-05T01:00:00Z",
         "paid_at": "2026-05-05T01:00:00Z", "status": "paid",
         "pdf_url": "https://assets.withorb.com/invoice/90007?token=PLACEHOLDER",
         "total": "550.76", "currency": "USD"},
        {"invoice_number": "NLPHVL-90008", "issued_at": "2026-05-05T02:00:00Z",
         "paid_at": "2026-05-05T02:00:00Z", "status": "paid",
         "pdf_url": "https://assets.withorb.com/invoice/90008?token=PLACEHOLDER",
         "total": "550.76", "currency": "USD"},
    ]}
    rows = SOURCE.parse_invoices(payload)
    assert len({r["provenance"] for r in rows}) == 2


def test_an_invoice_with_no_invoice_number_is_not_given_a_shared_provenance():
    # A blank key would make two different invoices compare equal and
    # match.py would silently drop one of them.
    payload = {"invoices": [
        {"invoice_number": "", "issued_at": "2026-05-05T01:00:00Z",
         "paid_at": "2026-05-05T01:00:00Z", "status": "paid",
         "pdf_url": "https://assets.withorb.com/invoice/1?token=PLACEHOLDER",
         "total": "1.00", "currency": "USD"},
        {"issued_at": "2026-05-05T02:00:00Z",
         "paid_at": "2026-05-05T02:00:00Z", "status": "paid",
         "pdf_url": "https://assets.withorb.com/invoice/2?token=PLACEHOLDER",
         "total": "2.00", "currency": "USD"},
    ]}
    rows = SOURCE.parse_invoices(payload)
    assert len({r["provenance"] for r in rows}) == len(rows), (
        f"provenance collided on invoices with no invoice_number: {rows}"
    )


def test_the_fallback_provenance_is_derived_from_the_invoice_not_its_position():
    # A row-position fallback ("row-0") is not a property of the invoice: insert
    # or reorder anything earlier in the listing and the same invoice gets a new
    # provenance next run. The upload idempotency key derives from provenance,
    # so a moved invoice is uploaded again instead of collapsing as a duplicate.
    a = {"issued_at": "2026-05-05T01:00:00Z", "paid_at": "2026-05-05T01:00:00Z",
         "status": "paid", "total": "1.00", "currency": "USD",
         "pdf_url": "https://assets.withorb.com/invoice/aaa?token=PLACEHOLDER"}
    b = {"issued_at": "2026-05-05T02:00:00Z", "paid_at": "2026-05-05T02:00:00Z",
         "status": "paid", "total": "2.00", "currency": "USD",
         "pdf_url": "https://assets.withorb.com/invoice/bbb?token=PLACEHOLDER"}
    newcomer = {"invoice_number": "NLPHVL-90099",
                "issued_at": "2026-05-04T00:00:00Z",
                "paid_at": "2026-05-04T00:00:00Z", "status": "paid",
                "total": "3.00", "currency": "USD",
                "pdf_url": "https://assets.withorb.com/invoice/ccc?token=PLACEHOLDER"}

    def prov(payload, pdf):
        for r in SOURCE.parse_invoices(payload):
            if r["pdf_url"] == pdf:
                return r["provenance"]
        raise AssertionError(f"{pdf} did not survive parsing")

    before = prov({"invoices": [a, b]}, a["pdf_url"])
    after_insert = prov({"invoices": [newcomer, a, b]}, a["pdf_url"])
    after_reorder = prov({"invoices": [b, a]}, a["pdf_url"])

    assert before == after_insert == after_reorder, (
        f"the fallback provenance moved with list position: {before!r} -> "
        f"{after_insert!r} / {after_reorder!r}"
    )
    assert "row-" not in before, (
        f"provenance must not be derived from the row index: {before!r}"
    )


def test_merchants_declared():
    assert SOURCE.MERCHANTS == ("neontech",), SOURCE.MERCHANTS


# ---------------------------------------------------------------------------
# Currency. Matching compares merchant, cents and date — never currency — so a
# non-USD invoice with the same numeric total would attach the wrong document
# to a real USD charge on a financial record.
# ---------------------------------------------------------------------------

def _foreign(code="EUR", number="NLPHVL-90020"):
    return {"invoice_number": number, "issued_at": "2026-05-01T00:00:00Z",
            "paid_at": "2026-05-01T00:00:00Z", "status": "paid",
            "pdf_url": f"https://assets.withorb.com/invoice/{number}?token=PLACEHOLDER",
            "total": "550.76", "currency": code}


def test_a_non_usd_invoice_is_never_turned_into_a_receipt():
    for code in ("EUR", "GBP", "CAD", "JPY"):
        rows = SOURCE.parse_invoices({"invoices": [_foreign(code)]})
        assert rows == [], (
            f"a {code} invoice must not become a USD-comparable receipt: {rows}"
        )
    # And the other half of the rule, so the guard can't be satisfied by
    # refusing everything: USD is USD however it is spelled.
    for code in ("USD", "usd", " Usd "):
        rows = SOURCE.parse_invoices({"invoices": [
            {**_foreign(code), "invoice_number": "NLPHVL-90021"},
        ]})
        assert len(rows) == 1, f"{code!r} is USD and must be kept: {rows}"


def test_an_invoice_with_no_currency_at_all_is_refused_rather_than_assumed():
    # Every invoice observed live carried `currency`. If the field ever
    # disappears, guessing "it was probably dollars" is a guess about a
    # financial record; refusing (and announcing it) is not.
    inv = _foreign()
    inv.pop("currency")
    assert SOURCE.parse_invoices({"invoices": [inv]}) == []


def test_a_dropped_non_usd_invoice_is_announced_not_silently_excluded():
    SOURCE.truncated = None
    out = _fetch({"invoices": [_foreign("EUR"), PAYLOAD["invoices"][0]]})
    assert [r.amount_cents for r in out] == [55076], out
    note = getattr(SOURCE, "truncated", None)
    assert note, "an excluded invoice must reach the report, not vanish quietly"
    assert "usd" in note.lower(), note
    assert "EUR" in note, f"name the currency that was received: {note}"
    # Two different exclusions with two different meanings. Reporting a EUR
    # invoice as "could not be read (missing pdf_url, or an unparseable
    # total…)" sends someone looking for a parsing bug that isn't there.
    assert "could not be read" not in note.lower(), note


# ---------------------------------------------------------------------------
# A malformed listing must not read as a clean empty search
# ---------------------------------------------------------------------------

def test_a_malformed_invoices_field_is_announced_rather_than_read_as_no_results():
    # `invoices` truthy but not a list: every item is skipped, nothing is
    # "lost" by the paid-row arithmetic, no pagination hint fires — and the
    # source returns [] with truncated unset. Real Neon charges then read as
    # genuinely receipt-less. That is this codebase's recurring failure mode.
    for bad in ({"NLPHVL-00016": {"status": "paid"}}, "NLPHVL-00016", 17, True):
        SOURCE.truncated = None
        out = _fetch({"invoices": bad})
        assert out == [], out
        note = getattr(SOURCE, "truncated", None)
        assert note, f"invoices={bad!r} must set truncated, not return a clean []"
        assert type(bad).__name__ in note, (
            f"name what was received ({type(bad).__name__}): {note}"
        )


def test_a_missing_invoices_field_is_announced_but_an_empty_one_is_not():
    SOURCE.truncated = None
    assert _fetch({}) == []
    note = getattr(SOURCE, "truncated", None)
    assert note, "a 200 with no `invoices` key at all is a shape change, not zero results"

    # The other half of the rule: an account with no invoices yet is a
    # complete, correct, empty answer. Crying truncation on it would train
    # every reader to ignore the signal.
    SOURCE.truncated = None
    assert _fetch({"invoices": []}) == []
    assert getattr(SOURCE, "truncated", None) is None


# ---------------------------------------------------------------------------
# fetch(): window filtering, downloads, truncation
# ---------------------------------------------------------------------------

def _fetch(payload, since="2026-01-01", until="2026-12-31", download=None):
    with patch.object(SOURCE, "_invoices", return_value=payload):
        with patch.object(SOURCE, "_download",
                          side_effect=download or (lambda url: b"%PDF-1.4 fake")):
            return SOURCE.fetch(since, until)


def test_fetch_returns_receipts_carrying_the_downloaded_pdf():
    out = _fetch(PAYLOAD)
    assert len(out) == 3
    assert all(isinstance(r, Receipt) for r in out)
    assert all(r.merchant == "neontech" for r in out)
    assert all(r.pdf_bytes.startswith(b"%PDF") for r in out)
    assert {r.amount_cents for r in out} == {55076, 42536, 31761}


def test_fetch_filters_to_the_window_on_the_matched_date():
    out = _fetch(PAYLOAD, since="2026-07-01", until="2026-07-31")
    assert [r.date for r in out] == ["2026-07-01"], [r.date for r in out]


def test_fetch_downloads_nothing_for_invoices_outside_the_window():
    seen = []

    def spy(url):
        seen.append(url)
        return b"%PDF-1.4"

    _fetch(PAYLOAD, since="2026-08-01", until="2026-08-31", download=spy)
    assert len(seen) == 1, f"only the in-window invoice may be downloaded: {seen}"


def test_one_bad_pdf_download_does_not_discard_every_other_invoice():
    def flaky(url):
        if "/16?" in url:
            raise SourceUnavailable("Expected PDF, got b'<html>'")
        return b"%PDF-1.4"

    out = _fetch(PAYLOAD, download=flaky)
    assert len(out) == 2, f"the good invoices must survive: {out}"
    note = getattr(SOURCE, "truncated", None)
    assert note and "download" in note.lower(), (
        "a dropped invoice must reach the report, not vanish quietly: " + str(note)
    )


def test_download_requires_the_pdf_magic_bytes():
    class _R:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"<html>expired link</html>"

    with patch("urllib.request.urlopen", lambda url, timeout=None: _R()):
        try:
            SOURCE._download("https://assets.withorb.com/invoice/16?token=PLACEHOLDER")
        except SourceUnavailable as exc:
            assert "PDF" in str(exc), str(exc)
            return
    raise AssertionError("a non-PDF body must raise SourceUnavailable")


def test_download_sends_no_credential_to_the_orb_host():
    # pdf_url resolves with no authentication at all (verified 2026-08-01) —
    # it carries its own token. The Neon API key must never be sent to a
    # third-party host.
    captured = {}

    class _R:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"%PDF-1.4 fake"

    def fake_urlopen(url, timeout=None):
        captured["url"] = url
        return _R()

    with patch("urllib.request.urlopen", fake_urlopen):
        data = SOURCE._download("https://assets.withorb.com/invoice/16?token=PLACEHOLDER")

    assert data.startswith(b"%PDF")
    assert isinstance(captured["url"], str), (
        "_download must pass a bare URL — no Request, no headers, no Authorization"
    )


def test_a_complete_ordinary_response_leaves_truncated_unset():
    SOURCE.truncated = "stale value from an earlier run"
    _fetch(PAYLOAD)
    assert getattr(SOURCE, "truncated", None) is None, (
        "a complete run must clear the signal, not inherit the previous run's"
    )


def test_a_pagination_hint_in_the_payload_sets_truncated_rather_than_being_invented():
    # The response is not paginated today — 16 invoices came back in one call
    # with no cursor and no has_more. Inventing pagination would be guessing;
    # returning a silently partial list if that ever changes would be the
    # failure this codebase keeps designing against. So: notice, and say so.
    for hint in ({"has_more": True}, {"next_cursor": "abc"}, {"pagination": {"next": "x"}},
                 {"next_page": "p2"}):
        SOURCE.truncated = None
        _fetch({**PAYLOAD, **hint})
        note = getattr(SOURCE, "truncated", None)
        assert note, f"{hint} suggests more results and must set truncated"
        assert "incomplete" in note.lower(), note


def test_a_suspiciously_round_invoice_count_sets_truncated():
    invoices = [
        {"invoice_number": f"NLPHVL-{i:05d}", "issued_at": "2026-05-01T00:00:00Z",
         "paid_at": "2026-05-01T00:00:00Z", "status": "paid",
         "pdf_url": f"https://assets.withorb.com/invoice/{i}?token=PLACEHOLDER",
         "total": "1.00", "currency": "USD"}
        for i in range(100)
    ]
    SOURCE.truncated = None
    out = _fetch({"invoices": invoices})
    assert len(out) == 100, "the results it did return must still be used"
    note = getattr(SOURCE, "truncated", None)
    assert note, "exactly 100 rows looks like a page size and must be announced"
    assert "incomplete" in note.lower(), note


def test_a_paid_invoice_that_cannot_be_parsed_is_announced_not_dropped_silently():
    payload = {"invoices": [
        {"invoice_number": "NLPHVL-90009", "issued_at": "2026-05-01T00:00:00Z",
         "paid_at": "2026-05-01T00:00:00Z", "status": "paid",
         "pdf_url": "https://assets.withorb.com/invoice/9?token=PLACEHOLDER",
         "total": "not-a-number", "currency": "USD"},
        {"invoice_number": "NLPHVL-90010", "issued_at": "2026-05-02T00:00:00Z",
         "paid_at": "2026-05-02T00:00:00Z", "status": "paid",
         "pdf_url": "https://assets.withorb.com/invoice/10?token=PLACEHOLDER",
         "total": "12.34", "currency": "USD"},
    ]}
    SOURCE.truncated = None
    out = _fetch(payload)
    assert [r.amount_cents for r in out] == [1234], out
    note = getattr(SOURCE, "truncated", None)
    assert note, "a paid invoice silently disappearing is the recurring bug here"
    assert "1" in note, note


# ---------------------------------------------------------------------------
# `neon:` is a third source prefix — the cross-source collapse must still hold
# ---------------------------------------------------------------------------

def _txn(i, cents, date, merchant="Neon Tech"):
    return Transaction(id=i, merchant=merchant, amount_cents=cents, date=date)


def test_a_neon_receipt_binds_a_neon_tech_ramp_charge():
    r = _fetch(PAYLOAD, since="2026-08-01", until="2026-08-31")[0]
    pairs = match([_txn("t1", 55076, "2026-08-01")], [r])
    assert pairs[0].outcome == CONFIDENT
    assert pairs[0].receipt.provenance == "neon:invoice NLPHVL-00016"


def test_one_charge_seen_by_neon_and_gmail_still_collapses_to_one():
    # `neon:` joining `anthropic:` and `gmail:` must not disturb the
    # one-document-per-source rule: a portal invoice plus an emailed receipt
    # for the same charge is one charge, and collapses.
    neon = _fetch(PAYLOAD, since="2026-08-01", until="2026-08-31")[0]
    gmail = Receipt("neontech", 55076, "2026-08-01", b"%PDF-1.4 from-email",
                    "gmail:msg 19f94f2f9efe8c87")
    pairs = match([_txn("t1", 55076, "2026-08-01")], [neon, gmail])
    assert len(pairs) == 1 and pairs[0].outcome == CONFIDENT, pairs


def test_two_neon_invoices_for_two_charges_stay_two():
    # Two documents from ONE source means two real charges — they must not
    # collapse into one just because they look alike.
    payload = {"invoices": [
        {"invoice_number": "NLPHVL-90011", "issued_at": "2026-05-05T01:00:00Z",
         "paid_at": "2026-05-05T01:00:00Z", "status": "paid",
         "pdf_url": "https://assets.withorb.com/invoice/11?token=PLACEHOLDER",
         "total": "550.76", "currency": "USD"},
        {"invoice_number": "NLPHVL-90012", "issued_at": "2026-05-05T02:00:00Z",
         "paid_at": "2026-05-05T02:00:00Z", "status": "paid",
         "pdf_url": "https://assets.withorb.com/invoice/12?token=PLACEHOLDER",
         "total": "550.76", "currency": "USD"},
    ]}
    docs = iter([b"%PDF-1.4 one", b"%PDF-1.4 two"])
    out = _fetch(payload, download=lambda url: next(docs))
    pairs = match([_txn("t1", 55076, "2026-05-05"), _txn("t2", 55076, "2026-05-05")], out)
    assert {p.outcome for p in pairs} == {BALANCED}
    assert len({p.receipt.provenance for p in pairs}) == 2


if __name__ == "__main__":
    print("Running neon source tests")
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f(); print(f"  ok {n}")
    print("\nAll neon source tests passed.")
