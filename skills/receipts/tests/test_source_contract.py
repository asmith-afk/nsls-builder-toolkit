#!/usr/bin/env python3.12
"""Contract applied to every source, so new vendors are covered on arrival."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from sources.base import Receipt, load_sources, normalize_merchant


def test_normalize_merchant_collapses_case_and_punctuation():
    assert normalize_merchant("Anthropic, PBC") == "anthropicpbc"
    assert normalize_merchant("Neon Tech") == "neontech"
    assert normalize_merchant("ANTHROPIC") == "anthropic"


def test_accented_latin_folds_to_its_base_letters():
    # Stripping every non-ASCII byte turns "München" into "mnchen" while a
    # receipt spelling it "Munchen" becomes "munchen" — same merchant, same
    # amount, same date, and they never bind.
    assert normalize_merchant("München") == normalize_merchant("Munchen")
    assert normalize_merchant("München") == "munchen"
    assert normalize_merchant("Café Sécurité") == normalize_merchant("Cafe Securite")
    assert normalize_merchant("ÄÖÜ Gmbh") == "aou gmbh".replace(" ", "")


def test_non_latin_merchants_do_not_all_collapse_into_one():
    # Every merchant written entirely in a non-Latin script normalizes to the
    # empty string, so they all compare equal to each other — a wrong receipt
    # bound to the wrong transaction, uploaded automatically.
    tokyo = normalize_merchant("東京カフェ")
    osaka = normalize_merchant("大阪ストア")
    moscow = normalize_merchant("Москва")
    assert tokyo, "a non-Latin merchant must not normalize to the empty string"
    assert len({tokyo, osaka, moscow}) == 3, (
        f"distinct non-Latin merchants must stay distinct: {tokyo!r} {osaka!r} {moscow!r}"
    )


def test_non_latin_normalization_is_stable_and_idempotent():
    # match.py re-normalizes an already-normalized Receipt.merchant, so
    # normalize(normalize(x)) must equal normalize(x) or the second pass
    # mangles the value and nothing binds.
    once = normalize_merchant("東京カフェ")
    assert normalize_merchant("東京カフェ") == once, "must be deterministic across calls"
    assert normalize_merchant(once) == once, "must be idempotent"


def test_empty_and_missing_names_stay_empty():
    assert normalize_merchant("") == ""
    assert normalize_merchant(None) == ""
    assert normalize_merchant("   ") == ""


def test_receipt_is_immutable():
    r = Receipt("anthropic", 21456, "2026-07-23", b"%PDF-1.4", "anthropic:inv A")
    try:
        r.amount_cents = 1
    except AttributeError:
        return
    raise AssertionError("Receipt must be frozen")


def test_every_source_declares_normalized_merchants():
    sources = load_sources()
    assert sources, "load_sources() found no sources"
    for s in sources:
        assert isinstance(s.MERCHANTS, tuple), f"{type(s).__name__}.MERCHANTS must be a tuple"
        for m in s.MERCHANTS:
            assert m == normalize_merchant(m), f"{type(s).__name__}: {m!r} is not normalized"


def test_every_source_exposes_fetch():
    for s in load_sources():
        assert callable(getattr(s, "fetch", None)), f"{type(s).__name__} missing fetch()"


def test_all_three_shipped_sources_are_discovered():
    # Discovery is by module scan, so a source that fails to import — a typo,
    # a missing dependency, a module-level side effect that raises — simply
    # stops appearing, and every transaction it would have covered comes back
    # UNFOUND with no sign anything was wrong. Name what must be there.
    names = {type(s).__name__ for s in load_sources()}
    assert {"AnthropicSource", "GmailSource", "NeonSource"} <= names, names


def test_source_names_do_not_collide_in_the_report():
    # run.py labels each source `type(src).__name__.replace("Source", "").upper()`
    # — two sources folding to the same label would make one source's SKIPPED
    # or TRUNCATED line read as the other's.
    labels = [type(s).__name__.replace("Source", "").upper() for s in load_sources()]
    assert len(labels) == len(set(labels)), labels


if __name__ == "__main__":
    print("Running source contract tests")
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f(); print(f"  ok {n}")
    print("\nAll source contract tests passed.")
