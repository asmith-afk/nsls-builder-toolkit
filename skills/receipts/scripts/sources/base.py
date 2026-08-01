#!/usr/bin/env python3.12
"""Contract every receipt source implements."""

import hashlib
import importlib
import pkgutil
import re
import unicodedata
from dataclasses import dataclass


class SourceUnavailable(Exception):
    """Source could not run — auth, network, config. Never a match failure."""


@dataclass(frozen=True)
class Receipt:
    merchant: str        # normalized
    amount_cents: int
    date: str            # ISO yyyy-mm-dd
    pdf_bytes: bytes
    provenance: str      # e.g. "anthropic:invoice 2026-07-19 108500"


def normalize_merchant(name: str) -> str:
    """Fold a merchant name to a comparable key.

    Two failures the naive `[^a-z0-9]` strip produced, both silent:

    * Accented Latin lost its letters instead of folding them. Ramp's
      "München" became "mnchen" while a receipt's "Munchen" became "munchen",
      so a real receipt for a real charge came back UNFOUND. NFKD decomposes
      the letter into base + combining mark; dropping only the marks keeps
      the base letter.
    * Merchants written entirely in a non-Latin script collapsed to "" — and
      so compared EQUAL to every other such merchant, and to a blank name.
      That is the dangerous direction: equal keys make one vendor's receipt an
      automatic upload against another vendor's charge. When nothing survives
      the fold, fall back to a per-name key that only ever equals itself.

    The result is always [a-z0-9]*, so normalize_merchant is idempotent —
    match.py re-normalizes already-normalized Receipt.merchant values.
    """
    decomposed = unicodedata.normalize("NFKD", name or "")
    folded = "".join(c for c in decomposed if not unicodedata.combining(c))
    slug = re.sub(r"[^a-z0-9]", "", folded.lower())
    if slug:
        return slug

    # Nothing survived. A name that is genuinely blank stays blank — there is
    # no merchant to distinguish. A name with real content gets a stable,
    # process-independent sentinel built only from [a-z0-9], so re-normalizing
    # it is a no-op and no two different names can ever collide into "".
    stripped = " ".join((name or "").split())
    if not stripped:
        return ""
    return "x" + hashlib.sha1(stripped.casefold().encode("utf-8")).hexdigest()[:16]


def load_sources(errors: list | None = None) -> list:
    """Every sources/*.py module exposing a SOURCE singleton.

    One source failing at import — a missing dependency, a syntax error, a
    module-level side effect that raises — must not end discovery for the
    others. Failures are appended to `errors` as "NAME: reason" so the caller
    can announce them the same way it announces a source that was skipped at
    fetch time. Swallowing them silently would leave a run that found fewer
    receipts than it should looking exactly like a clean one.
    """
    import sources

    found = []
    for mod in pkgutil.iter_modules(sources.__path__):
        if mod.name == "base":
            continue
        try:
            module = importlib.import_module(f"sources.{mod.name}")
        except Exception as exc:
            if errors is not None:
                errors.append(f"{mod.name.upper()}: import failed — {type(exc).__name__}: {exc}")
            continue
        if hasattr(module, "SOURCE"):
            found.append(module.SOURCE)
    return found
