#!/usr/bin/env python3
"""Verdict engine for email A/B tests.

Takes a JSON file describing the arms of one test and decides whether there is
a read. Refusing to call a winner is a first-class result, not a failure.

Usage:
    python abstats.py test.json
    python abstats.py test.json --alpha 0.05 --power 0.8 --json

Input shape (see qa.example.json):

    {
      "test": "Spring promo - urgency vs benefit",
      "primary_metric": "clicked",
      "arms": [
        {
          "id": "1111",
          "name": "Control",
          "subject": "Your subject line here",
          "delivered": 5000,
          "opened": 1400,
          "clicked": 90,
          "human_opened": 1100,
          "human_clicked": 70,
          "converted": 10,
          "unsubscribed": 20,
          "spammed": 0,
          "periods": {"delivered": [...], "clicked": [...], "opened": [...]}
        },
        ...
      ]
    }

Scoring defaults to raw `clicked` and raw `opened` — every click and open,
machine or human — because for comparing two arms the machine activity falls on
both sides. Set `primary_metric` to score on any other field, including the
human-only ones; that is a deliberate choice and it is honoured. The fallback to
a human-only field happens only when no raw count was supplied at all, and the
output says so when it does.

`periods` is optional. Supplied, it lets the engine find the window where every
arm was live and score that, rather than comparing totals drawn from different
calendars; without it, the send windows have to be checked by hand. Arms running
at different times is not automatically fatal — whether two sends are comparable
is the cohort question, not the calendar one.
"""

import argparse
import calendar
import json
import math
import re
import sys
import time
from itertools import combinations
from statistics import NormalDist

from espconfig import utf8_stdout

# Normal quantiles, hardcoded so the skill has no scipy dependency.
# Computed, not looked up. A table keyed on 0.10/0.05/0.01 answers a
# multiple-comparison-corrected alpha with the 0.05 z-value and no complaint,
# so the sizing figures come back quietly sized against a bar nobody is using.
_NORM = NormalDist()


def z_alpha(alpha):
    """Two-sided critical z for a significance level."""
    return _NORM.inv_cdf(1 - alpha / 2)


def z_power(power):
    """One-sided z for a power level."""
    return _NORM.inv_cdf(power)

# Which elements a metric normally speaks to. Subject and preheader are
# pre-open decisions; body and CTA are post-open. This is the default reading,
# not a wall: a body that earns clicks lifts that send's inbox placement and so
# its opens, and a subject that brings in better readers can lift clicks on
# identical copy. Call the crossover out when the numbers point at it.
METRIC_SCOPE = {
    "opened": ("subject", "preheader", "from_name", "send_time", "deliverability"),
    "human_opened": ("subject", "preheader", "from_name", "send_time",
                     "deliverability"),
    "clicked": ("body", "cta", "layout", "links", "offer"),
    "human_clicked": ("body", "cta", "layout", "links", "offer"),
    "converted": ("body", "cta", "offer", "landing_page"),
    "unsubscribed": ("body", "offer", "frequency"),
}

# Candidate fields in preference order, used to pick a default and to fall back
# when the preferred one is absent. Raw counts come first: machine activity acts
# on both arms alike, so it cannot favour one, and a machine click is itself
# evidence the mail reached a real inbox-placed account. An explicit
# primary_metric overrides this entirely.
CLICK_FIELDS = ("clicked", "human_clicked")
OPEN_FIELDS = ("opened", "human_opened")

# Share of volume above which a two-arm split stops looking like randomisation
# and starts looking like someone moved traffic to a presumed winner.
SPLIT_LOPSIDED = 0.65


def first_present(arms, names):
    """First of `names` that any arm actually carries a value for.

    Presence, not truthiness. A measured zero is a value: an arm that genuinely
    earned no clicks reported `clicked: 0`, read as "no raw count was supplied",
    and got silently rescored on human clicks — under a warning that said the
    raw count was missing when it was there and was zero.
    """
    for n in names:
        if any(a.get(n) is not None for a in arms):
            return n
    return names[-1]


# Fully matched, and only a calendar date or an ISO datetime. Anchored at one
# end only, this matched any 9-13 digit run — so `"123456789"`, an ordinary
# customer or list identifier, was blanked to "<date>" and two rules naming
# different populations compared as one rule run twice. A numeric timestamp is
# still blanked, but by the int/float branch of `undate`, where the type itself
# says it is not an identifier string.
DATEISH = re.compile(
    r"^\s*\d{4}-\d{2}-\d{2}"
    r"(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?\s*$")


def trigger_rules(cohort):
    """The membership rules behind a cohort, or None if any are unreadable.

    None is the honest answer for a static list — one built by hand or imported
    from a CSV. There is no rule to read, only whoever was put in it.
    """
    segs = (cohort or {}).get("segments")
    if not segs:
        return None
    rules = [s.get("rule") for s in segs]
    return rules if all(r for r in rules) else None


