#!/usr/bin/env python3
"""Tests for composing arms from separate tests into one cross-test payload.

Composition is the step where two fetches stop being two fetches, and the thing
that must survive it is what each arm was actually measured on. A payload that
labels itself with one metric while an arm carries another does not fail — it
scores that arm as zero and prints a comparison.

Hermetic: writes and reads payloads under tmp_path, no network.
"""

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import abcompare  # noqa: E402


def _write(tmp_path, prefix, metric, arm_id, **fields):
    base = {"id": arm_id, "name": f"arm {arm_id}", "subject": "S",
            "delivered": 1000}
    base.update(fields)
    (tmp_path / f"{prefix}.stats.json").write_text(json.dumps(
        {"test": prefix, "primary_metric": metric, "arms": [base]}),
        encoding="utf-8")
    (tmp_path / f"{prefix}.copy.json").write_text(json.dumps(
        {"arms": [{"id": arm_id, "name": f"arm {arm_id}", "subject": "S",
                   "body_html": "<p>x</p>"}]}), encoding="utf-8")


def _run_abcompare(tmp_path, monkeypatch, argv):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["abcompare.py"] + argv)
    abcompare.main()


def test_sources_scored_on_different_metrics_are_refused(tmp_path, monkeypatch,
                                                        capsys):
    """`metric = metric or ...` only ever initialised. A second source scored on
    another metric was relabelled with the first one's, and its arm — carrying
    no such field — scored as zero. That is a false comparison, and nothing
    about it looks like a failure."""
    _write(tmp_path, "q1", "clicked", "101", clicked=50)
    _write(tmp_path, "q2", "converted", "202", converted=30)
    with pytest.raises(SystemExit):
        _run_abcompare(tmp_path, monkeypatch,
                       ["--out", "cross", "q1:101", "q2:202"])
    err = capsys.readouterr().err
    assert "'converted'" in err and "'clicked'" in err
    assert not (tmp_path / "cross.stats.json").exists(), (
        "a refused composition must not leave a payload behind")


def test_an_explicit_metric_overrides_the_mismatch(tmp_path, monkeypatch):
    """The documented escape hatch: name the metric every arm carries."""
    _write(tmp_path, "q1", "clicked", "101", clicked=50, converted=10)
    _write(tmp_path, "q2", "converted", "202", clicked=90, converted=30)
    _run_abcompare(tmp_path, monkeypatch,
                   ["--out", "cross", "--metric", "clicked",
                    "q1:101", "q2:202"])
    out = json.loads((tmp_path / "cross.stats.json").read_text(encoding="utf-8"))
    assert out["primary_metric"] == "clicked"


def test_matching_metrics_compose_as_before(tmp_path, monkeypatch):
    _write(tmp_path, "q1", "clicked", "101", clicked=50)
    _write(tmp_path, "q2", "clicked", "202", clicked=90)
    _run_abcompare(tmp_path, monkeypatch,
                   ["--out", "cross", "q1:101", "q2:202"])
    out = json.loads((tmp_path / "cross.stats.json").read_text(encoding="utf-8"))
    assert out["primary_metric"] == "clicked" and out["mode"] == "cross_test"
