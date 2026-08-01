#!/usr/bin/env python3.12
"""Contract every receipt source implements."""

import importlib
import pkgutil
import re
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
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


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
