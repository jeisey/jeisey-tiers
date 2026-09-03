"""Capturing and resolving the Phase-10 market sources through one shared path.

**Boundary module.** Market data only.

Phase 5 built the capture path around MyFantasyLeague, and Phase 10 adds two more sources
that resolve identity in two more ways. The temptation is a base class with three
overridable hooks; what this module does instead is describe each source *as data* — a
:class:`MarketSourceSpec` — and keep one capture function. There are three sources and there
will not be thirty, and a spec you can print is easier to audit than an inheritance chain.

The three identity strategies are genuinely different, and that difference is the reason the
spec exists rather than a flag:

``myfantasyleague_adp``
    Two live id bridges (``espn_id`` primary, ``mfl_id`` via the crosswalk) cross-checked
    against each other, plus the reviewed alias hatch. Unchanged from Phase 5 and captured
    by :mod:`ffdraft.market.capture`, which this module deliberately does not touch —
    roadmap 10.1.2 requires MFL's behaviour to be identical, and the safest way to keep code
    identical is not to edit it.

``fantasyfootballcalculator_adp``
    No bridge at all: FFC's ``player_id`` maps to nothing outside FFC. Resolution is by
    **stored alias only**, generated once by :mod:`ffdraft.identity.linkage` and reviewed
    afterwards. Production capture never fuzzy-matches; it looks up an id.

``fantasypros_ecr``
    Two live bridges again — ``sportsdata_id`` resolved 40/40 through the Sportradar index
    and ``player_yahoo_id`` 36/40 through the Yahoo index on 2026-09-02 — so it joins by id
    like MFL and needs no linkage.

Everything here is offline-testable: :func:`build_source_snapshot` takes already-retrieved
payloads, and :func:`capture_source` is the thin network wrapper around it.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from ffdraft.config import AppConfig, load_app_config
from ffdraft.contracts import (
    EntityKind,
    MarketCohort,
    QualityCheck,
    SourceBatch,
    ValidationReport,
)
from ffdraft.contracts.enums import Severity
from ffdraft.identity.aliases import AliasMap, load_production_aliases
from ffdraft.identity.ids import IdNamespace
from ffdraft.market.identity import MarketIdentity, load_market_identity
from ffdraft.market.snapshot import (
    ADP_RAW_FILENAME,
    SNAPSHOT_MANIFEST_VERSION,
    CohortCapture,
    MarketSnapshotStore,
    SnapshotManifest,
)
from ffdraft.quality import QualityGate
from ffdraft.sources.base import SourceConfig
from ffdraft.sources.fantasypros import (
    FANTASYPROS_COHORTS,
    FANTASYPROS_SOURCE_ID,
    CallPlan,
    FantasyProsEcrAdapter,
    RequestBudget,
)
from ffdraft.sources.ffc import FFC_COHORTS, FFC_SOURCE_ID, FfcAdpAdapter
from ffdraft.timeutil import isoformat_utc, utc_now

__all__ = [
    "MARKET_SOURCE_SPECS",
    "IdentityStrategy",
    "MarketSourceSpec",
    "SourceCaptureResult",
    "build_source_snapshot",
    "capture_source",
    "resolve_rows",
    "spec_for",
]


# --------------------------------------------------------------------------------------
# Source specifications
# --------------------------------------------------------------------------------------


@runtime_checkable
class MarketQuoteAdapter(Protocol):
    """The slice of an adapter this module drives.

    Narrower than :class:`~ffdraft.sources.base.SourceAdapter` on purpose. A market adapter's
    ``normalize`` takes a season and a cohort, which the generic protocol's does not, and
    stating that here is what lets the type checker see that ``FfcAdpAdapter`` and
    ``FantasyProsEcrAdapter`` are interchangeable to this caller while ``SleeperPlayerAdapter``
    is not.
    """

    source_id: str
    adapter_version: str
    license_policy_version: str

    def normalize(
        self,
        payload: Any,
        *,
        season: int,
        cohort: MarketCohort,
        retrieved_at: datetime | None = None,
    ) -> SourceBatch: ...

    def validate_raw(self, batch: SourceBatch) -> ValidationReport: ...


@dataclass(frozen=True, slots=True)
class IdentityStrategy:
    """How one source's external ids reach a canonical player.

    ``bridges`` names the registry indexes a row may be looked up through, in priority
    order. ``alias_only`` says the source has no bridge at all and may resolve *only*
    through a stored alias, which is a stronger statement than an empty bridge list: it
    means a missing alias is the expected failure mode rather than a bug.
    """

    bridges: tuple[tuple[str, IdNamespace], ...] = ()
    alias_only: bool = False
    #: Two bridges that disagree fail closed rather than picking one (ADR-005).
    cross_check: bool = True


@dataclass(frozen=True, slots=True)
class MarketSourceSpec:
    """Everything the capture path needs to know about one market source."""

    source_id: str
    adapter_factory: Callable[[], MarketQuoteAdapter]
    cohorts: tuple[MarketCohort, ...]
    identity: IdentityStrategy
    #: Human-readable label for reports and the frontend's source selector.
    label: str
    #: Whether a capture's rows may reach a public artifact. A source can be fully
    #: implemented, tested and retained while remaining unpublished — which is exactly
    #: FantasyPros' state until a key without the free tier's row cap is provisioned.
    publishable: bool = True
    #: Why not, when not. Printed in reports rather than living only in an ADR.
    unpublishable_reason: str = ""

    @property
    def cohort_ids(self) -> tuple[str, ...]:
        return tuple(cohort.cohort_id for cohort in self.cohorts)


#: FFC: three scoring cohorts, alias-only identity, publishable.
FFC_SPEC = MarketSourceSpec(
    source_id=FFC_SOURCE_ID,
    adapter_factory=FfcAdpAdapter,
    cohorts=FFC_COHORTS,
    identity=IdentityStrategy(alias_only=True),
    label="FFC Recent",
)

#: FantasyPros: implemented in full, retained, and **not published**.
#:
#: Four probe runs on 2026-09-02 measured a hard ten-row cap the vendor attributes to the
#: key's free tier, no ADP anywhere the key can reach, and forty players total across the
#: four core positions against a documented population of 407 receivers alone. Publishing
#: that as "FantasyPros ECR" would describe a consensus the reader cannot get. The adapter,
#: the budget, the cache and the retention all work; only the publication is withheld, and
#: it becomes a one-line change the day the tier does.
FANTASYPROS_SPEC = MarketSourceSpec(
    source_id=FANTASYPROS_SOURCE_ID,
    adapter_factory=FantasyProsEcrAdapter,
    cohorts=FANTASYPROS_COHORTS,
    identity=IdentityStrategy(
        bridges=(
            ("sportsdata_id", IdNamespace.SPORTRADAR),
            ("player_yahoo_id", IdNamespace.YAHOO),
        ),
    ),
    label="FantasyPros ECR",
    publishable=False,
    unpublishable_reason=(
        "the provisioned key is on the free tier: every response returns ten rows with "
        "public_api_limited=true, no parameter widens it, and no endpoint the key can reach "
        "carries an ADP field (measured 2026-09-02, ADR-064)"
    ),
)

MARKET_SOURCE_SPECS: dict[str, MarketSourceSpec] = {
    FFC_SPEC.source_id: FFC_SPEC,
    FANTASYPROS_SPEC.source_id: FANTASYPROS_SPEC,
}


def spec_for(source_id: str) -> MarketSourceSpec:
    spec = MARKET_SOURCE_SPECS.get(source_id)
    if spec is None:
        raise ValueError(
            f"unknown market source {source_id!r}; known: {sorted(MARKET_SOURCE_SPECS)}",
        )
    return spec


# --------------------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RowResolution:
    """One row's identity outcome, with the reason it came out that way."""

    external_player_id: str
    player_id: str | None
    reason: str
    bridges_agreed: tuple[str, ...] = ()


