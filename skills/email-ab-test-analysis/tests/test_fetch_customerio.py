#!/usr/bin/env python3
"""Tests for the Customer.io fetcher's refusals and its handling of credentials.

These pin four failures that all share a shape: the fetcher produced a payload
that looked complete, so nothing downstream could tell it apart from a real one.
An unresolved segment reported as resolved, an arm with no sends stamped with
today's date and marked verified, and lifetime totals handed back for a window
that was asked for explicitly and turned out to be empty. The fourth is the
credential itself, sent to whatever host a redirect named.

Hermetic: the API is a dict of canned responses; no socket is ever opened.
"""

import io
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import fetch_customerio as fc  # noqa: E402


# --- the credential ---------------------------------------------------------

def test_the_api_key_is_not_carried_across_a_redirect(monkeypatch):
    """urllib copies a Request's ordinary headers onto the request it makes
    after a redirect, and the host check runs on the response — too late. An
    unredirected header is sent to this host and no other."""
    seen = {}

    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def geturl(self): return "https://api.customer.io/v1/campaigns/1"
        def read(self): return b'{"ok": true}'

    def fake_urlopen(req, timeout=None):
        seen["headers"] = dict(req.headers)
        seen["unredirected"] = dict(req.unredirected_hdrs)
        return FakeResponse()

    monkeypatch.setattr(fc.urllib.request, "urlopen", fake_urlopen)
    fc.get("https://api.customer.io/v1", "/campaigns/1", "SECRET-KEY")

    ordinary = json.dumps(seen["headers"])
    assert "SECRET-KEY" not in ordinary, (
        "the key is in a header urllib will replay to a redirect target")
    assert any("SECRET-KEY" in str(v) for v in seen["unredirected"].values())


# --- the cohort -------------------------------------------------------------

def test_a_campaign_whose_segments_all_failed_to_read_is_not_resolved(monkeypatch):
    """`resolved` is what the gate reads to decide it may proceed without
    asking. A campaign that names three segments and read none of them knows no
    more about its population than one that named none."""
    monkeypatch.setattr(fc, "get", lambda *a, **k: (_ for _ in ()).throw(
        SystemExit("HTTP 403")))
    camp = {"name": "c", "trigger_segment_ids": [1, 2, 3]}
    c = fc.cohort_of(camp, "9", "https://base", "key")
    assert c["segments"] == []
    assert c["resolved"] is False


def test_a_partial_segment_read_is_not_resolved_either(monkeypatch):
    def flaky(base, path, key, *a, **k):
        if path.endswith("/1"):
            return {"segment": {"name": "one", "type": "dynamic",
                                "conditions": [{"x": 1}]}}
        raise SystemExit("HTTP 403")

    monkeypatch.setattr(fc, "get", flaky)
    c = fc.cohort_of({"name": "c", "trigger_segment_ids": [1, 2]}, "9",
                     "https://base", "key")
    assert len(c["segments"]) == 1
    assert c["resolved"] is False


def test_a_full_segment_read_is_resolved(monkeypatch):
    monkeypatch.setattr(fc, "get", lambda *a, **k: {
        "segment": {"name": "s", "type": "dynamic", "conditions": [{"x": 1}]}})
    c = fc.cohort_of({"name": "c", "trigger_segment_ids": [1, 2]}, "9",
                     "https://base", "key")
    assert len(c["segments"]) == 2 and c["resolved"] is True


# --- the window -------------------------------------------------------------

class Api:
    """Canned responses for every endpoint main() reaches, keyed by path."""

    def __init__(self, messages_by_action, metrics, actions=("1", "2")):
        self.messages = messages_by_action
        self.metrics = metrics
        self.actions = actions

    def __call__(self, base, path, key, params=None, soft=False):
        if path == "/campaigns/9":
            return {"campaign": {"name": "campaign nine"}}
        if path == "/campaigns/9/actions":
            return {"actions": [{"id": a, "type": "email", "name": f"arm {a}"}
                                for a in self.actions]}
        if path.endswith("/metrics"):
            aid = path.split("/")[-2]
            return {"metric": {"series": self.metrics[aid]}}
        if path.startswith("/campaigns/9/actions/"):
            aid = path.rsplit("/", 1)[-1]
            return {"action": {"subject": f"subject {aid}", "body": "<p>b</p>"}}
        if path == fc.MESSAGES_PATH:
            aid = str(params.get("metric_action_id") or
                      params.get("action_id") or "")
            return {"messages": list(self.messages.get(aid, []))}
        raise AssertionError(f"unexpected path {path}")


