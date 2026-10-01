"""The weekly v2 development evaluation: each family's value over v1, and the frozen verdict.

Everything this module decides was declared in :mod:`ffdraft.weekly.frozen_v2` before it ran.
It measures, on v1's own folds and rows:

* **v1 refitted per fold** — v1's frozen specification through v1's own fitting code, so its
  numbers reproduce v1's committed development report (a determinism check, not a choice);
* **each family variant** — v1's features plus one family, and v1 plus all three;
* **B0-B2** — the declared baselines, unchanged.

The decision pools, pairs, metrics and week clusters are v1's (:mod:`ffdraft.weekly.evaluate`),
so a family's value is the same question v1 was judged on, asked once more with one input
added. ``weekly_family_selection_v1`` then picks v2's families; the report prints every
family's measured value whether or not it is selected, and the rows where a family has
something to say (``active`` subsets) as a diagnostic that decides nothing.

2025 is scored the same way with the models trained through 2024 and is printed as
previously examined evidence: v1's sealed season, already consumed (ADR-096).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import polars as pl
from numpy.typing import NDArray

from ffdraft.modeling.preprocessing import scalar_float
from ffdraft.weekly.baselines import fit_baseline
from ffdraft.weekly.dataset import TARGET_COLUMN
from ffdraft.weekly.evaluate import (
    CANDIDATE_ID,
    _pair_metrics,
    _pool_pairs,
    bootstrap_accuracy_difference,
    concat_pairs,
    pinball,
    verdict,
)
from ffdraft.weekly.frozen import (
    BASELINE_IDS,
    PROMOTION_RULE,
    WEEKLY_QUANTILE_LEVELS,
    WEEKLY_SEED,
    WEEKLY_TRAIN_START_SEASON,
    WeeklySpec,
)
from ffdraft.weekly.frozen_v2 import (
    CANDIDATE_VARIANTS,
    FAMILY_SELECTION_RULE,
    V2_FAMILIES,
    WEEKLY_V2_DEVELOPMENT_SEASONS,
    WEEKLY_V2_PREVIOUSLY_EXAMINED_SEASON,
    frozen_rules,
    v2_spec,
    variant_families,
)
from ffdraft.weekly.model import fit_weekly_model

__all__ = [
    "ACTIVE_SUBSETS",
    "bootstrap_pinball_difference",
    "family_selection",
    "run_v2_development",
    "variant_spec",
]

Floats = NDArray[np.float64]

#: Rows where a family has something to say. A diagnostic only: ``weekly_family_selection_v1``
#: reads the pooled rows, never these.
ACTIVE_SUBSETS: Mapping[str, pl.Expr] = {
    "weather": (
        (pl.col("wx_wind_mph") >= 15.0)
        | (pl.col("wx_precip") == 1.0)
        | (pl.col("wx_temp_f") <= 32.0)
    ).fill_null(False),
    "lineup": (
        (pl.col("own_ol_out") >= 1.0)
        | (pl.col("own_qb_out") >= 1.0)
        | (pl.col("own_vacated_targets") >= 0.10)
        | (pl.col("own_vacated_carries") >= 0.20)
    ).fill_null(False),
    "defense": (
        (pl.col("opp_cb_out") >= 1.0) | (pl.col("opp_s_out") >= 1.0) | (pl.col("opp_dl_out") >= 2.0)
    ).fill_null(False),
}


def variant_spec(
    variant: str,
    *,
    weather_parameters_digest: str,
    transform: Callable[[Any], Any] | None = None,
) -> Any:
    """v1's frozen spec for ``"v1"``; a v2 spec for ``"v1+..."``.

    ``transform`` exists for the unit tests only (a few boosting rounds instead of the frozen
    number); no command passes it, and an artifact fitted under one fails v1's and v2's
    configuration-hash check at load.
    """
    spec = (
        WeeklySpec()
        if variant == "v1"
        else v2_spec(variant_families(variant), weather_parameters_digest=weather_parameters_digest)
    )
    return spec if transform is None else transform(spec)


@dataclass
class V2Fold:
    season: int
    rows: pl.DataFrame
    pairs: dict[str, dict[str, Any]]
    crossing: dict[str, dict[str, float]] = field(default_factory=dict)


def _row_metrics(actual: Floats, matrix: Floats) -> dict[str, Floats]:
    levels = list(WEEKLY_QUANTILE_LEVELS)
    clean = np.nan_to_num(matrix, nan=0.0)
    return {
        "pinball": pinball(actual, clean, levels),
        "median": clean[:, levels.index(0.5)],
        "in80": (
            (actual >= clean[:, levels.index(0.1)]) & (actual <= clean[:, levels.index(0.9)])
        ).astype(np.float64),
        "in50": (
            (actual >= clean[:, levels.index(0.25)]) & (actual <= clean[:, levels.index(0.75)])
        ).astype(np.float64),
    }


def evaluate_v2_fold(
    frame: pl.DataFrame,
    *,
    season: int,
    variants: Mapping[str, Any],
    progress: Callable[[str], None] | None = None,
) -> V2Fold:
    """Fit every variant and baseline on seasons before ``season`` and score ``season``."""
    train = frame.filter(
        (pl.col("season") >= WEEKLY_TRAIN_START_SEASON) & (pl.col("season") < season),
    )
    valid = frame.filter(pl.col("season") == season)
    if train.is_empty() or valid.is_empty():
        raise ValueError(f"fold {season} has no training or no validation rows")
    predictions: dict[str, Floats] = {}
    baselines = {baseline_id: fit_baseline(baseline_id, train) for baseline_id in BASELINE_IDS}
    for baseline_id, baseline in baselines.items():
        predictions[baseline_id] = baseline.predict(valid)
    crossing: dict[str, dict[str, float]] = {}
    for name, spec in variants.items():
        if progress is not None:
            progress(f"fold {season}: {name}")
        model = fit_weekly_model(train, spec=spec)
        predictions[name] = model.predict(valid)
        crossing[name] = {key: group.raw_crossing_rate for key, group in model.groups.items()}
    actual = valid.get_column(TARGET_COLUMN).cast(pl.Float64).to_numpy()
    columns: dict[str, Any] = {}
    for model_id, matrix in predictions.items():
        for metric, values in _row_metrics(actual, matrix).items():
            columns[f"{model_id}__{metric}"] = values
    keep = ["season", "target_week", "player_id", "position", "scoring_preset", TARGET_COLUMN]
    active = {
        f"active__{family}": expr
        for family, expr in ACTIVE_SUBSETS.items()
        if all(column in valid.columns for column in V2_FAMILIES[family])
    }
    rows = valid.select(
        *keep,
        *[expr.alias(name) for name, expr in active.items()],
    ).with_columns([pl.Series(name, values) for name, values in columns.items()])
    b0_points = baselines["b0_season_rate"].point(valid)
    pair_sets = _pool_pairs(valid, predictions, b0_points, season=season)
    return V2Fold(
        season=season,
        rows=rows,
        pairs={model_id: pair_set.arrays() for model_id, pair_set in pair_sets.items()},
        crossing=crossing,
    )


def _macro_pinball(rows: pl.DataFrame, model_id: str) -> float:
    cells = rows.group_by("position", "scoring_preset", maintain_order=True).agg(
        pl.col(f"{model_id}__pinball").mean().alias("value"),
    )
    return scalar_float(cells.get_column("value").mean(), math.nan)


def summarise(
    rows: pl.DataFrame, pairs: Mapping[str, Mapping[str, Any]], model_id: str
) -> dict[str, float]:
    metrics = _pair_metrics(pairs[model_id])
    return {
        "pinball": _macro_pinball(rows, model_id),
        "pinball_rows": scalar_float(rows.get_column(f"{model_id}__pinball").mean(), math.nan),
        "mae_median": scalar_float(
            (rows.get_column(f"{model_id}__median") - rows.get_column(TARGET_COLUMN)).abs().mean(),
            math.nan,
        ),
        "coverage_80": scalar_float(rows.get_column(f"{model_id}__in80").mean(), math.nan),
        "coverage_50": scalar_float(rows.get_column(f"{model_id}__in50").mean(), math.nan),
        "pair_accuracy": metrics["accuracy"],
        "pair_brier": metrics["brier"],
        "pairs": metrics["pairs"],
        "rows": rows.height,
    }


def bootstrap_pinball_difference(
    rows: pl.DataFrame,
    reference: str,
    candidate: str,
    *,
    replicates: int,
    level: float,
    seed: int = WEEKLY_SEED,
) -> dict[str, float]:
    """Week-clustered bootstrap of the row-level mean pinball difference (reference - candidate).

    Positive favours the candidate. Clusters are ``(season, target_week)``, as for v1's
    accuracy interval, because a week's rows share games and are not independent.
    """
    cluster = (rows.get_column("season") * 100 + rows.get_column("target_week")).to_numpy()
    difference = (
        rows.get_column(f"{reference}__pinball") - rows.get_column(f"{candidate}__pinball")
    ).to_numpy()
    unique, inverse = np.unique(cluster, return_inverse=True)
    sums = np.bincount(inverse, weights=difference, minlength=unique.shape[0])
    counts = np.bincount(inverse, minlength=unique.shape[0]).astype(np.float64)
    rng = np.random.default_rng(seed)
    draws = np.empty(replicates, dtype=np.float64)
    for index in range(replicates):
        pick = rng.integers(0, unique.shape[0], unique.shape[0])
        draws[index] = sums[pick].sum() / counts[pick].sum()
    tail = (1.0 - level) / 2.0
    return {
        "difference": float(sums.sum() / counts.sum()),
        "lower": float(np.quantile(draws, tail)),
        "upper": float(np.quantile(draws, 1.0 - tail)),
        "clusters": int(unique.shape[0]),
        "replicates": replicates,
        "level": level,
    }


def _clauses(
    rows: pl.DataFrame,
    folds: Sequence[V2Fold],
    pooled: Mapping[str, Mapping[str, float]],
    candidate: str,
) -> dict[str, Any]:
    """``weekly_family_selection_v1``'s four clauses for ``candidate`` against v1."""
    rule = FAMILY_SELECTION_RULE
    base = pooled["v1"]
    mine = pooled[candidate]
    interval = bootstrap_pinball_difference(
        rows,
        "v1",
        candidate,
        replicates=rule.bootstrap_replicates,
        level=rule.bootstrap_level,
    )
    wins = sum(
        1
        for fold in folds
        if _macro_pinball(fold.rows, candidate) < _macro_pinball(fold.rows, "v1")
    )
    clauses: dict[str, dict[str, Any]] = {
        "pinball_below_v1": {
            "candidate": mine["pinball"],
            "v1": base["pinball"],
            "difference": base["pinball"] - mine["pinball"],
            "passed": mine["pinball"] < base["pinball"],
        },
        "pinball_interval_above_zero": {**interval, "passed": interval["lower"] > 0.0},
        "pinball_fold_wins": {
            "wins": wins,
            "folds": len(folds),
            "minimum": rule.min_fold_wins,
            "passed": wins >= rule.min_fold_wins,
        },
        "decision_not_worse": {
            "accuracy": mine["pair_accuracy"],
            "accuracy_v1": base["pair_accuracy"],
            "brier": mine["pair_brier"],
            "brier_v1": base["pair_brier"],
            "accuracy_tolerance": rule.accuracy_tolerance,
            "brier_tolerance": rule.brier_tolerance,
            "passed": mine["pair_accuracy"] >= base["pair_accuracy"] - rule.accuracy_tolerance
            and mine["pair_brier"] <= base["pair_brier"] + rule.brier_tolerance,
        },
    }
    return {"clauses": clauses, "passed": all(c["passed"] for c in clauses.values())}


