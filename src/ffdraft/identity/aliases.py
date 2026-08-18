"""Human-reviewed identity aliases.

The resolver refuses to guess. That is correct, and it means some genuine records will not
resolve - a player MFL prices before nflverse lists him, an id an upstream never published.
The escape hatch is deliberately manual: a person inspects the case and writes it down here,
which produces a ``resolved_reviewed_alias`` outcome (`docs/DATA_CONTRACTS.md` 2.3).

The file format is intentionally boring::

    schema_version: "1.0"
    aliases:
      - source_id: myfantasyleague_adp
        external_id: "16162"
        player_id: "gsis:00-0039163"
        reviewed_by: someone
        reviewed_at: "2026-08-18"
        note: why this could not resolve by id

An alias never overrides an id bridge. If the bridges resolve to a different player, the
record fails closed as ambiguous instead - otherwise a stale alias would quietly outvote
live data, which is the failure mode the manual review exists to avoid.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

__all__ = ["AliasEntry", "AliasMap", "load_alias_map"]


@dataclass(frozen=True, slots=True)
class AliasEntry:
    """One reviewed mapping from an external id to a canonical player id."""

    source_id: str
    external_id: str
    player_id: str
    reviewed_by: str = ""
    reviewed_at: str = ""
    note: str = ""


@dataclass(frozen=True, slots=True)
class AliasMap:
    """Reviewed aliases, indexed by ``(source_id, external_id)``."""

    entries: Mapping[tuple[str, str], AliasEntry] = field(default_factory=dict)

    def get(self, source_id: str, external_id: str) -> AliasEntry | None:
        return self.entries.get((source_id, external_id))

    def __len__(self) -> int:
        return len(self.entries)

    @classmethod
    def empty(cls) -> AliasMap:
        return cls(entries={})


def load_alias_map(path: Path | None) -> AliasMap:
    """Load an alias file. A missing path yields an empty map, which is the normal state."""
    if path is None or not path.is_file():
        return AliasMap.empty()
    loaded: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries: dict[tuple[str, str], AliasEntry] = {}
    for raw in loaded.get("aliases") or ():
        entry = AliasEntry(
            source_id=str(raw["source_id"]),
            external_id=str(raw["external_id"]).strip(),
            player_id=str(raw["player_id"]).strip(),
            reviewed_by=str(raw.get("reviewed_by", "")),
            reviewed_at=str(raw.get("reviewed_at", "")),
            note=str(raw.get("note", "")),
        )
        key = (entry.source_id, entry.external_id)
        if key in entries:
            raise ValueError(f"{path}: duplicate alias for {key}")
        entries[key] = entry
    return AliasMap(entries=entries)
