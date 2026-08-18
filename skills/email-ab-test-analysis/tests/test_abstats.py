#!/usr/bin/env python3
"""Tests for the verdict engine — pure, no I/O.

The failure this file exists to prevent is a confident winner printed over a
difference that was never there. Every test below pins one of the gates that
stands between a spread and a claim: the significance threshold, the metric the
spread is measured on, and the window it is measured over.

Hermetic: builds payloads in memory, touches no network and no files.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from abstats import (analyse, check_counts, first_present, mde_at_n, num,
                     render, required_n_per_arm, two_proportion_z)


def arm(name, delivered, clicked, opened=None, subject="Same subject",
        periods=None, **extra):
    a = {"id": name, "name": name, "subject": subject,
         "delivered": delivered, "clicked": clicked}
    if opened is not None:
        a["opened"] = opened
    if periods:
        a["periods"] = periods
    a.update(extra)
    return a


def payload(*arms, **kw):
    p = {"test": "t", "arms": list(arms)}
    p.update(kw)
    return p


# --- the statistics themselves ----------------------------------------------

def test_two_proportion_z_matches_a_hand_computed_case():
    # 50/1000 vs 100/1000: pooled p = 0.075, se = 0.01178, z = -4.244
    _, _, _, z, p = two_proportion_z(50, 1000, 100, 1000)
    assert abs(z + 4.244) < 0.01, f"z drifted: {z}"
    assert p < 0.0001


def test_identical_rates_are_never_significant():
    _, _, _, z, p = two_proportion_z(100, 1000, 100, 1000)
    assert z == 0 and p == 1.0


def test_empty_arm_cannot_produce_a_verdict():
    """A zero denominator must return "no difference", not divide by zero."""
    assert two_proportion_z(0, 0, 10, 100) == (0.0, 0.0, 0.0, 0.0, 1.0)


def test_required_sample_grows_as_the_effect_shrinks():
    small, large = required_n_per_arm(0.02, 0.05), required_n_per_arm(0.02, 0.50)
    assert small > large * 10, "detecting a smaller lift must cost more volume"


def test_mde_shrinks_as_the_sample_grows():
    assert mde_at_n(0.02, 100_000) < mde_at_n(0.02, 1_000)


# --- the gate ---------------------------------------------------------------

def test_a_spread_inside_the_noise_is_a_no_read_with_the_cost_of_settling_it():
    r = analyse(payload(arm("A", 1000, 20), arm("B", 1000, 25)))
    c = r["comparisons"][0]
    assert not c["significant"] and c["winner"] is None
    assert c["mde_at_current_n"] and c["n_needed_per_arm"], (
        "a no read must say what this sample could have detected and what "
        "would settle it — otherwise it reads as a shrug")
    assert "NO READ" in render(r)


def test_a_real_difference_names_a_winner():
    r = analyse(payload(arm("A", 20000, 200), arm("B", 20000, 400)))
    c = r["comparisons"][0]
    assert c["significant"] and c["winner"] == "B"


def test_a_lopsided_split_still_reads_when_the_smaller_arm_has_the_volume():
    """The ratio settles nothing; only the smaller arm's volume does."""
    r = analyse(payload(arm("Big", 1_000_000, 20_000), arm("Small", 20_000, 600)))
    c = r["comparisons"][0]
    assert c["significant"], "a 98/2 split with a well-powered small arm reads"
    assert any("SPLIT IMBALANCE" in w for w in r["warnings"]), (
        "it still has to say the split was lopsided")


# --- the pre-shift rescore --------------------------------------------------
#
# A lopsided split usually means traffic was moved to a presumed winner
# mid-flight. Everything after that moment is not randomised. Warning about it
# and then scoring the whole window anyway states a rule and breaks it in the
# same breath.

def test_a_lopsided_split_is_rescored_on_the_periods_before_the_shift():
    a = arm("A", 10_000, 300, periods={"delivered": [1000, 1000, 8000],
                                       "clicked": [30, 30, 240]})
    b = arm("B", 2_100, 63, periods={"delivered": [1000, 1000, 100],
                                     "clicked": [30, 30, 3]})
    r = analyse(payload(a, b))
    assert r["basis"] == "pre_shift", (
        "the balanced periods exist and are the only randomised evidence")
    c = r["comparisons"][0]
    assert (c["a_n"], c["b_n"]) == (2000, 2000), "must drop the post-shift period"


