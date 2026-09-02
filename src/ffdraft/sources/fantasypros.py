"""The FantasyPros public v2 expert-consensus adapter (Phase 10, ADR-064).

**Boundary module.** Market/reference data only; nothing under an intrinsic feature package
may import it, and a test asserts that.

**Read the disposition before the code.** `docs/RELEASE2_ROADMAP.md` 10.1.3 asked for
FantasyPros as a production source for **both** ADP and ECR, publicly visible in the Tier
and Arbitrage surfaces. Four runner probes on 2026-09-02 measured what the provisioned key
can actually serve, and the answer changes what may ship (`docs/DATA_SOURCES.md` 14.2):

1. The key is on the **free** tier. Every response carries ``public_api_limited: true`` and
   returns exactly **ten rows**. ``limit``, ``offset``, ``start``, ``page``, ``max_results``
   and ``ranks`` were each tried; all eight variants returned the same ten rows and the same
   first player. The cap is the tier, not a page size.
2. **There is no ADP.** ``/json/nfl/{season}/adp`` answers ``403 Missing Authentication
   Token``, and ``type=adp`` on the consensus endpoint returns the ECR row shape with no
   ADP-like field on it. A ``fantasypros_adp`` column would have nothing behind it, so this
   adapter does not emit one. Fabricating it was the alternative and is not an alternative.
3. The **ECR is real and correctly scoped**: ``rank_ecr``, ``rank_ave``, ``rank_min``,
   ``rank_max``, ``rank_std``, ``pos_rank``, ``tier``, ``player_ecr_delta``, with
   ``total_experts`` between 93 and 109 and a ``last_updated`` date. STD, HALF and PPR
   genuinely reorder, so the scoring axis is exact rather than decorative.
4. The reachable population is **forty players** — the top ten at each of QB/RB/WR/TE —
   against a documented ``count`` of 407 receivers and 225 tight ends alone.

So the adapter is written in full, against the measured contract, and **fails closed**:
:meth:`FantasyProsEcrAdapter.semantic_checks` raises a critical check whenever the response
declares itself limited, and the capture marks the source degraded rather than publishing a
forty-row slice of a market as though it were the market. Enabling it is a one-line registry
change the day a key without the cap is provisioned; until then this is a tested interface
and a retained snapshot, not a published number.

The measured request::

    GET https://api.fantasypros.com/public/v2/json/nfl/{season}/consensus-rankings
        ?position={QB|RB|WR|TE|FLX|ALL}&scoring={STD|HALF|PPR}&type=draft&week=0
    x-api-key: <secret>

``position=ALL`` is rejected as an invalid position *unless* ``type=draft&week=0`` accompany
it — measured, not guessed, from the vendor's own 400 response, which also named the valid
vocabulary: ``QB, RB, WR, TE, K, OP, FLX, DST, IDP, DL, LB, DB, TK, TQB, TRB, TWR, TTE,
TOL, HC, P``.

**Secret handling.** The key is read from ``FANTASYPROS_API_KEY`` through
:mod:`ffdraft.secret`, sent only as the ``x-api-key`` header, and never printed, serialized,
cached or written into a snapshot. Only the backend capture path may call this vendor; the
browser never receives the key and never calls FantasyPros.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
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
    "FANTASYPROS_API_BASE_URL",
    "FANTASYPROS_COHORTS",
    "FANTASYPROS_DAILY_REQUEST_CAP",
    "FANTASYPROS_MIN_REQUEST_INTERVAL_SECONDS",
    "FANTASYPROS_SOURCE_ID",
    "FANTASYPROS_USER_AGENT",
    "RESPONSE_TRUNCATED",
    "SOURCE_AS_OF_PARTIAL",
    "CallPlan",
    "FantasyProsEcrAdapter",
    "RequestBudget",
    "fantasypros_cohort",
]

FANTASYPROS_SOURCE_ID = "fantasypros_ecr"
FANTASYPROS_API_BASE_URL = "https://api.fantasypros.com/public/v2/json/"
_FANTASYPROS_LICENSE = "fantasypros-public-v2-terms/2026-09-02"

FANTASYPROS_USER_AGENT = (
    "jeisey-tiers (+https://github.com/jeisey/jeisey-tiers); "
    "free non-commercial fantasy football project"
)

#: The project's own budget. The vendor's terms state one request per second and up to 100
#: per day; roadmap 10.1.3 deliberately halves the daily allowance for operational headroom
#: and both numbers are treated as hard application constraints rather than guidance.
FANTASYPROS_DAILY_REQUEST_CAP = 50
FANTASYPROS_MIN_REQUEST_INTERVAL_SECONDS = 1.0

#: Row-level quality flags.
#:
#: The first is the one that stops a truncated response being read as a market.
RESPONSE_TRUNCATED = "source_response_truncated"
SOURCE_AS_OF_PARTIAL = "source_as_of_date_partial"

#: The scoring tokens the vendor accepts, mapped onto this project's vocabulary. Measured
#: to produce genuinely different orderings, so the axis is exact.
_SCORING_TOKENS: dict[str, str] = {"STD": "STD", "HALF": "HALF", "PPR": "PPR"}

#: The positions a complete capture requests. `ALL` is deliberately not used: it returns the
#: same ten rows as any single position, so per-position calls are the only way to widen the
#: population at all, and four of them is still only forty players.
_CAPTURE_POSITIONS: tuple[str, ...] = ("QB", "RB", "WR", "TE")


def fantasypros_cohort(scoring: str) -> MarketCohort:
    """The cohort one FantasyPros scoring request describes."""
    token = _SCORING_TOKENS.get(scoring.upper())
    if token is None:
        raise ValueError(
            f"unknown FantasyPros scoring {scoring!r}; measured values are "
            f"{sorted(_SCORING_TOKENS)}",
        )
    return MarketCohort(
        cohort_id=f"fantasypros-{token.lower()}-ecr",
        filters={"scoring": token, "type": "draft", "week": "0"},
        label=f"FantasyPros {token} expert consensus",
        scoring_semantics=token,
        # An expert ranking is not produced for a league size at all. This is `None` for a
        # different reason than FFC's is: not "unobservable", but "not a dimension of this
        # measurement". Both are honestly null; the label carries the distinction.
        league_size_semantics=None,
    )


FANTASYPROS_COHORTS: tuple[MarketCohort, ...] = tuple(
    fantasypros_cohort(scoring) for scoring in ("HALF", "PPR", "STD")
)


@dataclass
class RequestBudget:
    """A counter that refuses to exceed the project's self-imposed daily cap.

    Enforced in code rather than trusted to a caller: roadmap 10.1.3 makes the cap an
    application constraint, and a constraint nothing checks is a comment.
    """

    limit: int = FANTASYPROS_DAILY_REQUEST_CAP
    min_interval_seconds: float = FANTASYPROS_MIN_REQUEST_INTERVAL_SECONDS
    used: int = 0
    _last: float | None = field(default=None, repr=False)

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    def spend(self, *, sleep: bool = True) -> None:
        if self.used >= self.limit:
            raise SourceFetchError(
                f"{FANTASYPROS_SOURCE_ID}: daily request cap reached "
                f"({self.used}/{self.limit}); refusing to issue another vendor request",
            )
        if sleep and self._last is not None:
            elapsed = time.monotonic() - self._last
            if elapsed < self.min_interval_seconds:
                time.sleep(self.min_interval_seconds - elapsed)
        self.used += 1
        self._last = time.monotonic()


@dataclass(frozen=True, slots=True)
class CallPlan:
    """The smallest deterministic set of requests that covers one cohort.

    Four positions per scoring cohort. Three cohorts is twelve requests a day, comfortably
    inside the internal fifty, and there is no cheaper plan that reaches more players —
    ``position=ALL`` returns the same ten rows as ``position=QB``.
    """

    cohort: MarketCohort
    positions: tuple[str, ...] = _CAPTURE_POSITIONS

    @property
    def request_count(self) -> int:
        return len(self.positions)

    def params(self, position: str) -> dict[str, str]:
        return {
            "position": position,
            "scoring": str(self.cohort.scoring_semantics),
            # Measured requirement: `position=ALL` 400s without these two, and every other
            # position accepts them. Sending them always keeps one request shape.
            "type": "draft",
            "week": "0",
        }


class FantasyProsEcrAdapter(BaseSourceAdapter):
    """``/consensus-rankings`` -> normalized expert-consensus quotes."""

    source_id = FANTASYPROS_SOURCE_ID
    resource = "json/nfl/{season}/consensus-rankings"
    adapter_version = "1.0"
    contract = MARKET_QUOTE_CONTRACT
    recorded_schema_fixture = "fantasypros_consensus_rankings_half"
    license_policy_version = _FANTASYPROS_LICENSE
    min_expected_records = 1
    required_source_columns = frozenset(
        {"player_id", "player_name", "player_position_id", "rank_ecr"},
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
        envelope = _envelope(payload)
        retrieved = retrieved_at or utc_now()
        rows: list[dict[str, Any]] = []
        dropped = 0

        truncated = _is_truncated(envelope, len(records))
        flags = [RESPONSE_TRUNCATED] if truncated else []
        if envelope.get("last_updated"):
            # "9/02" — a month and a day, with no year and no time. Recorded as evidence,
            # never promoted to `source_as_of_utc`: a date is not an instant, and inventing
            # the missing year would be worse than leaving the field null.
            flags.append(SOURCE_AS_OF_PARTIAL)
        row_flags = ",".join(sorted(flags))

        for record in records:
            external = _text(record.get("player_id"))
            rank = _int(record.get("rank_ecr"))
            if external is None or rank is None or rank < 1:
                dropped += 1
                continue
            raw_position = _text(record.get("player_position_id"))
            kind = (
                EntityKind.PLAYER
                if Position.parse(raw_position) is not None
                else EntityKind.TEAM_UNIT
                if (raw_position or "").upper() in {"DST", "DEF"}
                else EntityKind.UNKNOWN
            )
            rows.append(
                {
                    "source_id": self.source_id,
                    "season": season,
                    "cohort_id": cohort.cohort_id,
                    "market_signal_type": str(MarketSignalType.ECR),
                    "external_player_id": external,
                    # There is no ADP behind this key. Every pick-denominated column stays
                    # null, and the consensus columns carry the dispersion that does exist.
                    "average_pick": None,
                    "market_rank": rank,
                    "min_pick": None,
                    "max_pick": None,
                    "adp_sd": None,
                    "consensus_rank_mean": _float(record.get("rank_ave")),
                    "consensus_rank_min": _int(record.get("rank_min")),
                    "consensus_rank_max": _int(record.get("rank_max")),
                    "consensus_rank_sd": _float(record.get("rank_std")),
                    # For an expert ranking the "sample" is the panel: 93 to 109 experts on
                    # 2026-09-02, which is exactly the "how many observations back this
                    # number" the column means for a draft price.
                    "sample_size": _int(envelope.get("total_experts")),
                    "selection_pct": None,
                    "scoring_preset": cohort.scoring_semantics,
                    "league_size": None,
                    # A ranking has no draft window. Not "unknown" — structurally absent.
                    "aggregation_window_type": str(AggregationWindow.NOT_APPLICABLE),
                    "aggregation_window_days": None,
                    "retrieved_at_utc": retrieved,
                    "source_as_of_utc": None,
                    "entity_kind": str(kind),
                    "raw_position": raw_position,
                    "source_display_name": _text(record.get("player_name")),
                    "source_team": _text(record.get("player_team_id")),
                    "source_format_detail": cohort.filter_query,
                    "quality_flags": row_flags,
                },
            )

        detail: dict[str, str] = {
            "season": str(season),
            "cohort_id": cohort.cohort_id,
            "cohort_filters": cohort.filter_query,
            "rows_without_usable_rank": str(dropped),
            "response_rows": str(len(records)),
            # The vendor's own account of what it withheld. `count` is the full population;
            # `limit` and `public_api_limited` are why only a slice arrived.
            "envelope_count": str(envelope.get("count", "")),
            "envelope_limit": str(envelope.get("limit", "")),
            "public_api_limited": str(envelope.get("public_api_limited", "")),
            "tier": str(envelope.get("tier", "")),
            "total_experts": str(envelope.get("total_experts", "")),
            "last_updated": str(envelope.get("last_updated", "")),
        }
        return self.build_batch(
            self.contract.build(rows),
            retrieved_at=retrieved,
            source_as_of=None,
            warning_codes=(RESPONSE_TRUNCATED,) if truncated else (),
            detail=detail,
        )

    def fetch(self, *, as_of: datetime, config: SourceConfig) -> SourceBatch:
        """Retrieve one cohort's complete call plan. **Network I/O, backend only.**"""
        cohort = config.options.get("cohort")
        if not isinstance(cohort, MarketCohort):
            raise ValueError("FantasyProsEcrAdapter.fetch requires options['cohort']")
        api_key = config.options.get("api_key")
        if not isinstance(api_key, str) or not api_key:
            raise SourceFetchError(
                f"{FANTASYPROS_SOURCE_ID}: no API key. The key is a backend Actions secret "
                "(FANTASYPROS_API_KEY); an unauthenticated call would measure a different "
                "product surface rather than fail honestly.",
            )
        budget = config.options.get("budget")
        if not isinstance(budget, RequestBudget):
            budget = RequestBudget()

        plan = CallPlan(cohort=cohort)
        merged: list[dict[str, Any]] = []
        envelope: dict[str, Any] = {}
        for position in plan.positions:
            payload = _fantasypros_get(
                season=config.season,
                params=plan.params(position),
                api_key=api_key,
                budget=budget,
                config=config,
            )
            merged.extend(_players(payload))
            if not envelope:
                envelope = _envelope(payload)
        return self.normalize(
            {"players": merged, **envelope},
            season=config.season,
            cohort=cohort,
            retrieved_at=as_of or utc_now(),
        )

    def semantic_checks(self, batch: SourceBatch) -> Sequence[QualityCheck]:
        if batch.frame.is_empty():
            return ()
        checks: list[QualityCheck] = []

        truncated = batch.frame.filter(
            pl.col("quality_flags").str.contains(RESPONSE_TRUNCATED, literal=True),
        ).height
        if truncated:
            checks.append(
                QualityCheck.fail(
                    "market.fantasypros_truncated",
                    stage=self.source_id,
                    message=(
                        "the response declares itself limited, so this is a slice of a "
                        "ranking rather than the ranking; roadmap 10.1.3 forbids treating "
                        "a truncated response as a complete market, and these rows must "
                        "not reach a public comparison"
                    ),
                    observed=f"{truncated} row(s) flagged {RESPONSE_TRUNCATED}",
                    expected="a complete response (public_api_limited absent or false)",
                ),
            )

        signals = set(batch.frame.get_column("market_signal_type").unique().to_list())
        if signals != {str(MarketSignalType.ECR)}:
            checks.append(
                QualityCheck.fail(
                    "market.fantasypros_signal_type",
                    stage=self.source_id,
                    message=(
                        "this key serves expert consensus only; no row may claim to be an "
                        "observed draft price (measured 2026-09-02: /adp is 403 and "
                        "type=adp carries no ADP field)"
                    ),
                    observed=", ".join(sorted(signals)),
                    expected=str(MarketSignalType.ECR),
                ),
            )
        priced = batch.frame.height - batch.frame.get_column("average_pick").null_count()
        if priced:
            checks.append(
                QualityCheck.fail(
                    "market.fantasypros_fabricated_adp",
                    stage=self.source_id,
                    message="an ECR row with an average_pick would be a manufactured price",
                    observed=f"{priced} row(s)",
                    expected="null average_pick on every row",
                ),
            )
        unknown = batch.frame.filter(pl.col("entity_kind") == str(EntityKind.UNKNOWN)).height
        if unknown:
            checks.append(
                QualityCheck.fail(
                    "market.unclassified_entities",
                    stage=self.source_id,
                    message="FantasyPros rows with an unrecognised position token",
                    observed=f"{unknown} row(s)",
                    expected="0",
                    severity=Severity.WARNING,
                ),
            )
        return checks


