"""The prospective holdout for ``weekly-startsit-v2`` (``frozen_v2.PROSPECTIVE_HOLDOUT``).

Judged only on what was retained before each kickoff, by production, after the freeze:

1. every retained shadow capture of the season is read (hash-verified);
2. for each ``(player, preset, game)`` the **last** row whose build time precedes the
   kickoff is kept (``last_refresh_before_kickoff_v1``); a row built after kickoff, or never
   retained, is not eligible — nothing is backfilled;
3. the row's outcome is joined from nflverse's weekly rows once the week is complete:
   points in the preset, for players who appeared (the target is points given an appearance);
4. until :data:`PROSPECTIVE_HOLDOUT`'s minimum evidence is met, only counts are reported;
   after it is, a look is taken (at most two), behind its own token, and the verdict is one of
   ``promote``, ``reject`` or ``insufficient_evidence``.

**When a look is due** (:func:`due_look`, ``prospective_looks_v1``; ADR-099). The frozen rule
names two moments and this module decides which one has arrived, so that a scheduled job
(``weekly-v2-prospective.yml``) can take each look the moment it is due and never at any
other time:

* the **first** look when the minimum evidence is first met and the season is not over;
* the **final** look once every week of the fantasy horizon is complete, unless the first
  look was decisive. The first look's 99% level is an interim boundary: a ``promote`` or
  ``reject`` there ends the evaluation, and ``insufficient_evidence`` leaves it to the final
  look. A minimum first met only when the season is already over is the final look alone.

Every look taken is recorded in the retained store (``capture.LOOK_SOURCE_ID``) before it is
reported, and a look already recorded is never taken again: the ledger, not the calendar or a
person's memory, is what makes "at most two" true.

**A complete week** (:func:`complete_weeks`, ``outcomes_complete_v1``) is one whose every
regular-season game kicked off more than six hours ago **and** whose outcomes have arrived:
nflverse's weekly stats and its snap counts each carry rows for every team that played. An
appearance is a stats row or an offensive snap, so a week read before its snap counts land
would silently drop the zero-point appearances; such a week waits for the next check.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import polars as pl

from ffdraft.modeling.holdout import HoldoutSealError
from ffdraft.timeutil import parse_utc
from ffdraft.weekly.distribution import grids_from_matrix, pairwise_matrix
from ffdraft.weekly.evaluate import pinball
from ffdraft.weekly.frozen import DECISION_POOL_DEPTH, WEEKLY_QUANTILE_LEVELS, WEEKLY_SEED
from ffdraft.weekly.frozen_v2 import (
    PROMOTION_RULE_V2,
    PROSPECTIVE_HOLDOUT,
    WEEKLY_V2_FROZEN_AT_UTC,
    WEEKLY_V2_PROSPECTIVE_TOKEN,
)

__all__ = [
    "LOOKS",
    "complete_weeks",
    "due_look",
    "eligible_rows",
    "evidence_counts",
    "prospective_verdict",
]

#: The declared looks, in order.
LOOKS: tuple[str, ...] = ("first", "final")
#: A first look with one of these outcomes ends the evaluation.
_DECISIVE = frozenset({"promote", "reject"})
#: How long after a week's last kickoff its games are taken to be over.
_FINISHED_AFTER = timedelta(hours=6)


def complete_weeks(
    games: Sequence[tuple[int, datetime | None, str, str]],
    *,
    stats_teams: Mapping[int, set[str]],
    snap_teams: Mapping[int, set[str]],
    horizon_weeks: Sequence[int],
    now: datetime,
) -> tuple[list[int], bool]:
    """``(complete weeks, every horizon week complete)`` under ``outcomes_complete_v1``.

    ``games`` are the season's regular-season games as ``(week, kickoff, home, away)``;
    ``stats_teams`` and ``snap_teams`` map a week to the teams nflverse has published rows for.
    """
    kickoffs: dict[int, list[datetime | None]] = {}
    playing: dict[int, set[str]] = {}
    for week, kickoff, home, away in games:
        kickoffs.setdefault(int(week), []).append(kickoff)
        playing.setdefault(int(week), set()).update((home, away))
    complete = sorted(
        week
        for week, times in kickoffs.items()
        if all(time is not None and time + _FINISHED_AFTER < now for time in times)
        and playing[week] <= stats_teams.get(week, set())
        and playing[week] <= snap_teams.get(week, set())
    )
    season_over = bool(horizon_weeks) and all(week in complete for week in horizon_weeks)
    return complete, season_over


def due_look(
    counts: Mapping[str, Any],
    *,
    season_complete: bool,
    recorded: Mapping[str, Mapping[str, Any]],
) -> str | None:
    """Which declared look is due now, if any (``prospective_looks_v1``, module docstring).

    ``recorded`` maps a look already taken to its verdict.
    """
    if "final" in recorded:
        return None
    first = recorded.get("first")
    if first is not None and first.get("outcome") in _DECISIVE:
        return None
    if season_complete:
        return "final"
    if first is None and counts.get("minimum_met"):
        return "first"
    return None


_KEYS = [f"q{round(level * 100):02d}" for level in WEEKLY_QUANTILE_LEVELS]


def eligible_rows(
    shadow_rows: Sequence[Mapping[str, Any]],
    *,
    frozen_at: datetime,
) -> pl.DataFrame:
    """The last pregame shadow row per player, preset and game, after the freeze."""
    best: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for row in shadow_rows:
        kickoff = row.get("kickoff_utc")
        if kickoff is None or row.get("v1") is None or row.get("v2") is None:
            continue
        built = parse_utc(str(row["as_of_utc"]))
        kicked = parse_utc(str(kickoff))
        if built >= kicked or kicked <= frozen_at:
            continue
        key = (str(row["player_id"]), str(row["scoring_preset"]), str(row["game_id"]))
        held = best.get(key)
        if held is None or parse_utc(str(held["as_of_utc"])) < built:
            best[key] = row
    records = []
    for (player, preset, game_id), row in sorted(best.items()):
        record: dict[str, Any] = {
            "player_id": player,
            "gsis_id": row.get("gsis_id"),
            "scoring_preset": preset,
            "game_id": game_id,
            "season": int(row["season"]),
            "target_week": int(row["target_week"]),
            "position": row["position"],
            "as_of_utc": row["as_of_utc"],
            "kickoff_utc": row["kickoff_utc"],
            "b0": _b0(row),
        }
        for model in ("v1", "v2"):
            for level_key in _KEYS:
                record[f"{model}__{level_key}"] = float(row[model][level_key])
        records.append(record)
    return pl.DataFrame(records) if records else pl.DataFrame()


def _b0(row: Mapping[str, Any]) -> float:
    """The neutral B0 point that ranks v1's decision pools, from the retained inputs."""
    inputs = row.get("b0_inputs") or {}
    games = inputs.get("games_to_date") or 0
    if games and inputs.get("ppg_to_date") is not None:
        return float(inputs["ppg_to_date"])
    std, ppr = inputs.get("prev1_fantasy_ppg_std"), inputs.get("prev1_fantasy_ppg_ppr")
    preset = row.get("scoring_preset")
    prior = (
        std
        if preset == "STD"
        else ppr
        if preset == "PPR"
        else (None if std is None or ppr is None else (float(std) + float(ppr)) / 2.0)
    )
    return float(prior) if prior is not None else 0.0


