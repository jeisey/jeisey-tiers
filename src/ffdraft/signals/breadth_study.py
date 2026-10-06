"""The drive-breadth development study (ADR-103): coverage first, then a frozen evaluation.

Two phases, deliberately separate commands:

* ``coverage`` reads no outcome. It measures, per position and season, how many appearances
  the definitions reach, how often a window clears the provisional display minimums, how
  often a game saturates, and how the windowed gap is distributed. ADR-103 was frozen after
  this and before the next phase was run.
* ``evaluate`` runs the predeclared comparison: does adding the breadth gap to volume, share
  and role-change readings help anticipate a next-appearance opportunity drought, out of time,
  by position? Development seasons only (2020-2024): 2025 is the spent sealed season of this
  project's models (ADR-025, ADR-069) and is not read, and 2026 is the season being shown.

Nothing here feeds a model, a ranking, Pick of the Week or a trade search.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from statistics import median
from typing import Any

import polars as pl

from ffdraft.signals.breadth import (
    BREADTH_METHOD_VERSION,
    BREADTH_WINDOW_APPEARANCES,
    DISPLAY_MIN_APPEARANCES,
    DISPLAY_MIN_ELIGIBLE_DRIVES,
    DISPLAY_MIN_OPPORTUNITIES,
    GameBreadth,
    window_breadth,
)
from ffdraft.signals.drive_play import (
    BREADTH_POSITIONS,
    Appearance,
    drive_plays,
    game_breadths,
    position_map,
)

__all__ = [
    "DEVELOPMENT_SEASONS",
    "DROUGHT_FRACTION",
    "EVALUATION_SEED",
    "StudyInputs",
    "appearances_from",
    "coverage_report",
    "evaluation_report",
    "load_study_inputs",
]

#: Development seasons the study may read. 2025 is excluded on purpose (see module docstring).
DEVELOPMENT_SEASONS = (2020, 2021, 2022, 2023, 2024)

#: The predeclared outcome: the next appearance's opportunities fall below this fraction of
#: the window's per-appearance mean (ADR-103).
DROUGHT_FRACTION = 0.5

#: Rolling-origin test seasons; each is predicted from every development season before it.
TEST_SEASONS = (2022, 2023, 2024)

EVALUATION_SEED = 20261006
BOOTSTRAP_REPLICATES = 1000


@dataclass(frozen=True)
class StudyInputs:
    season: int
    plays: pl.DataFrame
    appearances: list[Appearance]
    positions: Mapping[tuple[int, str], str]


def appearances_from(
    season: int,
    *,
    stats: pl.DataFrame,
    snaps: pl.DataFrame,
    roster: pl.DataFrame,
) -> list[Appearance]:
    """Completed regular-season appearances: a stats row **or** an offensive snap (ADR-091).

    The snap file is keyed by Pro-Football-Reference id; it is bridged to GSIS through the
    season roster's own ``pfr_id`` (licensed nflverse data), never by name. Position is the
    season roster's: verified position evidence, not the stats file's label.
    """
    positions = position_map([roster])
    pfr_to_gsis = {
        str(pfr): str(gsis)
        for pfr, gsis in roster.select("pfr_id", "gsis_id").drop_nulls().unique().iter_rows()
    }
    seen: dict[tuple[int, str], str] = {}
    for week, gsis, team in (
        stats.filter((pl.col("season_type") == "REG") & pl.col("team").is_not_null())
        .select("week", "player_id", "team")
        .drop_nulls()
        .iter_rows()
    ):
        seen.setdefault((int(week), str(gsis)), str(team))
    for week, pfr, team, offense in (
        snaps.filter(pl.col("game_type") == "REG")
        .select("week", "pfr_player_id", "team", "offense_snaps")
        .drop_nulls()
        .iter_rows()
    ):
        gsis = pfr_to_gsis.get(str(pfr))
        if gsis is not None and float(offense) > 0:
            seen.setdefault((int(week), gsis), str(team))
    return [
        Appearance(season, week, gsis, team, positions[(season, gsis)])
        for (week, gsis), team in sorted(seen.items())
        if (season, gsis) in positions
    ]


def load_study_inputs(season: int, loaders: Any) -> StudyInputs:
    """One development season from the cached nflverse loaders, reduced immediately."""
    pbp = loaders.load_pbp(seasons=[season])
    plays = drive_plays(pbp if isinstance(pbp, pl.DataFrame) else pl.DataFrame(pbp))
    roster = loaders.load_rosters(seasons=[season])
    roster = roster if isinstance(roster, pl.DataFrame) else pl.DataFrame(roster)
    appearances = appearances_from(
        season,
        stats=loaders.load_player_stats(seasons=[season], summary_level="week"),
        snaps=loaders.load_snap_counts(seasons=[season]),
        roster=roster,
    )
    return StudyInputs(season, plays, appearances, position_map([roster]))


def _quantiles(values: Sequence[float]) -> dict[str, float] | None:
    if not values:
        return None
    ordered = sorted(values)

    def at(q: float) -> float:
        return round(ordered[min(len(ordered) - 1, int(q * (len(ordered) - 1) + 0.5))], 1)

    return {"p10": at(0.1), "p25": at(0.25), "p50": at(0.5), "p75": at(0.75), "p90": at(0.9)}


def _windows(games: Sequence[GameBreadth]) -> list[tuple[GameBreadth, Any, GameBreadth | None]]:
    """(window end, window reading, next appearance) for every appearance, within a season."""
    ordered = sorted(games, key=lambda game: (game.season, game.week))
    out = []
    for index, game in enumerate(ordered):
        same = [g for g in ordered[: index + 1] if g.season == game.season]
        following = ordered[index + 1] if index + 1 < len(ordered) else None
        nxt = following if following is not None and following.season == game.season else None
        out.append((game, window_breadth(same), nxt))
    return out


def coverage_report(inputs: Sequence[StudyInputs]) -> dict[str, Any]:
    """Phase 1: reach, display coverage, saturation and the gap's spread. No outcome is read."""
    report: dict[str, Any] = {
        "method_version": BREADTH_METHOD_VERSION,
        "window_appearances": BREADTH_WINDOW_APPEARANCES,
        "display_minimums": {
            "appearances": DISPLAY_MIN_APPEARANCES,
            "eligible_drives": DISPLAY_MIN_ELIGIBLE_DRIVES,
            "opportunities": DISPLAY_MIN_OPPORTUNITIES,
        },
        "seasons": {},
    }
    for season_inputs in inputs:
        games, diagnostics = game_breadths(
            season_inputs.plays,
            season_inputs.appearances,
            season_inputs.positions,
        )
        by_position: dict[str, dict[str, Any]] = {}
        for position in BREADTH_POSITIONS:
            ids = {
                f"gsis:{a.player_id}" for a in season_inputs.appearances if a.position == position
            }
            player_games = [g for pid in ids for g in games.get(pid, [])]
            windows = [w for pid in ids for _, w, _ in _windows(games.get(pid, []))]
            shown = [w for w in windows if w.displayable]
            saturated = sum(
                1
                for g in player_games
                if g.opportunities > 0 and g.expected_drives >= g.eligible_drives - 1e-9
            )
            reasons: dict[str, int] = {}
            for w in windows:
                if w.withheld_reason:
                    reasons[w.withheld_reason] = reasons.get(w.withheld_reason, 0) + 1
            by_position[position] = {
                "players": len(ids),
                "appearances": len(player_games),
                "appearances_with_zero_opportunities": sum(
                    1 for g in player_games if g.opportunities == 0
                ),
                "median_eligible_drives_per_game": (
                    median([g.eligible_drives for g in player_games]) if player_games else None
                ),
                "median_opportunities_per_game": (
                    median([g.opportunities for g in player_games]) if player_games else None
                ),
                "saturated_games": saturated,
                "windows": len(windows),
                "windows_displayable": len(shown),
                "displayable_share": round(len(shown) / len(windows), 3) if windows else None,
                "withheld": reasons,
                "gap_pp_displayed": _quantiles([w.breadth_gap_pp for w in shown]),
            }
        report["seasons"][str(season_inputs.season)] = {
            "diagnostics": diagnostics,
            "positions": by_position,
        }
    return report