def test_a_lopsided_split_with_no_period_data_says_it_could_not_be_rescored():
    """Never imply a rescore that did not happen."""
    r = analyse(payload(arm("A", 10_000, 300), arm("B", 2_000, 40)))
    w = [x for x in r["warnings"] if "SPLIT IMBALANCE" in x]
    assert w and "could not" in w[0].lower()
    assert r["basis"] == "lifetime"


def test_a_split_lopsided_from_the_first_period_is_not_rescored():
    """No balanced prefix means there is no randomised window to fall back to."""
    a = arm("A", 9_000, 270, periods={"delivered": [3000, 3000, 3000],
                                      "clicked": [90, 90, 90]})
    b = arm("B", 900, 27, periods={"delivered": [300, 300, 300],
                                   "clicked": [9, 9, 9]})
    r = analyse(payload(a, b))
    assert r["basis"] != "pre_shift"
    assert any("no balanced" in w.lower() for w in r["warnings"])


# --- a winner declared part way through ----------------------------------
#
# The usual end of a test is not both arms stopping together. One arm stops and
# the other keeps sending, because somebody called it and routed the remaining
# traffic to the winner. The volume ratio does not reveal this — a designed
# uneven split produces the same ratio — but the shape of the series does.

def test_an_arm_that_stops_while_another_continues_is_flagged_as_a_declaration():
    a = arm("A", 3000, 90, periods={"delivered": [1000, 1000, 1000],
                                    "clicked": [30, 30, 30]})
    b = arm("B", 1000, 30, periods={"delivered": [1000, 0, 0],
                                    "clicked": [30, 0, 0]})
    w = [x for x in analyse(payload(a, b))["warnings"] if "DECLARED" in x]
    assert w, "an arm ending while another continues is the declaration pattern"
    assert "finer" in w[0].lower(), (
        "the shared period can itself straddle the moment, so it must say the "
        "resolution may be too coarse rather than implying a clean window")


def test_arms_that_run_together_throughout_are_not_flagged():
    a = arm("A", 2000, 60, periods={"delivered": [1000, 1000], "clicked": [30, 30]})
    b = arm("B", 2000, 60, periods={"delivered": [1000, 1000], "clicked": [30, 30]})
    assert not any("DECLARED" in w for w in analyse(payload(a, b))["warnings"])


def test_the_declaration_check_is_suppressed_across_two_different_tests():
    """Two campaigns are expected to start and stop on their own calendars."""
    a = arm("A", 3000, 90, periods={"delivered": [1000, 1000, 1000],
                                    "clicked": [30, 30, 30]})
    b = arm("B", 1000, 30, periods={"delivered": [1000, 0, 0],
                                    "clicked": [30, 0, 0]})
    assert not any("DECLARED" in w
                   for w in analyse(payload(a, b), cross=True)["warnings"])


def test_the_split_check_is_suppressed_across_two_different_tests():
    """Two campaigns were never one pool, so unequal volume implies nothing."""
    r = analyse(payload(arm("A", 100_000, 2000), arm("B", 10_000, 200)),
                cross=True)
    assert not any("SPLIT IMBALANCE" in w for w in r["warnings"])


# --- which metric gets scored -----------------------------------------------

def test_raw_clicks_are_preferred_over_human_only_counts():
    r = analyse(payload(arm("A", 1000, 50, human_clicked=30),
                        arm("B", 1000, 40, human_clicked=25)))
    assert r["primary_metric"] == "clicked"


def test_human_clicks_are_scored_only_when_raw_counts_are_absent_and_it_says_so():
    a = {"id": "A", "name": "A", "delivered": 1000, "human_clicked": 30}
    b = {"id": "B", "name": "B", "delivered": 1000, "human_clicked": 25}
    r = analyse(payload(a, b))
    assert r["primary_metric"] == "human_clicked"
    assert any("HUMAN CLICKS ONLY" in w for w in r["warnings"])


def test_first_present_falls_through_to_the_last_candidate():
    assert first_present([{"human_clicked": 3}], ("clicked", "human_clicked")) \
        == "human_clicked"


# --- the window -------------------------------------------------------------

def test_scoring_prefers_the_window_where_both_arms_were_live():
    """Lifetime totals compare different calendars; the overlap does not."""
    a = arm("A", 11000, 300, periods={"delivered": [10000, 1000],
                                      "clicked": [280, 20]})
    b = arm("B", 1000, 10, periods={"delivered": [0, 1000], "clicked": [0, 10]})
    r = analyse(payload(a, b))
    assert r["basis"] == "overlap"
    assert r["comparisons"][0]["a_n"] == 1000, "must score the shared period only"


