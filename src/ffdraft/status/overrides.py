"""Reviewed availability overrides (ADR-101): ``config/availability-overrides.yaml``.

Neither status feed says "out for the season": nflverse's ``RES`` and Sleeper's ``IR`` are the
same for a two-week stay and a season-long one. A person records the season-long case here,
from reliable public reporting, and the entry travels on the player's ``player_status`` record
as ``availability_override``. Only the downstream availability policy reads it.

The loader is strict because an entry removes a player from actionable lists: an unknown key,
a non-canonical id, a missing source, an expiry before the review, or a horizon other than
``season`` is a configuration error, not a warning. Whether an entry is *honoured* is the
policy's decision (it also requires a feed to still show the player on a reserve list), and is
deliberately not made here: this module only says which entries are in force for a build.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from ffdraft.paths import repo_root

__all__ = [
    "AVAILABILITY_OVERRIDES_PATH",
    "AvailabilityOverride",
    "AvailabilityOverrideError",
    "active_overrides",
    "load_availability_overrides",
]

AVAILABILITY_OVERRIDES_PATH = Path("config/availability-overrides.yaml")

_CANONICAL_ID = re.compile(r"^gsis:\d{2}-\d{7}$")
_ENTRY_KEYS = frozenset(
    {
        "player_id",
        "display_name",
        "season",
        "horizon",
        "summary",
        "sources",
        "reviewed_by",
        "reviewed_at",
        "expires_at",
    },
)
_HORIZONS = frozenset({"season"})


class AvailabilityOverrideError(ValueError):
    """The overrides file is malformed. Fatal: an entry changes what is actionable."""


@dataclass(frozen=True, slots=True)
class AvailabilityOverride:
    player_id: str
    display_name: str
    season: int
    horizon: str
    summary: str
    source_urls: tuple[str, ...]
    reviewed_by: str
    reviewed_at: date
    expires_at: date

    def in_force(self, *, season: int, as_of: datetime) -> bool:
        """For this season, and before the expiry date (UTC)."""
        return self.season == season and as_of.astimezone(UTC).date() < self.expires_at

    def to_record(self) -> dict[str, Any]:
        """The ``availability_override`` object a ``player_status`` record carries."""
        return {
            "horizon": self.horizon,
            "summary": self.summary,
            "source_urls": list(self.source_urls),
            "reviewed_at": self.reviewed_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }


def _date(value: Any, field: str, index: int) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as error:
            raise AvailabilityOverrideError(f"override {index}: {field} is not a date") from error
    raise AvailabilityOverrideError(f"override {index}: {field} is not a date")


def _text(entry: Mapping[str, Any], field: str, index: int) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise AvailabilityOverrideError(f"override {index}: {field} must be non-empty text")
    return " ".join(value.split())


def _entry(raw: Any, index: int) -> AvailabilityOverride:
    if not isinstance(raw, Mapping):
        raise AvailabilityOverrideError(f"override {index}: not a mapping")
    unknown = set(raw) - _ENTRY_KEYS
    missing = _ENTRY_KEYS - set(raw)
    if unknown or missing:
        raise AvailabilityOverrideError(
            f"override {index}: unknown keys {sorted(unknown)}, missing keys {sorted(missing)}",
        )
    player_id = _text(raw, "player_id", index)
    if not _CANONICAL_ID.match(player_id):
        raise AvailabilityOverrideError(
            f"override {index}: {player_id!r} is not a canonical gsis id"
        )
    season = raw.get("season")
    if not isinstance(season, int) or isinstance(season, bool) or season < 2000:
        raise AvailabilityOverrideError(f"override {index}: season must be a year")
    horizon = _text(raw, "horizon", index)
    if horizon not in _HORIZONS:
        raise AvailabilityOverrideError(
            f"override {index}: horizon must be one of {sorted(_HORIZONS)}"
        )
    sources = raw.get("sources")
    if not isinstance(sources, Sequence) or isinstance(sources, str) or not sources:
        raise AvailabilityOverrideError(f"override {index}: at least one source is required")
    urls: list[str] = []
    for source in sources:
        if not isinstance(source, Mapping) or not isinstance(source.get("url"), str):
            raise AvailabilityOverrideError(f"override {index}: each source needs a url")
        url = str(source["url"]).strip()
        if not url.startswith("https://"):
            raise AvailabilityOverrideError(f"override {index}: source urls must be https")
        if not isinstance(source.get("publisher"), str) or not str(source["publisher"]).strip():
            raise AvailabilityOverrideError(f"override {index}: each source needs a publisher")
        urls.append(url)
    reviewed_at = _date(raw.get("reviewed_at"), "reviewed_at", index)
    expires_at = _date(raw.get("expires_at"), "expires_at", index)
    if expires_at <= reviewed_at:
        raise AvailabilityOverrideError(f"override {index}: expires_at must follow reviewed_at")
    return AvailabilityOverride(
        player_id=player_id,
        display_name=_text(raw, "display_name", index),
        season=season,
        horizon=horizon,
        summary=_text(raw, "summary", index),
        source_urls=tuple(urls),
        reviewed_by=_text(raw, "reviewed_by", index),
        reviewed_at=reviewed_at,
        expires_at=expires_at,
    )


def load_availability_overrides(path: Path | None = None) -> tuple[AvailabilityOverride, ...]:
    """Parse and validate the file. A missing file is no overrides; a malformed one raises."""
    target = path if path is not None else repo_root() / AVAILABILITY_OVERRIDES_PATH
    if not target.exists():
        return ()
    document = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    if not isinstance(document, Mapping) or document.get("schema_version") != "1.0":
        raise AvailabilityOverrideError('availability overrides: schema_version must be "1.0"')
    raw = document.get("overrides") or []
    if not isinstance(raw, Sequence) or isinstance(raw, str):
        raise AvailabilityOverrideError("availability overrides: `overrides` must be a list")
    entries = tuple(_entry(item, index) for index, item in enumerate(raw))
    keys = [(entry.player_id, entry.season) for entry in entries]
    if len(set(keys)) != len(keys):
        raise AvailabilityOverrideError("availability overrides: one entry per player and season")
    return entries


def active_overrides(
    overrides: Sequence[AvailabilityOverride],
    *,
    season: int,
    as_of: datetime,
) -> dict[str, AvailabilityOverride]:
    """``player_id -> override`` for the entries in force for this build."""
    return {
        entry.player_id: entry for entry in overrides if entry.in_force(season=season, as_of=as_of)
    }
