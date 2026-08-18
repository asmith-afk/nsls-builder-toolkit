#!/usr/bin/env python3
"""Tests for windows rebuilt from per-send records.

Two wrong verdicts produced this file, and both came from the same place: the
metric period arrays are monthly for anything older than a quarter, and a
monthly bucket cannot show what happened inside a month. One test read as a
decisive win because a short-lived arm was scored against a full bucket of its
rival sending alone. Another reported a concurrent window for two arms whose
sends never touched, one stopping a day before the other started — they shared
nothing but a calendar bucket.

Both are shape errors rather than arithmetic ones, so every test here works on
shapes: an arm that stops mid-bucket, two arms that are adjacent but never
simultaneous, a pull that silently stopped early, and a fetch with no per-send
records at all.

Hermetic: no network. The API is a fake that reproduces the three behaviours
that actually bite — newest-first ordering, a hard page cap, and a cursor that
can stall.
"""

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from abstats import analyse, declaration_by_timestamp, render, \
    scored_window, send_windows, window_intersection  # noqa: E402
from fetch_customerio import daily_counts, fetch_arm_messages, on_axis, \
    reconcile, shared_axis  # noqa: E402

DAY = 86400


def msg(i, ts, **metrics):
    m = {"sent": ts}
    m.update(metrics)
    return {"id": f"m{i}", "action_id": "1", "created": ts, "metrics": m}


def arm(name, dates, sent, delivered=None, clicked=None, first=None, last=None,
        verified=True):
    """A payload arm carrying a dated daily series, as the fetcher emits it."""
    delivered = delivered if delivered is not None else sent
    clicked = clicked if clicked is not None else [0] * len(sent)
    a = {
        "id": name, "name": name, "subject": f"<subject for {name}>",
        "delivered": sum(delivered), "clicked": sum(clicked),
        "opened": 0, "converted": 0, "unsubscribed": 0, "spammed": 0,
        "periods": {"sent": sent, "delivered": delivered, "clicked": clicked},
        "period_dates": dates, "period_resolution": "day",
    }
    if verified:
        live = [d for d, v in zip(dates, sent) if v]
        a["window"] = {
            "verified": True,
            "first_send": first if first is not None else _ts(live[0]),
            "last_send": last if last is not None else _ts(live[-1]) + 3600,
            "first_send_date": live[0], "last_send_date": live[-1],
            "source": "per-send records",
        }
    return a


def _ts(date):
    import calendar
    import time as _t
    return calendar.timegm(_t.strptime(date, "%Y-%m-%d"))


# Dates are asserted on literally throughout, so the start of the fixture month
# is derived rather than pasted as a magic number.
T0 = _ts("2026-06-01")


def days(start_ts, n):
    import time as _t
    return [_t.strftime("%Y-%m-%d", _t.gmtime(start_ts + i * DAY))
            for i in range(n)]


class FakeAPI:
    """The three API behaviours that produced the defect.

    Newest-first, because that is what makes a capped page truncate the OLD end
    — the start of a flight, where a challenger arm's whole life may sit. A hard
    cap that silently clamps an over-large `limit`. And an optionally stalling
    cursor, because the internal API was observed re-serving page one forever.
    """

    def __init__(self, messages, cap=3, stall=False):
        self.messages = sorted(messages, key=lambda m: m["created"],
                               reverse=True)
        self.cap = cap
        self.stall = stall
        self.calls = 0

    def __call__(self, params):
        self.calls += 1
        if self.calls > 200:
            raise AssertionError("runaway paging")
        rows = self.messages
        if params.get("end_ts") is not None:
            rows = [m for m in rows if m["created"] <= int(params["end_ts"])]
        if params.get("start_ts") is not None:
            rows = [m for m in rows if m["created"] >= int(params["start_ts"])]
        offset = int(params.get("start") or 0)
        limit = min(int(params.get("limit", self.cap)), self.cap)
        page = rows[offset:offset + limit]
        nxt = None
        if offset + limit < len(rows):
            nxt = str(0 if self.stall else offset + limit)
        return {"messages": page, "next": nxt}


# --- paging: the page cap truncates the start of a flight -------------------