def test_no_period_data_says_the_windows_were_never_verified():
    r = analyse(payload(arm("A", 1000, 30), arm("B", 1000, 25)))
    assert r["basis"] == "lifetime"
    assert any("NO PERIOD DATA" in w for w in r["warnings"])


# --- reading the open gap ---------------------------------------------------

def test_an_open_gap_under_an_identical_subject_is_flagged_for_investigation():
    r = analyse(payload(arm("A", 20000, 300, opened=10000),
                        arm("B", 20000, 300, opened=6000)))
    gap = [w for w in r["warnings"] if "OPEN GAP" in w]
    assert gap, "the subject cannot explain it, so it must be raised"
    assert "deliverability" in gap[0], (
        "the first suspect is the lower-opening template, not a broken split")
    assert "B" in gap[0], "it has to name which arm opened worse"


def test_the_open_gap_check_is_suppressed_across_two_different_tests():
    """Two campaigns months apart are expected to differ on opens."""
    r = analyse(payload(arm("A", 20000, 300, opened=10000),
                        arm("B", 20000, 300, opened=6000)), cross=True)
    assert not any("OPEN GAP" in w for w in r["warnings"])


# --- inputs that must not produce a confident answer ------------------------

def test_a_numerator_above_its_denominator_is_refused_not_scored():
    """A mis-mapped column produced a 500% click rate at p=0.0000."""
    with pytest.raises(SystemExit) as e:
        analyse(payload(arm("A", 100, 500), arm("B", 1000, 20)))
    assert "impossible counts" in str(e.value)
    assert "exceeds delivered" in str(e.value)


def test_impossible_counts_never_reach_the_maths():
    """Both arms over 100% used to raise ValueError out of math.sqrt."""
    assert two_proportion_z(500, 100, 500, 100) == (5.0, 5.0, 0.0, 0.0, 1.0)


def test_a_null_inside_a_period_series_is_read_as_zero():
    """ESPs return null for a month with no data; comparing it raised."""
    a = arm("A", 100, 5, periods={"delivered": [10, None, 20],
                                  "clicked": [1, 0, 4]})
    b = arm("B", 100, 7, periods={"delivered": [10, 5, 20],
                                  "clicked": [1, 2, 4]})
    r = analyse(payload(a, b))
    assert r["comparisons"][0]["p_value"] <= 1.0


def test_num_coerces_only_real_numbers():
    assert num(None) == 0 and num("12") == 0 and num(True) == 0
    assert num(7) == 7 and num(1.5) == 1.5


def test_every_arm_shares_one_basis_or_none_of_them_do():
    """One arm's window against another's lifetime produced a decisive winner
    out of a mismatch — p=0.00026 on numbers that were never comparable."""
    a = arm("A", 11000, 300, periods={"delivered": [10000, 1000],
                                      "clicked": [280, 20]})
    b = arm("B", 1000, 50, periods={"delivered": [0, 1000]})  # no clicked series
    r = analyse(payload(a, b))
    assert r["basis"] == "lifetime", "cannot window one arm and not the other"
    c = r["comparisons"][0]
    assert (c["a_n"], c["a_x"]) == (11000, 300)
    assert (c["b_n"], c["b_x"]) == (1000, 50)
    assert any("MIXED PERIOD DATA" in w for w in r["warnings"])


def test_check_counts_passes_clean_data():
    check_counts([{"name": "A", "delivered": 100, "clicked": 5}], {"clicked"})


def test_a_cross_test_read_is_labelled_observational_without_being_asked():
    r = analyse(payload(arm("A", 20000, 400), arm("B", 20000, 200)), cross=True)
    assert any("OBSERVATIONAL" in w for w in r["warnings"])


def test_a_cross_test_never_reads_like_a_randomised_win():
    """Even once the cohort is confirmed, the language has to stay downgraded."""
    r = analyse(payload(arm("A", 20000, 400), arm("B", 20000, 200)),
                cross=True, cohort_answered=True)
    out = render(r)
    assert "outperformed" in out and "wins" not in out


