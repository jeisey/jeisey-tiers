"""The Fantasy Football Calculator ADP adapter (Phase 10, ADR-062).

**Boundary module.** Market data only. `docs/ARCHITECTURE.md` section 3.1 forbids any of it
reaching an intrinsic feature, and the boundary is structural: nothing under an intrinsic
feature package may import this module, and a test asserts it.

The contract implemented here is the one the runner measured on 2026-09-02
(`docs/DATA_SOURCES.md` 14.1), not a remembered one::

    GET https://fantasyfootballcalculator.com/api/v1/adp/{format}
        ?teams={n}&year={season}&position=all

    {"status": "Success",
     "meta": {"type", "teams", "rounds", "total_drafts", "start_date", "end_date"},
     "players": [{"player_id": int, "name", "position", "team",
                  "adp": float, "adp_formatted", "times_drafted": int,
                  "high": int, "low": int, "stdev": float, "bye": int}]}

Four measured facts shape everything below.

**1. `teams` is accepted and ignored.** ADR-056 measured it in Phase 8 and the Phase-10
re-probe reproduced it exactly: per-player `adp` and `times_drafted` are byte-identical
across 8/10/12/14-team requests in all three formats. So FFC offers three *scoring* cohorts,
not twelve scoring x league-size cohorts, and ``league_size_semantics`` is ``None``. The
parameter is still sent, because sending what the probe sent is what makes a capture
reproducible against the evidence — and the row carries
``LEAGUE_SIZE_NOT_OBSERVED`` so the null is a recorded refusal to claim rather than a gap.

**2. The window is bounded and recent.** ``meta.start_date``/``meta.end_date`` came back as
``2026-08-26``/``2026-09-02``: a seven-day rolling window. MyFantasyLeague aggregates the
whole season. Both are called "ADP"; they are different measurements, and the quote carries
:class:`~ffdraft.contracts.enums.AggregationWindow` so nothing downstream can forget.

**3. `stdev` is a real standard deviation, and `high`/`low` are not.** FFC publishes both —
221/221 populated, 0.60 to 31.90 on the standard cohort. They go in different columns.
Collapsing a dispersion estimate and two extreme order statistics into one field would be a
data error, and MFL's lack of the former is exactly why the distinction has to survive.

**4. `high`/`low` name a draft position, and the direction of that naming is a convention,
not a fact this adapter is willing to assume.** FFC's own table reads "High" for the
earliest pick a player went at, which is the *smaller* number. Rather than encode that
belief, :func:`_pick_bounds` orders the two numerically, so ``min_pick``/``max_pick`` are
correct whichever way round the vendor means them. The observed orientation is counted into
the batch detail as evidence instead of being trusted.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import polars as pl

from ffdraft.contracts import (
    MARKET_QUOTE_CONTRACT,
    AggregationWindow,
    EntityKind,
    MarketCohort,
    MarketSignalType,
    Position,
    QualityCheck,
    SourceBatch,
)
from ffdraft.contracts.enums import Severity
from ffdraft.sources.base import (
    BaseSourceAdapter,
    RawRecords,
    SourceConfig,
    SourceFetchError,
    as_rows,
)
from ffdraft.timeutil import utc_now

__all__ = [
    "FFC_API_BASE_URL",
    "FFC_USER_AGENT",
    "FFC_COHORTS",
    "FFC_SOURCE_ID",
    "LEAGUE_SIZE_NOT_OBSERVED",
    "SOURCE_WINDOW_PUBLISHED",
    "FfcAdpAdapter",
    "classify_ffc_entity",
    "ffc_cohort",
]

FFC_SOURCE_ID = "fantasyfootballcalculator_adp"
FFC_API_BASE_URL = "https://fantasyfootballcalculator.com/api/v1/adp/"
_FFC_LICENSE = "ffc-adp-rest-api-terms/2026-09-02"

#: FFC's published terms permit API use with attribution and ask clients not to poll
#: unnecessarily. A descriptive, contactable User-Agent is how a free client identifies
#: itself when the source has no developer registration to complete (`AGENTS.md` section 5).
FFC_USER_AGENT = (
    "jeisey-tiers (+https://github.com/jeisey/jeisey-tiers); "
    "free non-commercial fantasy football project, one refresh per day"
)

#: Row-level quality flags.
#:
#: The first is the load-bearing one. A board that showed "12-team FFC ADP" would be
#: claiming a cohort the API does not substantiate, and the flag is how every row says so.
LEAGUE_SIZE_NOT_OBSERVED = "league_size_not_observed"
SOURCE_WINDOW_PUBLISHED = "source_window_published"

#: The request FFC's probe made, and the one a capture reproduces. `teams` is sent because
#: the measurement was taken with it sent; it changes nothing (fact 1 above).
_REQUEST_TEAMS = "12"

#: `meta.start_date`/`meta.end_date` spanned exactly seven days on 2026-09-02. The value is
#: recomputed per capture from the response rather than hard-coded — this is the fallback
#: recorded for a response that omits the dates, not the claim.
FFC_WINDOW_DAYS_OBSERVED = 7

#: FFC's format token -> this project's scoring vocabulary. All three exist and carry
#: materially different volume (1,794 / 3,142 / 8,007 drafts on 2026-09-02).
_FORMAT_TO_SCORING: dict[str, str] = {
    "standard": "STD",
    "half-ppr": "HALF",
    "ppr": "PPR",
}

#: FFC position tokens that are not a person. `DEF` is a team defence; `PK` is a kicker,
#: which is a real player but outside this project's modelled positions and therefore
#: excluded from linkage rather than misclassified here.
_TEAM_UNIT_POSITIONS = frozenset({"DEF", "DST", "D/ST"})


def classify_ffc_entity(raw_position: str | None) -> EntityKind:
    """Classify an FFC row from its position token."""
    if raw_position is None:
        return EntityKind.UNKNOWN
    token = raw_position.strip().upper()
    if not token:
        return EntityKind.UNKNOWN
    if token in _TEAM_UNIT_POSITIONS:
        return EntityKind.TEAM_UNIT
    return EntityKind.PLAYER if Position.parse(token) is not None else EntityKind.UNKNOWN


def ffc_cohort(fmt: str) -> MarketCohort:
    """The cohort one FFC scoring format describes.

    ``league_size_semantics`` is ``None`` on every one of them, which is the whole point:
    the cohort object is where "this request constrains scoring but not league size" is
    written down once, so no caller has to remember it (ADR-039, ADR-056).
    """
    scoring = _FORMAT_TO_SCORING.get(fmt)
    if scoring is None:
        raise ValueError(
            f"unknown FFC format {fmt!r}; measured formats are {sorted(_FORMAT_TO_SCORING)}",
        )
    return MarketCohort(
        cohort_id=f"ffc-{fmt}",
        filters={"format": fmt, "teams": _REQUEST_TEAMS, "position": "all"},
        label=f"FFC recent {scoring} ADP",
        scoring_semantics=scoring,
        # Measured, twice, across four league sizes and three formats: `teams` is ignored.
        league_size_semantics=None,
    )


#: The production cohort set: one per scoring format, which is every cohort FFC has.
FFC_COHORTS: tuple[MarketCohort, ...] = tuple(ffc_cohort(fmt) for fmt in sorted(_FORMAT_TO_SCORING))


@dataclass(frozen=True, slots=True)
class FfcWindow:
    """The aggregation window one response describes."""

    start_date: date | None
    end_date: date | None
    total_drafts: int | None

    @property
    def days(self) -> int | None:
        if self.start_date is None or self.end_date is None:
            return None
        return (self.end_date - self.start_date).days

    def to_detail(self) -> dict[str, str]:
        return {
            "window_start_date": str(self.start_date) if self.start_date else "",
            "window_end_date": str(self.end_date) if self.end_date else "",
            "window_days": str(self.days) if self.days is not None else "",
            "total_drafts": str(self.total_drafts) if self.total_drafts is not None else "",
        }


class FfcAdpAdapter(BaseSourceAdapter):
    """``/api/v1/adp/{format}`` -> normalized market quotes."""

    source_id = FFC_SOURCE_ID
    resource = "api/v1/adp/{format}"
    adapter_version = "1.0"
    contract = MARKET_QUOTE_CONTRACT
    recorded_schema_fixture = "ffc_adp_half_ppr"
    license_policy_version = _FFC_LICENSE
    min_expected_records = 1
    required_source_columns = frozenset(
        {"player_id", "name", "position", "adp", "times_drafted", "stdev"},
    )

    def normalize(
        self,
        payload: RawRecords | Mapping[str, Any],
        *,
        season: int,
        cohort: MarketCohort,
        retrieved_at: datetime | None = None,
    ) -> SourceBatch:
        records = _players(payload)
        window = _window(payload)
        retrieved = retrieved_at or utc_now()
        rows: list[dict[str, Any]] = []
        dropped = 0
        high_le_low = 0
        comparable = 0
        team_units = 0

        window_type = (
            AggregationWindow.ROLLING if window.days is not None else AggregationWindow.UNKNOWN
        )
        base_flags = [LEAGUE_SIZE_NOT_OBSERVED]
        if window.days is not None:
            base_flags.append(SOURCE_WINDOW_PUBLISHED)
        flags = ",".join(sorted(base_flags))

        for record in records:
            external = _text(record.get("player_id"))
            adp = _float(record.get("adp"))
            if external is None or adp is None or adp <= 0:
                dropped += 1
                continue
            raw_position = _text(record.get("position"))
            kind = classify_ffc_entity(raw_position)
            if kind is EntityKind.TEAM_UNIT:
                team_units += 1
            high = _float(record.get("high"))
            low = _float(record.get("low"))
            if high is not None and low is not None:
                comparable += 1
                if high <= low:
                    high_le_low += 1
            minimum, maximum = _pick_bounds(high, low)
            rows.append(
                {
                    "source_id": self.source_id,
                    "season": season,
                    "cohort_id": cohort.cohort_id,
                    "market_signal_type": str(MarketSignalType.ADP),
                    "external_player_id": external,
                    "average_pick": adp,
                    # FFC publishes no rank column; the order is the ADP order. Deriving a
                    # rank here would invent a field the source does not have.
                    "market_rank": None,
                    "min_pick": minimum,
                    "max_pick": maximum,
                    "adp_sd": _float(record.get("stdev")),
                    "sample_size": _int(record.get("times_drafted")),
                    # FFC publishes no selection percentage.
                    "selection_pct": None,
                    "scoring_preset": cohort.scoring_semantics,
                    "league_size": None,
                    "aggregation_window_type": str(window_type),
                    "aggregation_window_days": window.days,
                    "retrieved_at_utc": retrieved,
                    # The window's END is the closest thing FFC publishes to a data-as-of
                    # time, and it is a date rather than an instant. Promoting a date to a
                    # timestamp would manufacture precision, so this stays null and the
                    # window travels in its own columns (AGENTS.md section 5).
                    "source_as_of_utc": None,
                    "entity_kind": str(kind),
                    "raw_position": raw_position,
                    "source_display_name": _text(record.get("name")),
                    "source_team": _text(record.get("team")),
                    "source_format_detail": cohort.filter_query,
                    "quality_flags": flags,
                },
            )

        detail: dict[str, str] = {
            "season": str(season),
            "cohort_id": cohort.cohort_id,
            "cohort_filters": cohort.filter_query,
            "rows_without_usable_price": str(dropped),
            "team_unit_rows": str(team_units),
            # Evidence for the `high`/`low` orientation rather than a belief about it. If
            # this equals `high_low_comparable_rows`, "high" is the earliest pick.
            "high_le_low_rows": str(high_le_low),
            "high_low_comparable_rows": str(comparable),
            **window.to_detail(),
        }
        return self.build_batch(
            self.contract.build(rows),
            retrieved_at=retrieved,
            source_as_of=None,
            detail=detail,
        )

    def fetch(self, *, as_of: datetime, config: SourceConfig) -> SourceBatch:
        cohort = config.options.get("cohort")
        if not isinstance(cohort, MarketCohort):
            raise ValueError("FfcAdpAdapter.fetch requires options['cohort']")
        fmt = str(cohort.filters.get("format", ""))
        payload = _ffc_get(fmt=fmt, season=config.season, cohort=cohort, config=config)
        return self.normalize(
            payload,
            season=config.season,
            cohort=cohort,
            retrieved_at=as_of or utc_now(),
        )

    def semantic_checks(self, batch: SourceBatch) -> Sequence[QualityCheck]:
        if batch.frame.is_empty():
            return ()
        checks: list[QualityCheck] = []

        claimed = batch.frame.get_column("league_size").null_count()
        if claimed != batch.frame.height:
            checks.append(
                QualityCheck.fail(
                    "market.ffc_claims_league_size",
                    stage=self.source_id,
                    message=(
                        "FFC accepts `teams` and ignores it (ADR-056, re-measured "
                        "2026-09-02); a populated league_size would be a cohort claim the "
                        "API does not substantiate"
                    ),
                    observed=f"{batch.frame.height - claimed} row(s) with a league size",
                    expected="null on every row",
                ),
            )
        if batch.frame.get_column("source_as_of_utc").null_count() != batch.frame.height:
            checks.append(
                QualityCheck.fail(
                    "market.fabricated_source_as_of",
                    stage=self.source_id,
                    message=(
                        "FFC publishes a window of dates, not a data-as-of instant; a "
                        "populated source_as_of_utc would manufacture precision"
                    ),
                    observed="populated",
                    expected="null for every row",
                ),
            )
        signals = set(batch.frame.get_column("market_signal_type").unique().to_list())
        if signals != {str(MarketSignalType.ADP)}:
            checks.append(
                QualityCheck.fail(
                    "market.ffc_signal_type",
                    stage=self.source_id,
                    message="FFC publishes draft prices only; no row may claim to be ECR",
                    observed=", ".join(sorted(signals)),
                    expected=str(MarketSignalType.ADP),
                ),
            )
        windows = set(batch.frame.get_column("aggregation_window_type").unique().to_list())
        if str(AggregationWindow.SEASON_CUMULATIVE) in windows:
            checks.append(
                QualityCheck.fail(
                    "market.ffc_window_semantics",
                    stage=self.source_id,
                    message=(
                        "FFC aggregates a bounded recent window; labelling it cumulative "
                        "would make it interchangeable with MFL, which it is not"
                    ),
                    observed=", ".join(sorted(windows)),
                    expected=f"{AggregationWindow.ROLLING} or {AggregationWindow.UNKNOWN}",
                ),
            )
        unknown = batch.frame.filter(pl.col("entity_kind") == str(EntityKind.UNKNOWN)).height
        if unknown:
            checks.append(
                QualityCheck.fail(
                    "market.unclassified_entities",
                    stage=self.source_id,
                    message="FFC rows whose position token is unrecognised cannot be classified",
                    observed=f"{unknown} row(s)",
                    expected="0",
                    severity=Severity.WARNING,
                ),
            )
        return checks


def _pick_bounds(high: float | None, low: float | None) -> tuple[float | None, float | None]:
    """Order FFC's two extreme picks numerically.

    FFC's table reads "High" for the earliest pick a player was taken at, which is the
    smaller number — the opposite of how ``max`` reads in English. Ordering the pair rather
    than trusting the label makes this correct under either convention, and if the vendor
    ever swaps them the adapter does not silently invert a published range.
    """
    values = [value for value in (high, low) if value is not None]
    if not values:
        return None, None
    return min(values), max(values)


def _players(payload: RawRecords | Mapping[str, Any]) -> list[dict[str, Any]]:
    """Accept either the full FFC envelope or a bare list of rows."""
    if isinstance(payload, Mapping):
        rows = payload.get("players", [])
        if isinstance(rows, Mapping):
            rows = [rows]
        return [dict(row) for row in rows] if isinstance(rows, list) else []
    return as_rows(payload)


def _window(payload: RawRecords | Mapping[str, Any]) -> FfcWindow:
    meta = payload.get("meta") if isinstance(payload, Mapping) else None
    if not isinstance(meta, Mapping):
        return FfcWindow(start_date=None, end_date=None, total_drafts=None)
    return FfcWindow(
        start_date=_date(meta.get("start_date")),
        end_date=_date(meta.get("end_date")),
        total_drafts=_int(meta.get("total_drafts")),
    )


def _ffc_get(
    *,
    fmt: str,
    season: int,
    cohort: MarketCohort,
    config: SourceConfig,
) -> Any:
    """One public FFC ADP request.

    The publisher's terms permit API use with attribution and ask clients not to poll
    unnecessarily, so a production refresh fetches once a day per cohort and every
    downstream stage reads the retained snapshot instead (`docs/DATA_SOURCES.md` 14.1).
    """
    import requests

    url = f"{FFC_API_BASE_URL}{fmt}"
    params = {
        "teams": cohort.filters.get("teams", _REQUEST_TEAMS),
        "year": str(season),
        "position": cohort.filters.get("position", "all"),
    }
    headers = {"User-Agent": FFC_USER_AGENT, "Accept": "application/json"}
    delay = config.min_interval_seconds
    last_error: Exception | None = None

    for attempt in range(1, max(1, config.max_retries) + 1):
        try:
            response = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=config.timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001 - re-raised as a typed adapter failure
            last_error = exc
        else:
            if response.status_code == 429:
                retry_after = response.headers.get("retry-after")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else delay
                last_error = SourceFetchError(f"{FFC_SOURCE_ID}: throttled (429)")
                if attempt < config.max_retries:
                    time.sleep(wait)
                    delay *= 2
                    continue
            elif response.ok:
                try:
                    return response.json()
                except ValueError as exc:
                    raise SourceFetchError(f"{FFC_SOURCE_ID}: non-JSON response") from exc
            else:
                last_error = SourceFetchError(
                    f"{FFC_SOURCE_ID}: HTTP {response.status_code} for format {fmt}",
                )
        if attempt < config.max_retries:
            time.sleep(delay)
            delay *= 2

    raise SourceFetchError(f"{FFC_SOURCE_ID}: request failed after retries: {last_error}")


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


def _date(value: object) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except (TypeError, ValueError):
        return None
