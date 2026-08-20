"""MyFantasyLeague market adapters.

**Boundary module.** Everything here is market data. `docs/ARCHITECTURE.md` section 3.1
forbids any of it from reaching an intrinsic feature, and the boundary is enforced by
keeping market code in this module rather than by convention: nothing under an intrinsic
feature package may import :mod:`ffdraft.sources.market`, and a test asserts that.

The Phase-0 contract this implements (`docs/DATA_SOURCES.md` 13.5):

* ``GET https://api.myfantasyleague.com/{season}/export?TYPE=adp&JSON=1`` — **no auth**.
  Per ADR-017 the request carries the registered developer-client User-Agent and nothing
  else; no username, password, ``APIKEY`` or ``Authorization`` header ever goes out.
* Player rows carry exactly ``id, rank, averagePick, minPick, maxPick, draftsSelectedIn,
  draftSelPct``, all as strings. **There is no standard-deviation field**, so ``adp_sd``
  stays null and dispersion comes from min/max pick.
* The envelope ``timestamp`` is response-generation time, not a data-as-of time, so
  ``source_as_of_utc`` stays null rather than inventing freshness.
* Cohort intersections collapse (``IS_PPR=0&FCOUNT=10`` returned two players), so a quote
  records the cohort it came from and the filters actually sent. Whether that cohort is an
  *exact* match for a published preset is decided later, per preset, by
  :mod:`ffdraft.market.cohorts` under the rule ADR-039 froze — never per row here.
* HTTP 429 means throttled: back off, never retry blindly.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import polars as pl

from ffdraft.config import MflClientConfig
from ffdraft.contracts import (
    MARKET_QUOTE_CONTRACT,
    MFL_PLAYER_CONTRACT,
    EntityKind,
    MarketCohort,
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
    "MFL_API_BASE_URL",
    "MFL_SOURCE_ID",
    "ADP_SD_UNAVAILABLE",
    "SOURCE_AS_OF_UNAVAILABLE",
    "MflAdpAdapter",
    "MflPlayerDirectory",
    "MflPlayerDirectoryAdapter",
    "classify_mfl_entity",
]

MFL_SOURCE_ID = "myfantasyleague_adp"
MFL_API_BASE_URL = "https://api.myfantasyleague.com/"
_MFL_LICENSE = "mfl-developer-rules/2026-08-17"

#: Row-level quality flags, serialized into ``market_snapshot.quality_flags``. Cohort
#: approximation is *not* one of them: it is a property of a preset assignment, not of a
#: quote, and lives in :mod:`ffdraft.market.cohorts` (ADR-039).
ADP_SD_UNAVAILABLE = "adp_sd_unavailable"
SOURCE_AS_OF_UNAVAILABLE = "source_as_of_unavailable"

# MFL position tokens that denote a team aggregate rather than a person. `Def` is a team
# defence; `TM*` rows aggregate a club's players at a position. Neither may enter QB/RB/WR/TE
# identity, and `TMWR` in particular must never be read as "WR" (AGENTS.md section 6).
_TEAM_UNIT_POSITIONS = frozenset({"DEF", "DST", "TEAM", "COACH"})
_TEAM_UNIT_PREFIX = "TM"


def classify_mfl_entity(raw_position: str | None) -> EntityKind:
    """Classify an MFL row from its position token."""
    if raw_position is None:
        return EntityKind.UNKNOWN
    token = raw_position.strip().upper()
    if not token:
        return EntityKind.UNKNOWN
    if token in _TEAM_UNIT_POSITIONS or token.startswith(_TEAM_UNIT_PREFIX):
        return EntityKind.TEAM_UNIT
    return EntityKind.PLAYER


@dataclass(frozen=True, slots=True)
class MflPlayerDirectory:
    """``mfl_id -> (name, position, team, espn_id, entity_kind)``.

    The ADP export carries ids only, so entity classification and the primary ``espn_id``
    bridge both come from here. MFL asks that the player database be requested at most once
    per day, so callers cache this and reuse it across ADP pulls.
    """

    frame: pl.DataFrame

    def espn_id(self, mfl_id: str) -> str | None:
        return self._lookup(mfl_id, "espn_id")

    def raw_position(self, mfl_id: str) -> str | None:
        return self._lookup(mfl_id, "raw_position")

    def name(self, mfl_id: str) -> str | None:
        return self._lookup(mfl_id, "name")

    def entity_kind(self, mfl_id: str) -> EntityKind:
        value = self._lookup(mfl_id, "entity_kind")
        return EntityKind(value) if value else EntityKind.UNKNOWN

    def _lookup(self, mfl_id: str, column: str) -> str | None:
        row = self.frame.filter(pl.col("mfl_id") == mfl_id)
        if row.height != 1:
            return None
        value = row.get_column(column).item()
        return None if value is None else str(value)

    @classmethod
    def empty(cls) -> MflPlayerDirectory:
        return cls(frame=MFL_PLAYER_CONTRACT.empty())


class MflPlayerDirectoryAdapter(BaseSourceAdapter):
    """``export?TYPE=players&DETAILS=1&JSON=1`` -> the MFL player directory."""

    source_id = MFL_SOURCE_ID
    resource = "export?TYPE=players&DETAILS=1"
    adapter_version = "1.0"
    contract = MFL_PLAYER_CONTRACT
    recorded_schema_fixture = "mfl_players_details"
    license_policy_version = _MFL_LICENSE
    min_expected_records = 1
    required_source_columns = frozenset({"id", "name", "position"})

    def normalize(
        self,
        payload: RawRecords | Mapping[str, Any],
        *,
        retrieved_at: datetime | None = None,
    ) -> SourceBatch:
        records = _unwrap(payload, "players", "player")
        flags = FlagCounter()
        rows: list[dict[str, Any]] = []
        dropped = 0

        for record in records:
            mfl = normalize_id(IdNamespace.MFL, record.get("id"))
            if mfl.value is None:
                dropped += 1
                continue
            flags.take(mfl)
            raw_position = _text(record.get("position"))
            kind = classify_mfl_entity(raw_position)
            if kind is EntityKind.TEAM_UNIT:
                flags.note("mfl_team_unit_row")
            rows.append(
                {
                    "mfl_id": mfl.value,
                    "name": _text(record.get("name")),
                    "raw_position": raw_position,
                    "team": _text(record.get("team")),
                    "espn_id": flags.take(normalize_id(IdNamespace.ESPN, record.get("espn_id"))),
                    "entity_kind": str(kind),
                }
            )

        flags.note("mfl_player_rows_without_id", dropped)
        return self.build_batch(
            self.contract.build(rows),
            retrieved_at=retrieved_at,
            warning_codes=flags.codes,
            detail=flags.detail,
        )

    def fetch(self, *, as_of: datetime, config: SourceConfig) -> SourceBatch:
        client = _client_from(config)
        payload = _mfl_get(
            season=config.season,
            params={"TYPE": "players", "DETAILS": "1", "JSON": "1"},
            client=client,
            config=config,
        )
        return self.normalize(payload, retrieved_at=as_of or utc_now())

    def directory(self, batch: SourceBatch) -> MflPlayerDirectory:
        return MflPlayerDirectory(frame=batch.frame)


class MflAdpAdapter(BaseSourceAdapter):
    """``export?TYPE=adp&JSON=1`` -> normalized market quotes."""

    source_id = MFL_SOURCE_ID
    resource = "export?TYPE=adp"
    #: 2.0 with `market_quote` contract 2.0: a quote records its cohort, not a preset.
    adapter_version = "2.0"
    contract = MARKET_QUOTE_CONTRACT
    recorded_schema_fixture = "mfl_adp_current_default"
    license_policy_version = _MFL_LICENSE
    min_expected_records = 1
    required_source_columns = frozenset(
        {"id", "rank", "averagePick", "minPick", "maxPick", "draftsSelectedIn"},
    )

    def normalize(
        self,
        payload: RawRecords | Mapping[str, Any],
        *,
        season: int,
        cohort: MarketCohort,
        directory: MflPlayerDirectory | None = None,
        retrieved_at: datetime | None = None,
    ) -> SourceBatch:
        records = _unwrap(payload, "adp", "player")
        envelope = _envelope(payload, "adp")
        retrieved = retrieved_at or utc_now()
        flags = FlagCounter()
        rows: list[dict[str, Any]] = []
        dropped = 0

        base_flags = [ADP_SD_UNAVAILABLE, SOURCE_AS_OF_UNAVAILABLE]

        for record in records:
            mfl = normalize_id(IdNamespace.MFL, record.get("id"))
            average = _float(record.get("averagePick"))
            if mfl.value is None or average is None or average <= 0:
                dropped += 1
                continue
            flags.take(mfl)
            raw_position = directory.raw_position(mfl.value) if directory else None
            kind = directory.entity_kind(mfl.value) if directory else EntityKind.UNKNOWN
            if kind is EntityKind.TEAM_UNIT:
                flags.note("market_team_unit_row")
            rows.append(
                {
                    "source_id": self.source_id,
                    "season": season,
                    "cohort_id": cohort.cohort_id,
                    "external_player_id": mfl.value,
                    "average_pick": average,
                    "market_rank": _int(record.get("rank")),
                    "min_pick": _float(record.get("minPick")),
                    "max_pick": _float(record.get("maxPick")),
                    "sample_size": _int(record.get("draftsSelectedIn")),
                    "selection_pct": _float(record.get("draftSelPct")),
                    "retrieved_at_utc": retrieved,
                    # Never populated for MFL: the envelope timestamp is generation time.
                    "source_as_of_utc": None,
                    "entity_kind": str(kind),
                    "raw_position": raw_position,
                    "source_format_detail": cohort.filter_query,
                    "quality_flags": ",".join(base_flags),
                }
            )

        flags.note("market_rows_without_usable_price", dropped)
        detail: dict[str, str] = {
            "season": str(season),
            "cohort_id": cohort.cohort_id,
            "cohort_filters": cohort.filter_query,
            **flags.detail,
        }
        if envelope:
            # Recorded as evidence, deliberately not promoted to `source_as_of_utc`.
            for key in ("timestamp", "totalDrafts", "totalPicks"):
                if key in envelope:
                    detail[f"response_{key}"] = str(envelope[key])
        return self.build_batch(
            self.contract.build(rows),
            retrieved_at=retrieved,
            source_as_of=None,
            warning_codes=flags.codes,
            detail=detail,
        )

    def fetch(self, *, as_of: datetime, config: SourceConfig) -> SourceBatch:
        cohort = config.options.get("cohort")
        if not isinstance(cohort, MarketCohort):
            raise ValueError("MflAdpAdapter.fetch requires options['cohort'] (ADR-012)")
        directory = config.options.get("directory")
        client = _client_from(config)
        payload = _mfl_get(
            season=config.season,
            params={"TYPE": "adp", "JSON": "1", **dict(cohort.filters)},
            client=client,
            config=config,
        )
        return self.normalize(
            payload,
            season=config.season,
            cohort=cohort,
            directory=directory if isinstance(directory, MflPlayerDirectory) else None,
            retrieved_at=as_of or utc_now(),
        )

    def semantic_checks(self, batch: SourceBatch) -> Sequence[QualityCheck]:
        if batch.frame.is_empty():
            return ()
        checks: list[QualityCheck] = []
        if batch.frame.get_column("source_as_of_utc").null_count() != batch.frame.height:
            checks.append(
                QualityCheck.fail(
                    "market.fabricated_source_as_of",
                    stage=self.source_id,
                    message=(
                        "MFL supplies no data-as-of time; a populated source_as_of_utc "
                        "would be a manufactured freshness claim"
                    ),
                    observed="populated",
                    expected="null for every row",
                ),
            )
        unknown = batch.frame.filter(pl.col("entity_kind") == str(EntityKind.UNKNOWN)).height
        if unknown:
            checks.append(
                QualityCheck.fail(
                    "market.unclassified_entities",
                    stage=self.source_id,
                    message=(
                        "quotes without a player directory cannot be classified, so team "
                        "units are indistinguishable from players"
                    ),
                    observed=f"{unknown} row(s)",
                    expected="0 with a directory supplied",
                    severity=Severity.WARNING,
                ),
            )
        return checks


# --------------------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------------------


def _client_from(config: SourceConfig) -> MflClientConfig:
    client = config.options.get("client")
    return client if isinstance(client, MflClientConfig) else MflClientConfig.from_env()


def _mfl_get(
    *,
    season: int,
    params: Mapping[str, str],
    client: MflClientConfig,
    config: SourceConfig,
) -> Any:
    """One public MFL export request, with 429-aware backoff.

    ADR-017: headers come from :meth:`MflClientConfig.request_headers`, which emits a
    User-Agent and an Accept and nothing else. Credentials are neither read nor sent here.
    """
    import requests

    url = f"{MFL_API_BASE_URL}{season}/export"
    headers = client.request_headers()
    delay = config.min_interval_seconds
    last_error: Exception | None = None

    for attempt in range(1, max(1, config.max_retries) + 1):
        try:
            response = requests.get(
                url,
                params=dict(params),
                headers=headers,
                timeout=config.timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001 - re-raised as a typed adapter failure
            last_error = exc
        else:
            if response.status_code == 429:
                # Documented throttle response. Honour Retry-After when present.
                retry_after = response.headers.get("retry-after")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else delay
                last_error = SourceFetchError(f"{MFL_SOURCE_ID}: throttled (429)")
                if attempt < config.max_retries:
                    time.sleep(wait)
                    delay *= 2
                    continue
            elif response.ok:
                try:
                    return response.json()
                except ValueError as exc:
                    raise SourceFetchError(f"{MFL_SOURCE_ID}: non-JSON response") from exc
            else:
                last_error = SourceFetchError(
                    f"{MFL_SOURCE_ID}: HTTP {response.status_code} for {params.get('TYPE')}",
                )
        if attempt < config.max_retries:
            time.sleep(delay)
            delay *= 2

    raise SourceFetchError(f"{MFL_SOURCE_ID}: request failed after retries: {last_error}")


# --------------------------------------------------------------------------------------
# Payload helpers
# --------------------------------------------------------------------------------------


def _unwrap(
    payload: RawRecords | Mapping[str, Any],
    envelope: str,
    key: str,
) -> list[dict[str, Any]]:
    """Accept either the full MFL envelope or a bare list of rows.

    Fixtures store the bare rows; the live endpoint wraps them. Supporting both keeps the
    fixture tests exercising exactly the code the live path runs.
    """
    if isinstance(payload, Mapping):
        body = payload.get(envelope, payload)
        rows = body.get(key, []) if isinstance(body, Mapping) else body
        if isinstance(rows, Mapping):
            rows = [rows]
        return [dict(row) for row in rows]
    return as_rows(payload)


def _envelope(payload: RawRecords | Mapping[str, Any], envelope: str) -> Mapping[str, Any]:
    if isinstance(payload, Mapping):
        body = payload.get(envelope)
        if isinstance(body, Mapping):
            return {k: v for k, v in body.items() if not isinstance(v, list | dict)}
    return {}


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


def _float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None