REASON_ALIAS = "resolved_generated_alias"
REASON_BRIDGE = "resolved_exact_id"
REASON_BRIDGES_AGREE = "resolved_crosswalk"
REASON_NO_ALIAS = "unresolved_no_alias"
REASON_NO_BRIDGE = "unresolved_no_bridge"
REASON_BRIDGE_DISAGREEMENT = "ambiguous_bridge_disagreement"
REASON_AMBIGUOUS_ID = "ambiguous_external_id"
REASON_NON_PLAYER = "excluded_non_player_entity"


def resolve_rows(
    batch: SourceBatch,
    *,
    spec: MarketSourceSpec,
    identity: MarketIdentity,
    aliases: AliasMap,
    bridge_ids: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, RowResolution]:
    """Resolve one batch's external ids to canonical players, failing closed.

    ``bridge_ids`` maps ``external_player_id -> {bridge field: value}`` and is supplied by
    the capture, which sees the raw payload. The quote contract deliberately does not carry
    a source's foreign ids: they are a property of the capture, not of the price, and a
    column per source's crosswalk would make the contract grow with every vendor.
    """
    outcomes: dict[str, RowResolution] = {}
    lookups = bridge_ids or {}

    for row in batch.frame.iter_rows(named=True):
        external = str(row["external_player_id"])
        if str(row["entity_kind"]) != str(EntityKind.PLAYER):
            outcomes[external] = RowResolution(external, None, REASON_NON_PLAYER)
            continue

        alias = aliases.get(spec.source_id, external)
        if spec.identity.alias_only:
            outcomes[external] = (
                RowResolution(external, alias.player_id, REASON_ALIAS)
                if alias
                else RowResolution(external, None, REASON_NO_ALIAS)
            )
            continue

        found: dict[str, str] = {}
        ambiguous = False
        for field_name, namespace in spec.identity.bridges:
            value = lookups.get(external, {}).get(field_name)
            if not value:
                continue
            result = identity.registry.lookup(namespace, value)
            if result.status == "ambiguous":
                ambiguous = True
                continue
            if result.player_id:
                found[field_name] = result.player_id

        distinct = set(found.values())
        if len(distinct) > 1:
            # Two bridges naming two players is the case ADR-005 exists for. Never pick.
            outcomes[external] = RowResolution(
                external,
                None,
                REASON_BRIDGE_DISAGREEMENT,
                tuple(sorted(found)),
            )
        elif distinct:
            outcomes[external] = RowResolution(
                external,
                next(iter(distinct)),
                REASON_BRIDGES_AGREE if len(found) > 1 else REASON_BRIDGE,
                tuple(sorted(found)),
            )
        elif alias:
            # A reviewed or generated alias is the fallback, never the override: it is only
            # consulted once every live bridge has failed to produce anything.
            outcomes[external] = RowResolution(external, alias.player_id, REASON_ALIAS)
        else:
            outcomes[external] = RowResolution(
                external,
                None,
                REASON_AMBIGUOUS_ID if ambiguous else REASON_NO_BRIDGE,
            )
    return outcomes