def _is_truncated(envelope: Mapping[str, Any], returned: int) -> bool:
    """Whether the vendor withheld rows, by its own account.

    Two independent signals, because either alone could be absent on a tier this project
    has not seen: the explicit ``public_api_limited`` flag, and ``count`` exceeding the
    number of rows actually delivered.
    """
    if bool(envelope.get("public_api_limited")):
        return True
    count = _int(envelope.get("count"))
    return count is not None and returned > 0 and count > returned


def _players(payload: RawRecords | Mapping[str, Any]) -> list[dict[str, Any]]:
    if isinstance(payload, Mapping):
        rows = payload.get("players", [])
        if isinstance(rows, Mapping):
            rows = [rows]
        return [dict(row) for row in rows] if isinstance(rows, list) else []
    return as_rows(payload)


def _envelope(payload: RawRecords | Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {}
    return {key: value for key, value in payload.items() if not isinstance(value, list | dict)}


def _fantasypros_get(
    *,
    season: int,
    params: Mapping[str, str],
    api_key: str,
    budget: RequestBudget,
    config: SourceConfig,
) -> Any:
    """One authenticated FantasyPros request, paced and budgeted.

    The key travels in a header and nowhere else. It is never placed in a query string,
    because a URL reaches logs, proxies and error messages that a header does not.
    """
    import requests

    url = f"{FANTASYPROS_API_BASE_URL}nfl/{season}/consensus-rankings"
    headers = {
        "User-Agent": FANTASYPROS_USER_AGENT,
        "Accept": "application/json",
        "x-api-key": api_key,
    }
    delay = max(config.min_interval_seconds, FANTASYPROS_MIN_REQUEST_INTERVAL_SECONDS)
    last_error: Exception | None = None

    for attempt in range(1, max(1, config.max_retries) + 1):
        budget.spend()
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
                retry_after = response.headers.get("retry-after")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else delay
                last_error = SourceFetchError(f"{FANTASYPROS_SOURCE_ID}: throttled (429)")
                if attempt < config.max_retries:
                    time.sleep(wait)
                    delay *= 2
                    continue
            elif response.ok:
                try:
                    return response.json()
                except ValueError as exc:
                    raise SourceFetchError(
                        f"{FANTASYPROS_SOURCE_ID}: non-JSON response",
                    ) from exc
            else:
                # The body can echo request detail; the status and the position are enough
                # to diagnose, and neither can contain the key.
                last_error = SourceFetchError(
                    f"{FANTASYPROS_SOURCE_ID}: HTTP {response.status_code} for "
                    f"position={params.get('position')}",
                )
        if attempt < config.max_retries:
            time.sleep(delay)
            delay *= 2

    raise SourceFetchError(f"{FANTASYPROS_SOURCE_ID}: request failed after retries: {last_error}")


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
