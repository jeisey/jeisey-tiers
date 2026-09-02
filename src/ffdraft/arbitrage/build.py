"""Building the current arbitrage board from published fair ranks and retained prices.

**Boundary module.** This is the *only* direction information is allowed to flow:

    intrinsic build -> tiers.json (fair rank, VORP)
                          |
    retained MFL snapshot -> canonical identity -> current market prices
                          |
                          +-> A0 -> arbitrage.json

Nothing here can reach back into an intrinsic feature, and nothing intrinsic imports it.

The build consumes the **published** tier artifact rather than re-running the model. That is
deliberate: it guarantees the two artifacts agree on `fair_rank` by construction (the
cross-artifact validator checks it anyway), and it means a market outage or a market bug can
never cause an intrinsic rebuild. A player with no market price simply has no arbitrage row.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ffdraft.arbitrage.baseline import signals_for_block
from ffdraft.arbitrage.confidence import CONFIDENCE_RUBRIC, ConfidenceVerdict
from ffdraft.arbitrage.frozen import ARBITRAGE_METHOD_VERSION, ARBITRAGE_MODE
from ffdraft.artifacts import record_schema_version
from ffdraft.contracts import QualityCheck, SurfaceReason
from ffdraft.contracts.enums import MarketSignalType, Severity
from ffdraft.market.comparison import (
    SourceQuote,
    cross_market_summary,
    ecr_comparison,
    source_comparisons,
)
from ffdraft.market.current import CurrentMarket
from ffdraft.market.surface import SurfaceUniverse
from ffdraft.quality import QualityGate
from ffdraft.quality.thresholds import (
    IDENTITY_COVERAGE_MINIMUM,
    TOP_OVERALL_RANKS,
)
from ffdraft.timeutil import isoformat_utc

__all__ = [
    "ArbitrageBuildResult",
    "build_arbitrage_records",
    "coverage_summary",
]

_ARBITRAGE_SCHEMA = "arbitrage_record"

#: Per-player quotes from the Phase-10 sources, keyed
#: ``source_id -> (scoring_preset, player_id) -> SourceQuote``.
ExtraQuotes = Mapping[str, Mapping[tuple[str, str], "SourceQuote"]]

#: One surfaced player who is outside the tier board but publicly relevant. Supplied by the
#: market pipeline from the surface universe, because the tier artifact by definition does
#: not contain him - which is the whole reason the blind spot existed (ADR-063).
SurfacedRow = Mapping[str, Any]

#: How much of the published top-150 board a critical build expects to be priced. Set to the
#: launch identity threshold: this is the same question - what share of the players a reader
#: will actually consider does the market layer have an opinion about - measured where it
#: matters most (`docs/DATA_CONTRACTS.md` 12).
TOP_BOARD_PRICED_MINIMUM = IDENTITY_COVERAGE_MINIMUM


@dataclass
class ArbitrageBuildResult:
    """The records, the coverage evidence and the gate one arbitrage build produced."""

    build_id: str
    season: int
    arbitrage_mode: str
    method_version: str
    records: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    confidence_counts: dict[str, int] = field(default_factory=dict)
    unpriced_top_players: list[dict[str, Any]] = field(default_factory=list)
    gate: QualityGate = field(default_factory=QualityGate)


def _blocks(
    tier_records: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str], list[Mapping[str, Any]]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for record in tier_records:
        key = (str(record["league_preset_id"]), str(record["scoring_preset"]))
        grouped.setdefault(key, []).append(record)
    return grouped


def build_arbitrage_records(
    tier_records: Sequence[Mapping[str, Any]],
    *,
    market: CurrentMarket,
    league_size_by_preset: Mapping[str, int],
    build_id: str,
    season: int,
    generated_at: datetime,
    gate: QualityGate | None = None,
    extra_quotes: ExtraQuotes | None = None,
    surfaces: Mapping[tuple[str, str], SurfaceUniverse] | None = None,
    surfaced_rows: Sequence[SurfacedRow] = (),
) -> ArbitrageBuildResult:
    """Compute A0 for every launch preset and assemble the public records.

    ``league_size_by_preset`` maps a league preset id to its team count, which is how a tier
    row finds the market cohort assigned to it. Passing it in rather than reading the league
    config here keeps this function pure and drivable from a fixture.

    The three Phase-10 arguments are all optional, and with none of them supplied this
    function produces exactly the Release 1 board plus the additive fields describing a
    single-source market. That is deliberate: an arbitrage build must keep working when the
    new sources are absent, stale or disabled, which is roadmap 10.1.3's noncritical-failure
    rule and the reason FantasyPros being unpublishable does not take the board down.

    ``surfaced_rows`` carries the players the surface universe admitted from *beyond* the
    tier depth. They cannot come from ``tier_records`` — the tier artifact does not contain
    them, which is precisely how the 300-row blind spot worked — so the market pipeline
    reads them from the intrinsic universe and passes them here (ADR-063).
    """
    checks = gate or QualityGate()
    result = ArbitrageBuildResult(
        build_id=build_id,
        season=season,
        arbitrage_mode=str(ARBITRAGE_MODE),
        method_version=ARBITRAGE_METHOD_VERSION,
        gate=checks,
    )
    schema_version = record_schema_version(_ARBITRAGE_SCHEMA)
    confidence_counts: dict[str, int] = {}
    per_block: list[dict[str, Any]] = []

    for (preset_id, scoring), rows in sorted(_blocks(tier_records).items()):
        league_size = league_size_by_preset.get(preset_id)
        if league_size is None:
            checks.add(
                QualityCheck.fail(
                    "arbitrage.unknown_league_preset",
                    stage="arbitrage.build",
                    message="a tier row names a league preset with no known team count",
                    observed=preset_id,
                    expected=", ".join(sorted(league_size_by_preset)),
                ),
            )
            continue

        surface = (surfaces or {}).get((preset_id, scoring))
        exceptions = [
            row
            for row in surfaced_rows
            if str(row.get("league_preset_id")) == preset_id
            and str(row.get("scoring_preset")) == scoring
        ]
        ordered = sorted(
            [*rows, *exceptions],
            key=lambda record: int(record["fair_rank"]),
        )
        priced: list[tuple[str, int, float]] = []
        prices = {}
        for record in ordered:
            player_id = str(record["player_id"])
            price = market.price(scoring, league_size, player_id)
            if price is None:
                continue
            prices[player_id] = price
            priced.append((player_id, int(record["fair_rank"]), price.market_adp))

        signals = signals_for_block(priced)
        for record in ordered:
            player_id = str(record["player_id"])
            signal = signals.get(player_id)
            if signal is None:
                continue
            price = prices[player_id]
            verdict: ConfidenceVerdict = CONFIDENCE_RUBRIC.assess(price)
            confidence_counts[str(verdict.confidence)] = (
                confidence_counts.get(str(verdict.confidence), 0) + 1
            )
            fair_rank = int(record["fair_rank"])
            quotes = _quotes_for(extra_quotes, scoring=scoring, player_id=player_id)
            # The MFL price is a quote like any other in the multi-source view. It is
            # reconstructed from the same `MarketPrice` the flat fields use, so the two can
            # never disagree about what MyFantasyLeague said.
            quotes.append(_quote_from_price(price, scoring=scoring))
            comparisons = source_comparisons(quotes, fair_rank=fair_rank)
            consensus = next(
                (
                    ecr_comparison(quote, fair_rank=fair_rank)
                    for quote in quotes
                    if quote.signal_type is MarketSignalType.ECR
                ),
                None,
            )
            entry = surface.entries.get(player_id) if surface else None
            result.records.append(
                {
                    "schema_version": schema_version,
                    "build_id": build_id,
                    "league_preset_id": preset_id,
                    "scoring_preset": scoring,
                    "player_id": player_id,
                    "display_name": str(record["display_name"]),
                    "team": record.get("team"),
                    "position": str(record["position"]),
                    "fair_rank": int(record["fair_rank"]),
                    "market_adp": price.market_adp,
                    "market_rank": price.market_rank,
                    "rank_gap": signal.rank_gap,
                    "regional_value_gap": signal.regional_value_gap,
                    "arbitrage_mode": str(ARBITRAGE_MODE),
                    "arbitrage_score": signal.arbitrage_score,
                    # ADR-010: baseline mode publishes no learned-model fields. Populating
                    # either would claim a model that was never trained.
                    "expected_surplus_vorp": None,
                    "p_positive_surplus": None,
                    "market_trend": price.market_trend,
                    "market_sample_size": price.sample_size,
                    # MFL publishes no standard deviation (docs/DATA_SOURCES.md 13.5).
                    "market_adp_sd": None,
                    "market_adp_low": price.adp_low,
                    "market_adp_high": price.adp_high,
                    "market_source_id": price.source_id,
                    "market_cohort_id": price.cohort_id,
                    "market_cohort_detail": price.cohort_detail,
                    "market_snapshot_at_utc": isoformat_utc(price.snapshot_at_utc),
                    "confidence": str(verdict.confidence),
                    "quality_flags": list(price.quality_flags),
                    # Additive, Phase 10. Every entry is an independent comparison against
                    # the same fair rank; nothing here is blended (roadmap 10.4).
                    "markets": [
                        comparisons[source_id].to_dict() for source_id in sorted(comparisons)
                    ],
                    # A ranking, never a price. Null when no consensus source is enabled.
                    "expert_consensus": consensus.to_dict() if consensus else None,
                    "cross_market": cross_market_summary(
                        quotes,
                        player_id=player_id,
                    ).to_dict(),
                    "surface_reasons": (
                        [str(reason) for reason in entry.reasons]
                        if entry
                        else [str(SurfaceReason.INTRINSIC_TOP_TIER_DEPTH)]
                    ),
                    "outside_tier_board": bool(entry.outside_tier_board) if entry else False,
                },
            )

        block_coverage = _block_coverage(ordered, prices)
        block_coverage.update({"league_preset_id": preset_id, "scoring_preset": scoring})
        per_block.append(block_coverage)
        result.unpriced_top_players.extend(
            {
                "league_preset_id": preset_id,
                "scoring_preset": scoring,
                "fair_rank": int(record["fair_rank"]),
                "player_id": str(record["player_id"]),
                "display_name": str(record["display_name"]),
                "position": str(record["position"]),
            }
            for record in ordered[:TOP_OVERALL_RANKS]
            if str(record["player_id"]) not in prices
        )

    result.confidence_counts = dict(sorted(confidence_counts.items()))
    result.coverage = coverage_summary(per_block)
    checks.extend(market.checks)
    checks.extend(_coverage_checks(result, per_block))
    checks.extend(_baseline_mode_checks(result.records))
    return result


def _quotes_for(
    extra: ExtraQuotes | None,
    *,
    scoring: str,
    player_id: str,
) -> list[SourceQuote]:
    if not extra:
        return []
    return [
        quote
        for source_id in sorted(extra)
        if (quote := extra[source_id].get((scoring, player_id))) is not None
    ]


def _quote_from_price(price: Any, *, scoring: str) -> SourceQuote:
    """The MyFantasyLeague price as a multi-source quote.

    Derived from the same object the flat 1.1 fields are written from, so the V1 surface and
    the V2 `markets` array are two views of one number rather than two numbers that have to
    be kept in step.
    """
    return SourceQuote(
        source_id=price.source_id,
        signal_type=MarketSignalType.ADP,
        player_id=price.player_id,
        scoring_preset=scoring,
        market_adp=price.market_adp,
        market_rank=price.market_rank,
        sample_size=price.sample_size,
        adp_sd=price.adp_sd,
        adp_low=price.adp_low,
        adp_high=price.adp_high,
        # The league size this quote was actually *observed* for, which is not the same as
        # the preset it is being shown under. `MarketPrice.league_size` is the preset's team
        # count; it is only an observation when the selection rule found an exact cohort
        # (ADR-039). An approximate cohort priced "any league size", so the column stays
        # null rather than borrowing the preset's number - the same refusal-to-claim that
        # makes FFC's league_size null, reached for a different reason.
        league_size=price.league_size if price.cohort_exact else None,
        # Phase 0 measured MFL's aggregate as season-cumulative; `DAYS` is ignored (ADR-010).
        aggregation_window_type="season_cumulative",
        aggregation_window_days=None,
        cohort_id=price.cohort_id,
        cohort_detail=price.cohort_detail,
        snapshot_at_utc=isoformat_utc(price.snapshot_at_utc),
        market_trend=price.market_trend,
        quality_flags=tuple(price.quality_flags),
    )


def _block_coverage(
    ordered: Sequence[Mapping[str, Any]],
    prices: Mapping[str, Any],
) -> dict[str, Any]:
    top = ordered[:TOP_OVERALL_RANKS]
    top100 = ordered[:100]
    return {
        "board_players": len(ordered),
        "priced_players": len(prices),
        "board_coverage": round(len(prices) / len(ordered), 4) if ordered else 0.0,
        "top100_priced": sum(1 for r in top100 if str(r["player_id"]) in prices),
        "top100_players": len(top100),
        "top150_priced": sum(1 for r in top if str(r["player_id"]) in prices),
        "top150_players": len(top),
        "top150_coverage": (
            round(sum(1 for r in top if str(r["player_id"]) in prices) / len(top), 4)
            if top
            else 0.0
        ),
    }


def coverage_summary(per_block: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate coverage across blocks, keeping the worst block visible.

    A mean would hide the case this gate exists to catch: eight healthy presets and one that
    lost its cohort. The minimum is what decides, and the per-block table is retained.
    """
    if not per_block:
        return {"blocks": [], "min_top150_coverage": 0.0, "min_board_coverage": 0.0}
    return {
        "blocks": [dict(block) for block in per_block],
        "min_top150_coverage": min(float(block["top150_coverage"]) for block in per_block),
        "min_board_coverage": min(float(block["board_coverage"]) for block in per_block),
        "total_priced_rows": sum(int(block["priced_players"]) for block in per_block),
    }


