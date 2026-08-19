"""Tier ordinals and the letters shown beside them.

`docs/MODELING.md` section 15: ordinal 0 is ``S``, then ``A``, ``B`` and so on. Past ``F``
the alphabet stops meaning anything, so deeper segments are labelled ``Late 1``, ``Late 2``
rather than inventing ``G`` or - worse - merging statistically distinct tiers to keep a
meme-style alphabet.

The ordinal is the data; the label is presentation. Nothing downstream should compute with a
letter, and a letter carries no claim beyond "this group sits above the next one in fair-rank
order".
"""

from __future__ import annotations

__all__ = ["LETTER_LABELS", "tier_label"]

#: The letters, in order. Ordinal 0 is the top tier.
LETTER_LABELS: tuple[str, ...] = ("S", "A", "B", "C", "D", "E", "F")


def tier_label(ordinal: int) -> str:
    """The display label for a tier ordinal."""
    if ordinal < 0:
        raise ValueError(f"tier ordinal must be non-negative, got {ordinal}")
    if ordinal < len(LETTER_LABELS):
        return LETTER_LABELS[ordinal]
    return f"Late {ordinal - len(LETTER_LABELS) + 1}"
