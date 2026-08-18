#!/usr/bin/env python3
"""Tests for the cohort gate — pure, no I/O.

Comparability is not a calendar question. Two sends can overlap perfectly and
still be incomparable because they went to different people, and they can be
months apart and perfectly comparable because the rule that selected them never
changed. The gate exists so that question is answered before a winner is named,
and these tests pin where it decides versus where it must ask.

Deciding wrongly in either direction is a real cost: a gate that cries void gets
switched off, and a gate that waves everything through is decoration.

Hermetic: builds cohort metadata in memory.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from abstats import analyse, cohort_gate, render, trigger_rules, undate

PRO = [{"attribute": {"field": "plan", "operator": "eq", "value": "pro"}}]
OTHER_RULE = [{"attribute": {"field": "country", "operator": "eq", "value": "CA"}}]
PRO_APRIL = PRO + [{"attribute": {"field": "joined", "operator": "gt",
                                  "value": "2026-04-01"}}]
PRO_JUNE = PRO + [{"attribute": {"field": "joined", "operator": "gt",
                                 "value": "2026-06-01"}}]


def cohort(cid, seg_id, seg_type="dynamic", rule=None):
    return {"campaign_id": str(cid), "campaign_name": f"campaign {cid}",
            "fields": {"trigger_segment_ids": [seg_id]}, "context": {},
            "segments": [{"id": seg_id, "name": f"segment {seg_id}",
                          "type": seg_type, "rule": rule}],
            "static_lists": [seg_id] if seg_type == "manual" else [],
            "resolved": True}


def arms(*cohorts):
    return [{"name": f"arm{i}", "cohort": c} for i, c in enumerate(cohorts)]


# --- where it can see, it decides -------------------------------------------

def test_identical_rules_proceed():
    g = cohort_gate(arms(cohort(1, 10, rule=PRO), cohort(2, 11, rule=PRO)),
                    cross=True)
    assert g["state"] == "ok"


def test_one_rule_run_at_two_different_times_proceeds():
    """The legitimate longitudinal case: same definition, April and June."""
    g = cohort_gate(arms(cohort(1, 10, rule=PRO_APRIL),
                         cohort(2, 11, rule=PRO_JUNE)), cross=True)
    assert g["state"] == "ok", g["why"]
    assert "date window" in g["why"]


def test_rules_that_plainly_differ_are_two_populations_and_it_says_so():
    g = cohort_gate(arms(cohort(1, 10, rule=PRO), cohort(2, 11, rule=OTHER_RULE)),
                    cross=True)
    assert g["state"] == "void", (
        "when the rules are readable and different, asking the operator is "
        "punting on a question already answered")


# --- where it cannot see, it asks -------------------------------------------

def test_a_static_list_has_no_rule_to_compare_so_it_asks():
    """A hand-built or CSV-imported list has no membership rule to read."""
    g = cohort_gate(arms(cohort(1, 10, "manual"), cohort(2, 11, "manual")),
                    cross=True)
    assert g["state"] == "ask"
    assert "static list" in g["why"]


def test_bare_segment_ids_are_pointers_not_answers():
    """A rebuilt segment can carry the same rule under a new id."""
    a = {"campaign_id": "1", "fields": {"trigger_segment_ids": [10]},
         "segments": [], "resolved": True}
    b = {"campaign_id": "2", "fields": {"trigger_segment_ids": [11]},
         "segments": [], "resolved": True}
    assert cohort_gate(arms(a, b), cross=True)["state"] == "ask"


# --- what must never be blocked ---------------------------------------------

def test_a_single_campaign_never_raises_the_question():
    """One campaign means one entry condition by construction."""
    g = cohort_gate(arms(cohort(7, 10, "manual"), cohort(7, 10, "manual")))
    assert g["state"] == "ok"


def test_a_legacy_payload_with_no_cohort_metadata_still_scores():
    """The gate is for comparisons across sends, not a tax on every payload."""
    r = analyse({"test": "t", "arms": [
        {"id": "A", "name": "A", "delivered": 20000, "clicked": 400},
        {"id": "B", "name": "B", "delivered": 20000, "clicked": 200}]})
    assert r["cohort_gate"]["state"] == "ok"
    assert r["comparisons"][0]["winner"] == "A"


# --- the operator's answer --------------------------------------------------

def test_the_operator_can_answer_either_way():
    a = arms(cohort(1, 10, "manual"), cohort(2, 11, "manual"))
    assert cohort_gate(a, cross=True, answered=True)["state"] == "ok"
    assert cohort_gate(a, cross=True, answered=False)["state"] == "void"


def test_an_unresolved_gate_withholds_the_winner_but_still_prints_the_rates():
    p = {"test": "t", "mode": "cross_test", "arms": [
        {"id": "A", "name": "A", "delivered": 20000, "clicked": 400,
         "cohort": cohort(1, 10, "manual")},
        {"id": "B", "name": "B", "delivered": 20000, "clicked": 200,
         "cohort": cohort(2, 11, "manual")}]}
    out = render(analyse(p))
    assert "VERDICT WITHHELD" in out
    assert "2.000%" in out and "1.000%" in out, (
        "the rates are facts and must survive a withheld verdict")


# --- the date-blanking pass -------------------------------------------------

def test_undate_blanks_dates_without_touching_the_rest_of_the_rule():
    out = undate({"field": "joined", "value": "2026-04-01", "op": "gt"})
    assert out == {"field": "joined", "value": "<date>", "op": "gt"}


def test_undate_leaves_a_duration_alone():
    """`within: 2592000` is thirty days expressed in seconds, not a timestamp."""
    assert undate({"within": 2592000}) == {"within": 2592000}


def test_undate_blanks_epoch_timestamps():
    assert undate({"ts": 1775767313}) == {"ts": "<date>"}


def test_trigger_rules_is_none_when_any_segment_has_no_rule():
    assert trigger_rules(cohort(1, 10, "manual")) is None
    assert trigger_rules(cohort(1, 10, rule=PRO)) is not None


# --- regressions from the Macroscope review on PR #144 -----------------------

def test_an_ordinary_numeric_identifier_is_not_blanked_as_a_date():
    """`undate` blanks the date window so one rule run twice reads as one rule.
    Matching any 9-13 digit run made it blank identifiers too, so two rules
    naming different lists compared as identical and a winner was named for
    populations that never overlapped."""
    assert undate({"list_id": "123456789"}) == {"list_id": "123456789"}
    assert undate({"list_id": "1234567890123"}) == {"list_id": "1234567890123"}


def test_two_rules_differing_only_by_a_list_id_are_two_populations():
    a = [{"attribute": {"field": "list_id", "operator": "eq",
                        "value": "123456789"}}]
    b = [{"attribute": {"field": "list_id", "operator": "eq",
                        "value": "987654321"}}]
    gate = cohort_gate(arms(cohort(1, "s1", rule=a), cohort(2, "s2", rule=b)),
                       cross=True)
    assert gate["state"] == "void", gate


def test_a_real_date_window_is_still_blanked():
    """The feature the regression above must not break: April and June are one
    rule applied twice, in either notation."""
    assert undate("2026-04-01") == "<date>"
    assert undate("2026-04-01T00:00:00Z") == "<date>"
    assert undate(1712000000) == "<date>"
    gate = cohort_gate(arms(cohort(1, "s1", rule=PRO_APRIL),
                            cohort(2, "s2", rule=PRO_JUNE)), cross=True)
    assert gate["state"] == "ok" and "date window" in gate["why"]