def test_it_pages_past_the_cap_instead_of_reading_page_one():
    """One page is the newest slice, and the oldest end is where a flight starts."""
    api = FakeAPI([msg(i, T0 + i * DAY) for i in range(10)], cap=3)
    got = fetch_arm_messages(api, "1", page_size=3)
    assert len(got) == 10
    assert min(m["created"] for m in got) == T0


def test_a_stalled_cursor_falls_back_to_walking_the_window():
    """A cursor that re-serves page one would otherwise loop to the cap."""
    api = FakeAPI([msg(i, T0 + i * DAY) for i in range(10)], cap=3, stall=True)
    got = fetch_arm_messages(api, "1", page_size=3)
    assert len(got) == 10


def test_it_refuses_when_a_full_page_shares_one_timestamp():
    """A batch send can put a whole page into one second, leaving no window to
    split. The counts would be short by an unknown amount, so this fails rather
    than returning them."""
    api = FakeAPI([msg(i, T0) for i in range(10)], cap=3, stall=True)
    with pytest.raises(SystemExit) as e:
        fetch_arm_messages(api, "1", page_size=3)
    assert "do not score this" in str(e.value)


def test_it_refuses_to_stop_early_on_a_huge_arm():
    """Stopping at a cap returns numbers that look complete."""
    api = FakeAPI([msg(i, T0 + i) for i in range(50)], cap=10)
    with pytest.raises(SystemExit) as e:
        fetch_arm_messages(api, "1", page_size=10, max_messages=20)
    assert "Narrow the window" in str(e.value)


# --- the reconciliation gate ------------------------------------------------

def test_a_truncated_pull_fails_the_reconciliation_gate():
    """Counting only what page one returned looks like a shorter test."""
    pulled = [msg(i, T0 + i * DAY, delivered=T0, clicked=T0) for i in range(3)]
    derived = daily_counts(pulled)
    rec = reconcile(derived, {"delivered": 30, "clicked": 30})
    assert not rec["ok"]
    assert any("counted 3 of 30" in s for s in rec["short"])


def test_a_complete_pull_passes_the_gate():
    pulled = [msg(i, T0 + i * DAY, delivered=T0, clicked=T0) for i in range(30)]
    rec = reconcile(daily_counts(pulled), {"delivered": 30, "clicked": 30})
    assert rec["ok"] and not rec["short"]


def test_more_records_than_the_series_covers_is_reported_not_fatal():
    """The metric series reaches back a fixed number of buckets; an older arm
    has real sends it no longer covers. That is not a paging failure."""
    pulled = [msg(i, T0 + i * DAY, delivered=T0) for i in range(30)]
    rec = reconcile(daily_counts(pulled), {"delivered": 20})
    assert rec["ok"]
    assert rec["over"]


def test_engagement_is_counted_against_the_day_it_was_sent():
    """A click three days later belongs to the send that earned it. Filing it
    under the click's own day would score it against a different denominator."""
    sent_at = T0
    derived = daily_counts([msg(1, sent_at, delivered=sent_at,
                                clicked=sent_at + 3 * DAY)])
    assert derived["per_day"]["clicked"] == {"2026-06-01": 1}


# --- alignment: index i must mean the same day for every arm ----------------

def test_arms_are_aligned_by_date_not_by_position():
    """Aligned by position, an arm that started a week later has its first day
    compared against the other's first day, and the overlap scan finds a window
    that never existed."""
    a = {"2026-06-01": 5, "2026-06-02": 5}
    b = {"2026-06-02": 7, "2026-06-03": 7}
    axis = shared_axis([a, b])
    assert axis == ["2026-06-01", "2026-06-02", "2026-06-03"]
    assert on_axis(a, axis) == [5, 5, 0]
    assert on_axis(b, axis) == [0, 7, 7]


# --- failure 1: an arm that stops mid-bucket --------------------------------

def build_stops_early():
    """A challenger that lived 8 days inside a month its rival ran the whole of."""
    dates = days(T0, 30)
    control_sent = [1000] * 30
    control_clicks = [10] * 30
    chal_sent = [1000] * 8 + [0] * 22
    chal_clicks = [10] * 8 + [0] * 22
    return {"test": "stops early", "primary_metric": "clicked", "arms": [
        arm("control", dates, control_sent, clicked=control_clicks),
        arm("challenger", dates, chal_sent, clicked=chal_clicks),
    ]}


