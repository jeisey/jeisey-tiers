"""Sleeper adapter — current player status and the season cross-check.

ADR-011 promoted Sleeper from optional to ``important``: nflverse's injury feed is weekly
in-season data, so it cannot describe a preseason draft anchor in any season, and Sleeper is
the verified source that can. Two Phase-0 measurements constrain this adapter:

* Sleeper's own ``gsis_id`` is present on only 31.9% of records, so the join runs
  **nflverse -> Sleeper on ``sleeper_id``**. Sleeper's ``gsis_id`` is kept as a cross-check
  and never as a key;
* ids can arrive with surrounding whitespace (``" 00-0035057"``), so every id goes through
  :mod:`ffdraft.identity.ids`.

Sleeper is non-commercial-only. That obligation is recorded in the registry and in
`docs/SECURITY_LICENSE.md` section 10, and it binds the deployment, not just this file.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from ffdraft.contracts import PLAYER_STATUS_CONTRACT, QualityCheck, SourceBatch
from ffdraft.contracts.enums import Severity
from ffdraft.identity.ids import IdNamespace, normalize_id
from ffdraft.sources.base import (
    BaseSourceAdapter,
    RawRecords,
    SourceConfig,
    SourceFetchError,
    as_rows,
)
from ffdraft.sources.nflverse import FlagCounter
from ffdraft.timeutil import utc_now

__all__ = [
    "SLEEPER_BASE_URL",
    "SLEEPER_SOURCE_ID",
    "SleeperPlayerAdapter",
    "SleeperState",
    "parse_sleeper_state",
    "player_map_to_records",
]

SLEEPER_SOURCE_ID = "sleeper"
SLEEPER_BASE_URL = "https://api.sleeper.app/v1/"
_SLEEPER_LICENSE = "sleeper-non-commercial/2026-08-17"


@dataclass(frozen=True, slots=True)
class SleeperState:
    """``/v1/state/nfl`` — an independent cross-check on the draft-target season.

    Phase 0 found ``nflreadpy.get_current_season()`` returning 2025 in August 2026 while
    ``get_current_season(roster=True)`` returned 2026. The pipeline therefore takes the
    target season from configuration and cross-checks it here rather than trusting either
    helper (`docs/DATA_SOURCES.md` 13.4).
    """

    season: int
    week: int
    season_type: str
    season_start_date: date | None = None

    def agrees_with(self, season: int) -> bool:
        return self.season == season


def parse_sleeper_state(payload: Mapping[str, Any]) -> SleeperState:
    """Parse the state endpoint's flat JSON object."""
    try:
        raw_start = payload.get("season_start_date")
        start = date.fromisoformat(str(raw_start)) if raw_start else None
        return SleeperState(
            season=int(payload["season"]),
            week=int(payload.get("week", 0)),
            season_type=str(payload.get("season_type", "")),
            season_start_date=start,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SourceFetchError(f"unreadable Sleeper state payload: {exc}") from exc


def player_map_to_records(payload: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Flatten ``/v1/players/nfl``'s ``{player_id: record}`` object into rows.

    The map key is authoritative: a record whose body omits ``player_id`` still has one.
    """
    rows: list[dict[str, Any]] = []
    for key, record in payload.items():
        row = dict(record)
        row.setdefault("player_id", key)
        rows.append(row)
    return rows


class SleeperPlayerAdapter(BaseSourceAdapter):
    """``/v1/players/nfl`` -> current status observations keyed by Sleeper player id."""

    source_id = SLEEPER_SOURCE_ID
    resource = "GET /v1/players/nfl"
    adapter_version = "1.0"
    contract = PLAYER_STATUS_CONTRACT
    recorded_schema_fixture = "sleeper_players_nfl"
    license_policy_version = _SLEEPER_LICENSE
    min_expected_records = 1
    required_source_columns = frozenset(
        {"player_id", "status", "injury_status", "team", "position", "gsis_id"},
    )

    def normalize(
        self,
        records: RawRecords | Mapping[str, Mapping[str, Any]],
        *,
        retrieved_at: datetime | None = None,
    ) -> SourceBatch:
        observed_at = retrieved_at or utc_now()
        raw_rows = (
            player_map_to_records(records) if isinstance(records, Mapping) else as_rows(records)
        )
        flags = FlagCounter()
        rows: list[dict[str, Any]] = []
        dropped = 0

        for record in raw_rows:
            player_id = normalize_id(IdNamespace.SLEEPER, record.get("player_id"))
            if player_id.value is None:
                dropped += 1
                continue
            row_flags: list[str] = list(player_id.quality_flags)
            flags.take(player_id)

            gsis = normalize_id(IdNamespace.GSIS, record.get("gsis_id"))
            row_flags.extend(gsis.quality_flags)
            flags.take(gsis)

            rows.append(
                {
                    "source_id": self.source_id,
                    "external_player_id": player_id.value,
                    # Sleeper publishes no per-record observation time, so the retrieval
                    # time is the honest answer. It is not a data-as-of claim.
                    "observed_at_utc": observed_at,
                    "team": _text(record.get("team")) or _text(record.get("team_abbr")),
                    "status": _text(record.get("status")),
                    "injury_status": _text(record.get("injury_status")),
                    "injury_body_part": _text(record.get("injury_body_part")),
                    "practice_participation": _text(record.get("practice_participation")),
                    "depth_chart_position": _text(record.get("depth_chart_position")),
                    "depth_chart_order": _int(record.get("depth_chart_order")),
                    "reported_gsis_id": gsis.value,
                    "quality_flags": ",".join(dict.fromkeys(row_flags)),
                }
            )

        flags.note("sleeper_rows_without_player_id", dropped)
        return self.build_batch(
            self.contract.build(rows),
            retrieved_at=observed_at,
            warning_codes=flags.codes,
            detail=flags.detail,
        )

    def fetch(self, *, as_of: datetime, config: SourceConfig) -> SourceBatch:
        """Retrieve the full player map.

        Sleeper documents a 1,000 calls/minute ceiling and the payload is ~14.6 MB, so the
        registry's cadence guidance is at most once per day. Callers cache; this method
        makes exactly one request.
        """
        payload = _get_json(
            f"{SLEEPER_BASE_URL}players/nfl",
            timeout=config.timeout_seconds,
            source_id=self.source_id,
        )
        if not isinstance(payload, Mapping):
            raise SourceFetchError("Sleeper player map did not return a JSON object")
        return self.normalize(payload, retrieved_at=as_of or utc_now())

    def semantic_checks(self, batch: SourceBatch) -> Sequence[QualityCheck]:
        """Record - but never rely on - Sleeper's sparse ``gsis_id`` coverage."""
        if batch.frame.is_empty():
            return ()
        total = batch.frame.height
        present = total - int(batch.frame.get_column("reported_gsis_id").null_count())
        coverage = present / total
        return (
            QualityCheck.fail(
                "sleeper.gsis_coverage_is_not_a_join_key",
                stage=self.source_id,
                message=(
                    "Sleeper gsis_id coverage is partial by design; joins must run "
                    "nflverse -> Sleeper on sleeper_id (ADR-011)"
                ),
                observed=f"{coverage:.1%} of {total} rows",
                expected="informational",
                severity=Severity.INFO,
            ),
        )


def fetch_sleeper_state(*, timeout: float = 30.0) -> SleeperState:
    """Retrieve ``/v1/state/nfl``. Network I/O; used by live checks and daily refresh."""
    payload = _get_json(
        f"{SLEEPER_BASE_URL}state/nfl",
        timeout=timeout,
        source_id=SLEEPER_SOURCE_ID,
    )
    if not isinstance(payload, Mapping):
        raise SourceFetchError("Sleeper state did not return a JSON object")
    return parse_sleeper_state(payload)


def _get_json(url: str, *, timeout: float, source_id: str) -> Any:
    import requests

    headers = {
        "User-Agent": (
            "jeisey-tiers/0.1 "
            "(+https://github.com/jeisey/jeisey-tiers; non-commercial fantasy research)"
        ),
        "Accept": "application/json",
    }
    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except Exception as exc:  # noqa: BLE001 - re-raised as a typed adapter failure
        raise SourceFetchError(f"{source_id}: {url} failed: {exc}") from exc


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
