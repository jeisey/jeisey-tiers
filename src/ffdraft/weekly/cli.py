"""``ffdraft`` commands for the weekly start/sit model (ADR-096).

Four commands, in the order they are run:

``build-weekly-dataset`` (network, cached)
    Join the rest-of-season snapshots to next-game targets, game environment and opponent
    readings, and write ``data/weekly/weekly_rows.parquet``.
``evaluate-weekly``
    The frozen development comparison (2020-2024). With ``--final-eval`` and the exact token,
    the single sealed evaluation of 2025 instead.
``train-weekly-production``
    Fit the promoted candidate on every season through 2025 and write the artifact, with the
    measurements the page publishes (matchup-margin uncertainty, same-game correlation,
    startable thresholds, injury-designation base rates). Refuses unless the holdout passed.

Kept out of :mod:`ffdraft.cli` so the new model's surface is one reviewable file; the main
CLI only registers it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import polars as pl

__all__ = ["register"]

DEFAULT_WEEKLY_DATA_DIR = Path("data/weekly")
DEFAULT_WEEKLY_EXPERIMENT_DIR = Path("docs/experiments/weekly-startsit")
DEFAULT_WEEKLY_MODEL_DIR = Path("models/production/weekly-startsit-v1")
ROWS_FILE = "weekly_rows.parquet"
INJURIES_FILE = "injuries.parquet"
APPEARANCES_FILE = "appearances.parquet"


def register(subparsers: Any, *, repo_root: Any) -> None:
    dataset = subparsers.add_parser(
        "build-weekly-dataset",
        help="build the weekly start/sit dataset from the ROS snapshots (performs network I/O)",
    )
    dataset.add_argument("--ros-data", type=Path, default=None, help="ROS snapshot directory")
    dataset.add_argument("--out", type=Path, default=None, help="output directory")
    dataset.add_argument("--first-season", type=int, default=2017)
    dataset.add_argument("--last-season", type=int, required=True)
    dataset.set_defaults(handler=lambda args: _build_dataset(args, repo_root()))

    evaluate = subparsers.add_parser(
        "evaluate-weekly",
        help="run the frozen weekly start/sit comparison and write its report",
    )
    evaluate.add_argument("--data", type=Path, default=None, help="weekly dataset directory")
    evaluate.add_argument("--out", type=Path, default=None, help="report directory")
    evaluate.add_argument("--final-eval", action="store_true", help="score the sealed 2025 season")
    evaluate.add_argument("--confirm-final-eval", default=None, help="the exact seal token")
    evaluate.add_argument("--final-eval-reason", default=None, help="why the seal was opened")
    evaluate.set_defaults(handler=lambda args: _evaluate(args, repo_root()))

    train = subparsers.add_parser(
        "train-weekly-production",
        help="fit the promoted weekly model on every season through the holdout",
    )
    train.add_argument("--data", type=Path, default=None, help="weekly dataset directory")
    train.add_argument("--reports", type=Path, default=None, help="experiment directory")
    train.add_argument("--out", type=Path, default=None, help="model artifact directory")
    train.add_argument("--confirm-final-eval", default=None, help="the seal token (2025 is used)")
    train.set_defaults(handler=lambda args: _train(args, repo_root()))

    card = subparsers.add_parser(
        "weekly-model-card",
        help="generate the weekly start/sit model card from the committed reports and artifact",
    )
    card.add_argument("--reports", type=Path, default=None, help="experiment directory")
    card.add_argument("--model", type=Path, default=None, help="model artifact directory")
    card.add_argument("--out", type=Path, default=None, help="card directory")
    card.add_argument("--git-sha", default="unknown", help="recorded code SHA")
    card.set_defaults(handler=lambda args: _card(args, repo_root()))


def _card(args: argparse.Namespace, root: Path) -> int:
    from ffdraft.weekly.card import write_weekly_card

    reports = args.reports or (root / DEFAULT_WEEKLY_EXPERIMENT_DIR)
    written = write_weekly_card(
        development_path=reports / "experiment.json",
        final_path=reports / "final_holdout.json",
        model_dir=args.model or (root / DEFAULT_WEEKLY_MODEL_DIR),
        out_dir=args.out or (root / "models/cards"),
        git_sha=args.git_sha,
    )
    for path in written:
        print(f"wrote {path}")
    return 0


def _build_dataset(args: argparse.Namespace, root: Path) -> int:
    from ffdraft.config import load_app_config
    from ffdraft.features.sources import load_historical_sources
    from ffdraft.ros.dataset import bridged_snap_counts
    from ffdraft.sources.nflverse_http import nflverse_loaders
    from ffdraft.weekly.context import scored_position_rows
    from ffdraft.weekly.dataset import appearances, build_weekly_dataset, describe
    from ffdraft.weekly.injuries import normalize_injuries

    ros_dir = args.ros_data or (root / "data/ros")
    out_dir = args.out or (root / DEFAULT_WEEKLY_DATA_DIR)
    snapshots = ros_dir / "ros_snapshots.parquet"
    if not snapshots.is_file():
        print(f"{snapshots} not found; run `ffdraft build-ros-dataset` first", file=sys.stderr)
        return 2
    seasons = list(range(args.first_season, args.last_season + 1))
    loaded = load_historical_sources(target_seasons=seasons)
    sources = loaded.sources
    config = load_app_config()
    dataset = build_weekly_dataset(
        pl.read_parquet(snapshots),
        sources,
        scoring=config.league.scoring,
        seasons=seasons,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    dataset.frame.write_parquet(out_dir / ROWS_FILE, compression="zstd")
    injuries = normalize_injuries(nflverse_loaders().load_injuries(seasons=seasons))
    injuries.write_parquet(out_dir / INJURIES_FILE, compression="zstd")
    # Every appearance in every scored week, not only the weeks that are model targets: the
    # designation base rates need week 1 too, and a player outside the snapshot universe
    # still either played or did not.
    every = (
        appearances(
            scored_position_rows(sources.weekly_stats, config.league.scoring, seasons),
            bridged_snap_counts(sources),
            seasons,
        )
        .select("season", "week", "gsis_id")
        .unique()
    )
    every.write_parquet(out_dir / APPEARANCES_FILE, compression="zstd")
    summary = describe(dataset)
    (out_dir / "weekly_manifest.json").write_text(
        json.dumps({**summary, "injury_rows": injuries.height}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))
    failed = [check for check in dataset.checks if check.blocking]
    for check in dataset.checks:
        print(f"  [{check.severity}] {check.check_id}: {check.observed}")
    return 1 if failed else 0


def _authorization(args: argparse.Namespace) -> Any:
    from ffdraft.weekly.evaluate import WeeklyFinalEvalAuthorization

    if not args.confirm_final_eval:
        return None
    return WeeklyFinalEvalAuthorization(
        confirmation=args.confirm_final_eval,
        reason=getattr(args, "final_eval_reason", None) or "production fit",
    )


def _evaluate(args: argparse.Namespace, root: Path) -> int:
    from ffdraft.weekly.evaluate import run_weekly_experiment
    from ffdraft.weekly.frozen import WEEKLY_DEVELOPMENT_SEASONS, WEEKLY_SEALED_SEASON
    from ffdraft.weekly.report import public_report, write_report

    data_dir = args.data or (root / DEFAULT_WEEKLY_DATA_DIR)
    out_dir = args.out or (root / DEFAULT_WEEKLY_EXPERIMENT_DIR)
    frame = pl.read_parquet(data_dir / ROWS_FILE)
    if args.final_eval:
        if not args.confirm_final_eval or not args.final_eval_reason:
            print(
                "--final-eval requires --confirm-final-eval <token> and --final-eval-reason",
                file=sys.stderr,
            )
            return 2
        authorization = _authorization(args)
        seasons: tuple[int, ...] = (WEEKLY_SEALED_SEASON,)
        stage, name = "final_holdout", "final_holdout"
    else:
        authorization = None
        seasons = WEEKLY_DEVELOPMENT_SEASONS
        stage, name = "development", "experiment"

    result = run_weekly_experiment(
        frame,
        seasons=seasons,
        authorization=authorization,
        progress=lambda message: print(message, flush=True),
    )
    extra: dict[str, Any] = {"dataset_rows": frame.height}
    if authorization is not None:
        extra["authorization"] = {"authorized": True, "reason": authorization.reason}
    report = public_report(result, stage=stage, extra=extra)
    for path in write_report(report, out_dir, name=name):
        print(f"wrote {path}")
    rows_path = data_dir / f"oof_{stage}.parquet"
    result["_rows"].write_parquet(rows_path, compression="zstd")
    print(f"wrote {rows_path}")
    print(f"verdict: {'PASS' if report['verdict']['passed'] else 'FAIL'}")
    for clause, detail in report["verdict"]["clauses"].items():
        print(f"  {clause}: {'pass' if detail['passed'] else 'FAIL'}")
    return 0 if report["verdict"]["passed"] else 1


def _train(args: argparse.Namespace, root: Path) -> int:
    from ffdraft.weekly.frozen import WEEKLY_SEALED_SEASON, WEEKLY_TRAIN_START_SEASON
    from ffdraft.weekly.measure import publishable_measurements
    from ffdraft.weekly.model import fit_weekly_model

    data_dir = args.data or (root / DEFAULT_WEEKLY_DATA_DIR)
    reports = args.reports or (root / DEFAULT_WEEKLY_EXPERIMENT_DIR)
    out_dir = args.out or (root / DEFAULT_WEEKLY_MODEL_DIR)
    holdout_path = reports / "final_holdout.json"
    development_path = reports / "experiment.json"
    if not holdout_path.is_file() or not development_path.is_file():
        print("both the development and the holdout reports must exist first", file=sys.stderr)
        return 2
    holdout = json.loads(holdout_path.read_text(encoding="utf-8"))
    development = json.loads(development_path.read_text(encoding="utf-8"))
    if not (holdout["verdict"]["passed"] and development["verdict"]["passed"]):
        print("the weekly candidate did not pass both stages; refusing to promote", file=sys.stderr)
        return 1
    authorization = _authorization(args)
    if authorization is None:
        print(
            f"training through {WEEKLY_SEALED_SEASON} uses the spent holdout; pass "
            "--confirm-final-eval with the token",
            file=sys.stderr,
        )
        return 2
    frame = pl.read_parquet(data_dir / ROWS_FILE).filter(
        (pl.col("season") >= WEEKLY_TRAIN_START_SEASON)
        & (pl.col("season") <= WEEKLY_SEALED_SEASON),
    )
    model = fit_weekly_model(frame)
    measurements = publishable_measurements(
        dataset=frame,
        development_rows=pl.read_parquet(data_dir / "oof_development.parquet"),
        holdout_rows=pl.read_parquet(data_dir / "oof_final_holdout.parquet"),
        injuries=pl.read_parquet(data_dir / INJURIES_FILE),
        appearances=pl.read_parquet(data_dir / APPEARANCES_FILE),
        development=development,
        holdout=holdout,
    )
    written = model.save(
        out_dir,
        extra={"refit_reason": "initial_production_fit", "measurements": measurements},
    )
    for path in written[-1:]:
        print(f"wrote {path} ({len(written)} files)")
    return 0