def evidence_counts(scored: pl.DataFrame) -> dict[str, Any]:
    """Weeks, rows and decision-pool pairs held, and whether the minimum is met."""
    rule = PROSPECTIVE_HOLDOUT
    minimum = {"weeks": rule.min_weeks, "rows": rule.min_rows, "pairs": rule.min_pairs}
    if scored.is_empty():
        return {"weeks": 0, "rows": 0, "pairs": 0, "minimum": minimum, "minimum_met": False}
    pairs = 0
    for (_, _, position), block in scored.group_by("target_week", "scoring_preset", "position"):
        depth = int(DECISION_POOL_DEPTH[str(position)])
        n = min(depth, block.height)
        pairs += n * (n - 1) // 2
    weeks = scored.get_column("target_week").n_unique()
    return {
        "weeks": int(weeks),
        "rows": scored.height,
        "pairs": pairs,
        "minimum": minimum,
        "minimum_met": weeks >= rule.min_weeks
        and scored.height >= rule.min_rows
        and pairs >= rule.min_pairs,
    }


def _bootstrap(rows: pl.DataFrame, level: float) -> dict[str, float]:
    cluster = rows.get_column("target_week").to_numpy()
    difference = (rows.get_column("v1__pinball") - rows.get_column("v2__pinball")).to_numpy()
    unique, inverse = np.unique(cluster, return_inverse=True)
    sums = np.bincount(inverse, weights=difference)
    counts = np.bincount(inverse).astype(np.float64)
    rng = np.random.default_rng(WEEKLY_SEED)
    draws = np.empty(1000)
    for index in range(1000):
        pick = rng.integers(0, unique.shape[0], unique.shape[0])
        draws[index] = sums[pick].sum() / counts[pick].sum()
    tail = (1.0 - level) / 2.0
    return {
        "difference": float(sums.sum() / counts.sum()),
        "lower": float(np.quantile(draws, tail)),
        "upper": float(np.quantile(draws, 1.0 - tail)),
        "weeks": int(unique.shape[0]),
        "level": level,
    }