def test_an_unqualified_cross_test_payload_asks_before_naming_a_winner():
    """Across two sends, no cohort metadata means the question is unanswered."""
    r = analyse(payload(arm("A", 20000, 400), arm("B", 20000, 200)), cross=True)
    assert r["cohort_gate"]["state"] == "ask"
    assert "VERDICT WITHHELD" in render(r)


# --- regressions from the Macroscope review on PR #144 -----------------------

def test_a_measured_zero_is_a_value_not_an_absent_field():
    """An arm that genuinely earned no clicks reported `clicked: 0`. Read by
    truthiness that was "no raw count was supplied", so the scorer switched to
    human clicks and printed a warning saying the raw count was missing when it
    was there and was zero."""
    arms = [arm("a", 1000, 0, **{"human_clicked": 5}),
            arm("b", 1000, 0, **{"human_clicked": 9})]
    assert first_present(arms, ("clicked", "human_clicked")) == "clicked"
    r = analyse(payload(*arms))
    assert r["primary_metric"] == "clicked"
    assert not any("HUMAN CLICKS ONLY" in w for w in r["warnings"])


def test_a_genuinely_absent_raw_count_still_falls_back():
    arms = [{"id": "a", "name": "a", "subject": "S", "delivered": 1000,
             "human_clicked": 40},
            {"id": "b", "name": "b", "subject": "S", "delivered": 1000,
             "human_clicked": 60}]
    r = analyse(payload(*arms))
    assert r["primary_metric"] == "human_clicked"
    assert any("HUMAN CLICKS ONLY" in w for w in r["warnings"])


def test_a_numerator_above_a_zero_denominator_is_still_a_mapping_error():
    """`delivered: 0, clicked: 10` is the same impossible count as 500%, but it
    does not print 500% — the z-test turns it into a neutral no-read, which is
    indistinguishable from a test that genuinely settled nothing."""
    with pytest.raises(SystemExit) as e:
        check_counts([arm("a", 0, 10), arm("b", 1000, 50)], ["clicked"])
    assert "exceeds delivered" in str(e.value)


def test_an_arm_that_has_simply_not_sent_yet_is_not_an_error():
    check_counts([arm("a", 0, 0), arm("b", 1000, 50)], ["clicked"])


def test_identical_subject_diagnostic_survives_string_counts():
    """These four values bypassed num(), so string open counts raised TypeError
    out of a diagnostic and aborted the whole analysis. num() reads a string as
    zero, so the diagnostic now declines to run instead of crashing."""
    arms = [arm("a", 1000, 50, opened="300"), arm("b", 1000, 50, opened="200")]
    r = analyse(payload(*arms))
    assert r["comparisons"]
    assert not any("OPEN GAP" in w for w in r["warnings"])


def test_a_wholly_stringly_typed_payload_is_a_mapping_error_not_a_no_read():
    """num() reads a string as zero, so string counts used to score as a tidy
    nothing-happened. With the zero-denominator guard gone they land where every
    other impossible count lands."""
    with pytest.raises(SystemExit) as e:
        analyse(payload(arm("a", "1000", 50), arm("b", "1000", 50)))
    assert "exceeds delivered" in str(e.value)


def test_a_raw_click_win_human_clicks_contradict_is_withheld():
    """Machine activity is only even-handed while it treats both arms alike, and
    it stops doing so when the links differ. A scanner working one arm's changed
    URLs lands in `clicked` looking exactly like a person acting."""
    arms = [arm("a", 10000, 200, **{"human_clicked": 100}),
            arm("b", 10000, 400, **{"human_clicked": 105})]
    r = analyse(payload(*arms))
    c = r["comparisons"][0]
    assert c["significant"], "the raw spread is real; that is the point"
    assert c["human_click_check"]["corroborates"] is False
    assert any("RAW CLICKS WIN, HUMAN CLICKS DO NOT" in w for w in r["warnings"])
    assert "VERDICT: WITHHELD" in render(r)


def test_a_raw_click_win_human_clicks_confirm_still_reads_as_a_win():
    arms = [arm("a", 10000, 200, **{"human_clicked": 180}),
            arm("b", 10000, 400, **{"human_clicked": 370})]
    r = analyse(payload(*arms))
    c = r["comparisons"][0]
    assert c["significant"] and c["human_click_check"]["corroborates"]
    out = render(r)
    assert "VERDICT: WITHHELD" not in out and "Human clicks agree" in out


