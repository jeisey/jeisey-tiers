"""Source-relative comparisons and the cross-market ADP diagnostic (Phase 10, ADR-065).

**Boundary module.** Consumes intrinsic outputs and market data; never the reverse.

Release 1 had one price and one gap. Release 2 has several, and the whole design problem is
resisting the urge to collapse them. `docs/RELEASE2_ROADMAP.md` 2.3 and 10.4 say it twice:
every component, transformation and timestamp must stay recoverable, and a consensus rank is
never an observed draft price.

So this module computes **one independent comparison per source**, using the same A0
quantities Phase 5 froze (`ffdraft.arbitrage.baseline`, ADR-040) rather than a new formula:

    rank_gap            = market_adp - fair_rank
    regional_value_gap  = ln(market_adp / fair_rank)

and then a cross-market summary that is explicitly a **convenience**, not a price:

    market_adp_min / max / median, market_disagreement_range,
    cheapest_market_source, most_expensive_market_source, sources_available

Three rules hold the shape together, and each is enforced rather than documented:

1. **ECR is excluded from every ADP aggregate.** :func:`cross_market_summary` filters on
   :class:`~ffdraft.contracts.enums.MarketSignalType`, and :func:`ecr_comparison` produces a
   separate object with its own field names. There is no code path that can put an expert
   rank into ``market_adp_median``.
2. **A source ADP keeps its source identity.** Comparisons are keyed by ``source_id`` all
   the way to the artifact; nothing is averaged into an unattributed number.
3. **The median is not promoted.** It is computed, published and labelled a summary. Making
   it the canonical price would need a frozen methodology version first, and roadmap 10.4
   says so explicitly.

An ECR comparison uses the same ``fair_rank`` on the other side, but its gap answers a
different question — *how far is the model from the experts* rather than *how far is the
model from the price* — so it is named ``ecr_gap`` and never enters ``rank_gap``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ffdraft.arbitrage.baseline import rank_gap, regional_value_gap
from ffdraft.contracts.enums import MarketSignalType

__all__ = [
    "COMPARISON_METHOD_VERSION",
    "CrossMarketSummary",
    "EcrComparison",
    "SourceComparison",
    "SourceQuote",
    "cross_market_summary",
    "ecr_comparison",
    "source_comparison",
    "source_comparisons",
]

#: Bumped when the meaning of a published comparison field changes. The comparison reuses
#: A0's arithmetic unchanged, so this version tracks the *multi-source layer* around it -
#: which sources participate, how the summary is computed - rather than the gap formula.
COMPARISON_METHOD_VERSION = "phase10_multimarket_v1"

_GAP_PRECISION = 2
_LOG_PRECISION = 6


@dataclass(frozen=True, slots=True)
class SourceQuote:
    """One source's reading for one player, whatever kind of reading it is.

    Deliberately flat and source-agnostic: the differences between sources live in the
    fields that are *populated*, not in three parallel types. FFC fills ``adp_sd`` and
    leaves ``league_size`` null; MFL fills ``adp_low``/``adp_high`` and leaves ``adp_sd``
    null; FantasyPros fills ``market_rank`` and ``consensus_rank_*`` and leaves
    ``market_adp`` null. A reader can tell which source a row came from by asking, rather
    than by having been told.
    """

    source_id: str
    signal_type: MarketSignalType
    player_id: str
    scoring_preset: str
    market_adp: float | None = None
    market_rank: int | None = None
    sample_size: int | None = None
    adp_sd: float | None = None
    adp_low: float | None = None
    adp_high: float | None = None
    consensus_rank_mean: float | None = None
    consensus_rank_min: int | None = None
    consensus_rank_max: int | None = None
    consensus_rank_sd: float | None = None
    league_size: int | None = None
    aggregation_window_type: str = ""
    aggregation_window_days: int | None = None
    cohort_id: str = ""
    cohort_detail: str = ""
    snapshot_at_utc: str = ""
    market_trend: float | None = None
    quality_flags: tuple[str, ...] = ()

    @property
    def is_adp(self) -> bool:
        return self.signal_type is MarketSignalType.ADP

    @property
    def is_ecr(self) -> bool:
        return self.signal_type is MarketSignalType.ECR


@dataclass(frozen=True, slots=True)
class SourceComparison:
    """One ADP source's comparison against intrinsic fair rank."""

    source_id: str
    player_id: str
    fair_rank: int
    market_adp: float
    rank_gap: float
    regional_value_gap: float
    market_rank: int | None
    sample_size: int | None
    adp_sd: float | None
    adp_low: float | None
    adp_high: float | None
    league_size: int | None
    aggregation_window_type: str
    aggregation_window_days: int | None
    cohort_id: str
    cohort_detail: str
    snapshot_at_utc: str
    market_trend: float | None
    quality_flags: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "market_signal_type": str(MarketSignalType.ADP),
            "market_adp": self.market_adp,
            "market_rank": self.market_rank,
            "rank_gap": self.rank_gap,
            "regional_value_gap": self.regional_value_gap,
            "market_sample_size": self.sample_size,
            "market_adp_sd": self.adp_sd,
            "market_adp_low": self.adp_low,
            "market_adp_high": self.adp_high,
            "league_size": self.league_size,
            "aggregation_window_type": self.aggregation_window_type,
            "aggregation_window_days": self.aggregation_window_days,
            "market_cohort_id": self.cohort_id,
            "market_cohort_detail": self.cohort_detail,
            "market_snapshot_at_utc": self.snapshot_at_utc,
            "market_trend": self.market_trend,
            "quality_flags": list(self.quality_flags),
        }