def test_the_scored_window_is_the_real_send_range_not_the_bucket():
    """A month-long bucket is not the window; eight days of shared sending is.

    The challenger's last send lands at 01:00 on the 8th, so the 8th is only
    partly inside the measured intersection — the control's sends over the rest
    of that day were randomised against nothing. Where a declared winner is
    detected the partly-covered boundary period is dropped, which is why this
    reads to the 7th rather than to the 8th.
    """
    r = analyse(build_stops_early(), cohort_answered="same")
    w = r["scored_window"]
    assert w["from"] == "2026-06-01" and w["to"] == "2026-06-07"
    assert w["days"] == 7 and w["verified"]
    assert any("BOUNDARY PERIOD(S) DROPPED" in x for x in r["warnings"])


def test_post_declaration_volume_is_excluded_from_the_comparison():
    """The whole defect in one assertion: the surviving arm's solo sends must
    not sit in the denominator it is scored on. That holds inside the boundary
    day as well as after it — hence 7 days rather than 8."""
    r = analyse(build_stops_early(), cohort_answered="same")
    c = r["comparisons"][0]
    assert c["a_n"] == 7000 and c["b_n"] == 7000
    assert r["basis"] == "overlap"


def test_a_clean_simultaneous_flight_keeps_its_last_day():
    """The clip must not fire on jitter. Arms almost never stop on the same
    second, so a rule that dropped every partly-covered boundary period would
    cost a clean eight-day test its eighth day to remove a couple of hours."""
    dates = days(T0, 8)
    payload = {"test": "clean", "primary_metric": "clicked", "arms": [
        arm("a", dates, [1000] * 8, clicked=[10] * 8),
        arm("b", dates, [1000] * 8, clicked=[12] * 8,
            last=_ts("2026-06-08") + 7200),
    ]}
    r = analyse(payload, cohort_answered="same")
    assert r["scored_window"]["to"] == "2026-06-08"
    assert r["scored_window"]["days"] == 8
    assert not any("BOUNDARY PERIOD(S)" in x for x in r["warnings"])


def test_the_declaration_is_reported_with_real_dates():
    r = analyse(build_stops_early(), cohort_answered="same")
    d = r["declared_winner"]
    assert d and d["stopper"] == "challenger" and d["runner"] == "control"
    assert d["stopped"] == "2026-06-08" and d["continued_to"] == "2026-06-30"
    assert any("DECLARED WINNER:" in w for w in r["warnings"])


def test_trailing_minutes_are_not_reported_as_a_declared_winner():
    """Arms rarely stop on the same second. Jitter must not read as a call."""
    dates = days(T0, 10)
    payload = {"test": "jitter", "primary_metric": "clicked", "arms": [
        arm("a", dates, [1000] * 10, clicked=[10] * 10),
        arm("b", dates, [1000] * 10, clicked=[10] * 10,
            last=_ts("2026-06-10") + 7200),
    ]}
    assert declaration_by_timestamp(payload["arms"],
                                    send_windows(payload["arms"])) is None


# --- failure 2: adjacent arms that never sent together ----------------------

def build_adjacent():
    """One arm's last send is the 18th; the other's first is the 19th."""
    dates = days(T0, 30)
    a_sent = [1000] * 18 + [0] * 12
    b_sent = [0] * 18 + [1000] * 12
    return {"test": "adjacent", "primary_metric": "clicked", "arms": [
        arm("earlier", dates, a_sent, clicked=[20] * 18 + [0] * 12),
        arm("later", dates, b_sent, clicked=[0] * 18 + [10] * 12),
    ]}


def test_adjacent_arms_are_not_reported_as_concurrent():
    r = analyse(build_adjacent(), cohort_answered="same")
    assert r["overlap_periods"] == []
    assert any(w.startswith("NO OVERLAP:") for w in r["warnings"])
    text = render(r)
    assert "concurrent period" not in text
    assert "concurrent window" not in text


