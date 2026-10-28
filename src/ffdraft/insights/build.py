"""Build ``insights`` (ADR-116): facts → family detectors → wording → selection → records.

An enrichment: it runs after every other in-season artifact exists, reads them, and changes
none of them. A core input missing (season actuals or usage) withholds every story; an optional
input missing (ESPN, weekly projections, the official report, play-by-play, recent form)
withholds only the families and facts that depend on it, and the metadata says which and why.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import polars as pl

from ffdraft.config import ScoringPreset, ScoringRules
from ffdraft.contracts import QualityCheck
from ffdraft.contracts.enums import Severity
from ffdraft.insights.facts import SeasonFacts, build_facts
from ffdraft.insights.families import DETECTORS, Context, Draft
from ffdraft.insights.rules import (
    FAMILIES,
    INSIGHT_DEFINITIONS,
    INSIGHT_LIMITATIONS,
    INSIGHT_RULE,
    INSIGHTS_RULE_VERSION,
    SELECTION_RULE,
    SELECTION_RULE_VERSION,
    UNSUPPORTED_CLAIMS,
    InsightRule,
    SelectionRule,
)
from ffdraft.insights.select import select
from ffdraft.insights.text import render
from ffdraft.timeutil import isoformat_utc

__all__ = ["InsightsResult", "build_insights", "edition_of"]

#: Record fields in schema order.
FIELD_ORDER: tuple[str, ...] = (
    "schema_version",
    "build_id",
    "season",
    "through_week",
    "target_week",
    "edition",
    "scoring_preset",
    "scoring_dependent",
    "story_id",
    "family",
    "variant",
    "horizon",
    "nature",
    "lead_rank",
    "family_rank",
    "player_id",
    "display_name",
    "position",
    "team",
    "headline",
    "dek",
    "facts",
    "counterpoint",
    "caveat",
    "window",
    "kickoff_utc",
    "espn_rostered",
    "ceiling_ranks",
    "injury",
    "opponent",
    "home_away",
    "chart",
    "evidence",
    "qualification",
    "also_qualifies",
    "sources",
    "source_times",
)


@dataclass(slots=True)
class InsightsResult:
    records: list[dict[str, Any]]
    metadata: dict[str, Any]
    checks: list[QualityCheck] = field(default_factory=list)

    @property
    def published(self) -> bool:
        return self.metadata.get("status") == "published"


def edition_of(season: int, through_week: int) -> str:
    return f"{season}w{through_week:02d}"


def _by_player(
    rows: Sequence[Mapping[str, Any]], preset: str | None = None
) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if preset is not None and row.get("scoring_preset") != preset:
            continue
        out.setdefault(str(row["player_id"]), row)
    return out


def _by_team(rows: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(row["team"]): row for row in rows if row.get("team")}


def _withheld(base: dict[str, Any], reason: str) -> InsightsResult:
    families = {
        family: {
            "status": "unavailable",
            "reason": reason,
            "qualified": {},
            "published": {},
            "suppressed": {},
        }
        for family in FAMILIES
    }
    return InsightsResult(
        records=[],
        metadata={**base, "status": "withheld", "withheld_reason": reason, "families": families},
        checks=[
            QualityCheck.fail(
                "insights.withheld",
                stage="insights",
                message="Insights stories are withheld; every board, value and rank is unaffected",
                observed=reason,
                expected="season actuals and usage records",
                severity=Severity.WARNING,
            ),
        ],
    )


def build_insights(
    *,
    weekly: pl.DataFrame,
    snap_counts: pl.DataFrame,
    schedule: pl.DataFrame,
    scoring: Mapping[ScoringPreset, ScoringRules],
    season: int,
    through_week: int,
    records: Mapping[str, Sequence[Mapping[str, Any]]],
    plays: pl.DataFrame | None,
    plays_error: str | None,
    generated_at: datetime,
    build_id: str,
    schema_version: str,
    rule: InsightRule = INSIGHT_RULE,
    selection: SelectionRule = SELECTION_RULE,
) -> InsightsResult:
    """Every preset's stories, the lead selection, and the metadata block."""
    presets = sorted(str(preset) for preset in scoring)
    usage = list(records.get("player_usage", ()))
    actuals = list(records.get("season_actuals", ()))
    weekly_records = list(records.get("weekly_projections", ()))
    target_week = int(weekly_records[0]["target_week"]) if weekly_records else None
    edition = edition_of(season, int(through_week))
    base: dict[str, Any] = {
        "status": "published",
        "withheld_reason": None,
        "rule_version": INSIGHTS_RULE_VERSION,
        "selection_rule_version": SELECTION_RULE_VERSION,
        "edition": edition,
        "season": season,
        "through_week": int(through_week),
        "target_week": target_week,
        "generated_at_utc": isoformat_utc(generated_at),
        "window": None,
        "rule": rule.to_dict(),
        "selection": selection.to_dict(),
        "families": {},
        "sources": {},
        "counts": {preset: {"stories": 0, "lead": 0} for preset in presets},
        "definitions": dict(INSIGHT_DEFINITIONS),
        "limitations": list(INSIGHT_LIMITATIONS),
        "unsupported": [{"claim": claim, "reason": reason} for claim, reason in UNSUPPORTED_CLAIMS],
    }
    if not actuals:
        return _withheld(
            base, "season actuals are withheld for this build, and every story's cohort is theirs"
        )
    if not usage:
        return _withheld(
            base, "no usage records were published, so no story has a player a card can open"
        )

    positions: dict[str, str] = {}
    names: dict[str, str] = {}
    for row in actuals:
        positions.setdefault(str(row["player_id"]), str(row["position"]))
        if row.get("display_name"):
            names.setdefault(str(row["player_id"]), str(row["display_name"]))
    for row in usage:
        if row.get("display_name"):
            names[str(row["player_id"])] = str(row["display_name"])
    facts = build_facts(
        weekly=weekly,
        snap_counts=snap_counts,
        schedule=schedule,
        scoring=scoring,
        season=season,
        through_week=through_week,
        positions=positions,
        plays=plays,
        window_size=rule.window_weeks,
        red_zone_yardline=rule.red_zone_yardline,
        inside_five_yardline=rule.inside_five_yardline,
    )
    if not facts.window:
        return _withheld(base, "no completed regular-season week through the cutoff")
    if plays is None and plays_error:
        facts.pbp_detail = plays_error
    base["window"] = {
        "first_week": facts.window[0],
        "last_week": facts.window[-1],
        "weeks": len(facts.window),
        "baseline_first_week": facts.baseline[0] if facts.baseline else None,
        "baseline_last_week": facts.baseline[-1] if facts.baseline else None,
    }

    espn_rows = list(records.get("espn_ownership", ()))
    recent_rows = list(records.get("recent_form", ()))
    context_rows = list(records.get("weekly_context", ()))
    sources = _sources(facts, espn_rows, weekly_records, recent_rows, context_rows)
    unavailable = _unavailable_families(sources, target_week)

    subjects = _by_player(usage)
    board = _by_player(list(records.get("inseason_opportunity", ())))
    team_context = _by_team(context_rows)
    matchups = _by_team(list(records.get("team_matchups", ())))
    espn = _by_player(espn_rows) if espn_rows else None

    checks: list[QualityCheck] = []
    out: list[dict[str, Any]] = []
    qualified: dict[str, Counter[str]] = {family: Counter() for family in FAMILIES}
    published: dict[str, Counter[str]] = {family: Counter() for family in FAMILIES}
    suppressed: dict[str, Counter[str]] = {family: Counter() for family in FAMILIES}
    failed: dict[str, str] = {}
    shared: dict[str, tuple[list[Draft], Counter[tuple[str, str]]]] = {}
    # Phase 1: every family in every preset. A family that fails in any preset is dropped from
    # all of them, so no preset publishes stories of a family the metadata calls unavailable.
    found_by_preset: dict[str, dict[str, list[Draft]]] = {}
    for preset in presets:
        ctx = Context(
            facts=facts,
            rule=rule,
            preset=preset,
            subjects=subjects,
            names=names,
            actuals=_by_player(actuals, preset),
            recent=_by_player(recent_rows, preset),
            weekly=_by_player(weekly_records, preset),
            team_context=team_context,
            matchups=matchups,
            espn=espn,
            board=board,
            generated_at=generated_at,
            target_week=target_week,
        )
        found_by_preset[preset] = {}
        for family in FAMILIES:
            if family in unavailable or family in failed:
                continue
            if family == "role_battle" and family in shared:
                # Scoring-independent: built once, published identically in every preset; its
                # refusals are counted once per preset, like every other family's.
                found, refusals = shared[family]
                ctx.suppressed.update(refusals)
            else:
                before = Counter(ctx.suppressed)
                try:
                    found = DETECTORS[family](ctx)
                except Exception as exc:  # noqa: BLE001 - a family's failure costs that family
                    failed[family] = f"{type(exc).__name__}: {exc}"
                    checks.append(
                        QualityCheck.fail(
                            "insights.family_failed",
                            stage="insights",
                            message=(
                                f"the {family} stories could not be built; every other family "
                                "is unaffected"
                            ),
                            observed=failed[family],
                            expected="a detector that completes",
                            severity=Severity.WARNING,
                        ),
                    )
                    continue
                if family == "role_battle":
                    shared[family] = (found, ctx.suppressed - before)
            found_by_preset[preset][family] = found
            qualified[family][preset] = len(found)
        for (family, why), number in ctx.suppressed.items():
            suppressed[family][why] += number

    # Phase 2: selection and records, per preset, over the families that held everywhere.
    for preset in presets:
        drafts = {
            family: found
            for family, found in found_by_preset[preset].items()
            if family not in failed
        }
        chosen = select(drafts, rule=rule, selection=selection)
        for (family, why), number in chosen.suppressed.items():
            suppressed[family][why] += number
        for draft in chosen.stories:
            out.append(
                _record(
                    draft,
                    preset=preset,
                    season=season,
                    through_week=int(through_week),
                    edition=edition,
                    build_id=build_id,
                    schema_version=schema_version,
                    lead_rank=chosen.lead_rank.get(draft.story_id),
                    also=chosen.also.get(draft.story_id, []),
                    name=names.get(draft.player_id, draft.player_id),
                ),
            )
            published[draft.family][preset] += 1
        base["counts"][preset] = {
            "stories": len(chosen.stories),
            "lead": len(chosen.lead_rank),
        }
    for family in failed:
        qualified[family].clear()
        suppressed[family].clear()

    families: dict[str, Any] = {}
    for family in FAMILIES:
        reason: str | None
        if family in unavailable or family in failed:
            status, reason = "unavailable", unavailable.get(family) or failed.get(family)
        elif sum(published[family].values()) == 0:
            status = "empty"
            reason = (
                "every qualifying player already leads a story in a higher-priority family"
                if sum(qualified[family].values())
                else "no player met this family's rule in this build"
            )
        else:
            status, reason = "published", None
        if (
            family == "opportunity_opening"
            and status != "unavailable"
            and sources["official_injury_report"]["state"] != "available"
        ):
            reason = "observed openings only: the target week's official report is not available"
        families[family] = {
            "status": status,
            "reason": reason,
            "qualified": dict(sorted(qualified[family].items())),
            "published": dict(sorted(published[family].items())),
            "suppressed": dict(sorted(suppressed[family].items())),
        }
    metadata = {**base, "families": families, "sources": sources}
    checks.append(
        QualityCheck.ok(
            "insights.published",
            stage="insights",
            message=(
                f"{len(out)} stories across {len(presets)} presets, edition {edition}; "
                + ", ".join(f"{family} {families[family]['status']}" for family in FAMILIES)
            ),
        ),
    )
    return InsightsResult(records=out, metadata=metadata, checks=checks)


