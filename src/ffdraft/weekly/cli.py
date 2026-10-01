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
V2_ROWS_FILE = "weekly_rows_v2.parquet"
DEFAULT_WEEKLY_V2_EXPERIMENT_DIR = Path("docs/experiments/weekly-startsit-v2")
DEFAULT_WEEKLY_V2_MODEL_DIR = Path("models/shadow/weekly-startsit-v2")


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

    v2_dataset = subparsers.add_parser(
        "build-weekly-v2-dataset",
        help=(
            "join the weekly v2 candidate families (weather, his offence's health, the "
            "opposing defence's health) to v1's rows (performs network I/O)"
        ),
    )
    v2_dataset.add_argument("--data", type=Path, default=None, help="weekly dataset directory")
    v2_dataset.add_argument("--first-season", type=int, default=2017)
    v2_dataset.add_argument("--last-season", type=int, required=True)
    v2_dataset.set_defaults(handler=lambda args: _build_v2_dataset(args, repo_root()))

    forecasts = subparsers.add_parser(
        "capture-forecasts",
        help=(
            "fetch the kickoff forecast for every upcoming game, once per venue, and retain it "
            "in the store (performs network I/O; NWS and Open-Meteo)"
        ),
    )
    forecasts.add_argument("--season", type=int, required=True)
    forecasts.add_argument("--store", type=Path, required=True, help="retained store checkout")
    forecasts.add_argument("--horizon-days", type=float, default=8.0)
    forecasts.add_argument("--git-sha", default=None)
    forecasts.set_defaults(handler=lambda args: _capture_forecasts(args))

    injury = subparsers.add_parser(
        "capture-injury-report",
        help="retain the season's nflverse injury report with per-week row digests (network)",
    )
    injury.add_argument("--season", type=int, required=True)
    injury.add_argument("--store", type=Path, required=True)
    injury.add_argument("--git-sha", default=None)
    injury.set_defaults(handler=lambda args: _capture_injuries(args))

    pit = subparsers.add_parser(
        "injury-pit-report",
        help="compare retained injury-report captures week by week (row contents, not counts)",
    )
    pit.add_argument("--season", type=int, required=True)
    pit.add_argument("--store", type=Path, required=True)
    pit.set_defaults(handler=lambda args: _injury_pit(args))

    shadow = subparsers.add_parser(
        "retain-weekly-shadow",
        help="append a build's private shadow record (v1 and v2 side by side) to the store",
    )
    shadow.add_argument("--file", type=Path, required=True)
    shadow.add_argument("--store", type=Path, required=True)
    shadow.set_defaults(handler=lambda args: _retain_shadow(args))

    v2_eval = subparsers.add_parser(
        "evaluate-weekly-v2",
        help="the frozen v2 development comparison: each family's value over v1 (offline)",
    )
    v2_eval.add_argument("--data", type=Path, default=None)
    v2_eval.add_argument("--out", type=Path, default=None)
    v2_eval.set_defaults(handler=lambda args: _evaluate_v2(args, repo_root()))

    v2_train = subparsers.add_parser(
        "train-weekly-v2-shadow",
        help="fit the selected v2 on 2017-2025 for shadow serving; refuses unless selected",
    )
    v2_train.add_argument("--data", type=Path, default=None)
    v2_train.add_argument("--reports", type=Path, default=None)
    v2_train.add_argument("--out", type=Path, default=None)
    v2_train.set_defaults(handler=lambda args: _train_v2(args, repo_root()))

    v2_prospective = subparsers.add_parser(
        "evaluate-weekly-v2-prospective",
        help="count, or (with the token, at a declared look) judge, the prospective holdout",
    )
    v2_prospective.add_argument("--season", type=int, default=2026)
    v2_prospective.add_argument("--store", type=Path, required=True)
    v2_prospective.add_argument("--look", choices=("first", "final"), default=None)
    v2_prospective.add_argument("--confirm", default=None)
    v2_prospective.add_argument("--out", type=Path, default=None)
    v2_prospective.set_defaults(handler=lambda args: _prospective(args, repo_root()))

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