def _coverage_checks(
    result: ArbitrageBuildResult,
    per_block: Sequence[Mapping[str, Any]],
) -> list[QualityCheck]:
    checks: list[QualityCheck] = []
    if not per_block:
        return [
            QualityCheck.fail(
                "arbitrage.no_blocks",
                stage="arbitrage.build",
                message="no tier block produced an arbitrage board",
                observed="0 blocks",
                expected=">= 1",
            ),
        ]
    worst = float(result.coverage["min_top150_coverage"])
    checks.append(
        QualityCheck.fail(
            "arbitrage.top_board_priced",
            stage="arbitrage.build",
            message=("the market layer has no price for too much of the published top-150 board"),
            observed=f"worst block {worst:.1%}",
            expected=f">= {TOP_BOARD_PRICED_MINIMUM:.0%}",
        )
        if worst < TOP_BOARD_PRICED_MINIMUM
        else QualityCheck.ok(
            "arbitrage.top_board_priced",
            stage="arbitrage.build",
            message="every published block prices enough of its top-150 board",
            observed=f"worst block {worst:.1%}",
        ),
    )
    if result.unpriced_top_players:
        # Surfaced individually rather than averaged away: a missing price on a
        # first-round player is a different problem from one on the 149th.
        sample = "; ".join(
            f"{item['scoring_preset']}/{item['league_preset_id']} #{item['fair_rank']} "
            f"{item['display_name']}"
            for item in result.unpriced_top_players[:10]
        )
        checks.append(
            QualityCheck.fail(
                "arbitrage.unpriced_top_players",
                stage="arbitrage.build",
                message="top-150 board players with no market price are excluded, not filled in",
                observed=f"{len(result.unpriced_top_players)} row(s): {sample}",
                expected="0",
                severity=Severity.WARNING,
            ),
        )
    return checks


def _baseline_mode_checks(records: Sequence[Mapping[str, Any]]) -> list[QualityCheck]:
    """ADR-010, enforced at the point of production as well as at validation."""
    leaked = [
        str(record["player_id"])
        for record in records
        if record.get("expected_surplus_vorp") is not None
        or record.get("p_positive_surplus") is not None
    ]
    if leaked:
        return [
            QualityCheck.fail(
                "arbitrage.baseline_mode_ml_fields",
                stage="arbitrage.build",
                message="baseline mode must not publish learned-model fields (ADR-010)",
                observed="; ".join(leaked[:10]),
                expected="null expected_surplus_vorp and p_positive_surplus",
            ),
        ]
    return [
        QualityCheck.ok(
            "arbitrage.baseline_mode",
            stage="arbitrage.build",
            message=(
                "arbitrage_mode=baseline; no learned surplus or probability is published (ADR-010)"
            ),
            observed=f"{len(records)} record(s)",
        ),
    ]
