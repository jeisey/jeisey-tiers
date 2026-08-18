"""Name normalization — for resolver *candidates* only.

`docs/DATA_CONTRACTS.md` section 2.2 and ADR-005 are unambiguous: a normalized-name match
is not authoritative and may never resolve a production record on its own. This module
therefore exists to *propose* and to *diagnose*, never to decide. Nothing here returns a
canonical id, and the resolver treats its output as commentary attached to an unresolved
record so a human can see why a join failed.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = ["normalize_name", "name_key"]

_SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv", "v"})
_PUNCTUATION = re.compile(r"[^a-z0-9\s]")
_WHITESPACE = re.compile(r"\s+")


def normalize_name(raw: str | None) -> str:
    """Lowercase, strip accents, punctuation and generational suffixes."""
    if not raw:
        return ""
    decomposed = unicodedata.normalize("NFKD", raw)
    ascii_only = "".join(char for char in decomposed if not unicodedata.combining(char))
    lowered = _PUNCTUATION.sub(" ", ascii_only.lower())
    parts = [part for part in _WHITESPACE.split(lowered) if part and part not in _SUFFIXES]
    return " ".join(parts)


def name_key(raw: str | None) -> str:
    """A comparison key. Empty when the input carries no usable name."""
    return normalize_name(raw)