# ----------------------------------------------------------------------------- phase 2


def _rows(inputs: Sequence[StudyInputs]) -> list[dict[str, Any]]:
    """One row per displayable window with a next appearance in the same season."""
    rows: list[dict[str, Any]] = []
    for season_inputs in inputs:
        games, _ = game_breadths(
            season_inputs.plays,
            season_inputs.appearances,
            season_inputs.positions,
        )
        position_of = {f"gsis:{a.player_id}": a.position for a in season_inputs.appearances}
        for player_id, player_games in games.items():
            for end, window, nxt in _windows(player_games):
                if nxt is None or not window.displayable:
                    continue
                recent = [
                    g
                    for g in sorted(player_games, key=lambda g: g.week)
                    if g.season == end.season and g.week <= end.week
                ][-BREADTH_WINDOW_APPEARANCES:]
                slots = sum(g.eligible_slots for g in recent)
                volume = window.opportunities / window.appearances
                share = window.opportunities / slots if slots else 0.0
                last_share = end.opportunities / end.eligible_slots if end.eligible_slots else 0.0
                rows.append(
                    {
                        "season": end.season,
                        "week": end.week,
                        "player_id": player_id,
                        "position": position_of.get(player_id),
                        "volume": volume,
                        "share": share,
                        "share_change": last_share - share,
                        "breadth_gap_pp": float(window.breadth_gap_pp or 0.0),
                        "next_opportunities": nxt.opportunities,
                        "drought": int(nxt.opportunities < DROUGHT_FRACTION * volume),
                    },
                )
    return rows