@dataclass(frozen=True, slots=True)
class EcrComparison:
    """An expert-consensus comparison. **Not a price, and never in an ADP aggregate.**

    The field is called ``ecr_gap`` rather than ``rank_gap`` so that a caller who reaches
    for the wrong one gets an ``AttributeError`` instead of a plausible number.
    """

    source_id: str
    player_id: str
    fair_rank: int
    ecr: int
    ecr_gap: float
    consensus_rank_mean: float | None
    consensus_rank_min: int | None
    consensus_rank_max: int | None
    consensus_rank_sd: float | None
    expert_count: int | None
    cohort_id: str
    snapshot_at_utc: str
    quality_flags: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "market_signal_type": str(MarketSignalType.ECR),
            "ecr": self.ecr,
            "ecr_gap": self.ecr_gap,
            "consensus_rank_mean": self.consensus_rank_mean,
            "consensus_rank_min": self.consensus_rank_min,
            "consensus_rank_max": self.consensus_rank_max,
            "consensus_rank_sd": self.consensus_rank_sd,
            "expert_count": self.expert_count,
            "market_cohort_id": self.cohort_id,
            "market_snapshot_at_utc": self.snapshot_at_utc,
            "quality_flags": list(self.quality_flags),
        }


@dataclass(frozen=True, slots=True)
class CrossMarketSummary:
    """Where the ADP sources agree and disagree. **A summary, never a canonical price.**

    ``market_adp_median`` exists because a reader asked "roughly what does the market
    think", and it is safe only as long as nothing downstream treats it as *the* price.
    The sources describe different populations over different windows — FFC's rolling week
    against MyFantasyLeague's whole season — so a median across them is a convenience with
    a caveat attached, and roadmap 10.4 requires a separate frozen methodology before it
    could ever become canonical.

    ``market_disagreement_range`` is the interesting number: it is the thing a
    single-source board could not tell you.
    """

    player_id: str
    sources_available: tuple[str, ...]
    market_adp_min: float | None
    market_adp_max: float | None
    market_adp_median: float | None
    market_disagreement_range: float | None
    cheapest_market_source: str | None
    most_expensive_market_source: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sources_available": list(self.sources_available),
            "market_adp_min": self.market_adp_min,
            "market_adp_max": self.market_adp_max,
            "market_adp_median": self.market_adp_median,
            "market_disagreement_range": self.market_disagreement_range,
            "cheapest_market_source": self.cheapest_market_source,
            "most_expensive_market_source": self.most_expensive_market_source,
        }