def test_the_no_overlap_warning_names_the_two_dates():
    r = analyse(build_adjacent(), cohort_answered="same")
    w = next(x for x in r["warnings"] if x.startswith("NO OVERLAP:"))
    assert "2026-06-18" in w and "2026-06-19" in w


def test_a_sequential_comparison_is_still_scored():
    """Non-overlapping arms are read, with the limitation stated. Refusing to
    compare them would throw away the only evidence there is."""
    r = analyse(build_adjacent(), cohort_answered="same")
    c = r["comparisons"][0]
    assert r["basis"] == "lifetime"
    assert c["a_n"] == 18000 and c["b_n"] == 12000
    assert c["a_rate"] > 0 and c["b_rate"] > 0
    w = next(x for x in r["warnings"] if x.startswith("NO OVERLAP:"))
    assert "sequential" in w and "seasonality" in w


def test_a_shared_month_is_not_an_intersection():
    """The unit under the phantom overlap: same bucket, no shared time."""
    windows = send_windows(build_adjacent()["arms"])
    assert window_intersection(windows) is None


# --- the coarse fallback must say that it is coarse -------------------------

def build_monthly():
    """What the fetcher emits when per-send records cannot be read."""
    a = {"id": "a", "name": "a", "subject": "<subject a>",
         "delivered": 30000, "clicked": 300, "opened": 0,
         "periods": {"delivered": [30000], "clicked": [300]},
         "period_resolution": "month",
         "window": {"verified": False, "source": "period arrays",
                    "why": "HTTP 404"}}
    b = dict(a, id="b", name="b", delivered=8000, clicked=95,
             periods={"delivered": [8000], "clicked": [95]})
    return {"test": "coarse", "primary_metric": "clicked", "arms": [a, b]}


def test_an_unverified_window_says_so():
    r = analyse(build_monthly(), cohort_answered="same")
    assert not r["scored_window"]["verified"]
    assert any("WINDOW NOT VERIFIED AT SEND RESOLUTION" in w
               for w in r["warnings"])


def test_the_coarse_path_still_produces_a_read():
    """Labelling it coarse is the point; refusing to run is not."""
    r = analyse(build_monthly(), cohort_answered="same")
    assert r["comparisons"] and r["comparisons"][0]["a_n"] == 30000


def test_a_payload_with_no_series_is_not_told_its_window_came_from_buckets():
    """The credential-free path carries no calendar at all. Saying its window
    came from calendar buckets is false, and NO PERIOD DATA already states the
    true thing — that there is nothing here to verify a window against."""
    payload = {"test": "csv", "primary_metric": "clicked", "arms": [
        {"id": "1", "name": "one", "delivered": 10000, "clicked": 200,
         "opened": 3000},
        {"id": "2", "name": "two", "delivered": 10000, "clicked": 150,
         "opened": 3000},
    ]}
    r = analyse(payload, cohort_answered="same")
    assert not any("NOT VERIFIED AT SEND RESOLUTION" in w for w in r["warnings"])
    assert any(w.startswith("NO PERIOD DATA") for w in r["warnings"])


def test_the_coarse_warning_names_both_failure_modes():
    """Someone reading it has to know which two errors are possible, not just
    that something is imprecise."""
    r = analyse(build_monthly(), cohort_answered="same")
    w = next(x for x in r["warnings"] if "NOT VERIFIED" in x)
    assert "stopping part way" in w and "never sent on the same day" in w


# --- regressions from the Macroscope review on PR #144 -----------------------

def test_both_declaration_guards_must_pass_not_either():
    """Two guards, documented as both required. Joined with `and` on the reject
    branch, either one on its own declared a winner — so a long tail of a few
    stragglers, or a wide gap carrying almost no volume, read as a called test.
    """
    dates = days(T0, 30)
    a_sent = [1000] * 8 + [0] * 22
    # A wide gap, and the runner puts almost nothing into it: 8 sends against
    # 8,000. Real, but nowhere near a routed-traffic shape.
    b_sent = [1000] * 8 + [1] * 8 + [0] * 14
    payload = {"test": "trickle", "primary_metric": "clicked", "arms": [
        arm("a", dates, a_sent, clicked=[10] * 8 + [0] * 22),
        arm("b", dates, b_sent, clicked=[10] * 8 + [0] * 22),
    ]}
    assert declaration_by_timestamp(payload["arms"],
                                    send_windows(payload["arms"])) is None


