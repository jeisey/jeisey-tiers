"""Which retained market snapshot a draft board is priced with (ADR-094).

The draft board's information stops at ``min(build time, season draft anchor)``
(:func:`ffdraft.pipeline.current.current_cutoff`). Before the anchor that is the build time
and the newest snapshot is the right market. After it, the board is the draft-time board
every day for the rest of the season, and its market comparison has to be the draft-time
market too: a draft ADP feed does not stop publishing when drafting stops, it thins, and a
board priced from it in October measures how few people are still drafting rather than what
the draft market thought.

So the rule is one line, and it is the board's own rule applied to the market: once the
anchor binds, read the newest snapshot retrieved **at or before** the board's cutoff. Before
it binds, nothing changes.

The cutoff is read from the ``information_cutoff`` block `build-current` writes into
``build_metadata.json``, because every market stage runs offline from the retained store
and has no schedule of its own. A build older than that block has no cutoff to honour and
is priced exactly as before.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from ffdraft.timeutil import parse_utc

__all__ = ["MARKET_CUTOFF_RULE_VERSION", "market_cutoff"]

MARKET_CUTOFF_RULE_VERSION = "draft_market_at_board_cutoff_v1"


def market_cutoff(metadata: Mapping[str, Any]) -> datetime | None:
    """The instant the market must be read at, or ``None`` for the newest snapshot."""
    block = metadata.get("information_cutoff")
    if not isinstance(block, Mapping) or not block.get("anchor_binds"):
        return None
    raw = block.get("cutoff_at_utc")
    return parse_utc(str(raw)) if raw else None