def test_no_machine_split_means_nothing_to_check():
    """Most ESPs do not report the split. Its absence must not manufacture a
    doubt, and must not crash the check either."""
    r = analyse(payload(arm("a", 10000, 200), arm("b", 10000, 400)))
    c = r["comparisons"][0]
    assert "human_click_check" not in c
    assert c["significant"] and c["winner"] == "b"


# --- regressions from the second Macroscope review on PR #144 ----------------

def test_a_metric_no_arm_carries_is_refused_not_scored_as_zero():
    """An absent count reads as zero, and zero is not an error anywhere below:
    against another zero it is a tidy no-read, and against a real count it is a
    significant win for whichever arm happened to carry the field."""
    with pytest.raises(SystemExit) as e:
        analyse({"test": "typo", "primary_metric": "clickd", "arms": [
            arm("a", 10000, 200), arm("b", 10000, 400)]})
    assert "clickd" in str(e.value)


def test_one_arm_missing_the_metric_cannot_hand_the_other_a_win():
    with pytest.raises(SystemExit) as e:
        analyse({"test": "half", "primary_metric": "converted", "arms": [
            arm("a", 10000, 200, converted=90),
            arm("b", 10000, 400)]})
    assert "converted" in str(e.value) and "b" in str(e.value)


def test_negative_counts_are_input_errors_not_a_no_read():
    with pytest.raises(SystemExit) as e:
        check_counts([arm("a", 1000, -5), arm("b", 1000, 50)], ["clicked"])
    assert "negative" in str(e.value)

    with pytest.raises(SystemExit) as e:
        check_counts([arm("a", -1000, 5), arm("b", 1000, 50)], ["clicked"])
    assert "negative" in str(e.value)


def test_three_arms_are_scored_against_a_tightened_bar():
    """Three pairwise tests at 0.05 each carry a ~14% chance of a false winner
    somewhere. A spread that clears 0.05 but not the corrected bar is a no-read,
    and saying otherwise is the error the correction exists to stop."""
    arms_ = [arm("a", 8000, 160), arm("b", 8000, 198), arm("c", 8000, 175)]
    r = analyse(payload(*arms_))
    assert r["comparisons_in_family"] == 3
    assert 0.016 < r["alpha_per_comparison"] < 0.018

    ab = next(c for c in r["comparisons"]
              if {c["a"], c["b"]} == {"a", "b"})
    assert 0.017 < ab["p_value"] < 0.05, "the fixture must sit in the gap"
    assert not ab["significant"], "read at 0.05 this would be a false winner"
    assert any("3 ARMS, 3 COMPARISONS" in w for w in r["warnings"])


def test_two_arms_keep_the_configured_alpha():
    r = analyse(payload(arm("a", 8000, 160), arm("b", 8000, 198)))
    assert r["comparisons_in_family"] == 1
    assert r["alpha_per_comparison"] == 0.05
    assert r["comparisons"][0]["significant"]
    assert not any("COMPARISONS:" in w for w in r["warnings"])


def test_the_required_sample_is_sized_against_the_corrected_bar():
    """Otherwise the answer to "how much more do I need" is short by the
    correction, and the next read arrives just as unable to settle it."""
    two = analyse(payload(arm("a", 8000, 160), arm("b", 8000, 170)))
    three = analyse(payload(arm("a", 8000, 160), arm("b", 8000, 170),
                            arm("c", 8000, 165)))
    ab2 = two["comparisons"][0]
    ab3 = next(c for c in three["comparisons"] if {c["a"], c["b"]} == {"a", "b"})
    assert ab3["n_needed_per_arm"] > ab2["n_needed_per_arm"]


# --- regressions from the third Macroscope review on PR #144 -----------------

def test_period_series_that_do_not_survive_summing_are_refused():
    """`check_counts` validated the lifetime totals. `windowed` sums a different
    set of numbers, and nothing had checked those — so a payload whose totals
    are sound and whose series are not reached the z-test as a rate above 100%
    and came back as the most decisive win the tool can print."""
    a = arm("a", 10000, 50, periods={"delivered": [10, 10], "clicked": [50, 0]})
    b = arm("b", 10000, 90, periods={"delivered": [5000, 5000],
                                     "clicked": [45, 45]})
    with pytest.raises(SystemExit) as e:
        analyse(payload(a, b))
    assert "scored window" in str(e.value)