def test_a_real_declaration_still_declares():
    """The guard above must not disarm the check it guards."""
    r = analyse(build_stops_early(), cohort_answered="same")
    assert r["declared_winner"] is not None


def test_a_dates_axis_shorter_than_the_series_reports_rather_than_raises():
    """`scored_window` is a reporting helper. A short axis made min() over an
    empty list raise out of it, taking the whole analysis with it."""
    dates = days(T0, 10)
    arms_ = [arm("a", dates, [1000] * 10, clicked=[10] * 10),
             arm("b", dates, [1000] * 10, clicked=[10] * 10)]
    for a in arms_:
        a["period_dates"] = dates[:2]
    w = scored_window(arms_, [5, 6, 7])
    assert w["periods"] == 3 and "from" not in w


# --- regressions from the second Macroscope review on PR #144 ----------------

def test_arms_from_separate_tests_are_aligned_by_date_not_by_position():
    """`abcompare.py` composes arms from independent payloads, each carrying its
    own date axis. Addressed by index, period 0 is June for one arm and August
    for the other — so an overlap window gets invented out of two calendars that
    never touched, and mismatched dates get summed into the rates."""
    june = days(T0, 10)
    august = days(_ts("2026-08-01"), 10)
    payload = {"test": "cross", "mode": "cross_test", "primary_metric": "clicked",
               "arms": [arm("q2", june, [1000] * 10, clicked=[20] * 10),
                        arm("q3", august, [1000] * 10, clicked=[40] * 10)]}
    r = analyse(payload, cohort_answered="same")
    assert r["overlap_periods"] == [], (
        "two flights two months apart never overlapped")
    assert r["basis"] == "lifetime"
    assert any("NO OVERLAP" in w for w in r["warnings"])


def test_a_genuine_overlap_across_different_axes_is_still_found():
    """Alignment must find the real overlap, not merely refuse everything."""
    a_dates = days(T0, 10)                       # 06-01 .. 06-10
    b_dates = days(T0 + 5 * DAY, 5)              # 06-06 .. 06-10
    payload = {"test": "staggered", "primary_metric": "clicked", "arms": [
        arm("a", a_dates, [1000] * 10, clicked=[20] * 10),
        arm("b", b_dates, [1000] * 5, clicked=[24] * 5)]}
    r = analyse(payload, cohort_answered="same")
    w = r["scored_window"]
    assert w["from"] == "2026-06-06" and w["to"] == "2026-06-10"
    assert w["days"] == 5


def test_series_at_different_resolutions_are_refused():
    dates = days(T0, 4)
    a = arm("a", dates, [1000] * 4, clicked=[20] * 4)
    b = arm("b", ["2026-06", "2026-07", "2026-08", "2026-09"], [1000] * 4,
            clicked=[24] * 4, verified=False)
    b["period_resolution"] = "month"
    with pytest.raises(SystemExit) as e:
        analyse({"test": "mixed", "primary_metric": "clicked", "arms": [a, b]})
    assert "different resolutions" in str(e.value)


def test_a_window_without_date_labels_reports_instead_of_raising():
    """`send_windows` guarantees the timestamps; the date labels beside them are
    written by the fetcher and absent from a hand-built payload. Reading them
    directly turned a missing label into a KeyError out of a warning."""
    dates = days(T0, 20)
    a = arm("a", dates, [1000] * 10 + [0] * 10, clicked=[10] * 10 + [0] * 10)
    b = arm("b", dates, [0] * 10 + [1000] * 10, clicked=[0] * 10 + [12] * 10)
    for x in (a, b):
        x["window"].pop("first_send_date")
        x["window"].pop("last_send_date")
    r = analyse({"test": "adjacent", "primary_metric": "clicked",
                 "arms": [a, b]}, cohort_answered="same")
    when = next(w for w in r["warnings"] if "NO OVERLAP" in w)
    assert "2026-06-10" in when and "2026-06-11" in when