# --------------------------------------------------------------------------------------
# Capture
# --------------------------------------------------------------------------------------


@dataclass
class SourceCaptureResult:
    """One source's capture: what was retrieved, resolved, and written."""

    source_id: str
    season: int
    snapshot_key: str
    retrieved_at_utc: datetime
    manifest: SnapshotManifest
    rows: list[dict[str, Any]] = field(default_factory=list)
    raw_payloads: dict[str, bytes] = field(default_factory=dict)
    gate: QualityGate = field(default_factory=QualityGate)

    @property
    def resolved(self) -> int:
        return sum(1 for row in self.rows if row.get("player_id"))

    @property
    def resolvable(self) -> int:
        return sum(1 for row in self.rows if str(row.get("entity_kind")) == str(EntityKind.PLAYER))

    @property
    def coverage(self) -> float:
        return self.resolved / self.resolvable if self.resolvable else 0.0


def build_source_snapshot(
    *,
    spec: MarketSourceSpec,
    season: int,
    retrieved_at: datetime,
    raw_by_cohort: Mapping[str, Any],
    identity: MarketIdentity,
    aliases: AliasMap | None = None,
    bridge_ids: Mapping[str, Mapping[str, str]] | None = None,
    git_sha: str | None = None,
    gate: QualityGate | None = None,
) -> SourceCaptureResult:
    """Normalize, resolve and assemble one source's snapshot from retrieved payloads.

    Pure with respect to the network, exactly as :func:`ffdraft.market.capture.build_snapshot`
    is: every fixture test drives this, and the live path only supplies the payloads.
    """
    from ffdraft.retention import canonical_json, content_hash, gzip_bytes, snapshot_key

    checks = gate or QualityGate()
    alias_map = (
        aliases if aliases is not None else load_production_aliases(source_ids=(spec.source_id,))
    )
    key = snapshot_key(retrieved_at)
    adapter = spec.adapter_factory()

    rows: list[dict[str, Any]] = []
    captures: list[CohortCapture] = []
    raw_payloads: dict[str, bytes] = {}

    for cohort_id, payload in sorted(raw_by_cohort.items()):
        cohort = next((c for c in spec.cohorts if c.cohort_id == cohort_id), None)
        if cohort is None:
            raise ValueError(f"{spec.source_id}: unknown cohort {cohort_id!r}")
        batch = adapter.normalize(
            payload,
            season=season,
            cohort=cohort,
            retrieved_at=retrieved_at,
        )
        report = adapter.validate_raw(batch)
        checks.extend(
            QualityCheck(
                check_id=check.check_id,
                stage=f"market.capture.{spec.source_id}.{cohort_id}",
                status=check.status,
                severity=check.severity,
                message=check.message,
                observed=check.observed,
                expected=check.expected,
            )
            for check in report.checks
        )

        outcomes = resolve_rows(
            batch,
            spec=spec,
            identity=identity,
            aliases=alias_map,
            bridge_ids=bridge_ids,
        )
        rows.extend(_snapshot_rows(batch, outcomes, identity))

        raw_path = f"cohorts/{cohort_id}/{ADP_RAW_FILENAME}"
        raw_bytes = gzip_bytes(canonical_json(payload))
        raw_payloads[raw_path] = raw_bytes
        resolved = sum(1 for o in outcomes.values() if o.player_id)
        resolvable = sum(1 for o in outcomes.values() if o.reason != REASON_NON_PLAYER)
        captures.append(
            CohortCapture(
                cohort_id=cohort_id,
                filters=dict(cohort.filters),
                label=cohort.label,
                raw_path=raw_path,
                raw_content_hash=content_hash(raw_bytes),
                row_count=batch.frame.height,
                resolved_players=resolved,
                resolvable_players=resolvable,
                ambiguous_players=sum(
                    1
                    for o in outcomes.values()
                    if o.reason in {REASON_BRIDGE_DISAGREEMENT, REASON_AMBIGUOUS_ID}
                ),
                non_player_entities=sum(
                    1 for o in outcomes.values() if o.reason == REASON_NON_PLAYER
                ),
                # A retained snapshot never claims exactness; that is a per-preset verdict
                # the selection rule reaches later (ADR-039).
                exact_cohort=False,
            ),
        )

    checks.extend(_capture_checks(spec, rows, len(raw_by_cohort)))
    manifest = SnapshotManifest(
        manifest_version=SNAPSHOT_MANIFEST_VERSION,
        source_id=spec.source_id,
        season=season,
        snapshot_key=key,
        retrieved_at_utc=isoformat_utc(retrieved_at),
        adapter_version=adapter.adapter_version,
        source_policy_version=adapter.license_policy_version,
        cohorts=tuple(captures),
        git_sha=git_sha,
        notes=_notes_for(spec),
    )
    return SourceCaptureResult(
        source_id=spec.source_id,
        season=season,
        snapshot_key=key,
        retrieved_at_utc=retrieved_at,
        manifest=manifest,
        rows=rows,
        raw_payloads=raw_payloads,
        gate=checks,
    )


