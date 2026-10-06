"""Who employs a player *now*: one evidence-precedence rule, separate from identity (ADR-102).

Four questions used to be answered by one object, the target season's nflverse roster, and the
answers were wrong for exactly the players a manager most wants to find on a waiver wire:

* **catalog membership** — is this a real, verified NFL player the site may name?
* **current employment** — which club, if any, holds his contract today?
* **numerical model coverage** — does a validated model output exist for him?
* **decision eligibility** — can a decision surface recommend him this week?

`load_rosters(season)` lists the players a club holds this season. A player released in the
spring and unsigned since (Tyreek Hill, 2026) is not in it, and neither is one whose signing
the file has not caught up with (Joe Mixon, signed by Seattle on 2026-10-05). Building the
identity registry from that file alone made both of them unresolvable: their Sleeper add
counts — the fifth- and tenth-largest on the site's own feed — could not be joined, and no
status row could be written for either (ADR-102's trace).

This module separates the first two questions. The other two stay where they were: model
coverage is whether a board row exists, and eligibility is the availability policy's.

**Identity** comes from :func:`identity_spine`: the current roster, plus the previous
season's roster for players the current one does not list. The prior rows are stripped to
identity — ids, name, position, biography — with ``team``, ``status`` and depth nulled, so a
historical crosswalk can verify *who* a Sleeper record is but cannot say where he plays. Two
canonical players claiming one external id poison it (ADR-019), across seasons as within one.

**Employment** comes from :func:`resolve_employment`, in this order (``employment_evidence_v1``):

1. The current-season nflverse roster names him on a club with a code other than ``CUT`` or
   ``RET`` → **signed**, that club, source ``nflverse_roster``. It is the official file and
   it wins; a fresh Sleeper record naming another club or none is recorded as a
   disagreement (``employment_sources_disagree``), not acted on.
2. The roster says ``RET`` → **retired**. Never catalogued as a free agent.
3. Otherwise (no current roster row, or ``CUT``) a Sleeper record no older than
   :data:`EMPLOYMENT_MAX_AGE_HOURS` at the build, joined nflverse-first through a verified,
   unpoisoned ``sleeper_id`` with Sleeper's own ``gsis_id`` agreeing where it reports one:
   a club → **signed**, source ``sleeper`` (a signing the roster file has not caught up
   with); no club and status ``Active`` → **unsigned**, source ``sleeper``.
4. Anything else — no current record, a stale feed, ``Inactive`` with no club, an identity
   refusal — is **unknown**. Unknown never prints as "FA".

Never evidence of current employment: nflverse's player master (``latest_team``,
``last_season``), a previous season's roster, a team at the season anchor, or the last club a
player appeared for. ``last_season < season`` is not evidence of retirement either; it is
how an unsigned veteran looks.

Annotation and eligibility only. Nothing here reaches a feature, a training population, a
projection, a VORP, a rank or a tier.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

import polars as pl

from ffdraft.contracts import (
    CORE_POSITIONS,
    PLAYER_STATUS_CONTRACT,
    Position,
    QualityCheck,
    ResolutionStatus,
)
from ffdraft.contracts.enums import Severity
from ffdraft.identity.ids import IdNamespace
from ffdraft.identity.registry import CanonicalRegistry, LookupStatus, build_registry
from ffdraft.identity.resolver import resolve_sleeper_status
from ffdraft.sources.nflverse import collided_gsis_ids
from ffdraft.status.capture import StatusCapture
from ffdraft.timeutil import isoformat_utc

__all__ = [
    "EMPLOYMENT_MAX_AGE_HOURS",
    "EMPLOYMENT_RULE_VERSION",
    "Employment",
    "EmploymentResult",
    "EmploymentSource",
    "EmploymentStatus",
    "build_identity_registry",
    "current_teams_with_employment",
    "employment_catalog",
    "employment_overlay",
    "identity_spine",
    "resolve_employment",
]

#: Bump when the precedence below changes meaning.
EMPLOYMENT_RULE_VERSION = "employment_evidence_v1"

#: A Sleeper record older than this at the build is not current employment evidence. The same
#: 48 hours the availability policy uses for status (ADR-101): one missed daily capture
#: degrades nothing, a second turns the reading into "unknown" rather than a stale "FA".
EMPLOYMENT_MAX_AGE_HOURS = 48.0

#: Roster codes that are not a current contract.
_RELEASED = "CUT"
_RETIRED = "RET"


class EmploymentStatus(StrEnum):
    SIGNED = "signed"
    UNSIGNED = "unsigned"
    RETIRED = "retired"
    UNKNOWN = "unknown"


class EmploymentSource(StrEnum):
    NFLVERSE_ROSTER = "nflverse_roster"
    SLEEPER = "sleeper"


@dataclass(frozen=True, slots=True)
class Employment:
    """One player's current employment reading and the evidence behind it."""

    player_id: str
    status: EmploymentStatus
    team: str | None
    source: EmploymentSource | None
    observed_at_utc: datetime | None
    #: The current-season roster code, when the roster has a row for him.
    roster_status: str | None = None
    #: A fresh Sleeper record disagrees with the official roster that decided the reading.
    sources_disagree: bool = False

    @property
    def unsigned(self) -> bool:
        return self.status is EmploymentStatus.UNSIGNED

    def to_record(self) -> dict[str, Any]:
        """The status artifact's employment fields (``player_status`` contract 1.2)."""
        return {
            "employment_status": str(self.status),
            "employment_source": None if self.source is None else str(self.source),
            "employment_observed_at_utc": (
                None if self.observed_at_utc is None else isoformat_utc(self.observed_at_utc)
            ),
        }