def _spearman(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) < 3:
        return None
    frame = pl.DataFrame({"a": left, "b": right}).with_columns(
        pl.col("a").rank(),
        pl.col("b").rank(),
    )
    value = frame.select(pl.corr("a", "b")).item()
    return None if value is None or math.isnan(value) else round(float(value), 3)


def _fit_predict(
    train: list[dict[str, Any]],
    test: list[dict[str, Any]],
    features: Sequence[str],
) -> list[float]:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    x_train = [[row[name] for name in features] for row in train]
    y_train = [row["drought"] for row in train]
    scaler = StandardScaler().fit(x_train)
    model = LogisticRegression(C=1.0, max_iter=1000)
    model.fit(scaler.transform(x_train), y_train)
    x_test = scaler.transform([[row[name] for name in features] for row in test])
    return [float(p) for p in model.predict_proba(x_test)[:, 1]]


def _log_loss(y: Sequence[int], p: Sequence[float]) -> list[float]:
    eps = 1e-12
    return [
        -(t * math.log(max(q, eps)) + (1 - t) * math.log(max(1 - q, eps)))
        for t, q in zip(y, p, strict=True)
    ]


def _auc(y: Sequence[int], p: Sequence[float]) -> float | None:
    positives = [q for t, q in zip(y, p, strict=True) if t == 1]
    negatives = [q for t, q in zip(y, p, strict=True) if t == 0]
    if not positives or not negatives:
        return None
    ranked = sorted([(q, 1) for q in positives] + [(q, 0) for q in negatives])
    rank_sum = 0.0
    index = 0
    while index < len(ranked):
        tie_end = index
        while tie_end + 1 < len(ranked) and ranked[tie_end + 1][0] == ranked[index][0]:
            tie_end += 1
        mean_rank = (index + tie_end) / 2 + 1
        rank_sum += mean_rank * sum(1 for k in range(index, tie_end + 1) if ranked[k][1] == 1)
        index = tie_end + 1
    n_pos, n_neg = len(positives), len(negatives)
    return round((rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg), 4)


BASELINE_FEATURES = ("volume", "share", "share_change")
CANDIDATE_FEATURES = (*BASELINE_FEATURES, "breadth_gap_pp")