def _build_v2_dataset(args: argparse.Namespace, root: Path) -> int:
    from ffdraft.features.sources import load_historical_sources
    from ffdraft.ros.dataset import bridged_snap_counts
    from ffdraft.weekly.dataset_v2 import attach_v2_families, game_weather_inputs
    from ffdraft.weekly.venues import load_venue_registry
    from ffdraft.weekly.weather import load_error_model

    data_dir = args.data or (root / DEFAULT_WEEKLY_DATA_DIR)
    rows_path = data_dir / ROWS_FILE
    injuries_path = data_dir / INJURIES_FILE
    if not rows_path.is_file() or not injuries_path.is_file():
        print(f"{rows_path} not found; run `ffdraft build-weekly-dataset` first", file=sys.stderr)
        return 2
    seasons = list(range(args.first_season, args.last_season + 1))
    loaded = load_historical_sources(target_seasons=seasons)
    sources = loaded.sources
    text = _game_weather_text(seasons)
    dataset = attach_v2_families(
        pl.read_parquet(rows_path),
        snaps=bridged_snap_counts(sources),
        weekly=sources.weekly_stats,
        injuries=pl.read_parquet(injuries_path),
        games=game_weather_inputs(sources.schedule, text),
        registry=load_venue_registry(),
        error_model=load_error_model(),
    )
    dataset.frame.write_parquet(data_dir / V2_ROWS_FILE, compression="zstd")
    text.write_parquet(data_dir / "game_weather_text.parquet", compression="zstd")
    (data_dir / "weekly_v2_manifest.json").write_text(
        json.dumps(dataset.coverage, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(dataset.coverage, indent=2))
    for check in dataset.checks:
        print(f"  [{check.severity}] {check.check_id}: {check.observed}")
    return 1 if any(check.blocking for check in dataset.checks) else 0


def _game_weather_text(seasons: list[int]) -> pl.DataFrame:
    """The game book's kickoff conditions, one row per game, from nflverse play-by-play."""
    from ffdraft.sources.nflverse_http import nflverse_loaders

    nflreadpy = nflverse_loaders()
    frames = []
    for season in seasons:
        pbp = nflreadpy.load_pbp(seasons=[season])
        frame = pbp if isinstance(pbp, pl.DataFrame) else pl.DataFrame(pbp)
        frames.append(
            frame.select("game_id", pl.col("weather").cast(pl.String)).unique(
                "game_id",
                keep="first",
                maintain_order=True,
            ),
        )
    return pl.concat(frames, how="vertical_relaxed").sort("game_id")


def _capture_forecasts(args: argparse.Namespace) -> int:
    from datetime import UTC, datetime, timedelta

    from ffdraft.retention import SnapshotStore
    from ffdraft.season.state import scheduled_kickoff_utc
    from ffdraft.sources.nflverse_history import NflverseScheduleAdapter
    from ffdraft.sources.nflverse_http import nflverse_loaders
    from ffdraft.weekly.capture import FORECAST_SOURCE_ID, GamedayCapture, write_gameday_capture
    from ffdraft.weekly.forecast import fetch_venue_forecast, forecast_capture_rows
    from ffdraft.weekly.venues import load_venue_registry

    now = datetime.now(UTC).replace(microsecond=0)
    schedule = NflverseScheduleAdapter().normalize(nflverse_loaders().load_schedules()).frame
    registry = load_venue_registry()
    games = []
    for row in schedule.filter(
        (pl.col("season") == args.season) & (pl.col("game_type") == "REG"),
    ).iter_rows(named=True):
        kickoff = scheduled_kickoff_utc(row.get("gameday"), row.get("gametime"))
        if kickoff is None or not (now <= kickoff <= now + timedelta(days=args.horizon_days)):
            continue
        venue = registry.resolve(
            season=args.season,
            stadium_id=row.get("stadium_id"),
            stadium=row.get("stadium"),
        )
        games.append(
            {
                "game_id": row["game_id"],
                "season": row["season"],
                "week": row["week"],
                "kickoff_utc": kickoff,
                "venue_id": venue.venue_id if venue else None,
            },
        )
    venues = [
        venue
        for venue in registry.venues
        if venue.venue_id in {game["venue_id"] for game in games} and venue.roof_type != "dome"
    ]
    fetched = {venue.venue_id: fetch_venue_forecast(venue) for venue in venues}
    rows = forecast_capture_rows(registry.venues, games, fetched)
    statuses: dict[str, int] = {}
    for row in rows:
        statuses[str(row["status"])] = statuses.get(str(row["status"]), 0) + 1
    capture = GamedayCapture(
        source_id=FORECAST_SOURCE_ID,
        season=args.season,
        observed_at_utc=now,
        rows=rows,
        details={
            "registry_version": registry.version,
            "registry_digest": registry.digest,
            "venues_fetched": len(fetched),
            "providers": {
                provider: sum(1 for item in fetched.values() if item.provider == provider)
                for provider in ("nws", "open_meteo")
            },
            "fetch_failures": sorted(key for key, item in fetched.items() if item.error),
            "statuses": statuses,
            "horizon_days": args.horizon_days,
        },
        git_sha=args.git_sha,
    )
    for path in write_gameday_capture(capture, store=SnapshotStore(root=args.store, prefix="")):
        print(f"wrote {path}")
    print(json.dumps({"games": len(rows), **capture.details}, indent=2))
    # A forecast is context and a shadow input, never a gate: a failed provider is reported.
    return 0


def _capture_injuries(args: argparse.Namespace) -> int:
    from datetime import UTC, datetime

    from ffdraft.retention import SnapshotStore
    from ffdraft.sources.nflverse_http import nflverse_loaders
    from ffdraft.weekly.capture import INJURY_SOURCE_ID, GamedayCapture, write_gameday_capture
    from ffdraft.weekly.pit import PIT_COLUMNS, week_digests

    now = datetime.now(UTC).replace(microsecond=0)
    raw = nflverse_loaders().load_injuries(seasons=[args.season])
    frame = raw if isinstance(raw, pl.DataFrame) else pl.DataFrame(raw)
    digests = week_digests(frame)
    present = [column for column in PIT_COLUMNS if column in frame.columns]
    capture = GamedayCapture(
        source_id=INJURY_SOURCE_ID,
        season=args.season,
        observed_at_utc=now,
        rows=[dict(row) for row in frame.select(present).iter_rows(named=True)],
        details={
            "rule": digests["rule"],
            "weeks": {
                key: {name: value for name, value in week.items() if name != "row_digests"}
                for key, week in digests["weeks"].items()
            },
            "columns": present,
        },
        git_sha=args.git_sha,
    )
    for path in write_gameday_capture(capture, store=SnapshotStore(root=args.store, prefix="")):
        print(f"wrote {path}")
    print(json.dumps(capture.details["weeks"], indent=2))
    return 0


def _injury_pit(args: argparse.Namespace) -> int:
    from ffdraft.retention import SnapshotStore
    from ffdraft.weekly.capture import GAMEDAY_PREFIX, INJURY_SOURCE_ID, read_gameday_capture
    from ffdraft.weekly.pit import compare_captures, week_digests

    store = SnapshotStore(root=args.store, prefix="")
    keys = SnapshotStore(root=args.store, prefix=GAMEDAY_PREFIX).keys(INJURY_SOURCE_ID, args.season)
    if len(keys) < 2:
        print(f"{len(keys)} retained capture(s); a comparison needs two", file=sys.stderr)
        return 0
    first = read_gameday_capture(store, source_id=INJURY_SOURCE_ID, season=args.season, key=keys[0])
    last = read_gameday_capture(store, source_id=INJURY_SOURCE_ID, season=args.season, key=keys[-1])
    assert first is not None and last is not None
    report = compare_captures(
        week_digests(pl.DataFrame(first.rows)),
        week_digests(pl.DataFrame(last.rows)),
    )
    print(json.dumps({"earliest": keys[0], "latest": keys[-1], **report}, indent=2))
    return 0


def _retain_shadow(args: argparse.Namespace) -> int:
    from ffdraft.retention import SnapshotStore
    from ffdraft.timeutil import parse_utc
    from ffdraft.weekly.capture import SHADOW_SOURCE_ID, GamedayCapture, write_gameday_capture

    document = json.loads(args.file.read_text(encoding="utf-8"))
    rows = list(document.get("rows") or [])
    if not rows:
        print("the shadow record holds no rows; nothing to retain")
        return 0
    capture = GamedayCapture(
        source_id=SHADOW_SOURCE_ID,
        season=int(document["season"]),
        observed_at_utc=parse_utc(str(document["as_of_utc"])),
        rows=rows,
        details={key: value for key, value in document.items() if key != "rows"},
        git_sha=document.get("git_sha"),
    )
    for path in write_gameday_capture(capture, store=SnapshotStore(root=args.store, prefix="")):
        print(f"wrote {path}")
    return 0


def _evaluate_v2(args: argparse.Namespace, root: Path) -> int:
    from ffdraft.weekly.evaluate_v2 import run_v2_development
    from ffdraft.weekly.report_v2 import write_v2_report
    from ffdraft.weekly.weather import load_error_model

    data_dir = args.data or (root / DEFAULT_WEEKLY_DATA_DIR)
    out_dir = args.out or (root / DEFAULT_WEEKLY_V2_EXPERIMENT_DIR)
    frame = pl.read_parquet(data_dir / V2_ROWS_FILE)
    result = run_v2_development(
        frame,
        weather_parameters_digest=load_error_model().digest,
        progress=lambda message: print(message, flush=True),
    )
    for path in write_v2_report(result, out_dir):
        print(f"wrote {path}")
    result["_rows"].write_parquet(data_dir / "oof_v2_development.parquet", compression="zstd")
    print(f"outcome: {result['outcome']}; families: {result['v2_families']}")
    return 0


def _train_v2(args: argparse.Namespace, root: Path) -> int:
    from ffdraft.weekly.frozen import WEEKLY_TRAIN_START_SEASON
    from ffdraft.weekly.frozen_v2 import WEEKLY_V2_PREVIOUSLY_EXAMINED_SEASON, v2_spec
    from ffdraft.weekly.model import fit_weekly_model
    from ffdraft.weekly.weather import load_error_model

    data_dir = args.data or (root / DEFAULT_WEEKLY_DATA_DIR)
    reports = args.reports or (root / DEFAULT_WEEKLY_V2_EXPERIMENT_DIR)
    out_dir = args.out or (root / DEFAULT_WEEKLY_V2_MODEL_DIR)
    report = json.loads((reports / "experiment.json").read_text(encoding="utf-8"))
    if report.get("outcome") != "selected" or not report.get("v2_families"):
        print("v2 was not selected at development; no shadow model is fitted", file=sys.stderr)
        return 1
    spec = v2_spec(
        tuple(report["v2_families"]),
        weather_parameters_digest=load_error_model().digest,
    )
    frame = pl.read_parquet(data_dir / V2_ROWS_FILE).filter(
        (pl.col("season") >= WEEKLY_TRAIN_START_SEASON)
        & (pl.col("season") <= WEEKLY_V2_PREVIOUSLY_EXAMINED_SEASON),
    )
    model = fit_weekly_model(frame, spec=spec)
    written = model.save(
        out_dir,
        extra={"refit_reason": "shadow_fit_after_development_selection", "status": "shadow"},
    )
    print(f"wrote {written[-1]} ({len(written)} files); configuration {spec.configuration_hash()}")
    return 0


def _prospective(args: argparse.Namespace, root: Path) -> int:
    from ffdraft.retention import SnapshotStore
    from ffdraft.timeutil import parse_utc
    from ffdraft.weekly.capture import GAMEDAY_PREFIX, SHADOW_SOURCE_ID, read_gameday_capture
    from ffdraft.weekly.frozen_v2 import WEEKLY_V2_FROZEN_AT_UTC
    from ffdraft.weekly.prospective import eligible_rows, evidence_counts, prospective_verdict

    store = SnapshotStore(root=args.store, prefix="")
    keys = SnapshotStore(root=args.store, prefix=GAMEDAY_PREFIX).keys(SHADOW_SOURCE_ID, args.season)
    rows: list[dict[str, Any]] = []
    for key in keys:
        capture = read_gameday_capture(
            store, source_id=SHADOW_SOURCE_ID, season=args.season, key=key
        )
        if capture is not None:
            rows.extend(capture.rows)
    eligible = eligible_rows(rows, frozen_at=parse_utc(WEEKLY_V2_FROZEN_AT_UTC))
    scored = _join_outcomes(eligible, args.season)
    counts = evidence_counts(scored)
    if args.look is None:
        print(json.dumps({"captures": len(keys), "eligible": eligible.height, **counts}, indent=2))
        return 0
    verdict = prospective_verdict(scored, look=args.look, confirmation=args.confirm)
    out = args.out or (root / DEFAULT_WEEKLY_V2_EXPERIMENT_DIR)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"prospective_{args.look}.json"
    path.write_text(json.dumps(verdict, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(verdict, indent=2))
    return 0


def _join_outcomes(eligible: pl.DataFrame, season: int) -> pl.DataFrame:
    """Points in each eligible row's preset, for players who appeared (network: nflverse)."""
    if eligible.is_empty():
        return eligible
    from ffdraft.config import load_app_config
    from ffdraft.features.sources import load_historical_sources
    from ffdraft.ros.dataset import bridged_snap_counts
    from ffdraft.weekly.context import scored_position_rows
    from ffdraft.weekly.dataset import appearances

    config = load_app_config()
    sources = load_historical_sources(target_seasons=[season]).sources
    scored = scored_position_rows(sources.weekly_stats, config.league.scoring, [season])
    appeared = appearances(scored, bridged_snap_counts(sources), [season]).select(
        pl.col("season").cast(pl.Int32),
        pl.col("week").cast(pl.Int32).alias("target_week"),
        "gsis_id",
        "scoring_preset",
        pl.col("target_points").alias("actual"),
    )
    return eligible.with_columns(
        pl.col("season").cast(pl.Int32),
        pl.col("target_week").cast(pl.Int32),
    ).join(appeared, on=["season", "target_week", "gsis_id", "scoring_preset"], how="inner")


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
