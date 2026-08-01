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


def load_sources() -> list:
    """Every sources/*.py module exposing a SOURCE singleton."""
    import sources

    found = []
    for mod in pkgutil.iter_modules(sources.__path__):
        if mod.name == "base":
            continue
        module = importlib.import_module(f"sources.{mod.name}")
        if hasattr(module, "SOURCE"):
            found.append(module.SOURCE)
    return found
