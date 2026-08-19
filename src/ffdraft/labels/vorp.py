"""Realized value-over-replacement labels.

One row per ``(season, player_id, scoring_preset, league_preset_id)``. The extra key is not
redundancy: replacement value depends on how many players a league starts, so the same 210
PPR points is a different amount of surplus in a 10-team league than in a 14-team one.

The allocation itself lives in :mod:`ffdraft.simulation.allocation`, unchanged, so the
realized label and the Phase-4 simulated VORP are computed by the same code. The only
difference is the points that go in: actual season totals here, Monte Carlo draws there.

**No market data touches this.** Replacement is derived from roster shape and realized
points alone, which is what makes realized VORP a legitimate intrinsic target and keeps the
later arbitrage surplus label - which *is* market-relative - a genuinely separate quantity
(`docs/MODELING.md` section 16).
"""

from __future__ import annotations

from collections.abc import Sequence

import polars as pl

from ffdraft.config import LeagueConfig, LeaguePreset
from ffdraft.features.dictionary import VORP_LABEL_CONTRACT
from ffdraft.simulation.allocation import PlayerPoints, vorp_for_players

__all__ = ["REPLACEMENT_UNAVAILABLE_FLAG", "build_vorp_labels", "vorp_for_one_group"]

#: Recorded when a position's pool was entirely consumed by starting slots, so no
#: replacement baseline exists and VORP is null rather than an invented zero.
REPLACEMENT_UNAVAILABLE_FLAG = "replacement_unavailable"


def vorp_for_one_group(
    rows: Sequence[dict[str, object]],
    preset: LeaguePreset,
) -> list[dict[str, object]]:
    """Compute VORP rows for one ``(season, scoring_preset)`` pool under one league preset."""
    players = [
        PlayerPoints(
            player_id=str(row["player_id"]),
            position=str(row["position"]),
            points=float(row["actual_fantasy_points"]),  # type: ignore[arg-type]
        )
        for row in rows
    ]
    allocation, vorp = vorp_for_players(players, preset)
    started = allocation.started_player_ids

    output: list[dict[str, object]] = []
    for row, player in zip(rows, players, strict=True):
        baseline = allocation.replacement_points.get(player.position)
        flags = "" if baseline is not None else REPLACEMENT_UNAVAILABLE_FLAG
        output.append(
            {
                "season": row["season"],
                "player_id": player.player_id,
                "scoring_preset": row["scoring_preset"],
                "league_preset_id": preset.preset_id,
                "position": player.position,
                "actual_fantasy_points": player.points,
                "replacement_points": baseline,
                "replacement_player_id": allocation.replacement_player_id.get(player.position),
                "actual_vorp": vorp[player.player_id],
                "actual_vorp_rank": None,
                "started_flag": player.player_id in started,
                "quality_flags": flags,
            },
        )
    return output


def build_vorp_labels(
    fantasy_labels: pl.DataFrame,
    league: LeagueConfig,
    *,
    preset_ids: Sequence[str] | None = None,
) -> pl.DataFrame:
    """Build realized VORP labels for every ``(season, scoring, league preset)`` combination.

    ``preset_ids`` defaults to the launch presets. Optional presets are supported but not
    built by default: each one multiplies the row count, and nothing before Phase 4 consumes
    them.
    """
    if fantasy_labels.is_empty():
        return VORP_LABEL_CONTRACT.empty()

    presets = [
        league.preset(preset_id)
        for preset_id in (preset_ids if preset_ids is not None else sorted(league.presets))
    ]

    rows: list[dict[str, object]] = []
    grouped = fantasy_labels.select(
        "season",
        "player_id",
        "scoring_preset",
        "position",
        "actual_fantasy_points",
    ).sort(["season", "scoring_preset", "player_id"])

    for (season, scoring_preset), group in grouped.group_by(
        ["season", "scoring_preset"],
        maintain_order=True,
    ):
        pool = group.to_dicts()
        for preset in presets:
            rows.extend(vorp_for_one_group(pool, preset))
        # `season`/`scoring_preset` are carried on each row already; the loop variables are
        # named for readability of the grouping, not used again.
        del season, scoring_preset

    if not rows:
        return VORP_LABEL_CONTRACT.empty()

    frame = VORP_LABEL_CONTRACT.coerce(pl.DataFrame(rows, orient="row"))
    ranked = frame.sort(
        ["season", "scoring_preset", "league_preset_id", "actual_vorp", "player_id"],
        descending=[False, False, False, True, False],
        nulls_last=True,
    ).with_columns(
        pl.when(pl.col("actual_vorp").is_not_null())
        .then(
            pl.int_range(1, pl.len() + 1).over(
                ["season", "scoring_preset", "league_preset_id"],
            ),
        )
        .otherwise(None)
        .cast(pl.Int32)
        .alias("actual_vorp_rank"),
    )
    return VORP_LABEL_CONTRACT.coerce(ranked).sort(
        ["season", "scoring_preset", "league_preset_id", "player_id"],
    )