def evaluation_report(inputs: Sequence[StudyInputs]) -> dict[str, Any]:
    """Phase 2, exactly as ADR-103 predeclares it."""
    import random

    rows = _rows(inputs)
    report: dict[str, Any] = {
        "method_version": BREADTH_METHOD_VERSION,
        "outcome": (
            f"drought: next appearance's opportunities < {DROUGHT_FRACTION} x the window's "
            "per-appearance mean"
        ),
        "baseline_features": list(BASELINE_FEATURES),
        "candidate_features": list(CANDIDATE_FEATURES),
        "test_seasons": list(TEST_SEASONS),
        "seed": EVALUATION_SEED,
        "bootstrap_replicates": BOOTSTRAP_REPLICATES,
        "positions": {},
    }
    for position in BREADTH_POSITIONS:
        mine = [row for row in rows if row["position"] == position]
        redundancy = {
            "spearman_with_share": _spearman(
                [r["breadth_gap_pp"] for r in mine],
                [r["share"] for r in mine],
            ),
            "spearman_with_volume": _spearman(
                [r["breadth_gap_pp"] for r in mine],
                [r["volume"] for r in mine],
            ),
            "spearman_with_share_change": _spearman(
                [r["breadth_gap_pp"] for r in mine],
                [r["share_change"] for r in mine],
            ),
        }
        per_season: list[dict[str, Any]] = []
        pooled: list[tuple[str, int, float, float]] = []  # player, y, base loss, cand loss
        for test_season in TEST_SEASONS:
            train = [r for r in mine if r["season"] < test_season]
            test = [r for r in mine if r["season"] == test_season]
            if len({r["drought"] for r in train}) < 2 or not test:
                per_season.append({"season": test_season, "rows": len(test), "skipped": True})
                continue
            base = _fit_predict(train, test, BASELINE_FEATURES)
            cand = _fit_predict(train, test, CANDIDATE_FEATURES)
            y = [r["drought"] for r in test]
            base_loss = _log_loss(y, base)
            cand_loss = _log_loss(y, cand)
            pooled.extend(
                (r["player_id"] + str(test_season), t, b, c)
                for r, t, b, c in zip(test, y, base_loss, cand_loss, strict=True)
            )
            per_season.append(
                {
                    "season": test_season,
                    "rows": len(test),
                    "drought_rate": round(sum(y) / len(y), 3),
                    "baseline_log_loss": round(sum(base_loss) / len(y), 4),
                    "candidate_log_loss": round(sum(cand_loss) / len(y), 4),
                    "baseline_brier": round(
                        sum((t - q) ** 2 for t, q in zip(y, base, strict=True)) / len(y),
                        4,
                    ),
                    "candidate_brier": round(
                        sum((t - q) ** 2 for t, q in zip(y, cand, strict=True)) / len(y),
                        4,
                    ),
                    "baseline_auc": _auc(y, base),
                    "candidate_auc": _auc(y, cand),
                },
            )
        verdict: dict[str, Any] = {"rows": len(pooled)}
        if pooled:
            clusters: dict[str, list[float]] = {}
            for cluster, _, b, c in pooled:
                clusters.setdefault(cluster, []).append(c - b)
            keys = sorted(clusters)
            rng = random.Random(EVALUATION_SEED)
            observed = sum(c - b for _, _, b, c in pooled) / len(pooled)
            draws = []
            for _ in range(BOOTSTRAP_REPLICATES):
                sample = [clusters[rng.choice(keys)] for _ in keys]
                flat = [value for group in sample for value in group]
                draws.append(sum(flat) / len(flat))
            draws.sort()
            low = draws[int(0.025 * BOOTSTRAP_REPLICATES)]
            high = draws[int(0.975 * BOOTSTRAP_REPLICATES) - 1]
            verdict.update(
                {
                    "delta_log_loss": round(observed, 5),
                    "delta_log_loss_ci95": [round(low, 5), round(high, 5)],
                    "incremental_evidence": high < 0,
                },
            )
        report["positions"][position] = {
            "rows": len(mine),
            "redundancy": redundancy,
            "seasons": per_season,
            "pooled": verdict,
        }
    return report
