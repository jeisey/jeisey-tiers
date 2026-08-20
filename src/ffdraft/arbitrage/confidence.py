"""The arbitrage confidence rubric: data quality, not prediction probability (ADR-041).

In baseline mode there is no fitted model, so ``confidence`` cannot mean "probability this
player is a bargain". It means something narrower and checkable: **how much the market price
on this row can be trusted as a description of the reader's league.**

The rubric is deterministic and evaluated in a fixed order, so exactly one clause decides
and Phase 6 can say which. Every clause that fired is returned alongside the label, which is
what makes a low-confidence row explainable rather than merely labelled.

Dispersion is deliberately absent from the tiers. ``adp_low``/``adp_high`` come from MFL's
``minPick``/``maxPick``, which are extreme order statistics: they widen as more drafts are
sampled. Using them as a confidence input would systematically punish the best-sampled
players. The range is published and flagged, and it does not move the tier.
"""

from __future__ import annotations

from dataclasses import dataclass

from ffdraft.arbitrage.frozen import ARBITRAGE_CONFIDENCE_VERSION
from ffdraft.contracts.enums import Confidence
from ffdraft.market.current import HIGH_SAMPLE_THRESHOLD, LOW_SAMPLE_THRESHOLD, MarketPrice

__all__ = [
    "CONFIDENCE_RUBRIC",
    "ConfidenceRubric",
    "ConfidenceVerdict",
    "assess",
]


@dataclass(frozen=True, slots=True)
class ConfidenceVerdict:
    """The label plus the clauses that produced it."""

    confidence: Confidence
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {"confidence": str(self.confidence), "reasons": list(self.reasons)}


@dataclass(frozen=True, slots=True)
class ConfidenceRubric:
    """The frozen rubric. A bound change is a new version with its own ADR."""

    version: str = ARBITRAGE_CONFIDENCE_VERSION
    low_sample: int = LOW_SAMPLE_THRESHOLD
    high_sample: int = HIGH_SAMPLE_THRESHOLD

    def assess(self, price: MarketPrice) -> ConfidenceVerdict:
        """Judge one price. Clauses are checked in order; the first band that fits wins."""
        if price.sample_size is None:
            return ConfidenceVerdict(
                Confidence.UNKNOWN,
                ("no market sample size published for this player",),
            )

        low_reasons: list[str] = []
        if not price.cohort_sufficient:
            low_reasons.append(
                f"cohort {price.cohort_id!r} failed the sufficiency rule (ADR-039)",
            )
        if price.sample_size < self.low_sample:
            low_reasons.append(
                f"only {price.sample_size} draft(s) priced this player (< {self.low_sample})",
            )
        if price.secondary_bridge_only:
            low_reasons.append("identity resolved through the secondary bridge only")
        if price.snapshot_stale:
            low_reasons.append("the market snapshot is older than the freshness budget")
        if low_reasons:
            return ConfidenceVerdict(Confidence.LOW, tuple(low_reasons))

        high_reasons: list[str] = []
        if not price.cohort_exact:
            high_reasons.append(
                f"cohort {price.cohort_id!r} is approximate for "
                f"{price.scoring_preset}/{price.league_size}-team (ADR-012)",
            )
        if price.sample_size < self.high_sample:
            high_reasons.append(
                f"{price.sample_size} draft(s) priced this player (< {self.high_sample})",
            )
        if high_reasons:
            return ConfidenceVerdict(Confidence.MEDIUM, tuple(high_reasons))

        return ConfidenceVerdict(
            Confidence.HIGH,
            (
                f"exact cohort for {price.scoring_preset}/{price.league_size}-team",
                f"{price.sample_size} draft(s) priced this player",
                "snapshot inside the freshness budget",
                "identity resolved through the primary bridge",
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "rubric_version": self.version,
            "meaning": "market-data quality, not a probability that the player is a bargain",
            "unknown": "no market sample size",
            "low": (
                "cohort failed the sufficiency rule, OR fewer than "
                f"{self.low_sample} drafts priced the player, OR identity resolved through "
                "the secondary bridge only, OR the snapshot is stale"
            ),
            "high": (
                "exact cohort for the preset AND at least "
                f"{self.high_sample} drafts priced the player AND a fresh snapshot AND "
                "primary-bridge identity"
            ),
            "medium": "everything else",
            "dispersion_excluded_because": (
                "minPick/maxPick are extreme order statistics that widen with sample size, "
                "so they are not comparable across players"
            ),
        }


CONFIDENCE_RUBRIC = ConfidenceRubric()


def assess(price: MarketPrice) -> ConfidenceVerdict:
    """Convenience wrapper over the production rubric."""
    return CONFIDENCE_RUBRIC.assess(price)
