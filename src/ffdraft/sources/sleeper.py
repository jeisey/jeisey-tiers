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

from ffdraft.contracts import (
    PLAYER_STATUS_CONTRACT,
    SLEEPER_BEHAVIOR_CONTRACT,
    BehaviorType,
    QualityCheck,
    SourceBatch,
)
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
    "TRENDING_LIMIT",
    "TRENDING_LOOKBACK_HOURS",
    "SleeperPlayerAdapter",
    "SleeperTrendingAdapter",
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
    #: 1.1 with `sleeper_player_status` contract 1.1: the three optional injury/practice
    #: fields the verified schema publishes and 1.0 did not read (ADR-043).
    adapter_version = "1.1"
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
                    # Present in the verified schema and frequently null: Sleeper omits
                    # them for healthy players, so they are normalized as nullable rather
                    # than required (ADR-043). Never invented when absent.
                    "injury_notes": _text(record.get("injury_notes")),
                    "injury_start_date": _text(record.get("injury_start_date")),
                    "practice_participation": _text(record.get("practice_participation")),
                    "practice_description": _text(record.get("practice_description")),
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


#: The trending request this project makes. Both parameters were measured to be honoured
#: on 2026-09-02 (`docs/source-probes/2026-09-02/phase10-report.md` 3): `limit` returns
#: exactly what is asked for, and a 6-hour window shares 24 of 25 ids with a 24-hour one
#: while a 72-hour window shares 22. A window that is requested but silently clamped would
#: make a retained count mean something other than what its manifest says, which is why the
#: snapshot records the request rather than assuming it.
TRENDING_LOOKBACK_HOURS = 24
TRENDING_LIMIT = 100


class SleeperTrendingAdapter(BaseSourceAdapter):
    """``/v1/players/nfl/trending/{add,drop}`` -> waiver behaviour snapshots.

    **Nothing consumes this yet, and that is the point.** Phase 12 is the in-season phase
    and it needs history that already exists when the season starts; a feed first captured
    in week 3 can only describe week 3 onward. Roadmap 10.1.4 asks Phase 10 to start
    retaining these now so Phase 12 inherits a real series rather than beginning from zero
    after kickoff.

    The response is a **bare JSON list** of ``{count, player_id}`` — no envelope, no
    timestamp, no metadata of any kind. Everything that makes a retained row interpretable
    later therefore has to come from the request: which window was asked for, what limit was
    sent, and when. That is what :class:`~ffdraft.contracts.SLEEPER_BEHAVIOR_CONTRACT`
    records, and it is why these rows are not squeezed into a market quote — an add count is
    not a pick number, and a schema that allowed it there would eventually see it charted on
    an ADP axis (roadmap 10.3).
    """

    source_id = SLEEPER_SOURCE_ID
    resource = "GET /v1/players/nfl/trending/{kind}"
    adapter_version = "1.0"
    contract = SLEEPER_BEHAVIOR_CONTRACT
    recorded_schema_fixture = "sleeper_trending_add"
    license_policy_version = _SLEEPER_LICENSE
    min_expected_records = 1
    required_source_columns = frozenset({"player_id", "count"})

    def normalize(
        self,
        records: RawRecords,
        *,
        behavior_type: BehaviorType,
        lookback_hours: int = TRENDING_LOOKBACK_HOURS,
        limit: int = TRENDING_LIMIT,
        retrieved_at: datetime | None = None,
    ) -> SourceBatch:
        observed_at = retrieved_at or utc_now()
        flags = FlagCounter()
        rows: list[dict[str, Any]] = []
        dropped = 0

        for record in as_rows(records):
            player_id = normalize_id(IdNamespace.SLEEPER, record.get("player_id"))
            count = _int(record.get("count"))
            if player_id.value is None or count is None:
                dropped += 1
                continue
            flags.take(player_id)
            rows.append(
                {
                    "source_id": self.source_id,
                    "behavior_type": str(behavior_type),
                    "external_player_id": player_id.value,
                    "count": count,
                    # The REQUEST, not a claim about the data. Sleeper publishes nothing
                    # about the window it actually used.
                    "lookback_hours": lookback_hours,
                    "request_limit": limit,
                    "snapshot_at_utc": observed_at,
                    "quality_flags": ",".join(dict.fromkeys(player_id.quality_flags)),
                }
            )

        flags.note("sleeper_trending_rows_without_id_or_count", dropped)
        return self.build_batch(
            self.contract.build(rows),
            retrieved_at=observed_at,
            warning_codes=flags.codes,
            detail={
                "behavior_type": str(behavior_type),
                "lookback_hours": str(lookback_hours),
                "request_limit": str(limit),
                **flags.detail,
            },
        )

    def fetch(self, *, as_of: datetime, config: SourceConfig) -> SourceBatch:
        behavior = config.options.get("behavior_type", BehaviorType.ADD)
        if not isinstance(behavior, BehaviorType):
            behavior = BehaviorType(str(behavior))
        lookback = int(config.options.get("lookback_hours", TRENDING_LOOKBACK_HOURS))
        limit = int(config.options.get("limit", TRENDING_LIMIT))
        payload = _get_json(
            f"{SLEEPER_BASE_URL}players/nfl/trending/{behavior}"
            f"?lookback_hours={lookback}&limit={limit}",
            timeout=config.timeout_seconds,
            source_id=self.source_id,
        )
        if not isinstance(payload, list):
            raise SourceFetchError(
                f"Sleeper trending/{behavior} returned {type(payload).__name__}, not a list",
            )
        return self.normalize(
            payload,
            behavior_type=behavior,
            lookback_hours=lookback,
            limit=limit,
            retrieved_at=as_of or utc_now(),
        )

    def semantic_checks(self, batch: SourceBatch) -> Sequence[QualityCheck]:
        """Waiver behaviour is never a model feature and never a price."""
        if batch.frame.is_empty():
            return ()
        kinds = set(batch.frame.get_column("behavior_type").unique().to_list())
        unknown = kinds - {str(BehaviorType.ADD), str(BehaviorType.DROP)}
        if unknown:
            return (
                QualityCheck.fail(
                    "sleeper.unknown_behavior_type",
                    stage=self.source_id,
                    message="a behaviour snapshot must be an add or a drop",
                    observed=", ".join(sorted(unknown)),
                    expected="add | drop",
                ),
            )
        return (
            QualityCheck.ok(
                "sleeper.behavior_is_not_a_price",
                stage=self.source_id,
                message=(
                    "add/drop counts are retained for Phase 12 and are excluded from "
                    "intrinsic features and from every ADP aggregate (roadmap 10.1.4)"
                ),
                observed=f"{batch.frame.height} row(s)",
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