def undate(obj):
    """The same rule with date and timestamp values blanked.

    "Joined between 1 and 30 April" and "joined between 1 and 30 June" are one
    rule run twice, not two populations. Blanking the window is what tells those
    apart from a genuinely different filter.
    """
    if isinstance(obj, dict):
        return {k: undate(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [undate(v) for v in obj]
    if isinstance(obj, (int, float)) and 10 ** 9 < obj < 10 ** 13:
        return "<date>"
    if isinstance(obj, str) and DATEISH.fullmatch(obj):
        return "<date>"
    return obj


def cohort_gate(arms, cross=False, answered=None):
    """Decide whether these arms are comparable at all.

    Comparability is a cohort question: did the arms go to the same population
    under the same rules? A check that cannot conclude must ASK, not shrug and
    print a winner underneath a warning nobody reads.

        ok    — one campaign, matching entry conditions, or the operator said so
        ask   — could not conclude; no winner until it is answered
        void  — the operator confirmed the rules differ

    Where the trigger rules are readable, this decides rather than asks: rules
    that plainly differ are two populations, and saying so is the whole point.
    What stays a question is a difference it cannot see through — segment ids
    alone are pointers, and a rebuilt segment can carry the same rule under a
    new id. A rule that differs only in its date window is one rule run twice.

    `answered` is the operator's reply: True same cohort, False rules differ.
    """
    cohorts = [a.get("cohort") for a in arms]
    ids = {(c or {}).get("campaign_id") for c in cohorts}

    # One campaign: every arm entered through the same door by construction.
    if len(ids) == 1 and None not in ids:
        return {"state": "ok", "why": "all arms come from one campaign, so "
                                      "they share its entry conditions"}

    # A single test carrying no cohort metadata at all — an older payload or a
    # hand-built one. Nothing here suggests two populations, so do not invent a
    # blocker; the gate exists for comparisons across sends, not for everything.
    if not cross and len(ids) <= 1:
        return {"state": "ok", "why": "a single test, so both arms share one "
                                      "entry condition"}

    if answered is True:
        return {"state": "ok", "why": "the operator confirmed the cohorts match"}
    if answered is False:
        return {"state": "void",
                "why": "the operator confirmed the cohort rules differ"}

    # Rules beat pointers. Where every side triggers off a segment that carries
    # its membership rule, the rules can simply be compared and the tool should
    # say so rather than hand the question back.
    rules = [trigger_rules(c) for c in cohorts]
    if all(r is not None for r in rules):
        if len({json.dumps(r, sort_keys=True) for r in rules}) == 1:
            return {"state": "ok", "why": "the trigger rules are identical"}
        if len({json.dumps(undate(r), sort_keys=True) for r in rules}) == 1:
            return {"state": "ok",
                    "why": "the trigger rules match apart from their date "
                           "window — one rule applied at two different times"}
        return {"state": "void",
                "why": "the trigger rules plainly differ, and not only on "
                       "dates — these are two different populations"}

    if any(c and c.get("static_lists") for c in cohorts):
        return {"state": "ask",
                "why": "at least one side was sent to a static list — built by "
                       "hand or imported rather than selected by a rule — so "
                       "there is nothing to compare. Only whoever built the "
                       "list knows who is in it"}

    known = [c for c in cohorts if c and c.get("resolved")]
    if len(known) == len(cohorts) and len(cohorts) > 1:
        fields = [json.dumps(c["fields"], sort_keys=True) for c in known]
        if len(set(fields)) == 1:
            return {"state": "ok",
                    "why": "the campaigns declare identical entry conditions"}
        return {"state": "ask",
                "why": "the campaigns point at different segments, but no rule "
                       "was readable — a rebuilt segment can carry the same "
                       "rule under a new id"}

    return {"state": "ask",
            "why": "the entry conditions could not be read for every arm"}


def cohort_question(gate, arms):
    """The specific question to put to the operator, with the facts on screen."""
    lines = [f"COHORT UNRESOLVED — {gate['why']}. Answer this before trusting "
             f"a winner; it decides whether these are comparable at all."]
    for a in arms:
        c = a.get("cohort") or {}
        who = c.get("campaign_name") or c.get("campaign_id") or a.get("name")
        if c.get("segments"):
            shown = "; ".join(
                f"segment {s['id']} '{s.get('name')}' [{s.get('type')}"
                f"{', rule readable' if s.get('rule') else ', no rule'}]"
                for s in c["segments"])
        elif c.get("fields"):
            shown = "; ".join(f"{k}={json.dumps(v)[:80]}"
                              for k, v in sorted(c["fields"].items()))
        else:
            shown = "entry conditions unavailable"
        lines.append(f"    {who}: {shown}")
    lines.append("    Did these go to the same population under the same "
                 "rules, with no major business change in between?")
    lines.append("    Re-run with --cohort-same to score it, or "
                 "--cohort-differs to record the comparison as void.")
    return "\n".join(lines)


def num(v):
    """A metric value as a number. A JSON null or a string reads as zero.

    ESP period arrays come back with nulls in months that carry no data, and
    comparing None to an int raises rather than returning a wrong answer — but
    it raises deep inside the window scan, where the traceback says nothing
    about which arm or which month.
    """
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return 0
    return v


def check_counts(arms, fields):
    """Refuse counts that cannot be real, rather than scoring them.

    A numerator above its denominator is a rate above 100%: always a mapping
    error, never a result. Left alone it does not crash — it produces a 500%
    click rate with z=95 and p=0.0000, which reads as the most decisive win the
    tool has ever printed.

    `delivered: 0` with a nonzero numerator is the same error wearing a quieter
    face: it does not print a 500% rate, it prints a neutral no-read, which is
    indistinguishable from a test that genuinely settled nothing.
    """
    problems = []
    for a in arms:
        who = a.get("name") or a.get("id")
        n = num(a.get("delivered"))
        # A negative count does not crash either. two_proportion_z returns a
        # neutral p=1 for it, so a malformed payload reads as a test that
        # settled nothing rather than as the input error it is.
        if n < 0:
            problems.append(f"  {who}: delivered={n:,} is negative")
        for f in fields:
            x = num(a.get(f))
            if x < 0:
                problems.append(f"  {who}: {f}={x:,} is negative")
            elif x > n:
                problems.append(f"  {who}: {f}={x:,} exceeds delivered={n:,}")
    if problems:
        raise SystemExit(
            "impossible counts — a numerator above its denominator is a "
            "mapping error, not a result:\n" + "\n".join(problems) +
            "\n  Check the column mapping (fetch_manual prints it, and --map "
            "overrides it) or the field names in a hand-built payload.")


def two_proportion_z(x1, n1, x2, n2):
    """Pooled two-proportion z-test. Returns (p1, p2, diff, z, p_value)."""
    if n1 <= 0 or n2 <= 0 or x1 < 0 or x2 < 0:
        return (0.0, 0.0, 0.0, 0.0, 1.0)
    p1, p2 = x1 / n1, x2 / n2
    pooled = (x1 + x2) / (n1 + n2)
    if pooled > 1:
        # Impossible input reaching the maths directly. check_counts catches
        # this earlier for a payload; refuse rather than raise from math.sqrt.
        return (p1, p2, p1 - p2, 0.0, 1.0)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if se == 0:
        return (p1, p2, p1 - p2, 0.0, 1.0)
    z = (p1 - p2) / se
    p_value = math.erfc(abs(z) / math.sqrt(2))  # two-sided
    return (p1, p2, p1 - p2, z, p_value)


def required_n_per_arm(p_base, rel_lift, alpha=0.05, power=0.80):
    """Per-arm sample needed to detect a relative lift on a base rate."""
    za, zb = z_alpha(alpha), z_power(power)
    p2 = p_base * (1 + rel_lift)
    if p2 >= 1 or p_base <= 0 or rel_lift == 0:
        return None
    var = p_base * (1 - p_base) + p2 * (1 - p2)
    return math.ceil(((za + zb) ** 2 * var) / ((p2 - p_base) ** 2))


def mde_at_n(p_base, n, alpha=0.05, power=0.80):
    """Smallest relative lift this sample size could have detected."""
    za, zb = z_alpha(alpha), z_power(power)
    if n <= 0 or p_base <= 0:
        return None
    abs_mde = (za + zb) * math.sqrt(2 * p_base * (1 - p_base) / n)
    return abs_mde / p_base


def align_period_axes(arms):
    """Put every arm's series on one date axis, or say why they cannot be.

    `overlap_window` and `windowed` address periods by INDEX. That is sound for
    one fetch, where the fetcher already builds a shared axis, and false for a
    payload composed by `abcompare.py`: two campaigns each carry their own axis,
    so index 0 is January for one arm and July for the other. Intersecting those
    positions invents an overlap window out of two calendars that never touched,
    and then sums mismatched dates into the rates it scores.

    Returns arms whose series are index-comparable, as shallow copies — the
    payload handed in is not modified.
    """
    axes = [a.get("period_dates") for a in arms]
    if not all(axes):
        return arms                      # nothing to align against; index is all there is
    resolutions = {a.get("period_resolution") for a in arms}
    if len(resolutions) > 1:
        raise SystemExit(
            "the arms carry series at different resolutions "
            f"({', '.join(sorted(str(r) for r in resolutions))}). A day summed "
            "against a month is not a comparison. Re-fetch both arms the same "
            "way, or score them on lifetime totals by dropping the series.")
    if all(ax == axes[0] for ax in axes):
        return arms                      # already one axis, which is the common case

    axis = sorted({d for ax in axes for d in ax})
    out = []
    for a in arms:
        at = {d: i for i, d in enumerate(a["period_dates"])}
        periods = {}
        for k, series in (a.get("periods") or {}).items():
            periods[k] = [num(series[at[d]]) if d in at and at[d] < len(series)
                          else 0 for d in axis]
        b = dict(a)
        b["periods"] = periods
        b["period_dates"] = axis
        out.append(b)
    return out


def overlap_window(arms, key="delivered"):
    """Indices of periods where every arm sent volume.

    Returns (indices, coverage) where coverage maps arm id -> fraction of that
    arm's total volume that falls inside the shared window. Low coverage means
    the arms largely did not run at the same time and the lifetime totals are
    comparing different calendars.
    """
    series = []
    for a in arms:
        p = (a.get("periods") or {}).get(key)
        if not p:
            return (None, {})
        series.append([num(v) for v in p])
    n = min(len(s) for s in series)
    idx = [i for i in range(n) if all(s[i] > 0 for s in series)]
    coverage = {}
    for a, s in zip(arms, series):
        total = sum(s) or 1
        coverage[a.get("id") or a.get("name")] = sum(s[i] for i in idx) / total
    return (idx, coverage)


def last_active_period(arm, key="delivered"):
    """Index of the last period in which this arm sent anything, or None."""
    s = (arm.get("periods") or {}).get(key)
    if not s:
        return None
    live = [i for i, v in enumerate(s) if num(v) > 0]
    return live[-1] if live else None


def declaration_signal(arms):
    """True when one arm stops sending while another keeps going.

    This is what the end of a test usually looks like: somebody called it and
    routed the remaining traffic to the winner. The volume ratio cannot show it
    — a deliberately uneven split produces the same ratio — but the shape of the
    series can, because a randomised split does not have one arm simply stop.
    """
    ends = [last_active_period(a) for a in arms]
    if any(e is None for e in ends) or len(set(ends)) < 2:
        return False
    return True


def pre_shift_window(arms, indices, threshold=SPLIT_LOPSIDED):
    """The leading run of periods where the split was still even.

    A lopsided total usually means traffic was moved to a presumed winner part
    way through the flight. The periods before that move are the only randomised
    evidence the payload contains, so they are what should be scored.

    Returns None when there is nothing to fall back on: no per-period volume,
    or a split that was already lopsided in the first period — which is not a
    shift at all, but a test that was never evenly randomised.
    """
    if not indices:
        return None
    series = []
    for a in arms:
        s = (a.get("periods") or {}).get("delivered")
        if not s:
            return None
        series.append([num(v) for v in s])

    run = []
    for i in indices:
        vols = [s[i] if i < len(s) else 0 for s in series]
        total = sum(vols)
        if not total or max(vols) / total >= threshold:
            break
        run.append(i)
    # A run covering the whole window means nothing was trimmed.
    return run if run and len(run) < len(indices) else None


def windowed(arm, indices, key):
    p = (arm.get("periods") or {}).get(key)
    if not p or indices is None:
        return None
    return sum(num(p[i]) for i in indices if i < len(p))


DAY_SECONDS = 86400


def day_start(date):
    """Unix timestamp of midnight UTC on a YYYY-MM-DD day label."""
    return calendar.timegm(time.strptime(date, "%Y-%m-%d"))


def clip_to_intersection(arms, indices, intersection):
    """Keep only the periods the measured intersection covers END TO END.

    A period is a bucket, and a bucket the intersection covers only part of
    holds volume from outside it. The shape that matters is the declared
    winner: the stopper's last send lands part way through a day, and the
    runner's sends over the rest of that day were randomised against nothing —
    yet the day qualifies as shared, because both arms have volume in it.

    Only meaningful at day resolution, which is the only resolution a verified
    window comes back at. Returns (indices, dropped).
    """
    dates = next((a.get("period_dates") for a in arms if a.get("period_dates")),
                 None)
    res = next((a.get("period_resolution") for a in arms
                if a.get("period_resolution")), None)
    if not dates or res != "day" or not indices:
        return indices, []
    lo, hi = intersection
    kept, dropped = [], []
    for i in indices:
        if i >= len(dates):
            continue
        start = day_start(dates[i])
        (kept if start >= lo and start + DAY_SECONDS <= hi + 1
         else dropped).append(i)
    if not kept:
        # Every period straddles an edge — a flight short enough that clipping
        # would leave nothing to score. Keep the partial window and say so
        # rather than turning a real, small test into no data at all.
        return indices, []
    return kept, dropped


def window_day(window, key):
    """A window's calendar day for `key`, formatted if it was not labelled.

    `send_windows` guarantees the timestamps and nothing else: the date labels
    beside them are written by the fetcher and absent from a hand-built payload.
    Reading them directly turned a missing label into a KeyError out of a
    warning, which is a worse answer than the warning.
    """
    return window.get(f"{key}_date") or time.strftime(
        "%Y-%m-%d", time.gmtime(window[key]))


def send_windows(arms):
    """Each arm's measured first and last send, or None if any arm lacks one.

    Either every arm's window was measured from per-send records or none of
    them can be treated as measured. One arm's timestamps against another's
    calendar buckets is the same class of mismatch as scoring one arm's window
    against another's lifetime: it does not fail, it just answers wrongly.
    """
    ws = [a.get("window") or {} for a in arms]
    if all(w.get("verified") and isinstance(w.get("first_send"), int)
           and isinstance(w.get("last_send"), int) for w in ws):
        return ws
    return None


def window_intersection(windows):
    """The stretch where every arm was sending, or None if there is none.

    An empty intersection is the answer to a question people rarely ask out
    loud: were these two arms ever running at the same time? Calendar buckets
    cannot answer it — two arms that sent on the 18th and the 19th share a
    month, and sharing a month is not concurrency.
    """
    lo = max(w["first_send"] for w in windows)
    hi = min(w["last_send"] for w in windows)
    return (lo, hi) if lo <= hi else None


def volume_after(arm, day, key="sent"):
    """(volume after `day`, total volume) from this arm's dated series."""
    dates = arm.get("period_dates") or []
    series = (arm.get("periods") or {}).get(key) or \
        (arm.get("periods") or {}).get("delivered") or []
    total = sum(num(v) for v in series)
    after = sum(num(v) for d, v in zip(dates, series) if d > day)
    return after, total


def declaration_by_timestamp(arms, windows, min_gap_share=0.10,
                             min_volume_share=0.05):
    """One arm stopped while another kept sending — measured, not inferred.

    Two guards against crying wolf. The gap has to be a real part of the
    flight, because arms rarely stop on the same second and a few minutes of
    trailing volume is jitter. And the arm that continued has to have put real
    volume into that gap, because a handful of stragglers is not a declared
    winner either. Both are satisfied by the shape this exists to catch: an arm
    that stops on the 8th while the other runs to the 30th, carrying most of
    its volume in between.
    """
    ends = [w["last_send"] for w in windows]
    first_end, last_end = min(ends), max(ends)
    gap = last_end - first_end
    if gap <= 0:
        return None
    span = max(w["last_send"] - w["first_send"] for w in windows) or 1
    stopper = arms[ends.index(first_end)]
    runner = arms[ends.index(last_end)]
    after, total = volume_after(runner, time.strftime(
        "%Y-%m-%d", time.gmtime(first_end)))
    share = after / total if total else 0.0
    if gap < min_gap_share * span or share < min_volume_share:
        return None
    return {"stopper": stopper.get("name"), "runner": runner.get("name"),
            "stopped": time.strftime("%Y-%m-%d", time.gmtime(first_end)),
            "continued_to": time.strftime("%Y-%m-%d", time.gmtime(last_end)),
            "gap_days": round(gap / 86400, 1), "runner_share_after": share}


def scored_window(arms, indices):
    """The window actually scored, as dates, with its resolution.

    "N concurrent period(s)" is not a window. It reads as a measurement while
    hiding the only thing that matters about one — how wide the periods were,
    and therefore what could have happened inside one without showing.
    """
    dates = next((a.get("period_dates") for a in arms if a.get("period_dates")),
                 None)
    res = next((a.get("period_resolution") for a in arms
                if a.get("period_resolution")), None)
    verified = bool(send_windows(arms))
    if indices is None:
        # Not "a window of zero days" — no window was scored at all. Reporting
        # a window beside lifetime totals describes a measurement that did not
        # happen.
        return {"scored": "lifetime totals", "resolution": res,
                "verified": verified}
    if not indices:
        return {"days": 0, "resolution": res, "verified": verified}
    if not dates:
        return {"periods": len(indices), "resolution": res,
                "verified": verified}
    picked = [dates[i] for i in indices if i < len(dates)]
    if not picked:
        # A dates axis shorter than the series it labels. Report the window the
        # way an undated one is reported rather than raising out of a helper
        # whose whole job is to describe what was scored.
        return {"periods": len(indices), "resolution": res,
                "verified": verified}
    return {"from": min(picked), "to": max(picked), "days": len(picked),
            "resolution": res, "verified": verified}


def analyse(payload, alpha=0.05, power=0.80, min_coverage=0.60, cross=False,
            cohort_answered=None):
    arms = payload["arms"]
    if len(arms) < 2:
        raise SystemExit("need at least two arms to compare")
    arms = align_period_axes(arms)

    metric = payload.get("primary_metric") or first_present(arms, CLICK_FIELDS)
    if metric in CLICK_FIELDS and not any(a.get(metric) is not None
                                          for a in arms):
        metric = first_present(arms, CLICK_FIELDS)
    no_denominator = [a.get("name") or a.get("id") or f"arm {i + 1}"
                      for i, a in enumerate(arms) if a.get("delivered") is None]
    if no_denominator:
        raise SystemExit(
            "`delivered` is missing for: " + ", ".join(no_denominator) +
            "\n  Every rate below is a numerator over that count. Absent, it "
            "reads as zero, and a zero denominator does not fail — it returns a "
            "neutral no-read, which is what a test that genuinely settled "
            "nothing looks like. Supply the delivered count per arm.")
    missing = [a.get("name") or a.get("id") or f"arm {i + 1}"
               for i, a in enumerate(arms) if a.get(metric) is None]
    if missing:
        raise SystemExit(
            f"the decision metric {metric!r} is missing for: "
            + ", ".join(missing) +
            f"\n  An absent count reads as zero, and zero is not an error "
            f"anywhere below it: against another zero it is a tidy no-read, and "
            f"against a real count it is a significant win for whichever arm "
            f"happened to carry the field. Check the field name, or name a "
            f"metric every arm carries with --metric.")
    open_field = first_present(arms, OPEN_FIELDS)

    cross = cross or payload.get("mode") == "cross_test"
    warnings = []
    if metric == "human_clicked":
        warnings.append(
            "SCORED ON HUMAN CLICKS ONLY: no raw click count was supplied. Raw "
            "clicks are the better default — machine activity acts on both arms "
            "alike, and a machine click still means the mail reached a real "
            "inbox-placed account. Supply `clicked` to score that way."
        )
    if cross:
        warnings.append(
            "OBSERVATIONAL: these arms come from different tests. There was no "
            "randomisation between them, so a difference is a fact about what "
            "happened, not evidence of what caused it. Audience, list state and "
            "deliverability all moved too."
        )
    check_counts(arms, {metric, open_field, "converted", "unsubscribed"})
    idx, coverage = overlap_window(arms)

    # Measured send windows outrank the period scan wherever they disagree. The
    # scan can only see buckets, and two arms that never sent on the same day
    # still share a month.
    windows = send_windows(arms)
    intersection = window_intersection(windows) if windows else None
    if windows and intersection is None:
        idx = []
    elif windows and intersection and idx and not cross and \
            declaration_by_timestamp(arms, windows):
        # Gated on a declaration, and deliberately. Arms almost never stop on
        # the same second, so the last shared period is partly uncovered in
        # nearly every well-run test — clipping on that alone would throw away
        # a whole period of a clean flight to remove a few minutes of jitter.
        # The guards in `declaration_by_timestamp` are what separate jitter
        # from an arm that was switched off while the other kept sending, and
        # that is the case where the uncovered remainder carries real volume.
        idx, clipped = clip_to_intersection(arms, idx, intersection)
        if clipped:
            warnings.append(
                f"BOUNDARY PERIOD(S) DROPPED: {len(clipped)} shared period(s) "
                f"were only partly inside the measured window — one arm started "
                f"or stopped part way through them, so the other arm's sends "
                f"over the rest of those periods were randomised against "
                f"nothing. A period counts as shared when both arms have volume "
                f"in it, which a partly-covered one does. Scored on the periods "
                f"the window covers end to end."
            )
    # Only where buckets exist to be mistaken for a window. With no series at
    # all there is no bucket to misread, NO PERIOD DATA below says so, and
    # claiming the window "came from calendar buckets" would be false on the
    # credential-free path, which carries no calendar at all.
    if not windows and idx is not None:
        res = next((a.get("period_resolution") for a in arms
                    if a.get("period_resolution")), None)
        warnings.append(
            "WINDOW NOT VERIFIED AT SEND RESOLUTION: the send windows come "
            f"from {res or 'calendar'} buckets, not from per-send timestamps. "
            "A bucket cannot show an arm stopping part way through one, so "
            "volume sent after a winner was declared can sit inside the "
            "numbers below, and two arms that never sent on the same day can "
            "still share a bucket and read as concurrent. Where the ESP exposes "
            "per-send records, re-fetch with them and both questions are "
            "settled; otherwise confirm each arm's first and last send by hand "
            "before treating this as a clean read.")

    # Every arm must be windowable on the same fields, or none of them are.
    # Scoring one arm's overlap window against another's lifetime total is a
    # comparison of two different things, and it does not fail loudly — it
    # produces a decisive winner out of a mismatch.
    windowable = bool(idx) and all(
        windowed(a, idx, "delivered") is not None
        and windowed(a, idx, metric) is not None for a in arms)
    if idx and not windowable:
        warnings.append(
            f"MIXED PERIOD DATA: the arms were live in the same window, but not "
            f"every arm carries a per-period series for `{metric}`. Scoring all "
            f"arms on lifetime totals instead — mixing one arm's window with "
            f"another's lifetime would compare two different things."
        )

    # Decide whether to score on lifetime totals or the concurrent window.
    if any(a.get("opens_not_split_by_source") for a in arms):
        warnings.append(
            "OPENS ARRIVE AS ONE COUNT: this ESP does not report opens by "
            "source. The open rate still reads; what is unavailable here is the "
            "human/prefetch split as a placement diagnostic."
        )

    # Identical subject lines should open at about the same rate. A gap outside
    # the noise means something other than the subject moved — most often the
    # deliverability of one template. Suppressed across tests, where two
    # campaigns are expected to differ on opens.
    subjects = [(a.get("subject") or "").strip() for a in arms]
    if not cross and len(arms) == 2 and all(subjects) and subjects[0] == subjects[1]:
        n1, n2 = num(arms[0].get("delivered")), num(arms[1].get("delivered"))
        o1, o2 = num(arms[0].get(open_field)), num(arms[1].get(open_field))
        if n1 and n2 and (o1 or o2):
            _, _, _, _, p_o = two_proportion_z(o1, n1, o2, n2)
            if p_o < alpha:
                low = arms[0] if (o1 / n1) < (o2 / n2) else arms[1]
                warnings.append(
                    f"OPEN GAP ON AN IDENTICAL SUBJECT: {o1/n1:.1%} vs "
                    f"{o2/n2:.1%} (p={p_o:.4f}). The subject cannot explain "
                    f"that, so something else did. Look first at the "
                    f"deliverability of '{low.get('name')}' — heavy images, "
                    f"spam-triggering wording, or broken and low-reputation "
                    f"links push a template out of the inbox, where it is never "
                    f"opened. It can also be a non-random split, or a difference "
                    f"in send time or sending domain. It can also be legitimate: "
                    f"an arm earning many more clicks gains placement over time, "
                    f"so the gap may be a downstream effect of that arm being "
                    f"better. Establish which before reading anything else, and "
                    f"say which."
                )

    basis = "lifetime"
    if idx is None:
        warnings.append(
            "NO PERIOD DATA: the arms carry no per-period series, so this "
            "cannot verify they sent over the same window. Scoring on lifetime "
            "totals. Confirm the send windows overlap before trusting the read."
        )
    elif idx is not None:
        if not idx:
            when = ""
            if windows:
                order = sorted(zip(windows, arms),
                               key=lambda p: p[0]["first_send"])
                earlier, later = order[0], order[-1]
                when = (f" '{earlier[1].get('name')}' last sent "
                        f"{window_day(earlier[0], 'last_send')}; "
                        f"'{later[1].get('name')}' first sent "
                        f"{window_day(later[0], 'first_send')}.")
            warnings.append(
                "NO OVERLAP: the arms never sent at the same time, so this is "
                f"sequential rather than simultaneous.{when} It can still be "
                "scored — see the cohort check — but name the weaknesses beside "
                "the number: list state, seasonality and deliverability all "
                "moved in between. Nothing below may be described as a "
                "concurrent or randomised comparison."
            )
        elif min(coverage.values()) < min_coverage:
            worst = min(coverage, key=coverage.get)
            if windowable:
                basis = "overlap"
                warnings.append(
                    f"PARTIAL OVERLAP: arm {worst} has only "
                    f"{coverage[worst]:.0%} of its volume inside the window "
                    f"where all arms were live. Scoring on that window, which "
                    f"is the stronger evidence. To use the rest, score it "
                    f"separately and state its weaknesses beside the number."
                )
            else:
                warnings.append(
                    f"PARTIAL OVERLAP, SCORED ON LIFETIME: arm {worst} has only "
                    f"{coverage[worst]:.0%} of its volume inside the shared "
                    f"window, which would normally be scored on its own — but "
                    f"the per-period data needed to do that is not present for "
                    f"every arm. These totals compare different calendars."
                )
        elif windowable:
            basis = "overlap"

    gate = cohort_gate(arms, cross=cross, answered=cohort_answered)
    if gate["state"] == "void":
        warnings.append(
            "COHORT MISMATCH: " + gate["why"] + ". These arms went to different "
            "populations, so the comparison is void — no winner is named below, "
            "and no amount of volume repairs it."
        )
    elif gate["state"] == "ask":
        warnings.append(cohort_question(gate, arms))
    elif cross:
        warnings.append(
            "COHORT: " + gate["why"] + ". This was still not a simultaneous "
            "randomised split — say so alongside any winner."
        )

    def on_basis(arm, field):
        """One field for one arm, over whatever window is being scored.

        None means unavailable, which is not zero: in the windowed basis this
        arm carries no series for the field, and in the lifetime basis it
        carries no such count at all.
        """
        # basis is decided once, for every arm together — see `windowable`.
        if basis in ("overlap", "pre_shift"):
            return windowed(arm, idx, field)
        return None if arm.get(field) is None else num(arm.get(field))

    def counts(arm):
        if basis in ("overlap", "pre_shift"):
            return (windowed(arm, idx, "delivered"),
                    windowed(arm, idx, metric),
                    windowed(arm, idx, open_field))
        return (num(arm.get("delivered")), num(arm.get(metric)),
                num(arm.get(open_field)))

    # Volume imbalance: the 70/30 tell. A lopsided split usually means someone
    # already called it and shifted traffic to the winner, which breaks the
    # randomisation from that moment on. Where the per-period series shows when
    # that happened, score the periods before it rather than warning about the
    # problem and then scoring straight through it.
    #
    # Only meaningful WITHIN a test. Across two different campaigns, unequal
    # volume says nothing about traffic being shifted — they were never one
    # pool to begin with — so the check is suppressed in cross-test mode.
    # A winner declared part way through does not look like an even split that
    # ended; it looks like one arm stopping while another carries on. Suppressed
    # across tests, where separate campaigns keep their own calendars.
    declared = (declaration_by_timestamp(arms, windows)
                if windows and not cross else None)
    if declared:
        warnings.append(
            f"DECLARED WINNER: '{declared['stopper']}' last sent "
            f"{declared['stopped']} while '{declared['runner']}' continued to "
            f"{declared['continued_to']} — {declared['gap_days']} days longer, "
            f"carrying {declared['runner_share_after']:.0%} of its volume after "
            f"the other arm had stopped. Those sends were randomised against "
            f"nothing. This is measured from per-send timestamps, not inferred "
            f"from a bucket, and the window scored below excludes it."
        )
    elif not cross and not windows and declaration_signal(arms):
        warnings.append(
            "DECLARED WINNER LIKELY: one arm stopped sending while another "
            "continued. That is what it looks like when a test is called and "
            "the remaining traffic is routed to the winner, so the arms were "
            "only randomised against each other up to that moment. The shared "
            "periods scored below can themselves straddle it, because a period "
            "is only as narrow as the series provided. Confirm the window at a "
            "finer resolution — per-send timestamps if the ESP exposes them — "
            "before treating this as a clean read."
        )

    vols = [counts(a)[0] for a in arms]
    total = sum(vols) or 1
    top = max(vols) / total
    if not cross and len(arms) == 2 and top >= SPLIT_LOPSIDED:
        leader = arms[vols.index(max(vols))]
        head = (f"SPLIT IMBALANCE: '{leader.get('name')}' holds {top:.0%} of "
                f"volume. That usually means traffic was shifted to a presumed "
                f"winner mid-flight, and nothing after that moment is randomised.")
        pre = pre_shift_window(arms, idx) if windowable else None
        if pre:
            idx = pre
            basis = "pre_shift"
            warnings.append(
                f"{head} Rescored on the {len(pre)} balanced period(s) before "
                f"the shift, which is the only randomised evidence here. The "
                f"lifetime totals still include the post-shift volume."
            )
        elif windowable:
            warnings.append(
                f"{head} There is no balanced window to fall back on: the "
                f"split was already uneven in the first period the series "
                f"covers. That can mean the split was designed uneven, which "
                f"reads fine when the smaller arm carries the volume, or that "
                f"the series is too coarse to contain the balanced part. It "
                f"does not on its own establish that the arms were never "
                f"randomised — the configuration and the send timestamps do."
            )
        else:
            warnings.append(
                f"{head} This could not be rescored on the pre-shift window: "
                f"the arms carry no per-period series, so the numbers below "
                f"still include everything after the shift. Verify the split "
                f"before trusting the read."
            )

    # Every extra arm is more chances to see a spread that is not there. Three
    # arms is three pairwise tests, and three tests at alpha=0.05 carry a ~14%
    # chance of at least one false winner; six arms is fifteen tests and better
    # than even odds. Šidák rather than Bonferroni because the exact form costs
    # nothing here and is fractionally less conservative.
    n_pairs = len(arms) * (len(arms) - 1) // 2
    pair_alpha = 1 - (1 - alpha) ** (1.0 / n_pairs) if n_pairs > 1 else alpha
    if n_pairs > 1:
        warnings.append(
            f"{len(arms)} ARMS, {n_pairs} COMPARISONS: the significance bar is "
            f"tightened from {alpha} to {pair_alpha:.4f} per comparison, so the "
            f"chance of naming a false winner ANYWHERE in this test stays at "
            f"{alpha}. Reading each pair at {alpha} instead would put it near "
            f"{1 - (1 - alpha) ** n_pairs:.0%}. The p-values below are raw; the "
            f"bar they are read against is the corrected one. A multi-arm test "
            f"needs more volume per arm than a two-arm test to say the same "
            f"thing, and that is a property of the design, not of this tool."
        )

    if basis in ("overlap", "pre_shift"):
        # `check_counts` validated the lifetime totals. These are different
        # numbers: `windowed` sums the period series, so a payload whose totals
        # are sound and whose series are not reaches the z-test as a rate above
        # 100% and comes back as the most decisive win the tool can print.
        #
        # Deliberately on the summed window and not period by period. Metrics
        # bucket on their own timestamp, so a click on a day with no deliveries
        # is ordinary and an element-wise check would refuse real data.
        problems = []
        for a in arms:
            who = a.get("name") or a.get("id")
            n, x, o = counts(a)
            if n is None:
                continue
            if n < 0:
                problems.append(f"  {who}: delivered={n:,} is negative "
                                f"over the scored window")
            for label, v in ((metric, x), (open_field, o)):
                if v is None:
                    continue
                if v < 0:
                    problems.append(f"  {who}: {label}={v:,} is negative "
                                    f"over the scored window")
                elif v > n:
                    problems.append(f"  {who}: {label}={v:,} exceeds "
                                    f"delivered={n:,} over the scored window")
        if problems:
            raise SystemExit(
                "the per-period series do not survive being summed over the "
                "window this would be scored on:\n" + "\n".join(problems) +
                "\n  A numerator above its denominator is a rate above 100%, "
                "which is a mapping error rather than a result — the lifetime "
                "totals passed, so the fault is in `periods`. Re-fetch, or "
                "score on lifetime totals by dropping the series.")

    results = []
    for a, b in combinations(arms, 2):
        n1, x1, o1 = counts(a)
        n2, x2, o2 = counts(b)
        p1, p2, diff, z, pv = two_proportion_z(x1, n1, x2, n2)
        winner = a if p1 > p2 else b
        loser = b if p1 > p2 else a
        hi, lo = max(p1, p2), min(p1, p2)
        rel = (hi - lo) / lo if lo > 0 else None

        significant = pv < pair_alpha
        base = lo or (x1 + x2) / (n1 + n2 or 1)
        entry = {
            "a": a.get("name"), "b": b.get("name"),
            "a_rate": p1, "b_rate": p2,
            "a_n": n1, "b_n": n2, "a_x": x1, "b_x": x2,
            "abs_diff_pp": diff * 100, "rel_lift": rel,
            "z": z, "p_value": pv, "significant": significant,
            "alpha_used": pair_alpha, "comparisons_in_family": n_pairs,
            # `leader` is the arm with the higher rate — a fact about the
            # numbers, true whether or not a winner may be named. `winner` is
            # the claim, and it is filled in below only if nothing blocks it.
            "leader": (winner.get("name") if p1 != p2 else None),
            "winner": None, "loser": None,
        }
        if not significant:
            # Sized against the bar it will actually be read at, or the answer
            # to "how much more do I need" is short by the correction.
            entry["mde_at_current_n"] = mde_at_n(base, min(n1, n2), pair_alpha,
                                                 power)
            observed_rel = rel or 0.10
            entry["n_needed_per_arm"] = required_n_per_arm(
                base, observed_rel if observed_rel > 0.01 else 0.10,
                pair_alpha, power
            )
        # Click-to-open, when we have opens: isolates body/CTA from subject.
        if metric in CLICK_FIELDS and o1 and o2:
            ctor1, ctor2, _, zc, pc = two_proportion_z(x1, o1, x2, o2)
            unsplit = any(x.get("opens_not_split_by_source") for x in (a, b))
            entry["ctor"] = {"a": ctor1, "b": ctor2, "z": zc, "p_value": pc,
                             "significant": pc < pair_alpha,
                             "opens_unsplit": unsplit}

        # The machine-click split. Raw clicks are the default because machine
        # activity falls on both arms alike — and that holds until the arms
        # differ in their links. A security gateway or a prefetcher visits a
        # changed URL, a new domain or a new redirect on its own schedule, and
        # those visits land in `clicked` as outcomes indistinguishable from a
        # person deciding to act. Where the ESP separates human from machine,
        # the split settles it, so check rather than assume. This does not
        # change the metric: it refuses to let a raw-click win stand as a claim
        # about people when the human counts do not corroborate it.
        if metric == "clicked":
            h1, h2 = on_basis(a, "human_clicked"), on_basis(b, "human_clicked")
            if h1 is not None and h2 is not None and (h1 or h2) \
                    and n1 and n2:
                hr1, hr2, _, _, ph = two_proportion_z(h1, n1, h2, n2)
                corroborates = ph < pair_alpha and (hr1 > hr2) == (p1 > p2)
                entry["human_click_check"] = {
                    "a_rate": hr1, "b_rate": hr2, "p_value": ph,
                    "significant": ph < alpha, "corroborates": corroborates}
                if significant and not corroborates:
                    lead = a if p1 > p2 else b
                    warnings.append(
                        f"RAW CLICKS WIN, HUMAN CLICKS DO NOT: "
                        f"'{lead.get('name')}' wins on every click "
                        f"(p={pv:.4f}) but the same comparison on human clicks "
                        f"only is {hr1:.2%} vs {hr2:.2%} (p={ph:.4f}). Machine "
                        f"activity is only neutral while it treats both arms "
                        f"alike, and it stops treating them alike when the "
                        f"links differ — a scanner or prefetcher visits a "
                        f"changed URL, a new domain or a new redirect on its "
                        f"own schedule. Check whether the links or their "
                        f"domains differ between the arms. If they do, this is "
                        f"a machine artefact and not a result; score it on "
                        f"human_clicked (--metric human_clicked) and say which "
                        f"you used. Do not name a winner on the raw count "
                        f"until that is settled."
                    )
        # One verdict, decided here rather than in the renderer. A refusal that
        # only exists in the text output is not a refusal: `--json` is what
        # anything downstream reads, and it was handing back winners the report
        # on screen declined to name.
        if gate["state"] in ("ask", "void"):
            entry["verdict"] = "withheld"
            entry["verdict_reason"] = (
                "the cohort rules differ" if gate["state"] == "void"
                else "the cohort question is unanswered")
        elif significant and not (entry.get("human_click_check") or
                                  {"corroborates": True})["corroborates"]:
            entry["verdict"] = "withheld"
            entry["verdict_reason"] = (
                "a raw-click win the human-click count does not corroborate")
        elif significant:
            entry["verdict"] = "winner"
            entry["verdict_reason"] = None
            entry["winner"] = winner.get("name")
            entry["loser"] = loser.get("name")
        else:
            entry["verdict"] = "no_read"
            entry["verdict_reason"] = "the difference is inside the noise"
        results.append(entry)

    return {
        "test": payload.get("test"),
        "primary_metric": metric,
        "basis": basis,
        "overlap_periods": idx,
        "scored_window": scored_window(
            arms, idx if basis in ("overlap", "pre_shift") else None),
        "declared_winner": declared,
        "coverage": coverage,
        "alpha": alpha,
        "power": power,
        "cross_test": cross,
        "cohort_gate": gate,
        "alpha_per_comparison": pair_alpha,
        "comparisons_in_family": n_pairs,
        "warnings": warnings,
        "comparisons": results,
        "metric_scope": METRIC_SCOPE.get(metric, ()),
    }


def render(r):
    out = []
    out.append(f"TEST: {r['test']}")
    fam = r.get("comparisons_in_family", 1)
    bar = (f"alpha={r['alpha']} over {fam} comparisons "
           f"→ {r['alpha_per_comparison']:.4f} each" if fam > 1
           else f"alpha={r['alpha']}")
    out.append(f"Decision metric: {r['primary_metric']}  "
               f"({bar}, power={r['power']}, basis={r['basis']})")
    w = r.get("scored_window") or {}
    if r["basis"] in ("overlap", "pre_shift") and r["overlap_periods"]:
        # State the window, not a count of buckets. A count reads as a
        # measurement while hiding how wide the buckets were.
        if w.get("from"):
            span = (w["from"] if w["from"] == w["to"]
                    else f"{w['from']} → {w['to']}")
            what = ("concurrent window" if r["basis"] == "overlap"
                    else "balanced window before the traffic shift")
            out.append(f"Scored on the {what}: {span} ({w['days']} "
                       f"{w.get('resolution') or 'period'}(s)"
                       f"{'' if w.get('verified') else ', UNVERIFIED'}).")
        else:
            out.append(f"Scored on {len(r['overlap_periods'])} "
                       f"{'concurrent' if r['basis'] == 'overlap' else 'pre-shift'}"
                       f" period(s) — dates unavailable, so the width of each "
                       f"period is unknown.")
        if r["basis"] == "pre_shift":
            out.append("See SPLIT IMBALANCE below.")
    elif r["overlap_periods"] == [] and w.get("verified"):
        out.append("Scored on lifetime totals: the arms have no window in "
                   "common — see NO OVERLAP below.")
    out.append("")

    for w in r["warnings"]:
        out.append(f"  [!] {w}")
    if r["warnings"]:
        out.append("")

    for c in r["comparisons"]:
        out.append(f"{c['a']}")
        out.append(f"   vs {c['b']}")
        out.append(f"   {c['a_x']}/{c['a_n']} = {c['a_rate']*100:.3f}%   "
                   f"vs   {c['b_x']}/{c['b_n']} = {c['b_rate']*100:.3f}%")
        out.append(f"   diff {c['abs_diff_pp']:+.3f}pp  z={c['z']:.2f}  p={c['p_value']:.4f}")
        # The verdict is decided in analyse(); this only chooses the words for
        # it. Deriving it twice is how the screen and the JSON came to disagree.
        cohort_blocked = c["verdict"] == "withheld" and "cohort" in \
            (c["verdict_reason"] or "")
        if cohort_blocked:
            out.append(f"   VERDICT WITHHELD — {c['verdict_reason']}. The rates "
                       f"are shown because they are facts; which one is "
                       f"'better' is not one until the populations are known "
                       f"to match.")
        elif c["verdict"] == "withheld":
            # The verdict leads, so a verdict the human counts do not support
            # cannot be printed clean and qualified three lines later.
            hc = c["human_click_check"]
            lift = f"{c['rel_lift']*100:.1f}%" if c["rel_lift"] else "n/a"
            out.append(f"   VERDICT: WITHHELD. {c['leader']} wins on every "
                       f"click (+{lift} relative, p={c['p_value']:.4f}), but "
                       f"human clicks alone are {hc['a_rate']*100:.2f}% vs "
                       f"{hc['b_rate']*100:.2f}% (p={hc['p_value']:.4f}) and do "
                       f"not agree. A raw-click win that human clicks do not "
                       f"corroborate is what a scanner visiting one arm's "
                       f"changed links looks like. Settle that before naming a "
                       f"winner — see the warning above.")
        elif c["verdict"] == "winner":
            lift = f"{c['rel_lift']*100:.1f}%" if c["rel_lift"] else "n/a"
            verb = "outperformed the other (+%s relative)" % lift if r["cross_test"] \
                else "wins (+%s relative)" % lift
            out.append(f"   VERDICT: {c['winner']} {verb}.")
            hc = c.get("human_click_check")
            if hc and hc["corroborates"]:
                out.append(f"      Human clicks agree: {hc['a_rate']*100:.2f}% "
                           f"vs {hc['b_rate']*100:.2f}% (p="
                           f"{hc['p_value']:.4f}), same direction, so the win "
                           f"is not machine activity on changed links.")
        else:
            out.append("   VERDICT: NO READ. The difference is inside the noise.")
            if c.get("mde_at_current_n"):
                out.append(f"      This sample could only have detected a "
                           f"{c['mde_at_current_n']*100:.0f}% relative lift.")
            if c.get("n_needed_per_arm"):
                out.append(f"      To call an effect this size you need "
                           f"~{c['n_needed_per_arm']:,} delivered per arm.")
        if "ctor" in c:
            ct = c["ctor"]
            verdict = "differs" if ct["significant"] else "does not differ"
            out.append(f"   Click-to-open: {ct['a']*100:.2f}% vs "
                       f"{ct['b']*100:.2f}% (p={ct['p_value']:.4f}) — "
                       f"post-open behaviour {verdict}.")
            if ct.get("opens_unsplit"):
                out.append("      The open denominator counts every open, on "
                           "both arms; this ESP does not report them by source.")
        out.append("")

    scope = ", ".join(r["metric_scope"])
    out.append(f"This metric normally speaks to: {scope}.")
    out.append("Anything outside that list needs an argument, not an assumption.")
    if r["cross_test"]:
        out.append("Cross-test: report the difference as observed, never as caused.")
    return "\n".join(out)


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("payload")
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--power", type=float, default=0.80)
    ap.add_argument("--cross", action="store_true",
                    help="arms come from different tests; suppresses the "
                         "split-imbalance check and marks the read observational")
    ap.add_argument("--cohort-same", action="store_true",
                    help="answer the cohort question: the arms went to the "
                         "same population under the same rules")
    ap.add_argument("--cohort-differs", action="store_true",
                    help="answer the cohort question: the rules differ, so "
                         "the comparison is void")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.cohort_same and args.cohort_differs:
        ap.error("--cohort-same and --cohort-differs are contradictory")
    answered = True if args.cohort_same else (False if args.cohort_differs
                                              else None)

    with open(args.payload, encoding="utf-8") as fh:
        payload = json.load(fh)

    r = analyse(payload, alpha=args.alpha, power=args.power, cross=args.cross,
                cohort_answered=answered)
    if args.json:
        json.dump(r, sys.stdout, indent=2)
    else:
        print(render(r))


if __name__ == "__main__":
    main()