@dataclass(frozen=True)
class EmploymentResult:
    """Every reading the evidence supports, plus the counts a build log wants."""

    readings: Mapping[str, Employment]
    rule_version: str = EMPLOYMENT_RULE_VERSION
    sleeper_observed_at_utc: datetime | None = None
    sleeper_fresh: bool = False
    identity_refusals: int = 0
    ambiguous_ids: int = 0

    def get(self, player_id: str) -> Employment | None:
        return self.readings.get(player_id)

    def unsigned_players(self) -> list[str]:
        """Canonical ids verified unsigned."""
        return sorted(player_id for player_id, reading in self.readings.items() if reading.unsigned)

    def counts(self) -> dict[str, int]:
        counted: dict[str, int] = {str(status): 0 for status in EmploymentStatus}
        for reading in self.readings.values():
            counted[str(reading.status)] += 1
        counted["signed_by_sleeper_only"] = sum(
            1
            for reading in self.readings.values()
            if reading.status is EmploymentStatus.SIGNED
            and reading.source is EmploymentSource.SLEEPER
        )
        counted["sources_disagree"] = sum(
            1 for reading in self.readings.values() if reading.sources_disagree
        )
        return counted

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_version": self.rule_version,
            "sleeper_observed_at_utc": (
                None
                if self.sleeper_observed_at_utc is None
                else isoformat_utc(self.sleeper_observed_at_utc)
            ),
            "sleeper_fresh": self.sleeper_fresh,
            "max_age_hours": EMPLOYMENT_MAX_AGE_HOURS,
            "identity_refusals": self.identity_refusals,
            "ambiguous_ids": self.ambiguous_ids,
            "counts": self.counts(),
        }

    def check(self, *, stage: str) -> QualityCheck:
        counts = self.counts()
        observed = (
            f"{counts['signed']} signed ({counts['signed_by_sleeper_only']} on Sleeper evidence "
            f"only), {counts['unsigned']} verified unsigned, {counts['retired']} retired, "
            f"{counts['unknown']} unknown; {counts['sources_disagree']} disagreement(s), "
            f"{self.identity_refusals} identity refusal(s)"
        )
        if not self.sleeper_fresh:
            return QualityCheck.fail(
                "employment.sleeper_not_current",
                stage=stage,
                message=(
                    "no Sleeper record inside the freshness window, so no player off the "
                    "current roster can be called unsigned or newly signed; they read as "
                    f"unknown ({EMPLOYMENT_RULE_VERSION}, ADR-102)"
                ),
                observed=observed,
                expected=f"a capture no older than {EMPLOYMENT_MAX_AGE_HOURS:.0f}h",
                severity=Severity.WARNING,
            )
        return QualityCheck.ok(
            "employment.resolved",
            stage=stage,
            message=(
                "current employment from the season roster, then Sleeper "
                f"({EMPLOYMENT_RULE_VERSION}); a previous club is never a current one (ADR-102)"
            ),
            observed=observed,
        )