def _notes_for(spec: MarketSourceSpec) -> tuple[str, ...]:
    """Provenance a reader of a retained snapshot needs without this code to hand."""
    if spec.source_id == FFC_SOURCE_ID:
        return (
            "FFC accepts `teams` and ignores it; league_size is null and not claimable "
            "(ADR-056, re-measured 2026-09-02).",
            "FFC aggregates a bounded recent window (meta.start_date/end_date), not the "
            "season to date. It is not interchangeable with MyFantasyLeague ADP.",
            "`stdev` is a genuine per-player standard deviation; `high`/`low` are extreme "
            "order statistics and occupy different columns.",
            "Identity resolves by stored alias only: FFC's player_id bridges to nothing "
            "outside FFC (ADR-061).",
        )
    if spec.source_id == FANTASYPROS_SOURCE_ID:
        return (
            "Expert consensus ranking, not an observed draft price. No ADP is available to "
            "this key: /adp is 403 and type=adp carries no ADP field (ADR-064).",
            "The free tier caps every response at ten rows (public_api_limited=true) and no "
            "parameter widens it. These rows are retained but NOT published.",
            "`last_updated` is a month/day with no year or time; source_as_of_utc stays null.",
        )
    return ()


def _snapshot_rows(
    batch: SourceBatch,
    outcomes: Mapping[str, RowResolution],
    identity: MarketIdentity,
) -> list[dict[str, Any]]:
    """Normalized quotes plus their identity outcome, ready to retain.

    Unresolved rows are retained with a null ``player_id`` and their refusal reason, for the
    same reason Phase 5 retained MFL's: a snapshot is evidence, and dropping the rows that
    did not join would hide the coverage question a later session needs to answer.
    """
    rows: list[dict[str, Any]] = []
    for row in batch.frame.iter_rows(named=True):
        external = str(row["external_player_id"])
        outcome = outcomes.get(external)
        player_id = outcome.player_id if outcome else None
        player = identity.registry.get(player_id) if player_id else None
        rows.append(
            {
                "source_id": str(row["source_id"]),
                "season": int(row["season"]),
                "cohort_id": str(row["cohort_id"]),
                "market_signal_type": str(row["market_signal_type"]),
                "external_player_id": external,
                "player_id": player_id,
                "resolution_reason": outcome.reason if outcome else None,
                "resolution_bridges": list(outcome.bridges_agreed) if outcome else [],
                "display_name": player.display_name if player else row["source_display_name"],
                "position": str(player.position) if player else None,
                "team": player.team if player else row["source_team"],
                "average_pick": row["average_pick"],
                "market_rank": row["market_rank"],
                "min_pick": row["min_pick"],
                "max_pick": row["max_pick"],
                "adp_sd": row["adp_sd"],
                "consensus_rank_mean": row["consensus_rank_mean"],
                "consensus_rank_min": row["consensus_rank_min"],
                "consensus_rank_max": row["consensus_rank_max"],
                "consensus_rank_sd": row["consensus_rank_sd"],
                "sample_size": row["sample_size"],
                "selection_pct": row["selection_pct"],
                "scoring_preset": row["scoring_preset"],
                "league_size": row["league_size"],
                "aggregation_window_type": str(row["aggregation_window_type"]),
                "aggregation_window_days": row["aggregation_window_days"],
                "entity_kind": str(row["entity_kind"]),
                "raw_position": row["raw_position"],
                "source_display_name": row["source_display_name"],
                "source_team": row["source_team"],
                "source_format_detail": str(row["source_format_detail"]),
                "quality_flags": [
                    flag for flag in str(row["quality_flags"] or "").split(",") if flag
                ],
            },
        )
    return rows