def source_comparison(quote: SourceQuote, *, fair_rank: int) -> SourceComparison | None:
    """One ADP source against fair rank, or ``None`` when the quote is not a price.

    Returning ``None`` for an ECR quote rather than raising is deliberate: callers iterate
    over a player's whole quote set, and a mixed set is the normal case, not an error.
    """
    if not quote.is_adp or quote.market_adp is None or quote.market_adp <= 0:
        return None
    if fair_rank < 1:
        raise ValueError(f"fair_rank must be >= 1, got {fair_rank!r}")
    return SourceComparison(
        source_id=quote.source_id,
        player_id=quote.player_id,
        fair_rank=fair_rank,
        market_adp=quote.market_adp,
        rank_gap=rank_gap(quote.market_adp, fair_rank),
        regional_value_gap=regional_value_gap(quote.market_adp, fair_rank),
        market_rank=quote.market_rank,
        sample_size=quote.sample_size,
        adp_sd=quote.adp_sd,
        adp_low=quote.adp_low,
        adp_high=quote.adp_high,
        league_size=quote.league_size,
        aggregation_window_type=quote.aggregation_window_type,
        aggregation_window_days=quote.aggregation_window_days,
        cohort_id=quote.cohort_id,
        cohort_detail=quote.cohort_detail,
        snapshot_at_utc=quote.snapshot_at_utc,
        market_trend=quote.market_trend,
        quality_flags=quote.quality_flags,
    )


def source_comparisons(
    quotes: Sequence[SourceQuote],
    *,
    fair_rank: int,
) -> dict[str, SourceComparison]:
    """Every ADP source's comparison for one player, keyed by source id."""
    out: dict[str, SourceComparison] = {}
    for quote in sorted(quotes, key=lambda q: q.source_id):
        comparison = source_comparison(quote, fair_rank=fair_rank)
        if comparison is not None:
            out[comparison.source_id] = comparison
    return out


def ecr_comparison(quote: SourceQuote, *, fair_rank: int) -> EcrComparison | None:
    """The expert-consensus comparison, or ``None`` when the quote is a price."""
    if not quote.is_ecr or quote.market_rank is None:
        return None
    if fair_rank < 1:
        raise ValueError(f"fair_rank must be >= 1, got {fair_rank!r}")
    return EcrComparison(
        source_id=quote.source_id,
        player_id=quote.player_id,
        fair_rank=fair_rank,
        ecr=quote.market_rank,
        # The same subtraction as `rank_gap`, on a different pair of quantities, under a
        # different name. Positive still means "the model likes him more than they do".
        ecr_gap=round(float(quote.market_rank) - float(fair_rank), _GAP_PRECISION),
        consensus_rank_mean=quote.consensus_rank_mean,
        consensus_rank_min=quote.consensus_rank_min,
        consensus_rank_max=quote.consensus_rank_max,
        consensus_rank_sd=quote.consensus_rank_sd,
        expert_count=quote.sample_size,
        cohort_id=quote.cohort_id,
        snapshot_at_utc=quote.snapshot_at_utc,
        quality_flags=quote.quality_flags,
    )