def identity_spine(
    current_roster: pl.DataFrame,
    prior_rosters: Iterable[pl.DataFrame | None] = (),
) -> pl.DataFrame:
    """One ``ROSTER_CONTRACT`` row per player: the current roster, then identity-only priors.

    The current roster keeps every row (the registry takes the first per player, sorted by
    team, which is the status artifact's existing choice). A prior-season row is added only
    for a player the current roster does not list, with every current-state column nulled:
    it can verify a crosswalk id, it cannot place him on a club.

    A GSIS id that names two different players in a prior roster is left out entirely, the
    same fail-closed rule the preseason universe applies (ADR-019).
    """
    frames: list[pl.DataFrame] = []
    columns = list(current_roster.columns) if not current_roster.is_empty() else None
    if not current_roster.is_empty():
        frames.append(current_roster)
    known = (
        set(current_roster.get_column("gsis_id").drop_nulls().to_list())
        if not current_roster.is_empty()
        else set()
    )
    for prior in prior_rosters:
        if prior is None or prior.is_empty() or "gsis_id" not in prior.columns:
            continue
        if columns is None:
            columns = list(prior.columns)
        poisoned = collided_gsis_ids(prior)
        identity = (
            prior.filter(
                pl.col("gsis_id").is_not_null()
                & ~pl.col("gsis_id").is_in(sorted(known | poisoned)),
            )
            .sort([name for name in ("gsis_id", "team") if name in prior.columns])
            .unique(subset=["gsis_id"], keep="first", maintain_order=True)
            .with_columns(
                *(
                    pl.lit(None, dtype=prior.schema[name]).alias(name)
                    for name in ("team", "status", "depth_chart_position")
                    if name in prior.columns
                ),
            )
        )
        if identity.is_empty():
            continue
        frames.append(identity.select(columns))
        known |= set(identity.get_column("gsis_id").to_list())
    if not frames:
        return current_roster
    return pl.concat(frames, how="vertical")


def _current_roster_rows(roster: pl.DataFrame) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = {}
    if roster.is_empty() or "gsis_id" not in roster.columns:
        return rows
    ordered = roster.sort([name for name in ("gsis_id", "team") if name in roster.columns])
    for row in ordered.iter_rows(named=True):
        gsis = row.get("gsis_id")
        if gsis:
            rows.setdefault(f"gsis:{gsis}", []).append(dict(row))
    return rows


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def resolve_employment(
    *,
    registry: CanonicalRegistry,
    current_roster: pl.DataFrame,
    capture: StatusCapture | None,
    as_of: datetime,
    positions: Iterable[Position] | None = None,
    max_age_hours: float = EMPLOYMENT_MAX_AGE_HOURS,
) -> EmploymentResult:
    """Apply ``employment_evidence_v1`` to every registry player at the given positions.

    ``registry`` should be built from :func:`identity_spine`, so a player the current roster
    omits can still be identified. The Sleeper join is nflverse-first and fails closed: a
    ``sleeper_id`` two canonical players claim, or a record whose own ``gsis_id`` contradicts
    the canonical one, reaches nobody.
    """
    wanted = tuple(positions) if positions is not None else tuple(CORE_POSITIONS)
    roster_rows = _current_roster_rows(current_roster)

    sleeper_by_player: dict[str, Mapping[str, Any]] = {}
    observed: datetime | None = None
    fresh = False
    refusals = 0
    ambiguous = 0
    if capture is not None and capture.rows:
        observed = capture.observed_at_utc
        age_hours = (as_of - observed).total_seconds() / 3600.0
        # An hour of clock skew is tolerated; a capture from the future beyond that is not.
        fresh = -1.0 <= age_hours <= max_age_hours
        if fresh:
            frame = PLAYER_STATUS_CONTRACT.build(
                {**row, "observed_at_utc": capture.observed_at_utc} for row in capture.rows
            )
            by_external = {str(row["external_player_id"]): row for row in capture.rows}
            for outcome in resolve_sleeper_status(
                frame,
                registry=registry,
                source_id=capture.source_id,
                positions=wanted,
            ):
                if outcome.resolved and outcome.player_id:
                    row = by_external.get(outcome.external_player_id)
                    if row is not None:
                        sleeper_by_player[outcome.player_id] = row
                elif outcome.status is ResolutionStatus.AMBIGUOUS:
                    refusals += 1
            ambiguous = sum(
                1
                for player in registry.players.values()
                if player.crosswalk.sleeper_id
                and registry.lookup(IdNamespace.SLEEPER, player.crosswalk.sleeper_id).status
                is LookupStatus.AMBIGUOUS
            )

    readings: dict[str, Employment] = {}
    for player_id in registry.eligible_players(wanted):
        rows = roster_rows.get(player_id, [])
        sleeper = sleeper_by_player.get(player_id)
        sleeper_team = _text((sleeper or {}).get("team"))
        sleeper_status = _text((sleeper or {}).get("status"))
        employed = [row for row in rows if _text(row.get("status")) not in (_RELEASED, _RETIRED)]
        retired = any(_text(row.get("status")) == _RETIRED for row in rows)
        roster_code = _text(rows[0].get("status")) if rows else None

        if employed:
            first = employed[0]
            team = _text(first.get("team"))
            disagree = sleeper is not None and sleeper_team != team
            readings[player_id] = Employment(
                player_id=player_id,
                status=EmploymentStatus.SIGNED,
                team=team,
                source=EmploymentSource.NFLVERSE_ROSTER,
                observed_at_utc=as_of,
                roster_status=_text(first.get("status")),
                sources_disagree=disagree,
            )
        elif retired:
            readings[player_id] = Employment(
                player_id=player_id,
                status=EmploymentStatus.RETIRED,
                team=None,
                source=EmploymentSource.NFLVERSE_ROSTER,
                observed_at_utc=as_of,
                roster_status=_RETIRED,
            )
        elif sleeper is not None and sleeper_team is not None:
            readings[player_id] = Employment(
                player_id=player_id,
                status=EmploymentStatus.SIGNED,
                team=sleeper_team,
                source=EmploymentSource.SLEEPER,
                observed_at_utc=observed,
                roster_status=roster_code,
            )
        elif sleeper is not None and (sleeper_status or "").lower() == "active":
            readings[player_id] = Employment(
                player_id=player_id,
                status=EmploymentStatus.UNSIGNED,
                team=None,
                source=EmploymentSource.SLEEPER,
                observed_at_utc=observed,
                roster_status=roster_code,
            )
        else:
            readings[player_id] = Employment(
                player_id=player_id,
                status=EmploymentStatus.UNKNOWN,
                team=None,
                source=None,
                observed_at_utc=None,
                roster_status=roster_code,
            )
    return EmploymentResult(
        readings=readings,
        sleeper_observed_at_utc=observed,
        sleeper_fresh=fresh,
        identity_refusals=refusals,
        ambiguous_ids=ambiguous,
    )