def _capture_checks(
    spec: MarketSourceSpec,
    rows: Sequence[Mapping[str, Any]],
    cohorts: int,
) -> list[QualityCheck]:
    if not rows:
        return [
            QualityCheck.fail(
                "market.capture_empty",
                stage=f"market.capture.{spec.source_id}",
                message="no cohort returned a usable quote; this is a source failure",
                observed=f"0 rows across {cohorts} cohort(s)",
                expected="> 0",
            ),
        ]
    checks = [
        QualityCheck.ok(
            "market.capture_nonempty",
            stage=f"market.capture.{spec.source_id}",
            message="the capture retained usable quotes",
            observed=f"{len(rows)} row(s) across {cohorts} cohort(s)",
        ),
    ]
    if not spec.publishable:
        checks.append(
            QualityCheck.fail(
                "market.source_retained_not_published",
                stage=f"market.capture.{spec.source_id}",
                message=(
                    f"{spec.source_id} is retained for evidence and excluded from public "
                    f"artifacts: {spec.unpublishable_reason}"
                ),
                observed=f"{len(rows)} retained row(s)",
                expected="publishable once the blocking condition clears",
                severity=Severity.WARNING,
            ),
        )
    return checks


def capture_source(
    *,
    source_id: str,
    season: int,
    store: MarketSnapshotStore,
    as_of: datetime | None = None,
    app: AppConfig | None = None,
    git_sha: str | None = None,
    identity: MarketIdentity | None = None,
    api_key: str | None = None,
    write: bool = True,
    pause_seconds: float = 1.5,
) -> SourceCaptureResult:
    """Retrieve every cohort for one source and append a snapshot. **Network I/O.**"""
    spec = spec_for(source_id)
    settings = app or load_app_config()
    stamped = (as_of or utc_now()).replace(microsecond=0)
    gate = QualityGate()
    resolved_identity = identity or load_market_identity(season, as_of=stamped)
    gate.extend(resolved_identity.checks)

    policy = settings.registry.source(source_id) if _has_policy(settings, source_id) else None
    budget = RequestBudget() if source_id == FANTASYPROS_SOURCE_ID else None

    raw_by_cohort: dict[str, Any] = {}
    bridge_ids: dict[str, dict[str, str]] = {}
    for index, cohort in enumerate(spec.cohorts):
        if index:
            time.sleep(pause_seconds)
        options: dict[str, Any] = {"cohort": cohort}
        if budget is not None:
            options["budget"] = budget
            options["api_key"] = api_key or ""
        config = SourceConfig(season=season, policy=policy, options=options)
        payload = _fetch_raw(spec=spec, cohort=cohort, config=config)
        raw_by_cohort[cohort.cohort_id] = payload
        bridge_ids.update(_bridge_ids(spec, payload))

    result = build_source_snapshot(
        spec=spec,
        season=season,
        retrieved_at=stamped,
        raw_by_cohort=raw_by_cohort,
        identity=resolved_identity,
        bridge_ids=bridge_ids,
        git_sha=git_sha,
        gate=gate,
    )
    if write:
        store.write(
            manifest=result.manifest,
            normalized_rows=result.rows,
            raw_payloads=result.raw_payloads,
        )
    return result