def run_main(monkeypatch, tmp_path, api, argv_extra=()):
    monkeypatch.setattr(fc, "get", api)
    monkeypatch.setattr(fc, "read_key", lambda *a, **k: "key")
    written = {}
    monkeypatch.setattr(
        fc, "write_payloads",
        lambda prefix, name, metric, stats, copy, **k: written.update(
            {"stats": stats, "copy": copy}))
    monkeypatch.setattr(sys, "argv", [
        "fetch_customerio.py", "--campaign", "9",
        "--out", str(tmp_path / "out")] + list(argv_extra))
    fc.main()
    return written


def test_an_explicitly_bounded_empty_window_is_refused_not_backfilled(
        monkeypatch, tmp_path):
    """--since/--until asked about an interval. Lifetime totals answer a
    different question, and nothing in the output said so."""
    lifetime = {"sent": [1000, 1000], "delivered": [1000, 1000],
                "clicked": [50, 90], "opened": [0, 0]}
    api = Api({"1": [], "2": []}, {"1": lifetime, "2": lifetime})
    with pytest.raises(SystemExit) as e:
        run_main(monkeypatch, tmp_path, api,
                 ["--since", "1780000000", "--until", "1780600000"])
    assert "bounded window" in str(e.value)
    assert "Refusing" in str(e.value)


def test_an_unbounded_fetch_with_no_records_still_gets_the_coarse_read(
        monkeypatch, tmp_path):
    """The refusal above is about the *requested* window, not about coarse
    reads in general — those are supported, and labelled."""
    lifetime = {"sent": [1000, 1000], "delivered": [1000, 1000],
                "clicked": [50, 90], "opened": [0, 0]}
    api = Api({"1": [], "2": []}, {"1": lifetime, "2": lifetime})
    w = run_main(monkeypatch, tmp_path, api)
    assert all(a["window"]["verified"] is False for a in w["stats"])
    assert all(a["delivered"] == 2000 for a in w["stats"])


def test_an_arm_with_no_sends_is_not_stamped_with_todays_date(
        monkeypatch, tmp_path):
    """day_of(None) is time.gmtime(None), which is now. The empty arm carried
    today as both its first and last send, marked verified, and so appeared to
    overlap every arm that really did send."""
    ts = 1780000000
    msgs = [{"id": f"m{i}", "action_id": "1", "created": ts + i,
             "metrics": {"sent": ts + i, "delivered": ts + i}}
            for i in range(5)]
    live = {"sent": [5], "delivered": [5], "clicked": [1], "opened": [0]}
    never = {"sent": [0], "delivered": [0], "clicked": [0], "opened": [0]}
    api = Api({"1": msgs, "2": []}, {"1": live, "2": never})
    w = run_main(monkeypatch, tmp_path, api)

    empty = next(a for a in w["stats"] if a["id"] == "2")
    assert empty["window"]["verified"] is False
    assert "first_send_date" not in empty["window"]
    assert empty["window"]["messages"] == 0

    # And because one arm's window is unmeasured, none of them may be treated
    # as measured — see abstats.send_windows.
    sys.path.insert(0, str(SCRIPTS))
    from abstats import send_windows
    assert send_windows(w["stats"]) is None


def test_an_unsupported_period_is_rejected_before_it_is_sent(monkeypatch,
                                                             tmp_path, capsys):
    """`month` for `months` is not an error at the API: it returns every field
    null and every total zero, which reads exactly like a campaign that never
    sent. Reject the typo here, where it is still visible."""
    api = Api({"1": [], "2": []}, {"1": {}, "2": {}})
    with pytest.raises(SystemExit):
        run_main(monkeypatch, tmp_path, api, ["--period", "month"])
    assert "invalid choice" in capsys.readouterr().err
