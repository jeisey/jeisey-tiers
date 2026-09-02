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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ffdraft.paths import config_dir

__all__ = [
    "ALIAS_FILENAME",
    "GENERATED_ALIAS_DIRNAME",
    "AliasEntry",
    "AliasMap",
    "default_alias_path",
    "generated_alias_path",
    "load_alias_map",
    "load_production_aliases",
]

#: The reviewed alias file, relative to ``config/``. One agreed location, so a capture and
#: the fixture pipeline cannot disagree about which reviews are in force.
ALIAS_FILENAME = "identity-aliases.yaml"

#: Where *generated* alias files live, one per source (Phase 10, ADR-061).
#:
#: They are kept out of ``identity-aliases.yaml`` deliberately. That file's whole meaning is
#: "a person looked at this and wrote it down"; a few hundred machine proposals mixed in
#: would destroy the distinction between a reviewed exception and a bulk linkage run. A
#: generated file carries its rule version and its run date in a header, so a reader can see
#: which rule produced it and re-run that rule to reproduce it.
GENERATED_ALIAS_DIRNAME = "market-aliases"


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


def default_alias_path(*, root: Path | None = None) -> Path:
    """The repository's reviewed alias file."""
    return config_dir(root=root) / ALIAS_FILENAME


def generated_alias_path(source_id: str, *, root: Path | None = None) -> Path:
    """The generated alias file for one source."""
    return config_dir(root=root) / GENERATED_ALIAS_DIRNAME / f"{source_id}.yaml"


def load_production_aliases(
    *,
    source_ids: Sequence[str] = (),
    root: Path | None = None,
) -> AliasMap:
    """The reviewed file plus each named source's generated file, merged.

    **The reviewed file wins.** A generated proposal is a machine's reading of a name; a
    reviewed entry is a person's decision about a specific player, usually written precisely
    because the automatic path got it wrong or could not see him. Letting a nightly
    regeneration overwrite that would make the review pointless, so the merge order is not
    negotiable and a test pins it.
    """
    merged: dict[tuple[str, str], AliasEntry] = {}
    for source_id in source_ids:
        merged.update(load_alias_map(generated_alias_path(source_id, root=root)).entries)
    merged.update(load_alias_map(default_alias_path(root=root)).entries)
    return AliasMap(entries=merged)