def _has_policy(settings: AppConfig, source_id: str) -> bool:
    try:
        settings.registry.source(source_id)
    except Exception:  # noqa: BLE001 - a source may not be in the registry yet
        return False
    return True


def _fetch_raw(
    *,
    spec: MarketSourceSpec,
    cohort: MarketCohort,
    config: SourceConfig,
) -> Any:
    """Retrieve one cohort's raw payload, preserving the envelope the manifest needs."""
    if spec.source_id == FFC_SOURCE_ID:
        from ffdraft.sources.ffc import _ffc_get  # noqa: PLC0415 - internal by design

        return _ffc_get(
            fmt=str(cohort.filters["format"]),
            season=config.season,
            cohort=cohort,
            config=config,
        )
    if spec.source_id == FANTASYPROS_SOURCE_ID:
        from ffdraft.sources.fantasypros import (  # noqa: PLC0415 - internal by design
            _fantasypros_get,
        )

        plan = CallPlan(cohort=cohort)
        merged: list[dict[str, Any]] = []
        envelope: dict[str, Any] = {}
        budget = config.options["budget"]
        for position in plan.positions:
            payload = _fantasypros_get(
                season=config.season,
                params=plan.params(position),
                api_key=str(config.options["api_key"]),
                budget=budget,
                config=config,
            )
            if isinstance(payload, Mapping):
                merged.extend(dict(row) for row in payload.get("players", []))
                if not envelope:
                    envelope = {k: v for k, v in payload.items() if not isinstance(v, list | dict)}
        return {"players": merged, **envelope}
    raise ValueError(f"no retrieval path for market source {spec.source_id!r}")


def _bridge_ids(spec: MarketSourceSpec, payload: Any) -> dict[str, dict[str, str]]:
    """Pull each row's bridge ids out of the raw payload, keyed by external id."""
    if spec.identity.alias_only or not isinstance(payload, Mapping):
        return {}
    out: dict[str, dict[str, str]] = {}
    for row in payload.get("players", []):
        if not isinstance(row, Mapping):
            continue
        external = row.get("player_id")
        if external is None:
            continue
        values = {
            field_name: str(row[field_name]).strip()
            for field_name, _ in spec.identity.bridges
            if row.get(field_name) not in (None, "")
        }
        if values:
            out[str(external)] = values
    return out
