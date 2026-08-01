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


if __name__ == "__main__":
    print("Running source contract tests")
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f(); print(f"  ok {n}")
    print("\nAll source contract tests passed.")