def _pairs(rows: pl.DataFrame, model: str) -> dict[str, float]:
    correct: list[float] = []
    brier: list[float] = []
    # Pools in key order and a stable sort, as in v1's evaluation: same pairs, same order,
    # the same float sums every run.
    groups = sorted(
        rows.group_by("target_week", "scoring_preset", "position"),
        key=lambda item: tuple(str(part) for part in item[0]),
    )
    for _, block in groups:
        depth = int(DECISION_POOL_DEPTH[str(block.get_column("position")[0])])
        pool = block.sort("b0", descending=True, maintain_order=True).head(depth)
        if pool.height < 2:
            continue
        matrix = pool.select([f"{model}__{key}" for key in _KEYS]).to_numpy()
        probability = pairwise_matrix(grids_from_matrix(matrix))
        median = matrix[:, _KEYS.index("q50")]
        actual = pool.get_column("actual").to_numpy()
        upper_i, upper_j = np.triu_indices(pool.height, k=1)
        outcome = np.where(
            actual[upper_i] > actual[upper_j],
            1.0,
            np.where(actual[upper_i] < actual[upper_j], 0.0, 0.5),
        )
        call = np.where(
            median[upper_i] > median[upper_j],
            1.0,
            np.where(median[upper_i] < median[upper_j], 0.0, 0.5),
        )
        decided = outcome != 0.5
        correct.extend((1.0 - np.abs(call - outcome))[decided].tolist())
        brier.extend(((probability[upper_i, upper_j] - outcome) ** 2).tolist())
    return {
        "accuracy": float(np.mean(correct)) if correct else math.nan,
        "brier": float(np.mean(brier)) if brier else math.nan,
        "pairs": len(brier),
    }


def prospective_verdict(
    scored: pl.DataFrame,
    *,
    look: str,
    confirmation: str | None,
) -> dict[str, Any]:
    """Apply ``weekly_promotion_v2`` at one declared look. ``scored`` carries ``actual``."""
    if look not in LOOKS:
        raise ValueError(f"look must be 'first' or 'final', not {look!r}")
    counts = evidence_counts(scored)
    if not counts["minimum_met"]:
        return {"outcome": "insufficient_evidence", "reason": "minimum evidence not met", **counts}
    if confirmation != WEEKLY_V2_PROSPECTIVE_TOKEN:
        raise HoldoutSealError(
            f"a prospective look needs the exact token {WEEKLY_V2_PROSPECTIVE_TOKEN!r}",
        )
    level = (
        PROSPECTIVE_HOLDOUT.first_look_level
        if look == "first"
        else PROSPECTIVE_HOLDOUT.final_look_level
    )
    actual = scored.get_column("actual").to_numpy()
    rows = scored
    for model in ("v1", "v2"):
        matrix = scored.select([f"{model}__{key}" for key in _KEYS]).to_numpy()
        rows = rows.with_columns(
            pl.Series(f"{model}__pinball", pinball(actual, matrix, list(WEEKLY_QUANTILE_LEVELS))),
            pl.Series(
                f"{model}__in80",
                (
                    (actual >= matrix[:, _KEYS.index("q10")])
                    & (actual <= matrix[:, _KEYS.index("q90")])
                ).astype(float),
            ),
        )
    interval = _bootstrap(rows, level)
    summary = {
        model: {
            "pinball": float(rows.get_column(f"{model}__pinball").mean()),  # type: ignore[arg-type]
            "coverage_80": float(rows.get_column(f"{model}__in80").mean()),  # type: ignore[arg-type]
            **_pairs(rows, model),
        }
        for model in ("v1", "v2")
    }
    rule = PROMOTION_RULE_V2
    v1, v2 = summary["v1"], summary["v2"]
    promote = (
        v2["pinball"] < v1["pinball"]
        and interval["lower"] > 0.0
        and rule.coverage_80_band[0] <= v2["coverage_80"] <= rule.coverage_80_band[1]
        and v2["brier"] <= v1["brier"] + rule.brier_tolerance
        and v2["accuracy"] >= v1["accuracy"] - rule.accuracy_tolerance
    )
    reject = (
        interval["upper"] < 0.0
        or not (rule.reject_coverage_band[0] <= v2["coverage_80"] <= rule.reject_coverage_band[1])
        or v2["brier"] > v1["brier"] + rule.reject_brier_margin
    )
    outcome = "promote" if promote else "reject" if reject else "insufficient_evidence"
    return {
        "outcome": outcome,
        "look": look,
        "interval": interval,
        "summary": summary,
        "frozen_at_utc": WEEKLY_V2_FROZEN_AT_UTC,
        **counts,
    }