def test_lifetime_scoring_is_not_blocked_by_the_windowed_check():
    """The check applies to the numbers actually scored. With no overlap basis
    there is no windowed sum to validate."""
    r = analyse(payload(arm("a", 10000, 200), arm("b", 10000, 400)))
    assert r["basis"] == "lifetime" and r["comparisons"]


def test_json_does_not_name_a_winner_the_report_withholds():
    """The renderer hid these verdicts and the JSON handed them straight back.
    A refusal that only exists in the text output is not a refusal — `--json` is
    what anything downstream reads."""
    arms_ = [arm("a", 10000, 200, **{"human_clicked": 100}),
             arm("b", 10000, 400, **{"human_clicked": 105})]
    c = analyse(payload(*arms_))["comparisons"][0]
    assert c["verdict"] == "withheld"
    assert c["winner"] is None and c["loser"] is None
    assert c["leader"] == "b", "who leads is a fact and stays reported"
    assert "corroborate" in c["verdict_reason"]


def test_a_blocked_cohort_also_clears_the_winner_in_json():
    def side(name, cid, seg, rule):
        a = arm(name, 10000, 200 if name == "a" else 400)
        a["cohort"] = {"campaign_id": cid, "campaign_name": cid,
                       "fields": {"trigger_segment_ids": [seg]}, "context": {},
                       "segments": [{"id": seg, "name": seg, "type": "manual",
                                     "rule": rule}],
                       "static_lists": [seg], "resolved": True}
        return a

    r = analyse(payload(side("a", "c1", "s1", None), side("b", "c2", "s2", None),
                        mode="cross_test"))
    c = r["comparisons"][0]
    assert r["cohort_gate"]["state"] in ("ask", "void")
    assert c["verdict"] == "withheld" and c["winner"] is None
    assert "cohort" in c["verdict_reason"]


def test_a_clean_win_still_names_its_winner():
    c = analyse(payload(arm("a", 10000, 200),
                        arm("b", 10000, 400)))["comparisons"][0]
    assert c["verdict"] == "winner" and c["winner"] == "b" and c["loser"] == "a"


def test_a_no_read_says_so_in_json():
    c = analyse(payload(arm("a", 10000, 200),
                        arm("b", 10000, 205)))["comparisons"][0]
    assert c["verdict"] == "no_read" and c["winner"] is None


def test_no_window_is_reported_when_none_was_scored():
    """Reporting a window beside lifetime totals describes a measurement that
    did not happen."""
    r = analyse(payload(arm("a", 10000, 200), arm("b", 10000, 400)))
    assert r["basis"] == "lifetime"
    assert r["scored_window"].get("scored") == "lifetime totals"
    assert "from" not in r["scored_window"] and "days" not in r["scored_window"]


# --- regressions from the fourth Macroscope review on PR #144 ----------------

def test_an_arm_without_a_delivered_count_is_refused():
    """`num(None)` is 0, and a zero denominator does not fail — it returns a
    neutral no-read, which is what a test that genuinely settled nothing looks
    like. `check_counts` only exposes it when the numerator above it is
    nonzero, so a 0/0 arm sailed through."""
    a = {"id": "a", "name": "a", "subject": "S", "clicked": 0}
    b = {"id": "b", "name": "b", "subject": "S", "delivered": 1000,
         "clicked": 50}
    with pytest.raises(SystemExit) as e:
        analyse(payload(a, b))
    assert "delivered" in str(e.value) and "a" in str(e.value)


def test_a_delivered_count_of_zero_is_still_a_value():
    """An arm that has not sent yet is not a malformed payload."""
    r = analyse(payload(arm("a", 0, 0), arm("b", 1000, 50)))
    assert r["comparisons"][0]["verdict"] == "no_read"


def test_no_period_data_is_not_reported_as_no_window_in_common():
    """`not x` is true for both None and []. None means there is no period
    series to scan; [] means the scan ran and found nothing shared. Only the
    second is 'no window in common', and saying it for the first contradicts
    the NO PERIOD DATA warning printed a few lines below it."""
    a = arm("a", 10000, 200)
    b = arm("b", 10000, 400)
    for x, first in ((a, 1780000000), (b, 1780000000)):
        x["window"] = {"verified": True, "first_send": first,
                       "last_send": first + 86400,
                       "first_send_date": "2026-05-28",
                       "last_send_date": "2026-05-29"}
    r = analyse(payload(a, b))
    assert r["overlap_periods"] is None
    assert "no window in common" not in render(r)
    assert any("NO PERIOD DATA" in w for w in r["warnings"])