def family_selection(
    rows: pl.DataFrame,
    folds: Sequence[V2Fold],
    pooled: Mapping[str, Mapping[str, float]],
) -> dict[str, Any]:
    """Apply the selection rule to every single-family variant."""
    results = {family: _clauses(rows, folds, pooled, f"v1+{family}") for family in V2_FAMILIES}
    selected = [family for family, result in results.items() if result["passed"]]
    return {"rule": FAMILY_SELECTION_RULE.version, "families": results, "selected": selected}


def _active_diagnostics(rows: pl.DataFrame, variants: Sequence[str]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for family in V2_FAMILIES:
        column = f"active__{family}"
        if column not in rows.columns:
            continue
        subset = rows.filter(pl.col(column))
        entry: dict[str, Any] = {
            "rows": subset.height,
            "share": subset.height / max(1, rows.height),
        }
        for name in variants:
            if subset.height:
                entry[name] = scalar_float(subset.get_column(f"{name}__pinball").mean(), math.nan)
        output[family] = entry
    return output


def run_v2_development(
    frame: pl.DataFrame,
    *,
    weather_parameters_digest: str,
    seasons: Sequence[int] = WEEKLY_V2_DEVELOPMENT_SEASONS,
    include_previously_examined: bool = True,
    progress: Callable[[str], None] | None = None,
    _spec_transform: Callable[[Any], Any] | None = None,
) -> dict[str, Any]:
    """The declared development run, the family selection, and the 2025 re-examination."""

    def spec_for(name: str) -> Any:
        return variant_spec(
            name,
            weather_parameters_digest=weather_parameters_digest,
            transform=_spec_transform,
        )

    variants = {name: spec_for(name) for name in CANDIDATE_VARIANTS}
    folds = [
        evaluate_v2_fold(frame, season=season, variants=variants, progress=progress)
        for season in seasons
    ]
    model_ids = [*CANDIDATE_VARIANTS, *BASELINE_IDS]
    all_rows = pl.concat([fold.rows for fold in folds], how="vertical_relaxed")
    pooled_pairs = {m: concat_pairs(fold.pairs[m] for fold in folds) for m in model_ids}
    pooled = {m: summarise(all_rows, pooled_pairs, m) for m in model_ids}
    by_season = {
        fold.season: {m: summarise(fold.rows, fold.pairs, m) for m in model_ids} for fold in folds
    }
    selection = family_selection(all_rows, folds, pooled)
    selected = list(selection["selected"])

    union: dict[str, Any] | None = None
    final_families: tuple[str, ...] = ()
    if len(selected) == 1:
        final_families = (selected[0],)
    elif len(selected) >= 2:
        name = "v1+" + "+".join(selected)
        if name not in variants:
            spec = spec_for(name)
            extra = [
                evaluate_v2_fold(
                    frame, season=fold.season, variants={name: spec}, progress=progress
                )
                for fold in folds
            ]
            for fold, more in zip(folds, extra, strict=True):
                fold.rows = fold.rows.with_columns(
                    *[
                        more.rows.get_column(column)
                        for column in more.rows.columns
                        if column.startswith(f"{name}__")
                    ],
                )
                fold.pairs[name] = more.pairs[name]
            all_rows = pl.concat([fold.rows for fold in folds], how="vertical_relaxed")
            pooled_pairs[name] = concat_pairs(fold.pairs[name] for fold in folds)
            pooled[name] = summarise(all_rows, pooled_pairs, name)
            for fold in folds:
                by_season[fold.season][name] = summarise(fold.rows, fold.pairs, name)
        union = {"variant": name, **_clauses(all_rows, folds, pooled, name)}
        if union["passed"]:
            final_families = tuple(selected)
        else:
            best = min(selected, key=lambda family: pooled[f"v1+{family}"]["pinball"])
            final_families = (best,)

    v2_variant = "v1+" + "+".join(final_families) if final_families else None
    development_verdict: dict[str, Any] | None = None
    if v2_variant is not None:
        # weekly_promotion_v1's development clauses, asked of v2 against B0-B2.
        as_v1 = {CANDIDATE_ID: pooled[v2_variant], **{b: pooled[b] for b in BASELINE_IDS}}
        by_season_v1 = {
            season: {CANDIDATE_ID: values[v2_variant], **{b: values[b] for b in BASELINE_IDS}}
            for season, values in by_season.items()
        }
        best_accuracy = max(BASELINE_IDS, key=lambda b: pooled[b]["pair_accuracy"])
        accuracy_interval = bootstrap_accuracy_difference(
            pooled_pairs[v2_variant],
            pooled_pairs[best_accuracy],
            replicates=PROMOTION_RULE.bootstrap_replicates,
            level=PROMOTION_RULE.bootstrap_level,
        )
        development_verdict = verdict(as_v1, by_season_v1, accuracy_interval, development=True)

    previously_examined: dict[str, Any] | None = None
    if include_previously_examined and v2_variant is not None:
        names = {"v1": variants["v1"]}
        names[v2_variant] = spec_for(v2_variant)
        fold = evaluate_v2_fold(
            frame,
            season=WEEKLY_V2_PREVIOUSLY_EXAMINED_SEASON,
            variants=names,
            progress=progress,
        )
        summary = {m: summarise(fold.rows, fold.pairs, m) for m in [*names, *BASELINE_IDS]}
        previously_examined = {
            "season": WEEKLY_V2_PREVIOUSLY_EXAMINED_SEASON,
            "status": (
                "previously examined (v1's sealed season, consumed by ADR-096); decides nothing"
            ),
            "summary": summary,
            "pinball_interval": bootstrap_pinball_difference(
                fold.rows,
                "v1",
                v2_variant,
                replicates=FAMILY_SELECTION_RULE.bootstrap_replicates,
                level=FAMILY_SELECTION_RULE.bootstrap_level,
            ),
            "consistent": summary[v2_variant]["pinball"] < summary["v1"]["pinball"],
        }

    by_position = {
        position: {
            m: summarise(
                all_rows.filter(pl.col("position") == position),
                {
                    m2: {
                        k: v[pooled_pairs[m2]["position"] == position]
                        for k, v in pooled_pairs[m2].items()
                    }
                    for m2 in [m]
                },
                m,
            )
            for m in pooled
        }
        for position in ("QB", "RB", "WR", "TE")
    }
    outcome = (
        "selected"
        if v2_variant is not None
        and development_verdict is not None
        and development_verdict["passed"]
        else "rejected_at_development"
    )
    return {
        "rules": frozen_rules(),
        "folds": [fold.season for fold in folds],
        "variants": list(pooled),
        "pooled": pooled,
        "by_season": {str(season): values for season, values in by_season.items()},
        "by_position": by_position,
        "selection": selection,
        "union": union,
        "v2_families": list(final_families),
        "v2_variant": v2_variant,
        "development_verdict": development_verdict,
        "outcome": outcome,
        "previously_examined": previously_examined,
        "active_subsets": _active_diagnostics(all_rows, list(pooled)),
        "crossing": {str(fold.season): fold.crossing for fold in folds},
        "_rows": all_rows,
    }