def employment_catalog(employment: EmploymentResult) -> list[str]:
    """Players off the current roster whose employment the evidence settles (ADR-102).

    Verified unsigned, or signed on Sleeper evidence the roster file has not caught up with.
    Bounded by construction: identity from the current or previous season's roster, a core
    position, and a Sleeper record inside the freshness window that says ``Active`` or names
    a club. A player whose employment is unknown is not added; a retired one never is.
    """
    return sorted(
        player_id
        for player_id, reading in employment.readings.items()
        if reading.status is EmploymentStatus.UNSIGNED
        or (
            reading.status is EmploymentStatus.SIGNED and reading.source is EmploymentSource.SLEEPER
        )
    )


def employment_overlay(employment: EmploymentResult | None) -> dict[str, str | None]:
    """The clubs the employment reading settles for players *off* the current roster.

    ``None`` for verified unsigned and retired players (no current club), the new club for a
    signing only Sleeper has reported. Roster-signed players are deliberately absent: their
    club stays whatever the roster rule already says, including its refusal to pick one for a
    player the file lists on two clubs after a trade.
    """
    overlay: dict[str, str | None] = {}
    if employment is None:
        return overlay
    for player_id, reading in employment.readings.items():
        if reading.status in (EmploymentStatus.UNSIGNED, EmploymentStatus.RETIRED):
            overlay[player_id] = None
        elif (
            reading.status is EmploymentStatus.SIGNED
            and reading.source is EmploymentSource.SLEEPER
            and reading.team is not None
        ):
            overlay[player_id] = reading.team
    return overlay


def current_teams_with_employment(
    roster_teams: Mapping[str, str],
    employment: EmploymentResult | None,
) -> dict[str, str | None]:
    """``player_id -> current club``: the roster's answer with :func:`employment_overlay` on top.

    A verified-unsigned player maps to ``None`` *explicitly*, which callers must read as "no
    current club" rather than "unknown, fall back to the last club he played for".
    """
    return {**roster_teams, **employment_overlay(employment)}


def build_identity_registry(
    current_roster: pl.DataFrame,
    prior_rosters: Iterable[pl.DataFrame | None] = (),
) -> CanonicalRegistry:
    """The annotation-side registry over :func:`identity_spine`. Never the model's."""
    spine = identity_spine(current_roster, prior_rosters)
    return build_registry(spine) if not spine.is_empty() else build_registry(pl.DataFrame())