def _sources(
    facts: SeasonFacts,
    espn_rows: Sequence[Mapping[str, Any]],
    weekly_records: Sequence[Mapping[str, Any]],
    recent_rows: Sequence[Mapping[str, Any]],
    context_rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    observed = sum(1 for row in espn_rows if row.get("reading_state") == "observed")
    reports = [row for row in context_rows if (row.get("lineup") or {}).get("report_available")]
    return {
        "nflverse_player_stats": {"state": "available", "detail": None},
        "nflverse_pbp": {"state": facts.pbp_state, "detail": facts.pbp_detail},
        "season_actuals": {"state": "available", "detail": None},
        "recent_form": {
            "state": "available" if recent_rows else "unavailable",
            "detail": None if recent_rows else "recent form is withheld for this build",
        },
        "weekly_projections": {
            "state": "available" if weekly_records else "unavailable",
            "detail": None
            if weekly_records
            else "the weekly start/sit layer is withheld for this build",
        },
        "official_injury_report": {
            "state": "available" if reports else "unavailable",
            "detail": (
                f"{len(reports)} of {len(context_rows)} teams' reports available"
                if context_rows
                else "no weekly game context for the target week"
            ),
        },
        "espn_fantasy_ownership": {
            "state": "available" if observed else "unavailable",
            "detail": (
                f"{observed} of {len(espn_rows)} published players observed"
                if espn_rows
                else "ESPN readings are not published for this build"
            ),
        },
    }


def _unavailable_families(
    sources: Mapping[str, Mapping[str, Any]], target_week: int | None
) -> dict[str, str]:
    out: dict[str, str] = {}
    if sources["weekly_projections"]["state"] != "available" or target_week is None:
        out["weekly_upside"] = "weekly projections are not available for this build"
    elif sources["espn_fantasy_ownership"]["state"] != "available":
        out["weekly_upside"] = (
            "ESPN roster readings are not available, so no roster ceiling can be applied"
        )
    if sources["recent_form"]["state"] != "available":
        out["streak_watch"] = "recent form is withheld for this build"
    return out


def _record(
    draft: Draft,
    *,
    preset: str,
    season: int,
    through_week: int,
    edition: str,
    build_id: str,
    schema_version: str,
    lead_rank: int | None,
    also: Sequence[str],
    name: str,
) -> dict[str, Any]:
    text = render(draft.family, draft.variant, draft.evidence)
    record: dict[str, Any] = {
        "schema_version": schema_version,
        "build_id": build_id,
        "season": season,
        "through_week": through_week,
        "target_week": draft.target_week,
        "edition": edition,
        "scoring_preset": preset,
        "scoring_dependent": draft.scoring_dependent,
        "story_id": draft.story_id,
        "family": draft.family,
        "variant": draft.variant,
        "horizon": draft.horizon,
        "nature": draft.nature,
        "lead_rank": lead_rank,
        "family_rank": draft.family_rank,
        "player_id": draft.player_id,
        "display_name": name,
        "position": draft.position,
        "team": draft.team,
        "headline": text["headline"],
        "dek": text["dek"],
        "facts": text["facts"],
        "counterpoint": text["counterpoint"],
        "caveat": text["caveat"],
        "window": draft.window,
        "kickoff_utc": draft.kickoff_utc,
        # Copies of three evidence values the feed slice needs without the evidence slice.
        "espn_rostered": draft.evidence.get("espn_rostered"),
        "ceiling_ranks": draft.evidence.get("ceiling_ranks")
        if draft.family == "weekly_upside"
        else None,
        "injury": draft.evidence.get("injury") if draft.horizon == "this_week" else None,
        "opponent": draft.evidence.get("opponent") if draft.horizon == "this_week" else None,
        "home_away": draft.evidence.get("home_away") if draft.horizon == "this_week" else None,
        "chart": draft.chart,
        "evidence": draft.evidence,
        "qualification": draft.qualification,
        "also_qualifies": sorted(set(also)),
        "sources": list(dict.fromkeys(draft.sources)),
        "source_times": {key: value for key, value in draft.source_times.items()},
    }
    return {key: record[key] for key in FIELD_ORDER}