def cross_market_summary(
    quotes: Sequence[SourceQuote],
    *,
    player_id: str,
) -> CrossMarketSummary:
    """Summarise the **ADP** sources. ECR quotes are filtered out, not weighted down.

    Deterministic in the way a published number has to be: sources are ordered by id, so
    ``cheapest_market_source`` resolves a tie the same way on every run rather than by
    whichever source happened to be captured first.
    """
    prices = sorted(
        (
            (quote.source_id, float(quote.market_adp))
            for quote in quotes
            if quote.is_adp and quote.market_adp is not None and quote.market_adp > 0
        ),
        key=lambda item: (item[1], item[0]),
    )
    if not prices:
        return CrossMarketSummary(
            player_id=player_id,
            sources_available=(),
            market_adp_min=None,
            market_adp_max=None,
            market_adp_median=None,
            market_disagreement_range=None,
            cheapest_market_source=None,
            most_expensive_market_source=None,
        )

    values = [price for _, price in prices]
    lowest_source, lowest = prices[0]
    highest_source, highest = prices[-1]
    return CrossMarketSummary(
        player_id=player_id,
        sources_available=tuple(sorted(source_id for source_id, _ in prices)),
        market_adp_min=round(lowest, _GAP_PRECISION),
        market_adp_max=round(highest, _GAP_PRECISION),
        market_adp_median=round(_median(values), _GAP_PRECISION),
        market_disagreement_range=round(highest - lowest, _GAP_PRECISION),
        # "Cheapest" means the market where the player costs the *earliest* pick, which is
        # the smallest ADP. Naming it from the drafter's point of view rather than the
        # number's is the thing a reader gets wrong at a glance, so it is stated here.
        cheapest_market_source=highest_source,
        most_expensive_market_source=lowest_source,
    )


def _median(values: Sequence[float]) -> float:
    """The median, written out rather than imported.

    `statistics.median` would do, but the tie behaviour of an even-length list is exactly
    the kind of thing a published number should not inherit silently from a standard
    library the reader has to go and check.
    """
    ordered = sorted(values)
    count = len(ordered)
    middle = count // 2
    if count % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def regional_gap_from(market_adp: float, fair_rank: int) -> float:
    """Exposed for tests that pin the A0 identity across the multi-source layer."""
    return round(math.log(market_adp / fair_rank), _LOG_PRECISION)


def quotes_from_snapshot_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    scoring_preset: str,
    snapshot_at_utc: str,
    trends: Mapping[str, float | None] | None = None,
) -> dict[str, SourceQuote]:
    """Build quotes from one retained snapshot's resolved rows, keyed by player id.

    Only resolved player rows become quotes. An unresolved row stays in the snapshot as
    evidence and is excluded from public comparison until its identity is settled, which is
    roadmap 10.3's rule and Phase 5's behaviour unchanged.
    """
    trend_by_player = trends or {}
    out: dict[str, SourceQuote] = {}
    for row in rows:
        player_id = row.get("player_id")
        if not player_id:
            continue
        if str(row.get("scoring_preset") or "") != scoring_preset:
            continue
        signal = MarketSignalType(str(row.get("market_signal_type", MarketSignalType.ADP)))
        out[str(player_id)] = SourceQuote(
            source_id=str(row["source_id"]),
            signal_type=signal,
            player_id=str(player_id),
            scoring_preset=scoring_preset,
            market_adp=_float(row.get("average_pick")),
            market_rank=_int(row.get("market_rank")),
            sample_size=_int(row.get("sample_size")),
            adp_sd=_float(row.get("adp_sd")),
            adp_low=_float(row.get("min_pick")),
            adp_high=_float(row.get("max_pick")),
            consensus_rank_mean=_float(row.get("consensus_rank_mean")),
            consensus_rank_min=_int(row.get("consensus_rank_min")),
            consensus_rank_max=_int(row.get("consensus_rank_max")),
            consensus_rank_sd=_float(row.get("consensus_rank_sd")),
            league_size=_int(row.get("league_size")),
            aggregation_window_type=str(row.get("aggregation_window_type") or ""),
            aggregation_window_days=_int(row.get("aggregation_window_days")),
            cohort_id=str(row.get("cohort_id") or ""),
            cohort_detail=str(row.get("source_format_detail") or ""),
            snapshot_at_utc=snapshot_at_utc,
            market_trend=trend_by_player.get(str(player_id)),
            quality_flags=tuple(row.get("quality_flags") or ()),
        )
    return out


def _float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None
