"""``ffdraft`` command line.

Phase 1 exposes the commands the exit gate needs and nothing more:

``config-check``
    Load and validate every configuration file, and report the secret *presence* the MFL
    client would see. Values are never printed (ADR-017).

``build-fixture-artifacts``
    Run the network-free fixture mini-pipeline and write validated artifacts.

``validate-artifacts``
    Validate a directory of generated artifacts against `schemas/` **and** the semantic
    rules in `docs/DATA_CONTRACTS.md` sections 8 and 12.

Phase 2 adds three:

``build-historical``
    Fetch nflverse history, build the modelling dataset and write it with its quality
    report. This is the only command that touches the network.

``validate-historical``
    Re-run the leakage and semantic audits over an already-written dataset, so a build can
    be checked without rebuilding it.

``feature-dictionary``
    Print the feature dictionary as Markdown or JSON. The dictionary is code, so this is
    how the documentation stays in step with it.

Phase 3 adds one:

``evaluate-intrinsic``
    Run the rolling-origin development experiment over the historical dataset and write the
    machine-readable and human-readable reports. Season 2025 is sealed; the command cannot
    reach it without ``--final-eval`` *and* the exact confirmation token.

Phase 4 adds the development studies that choose the production system, each writing its
own experiment report and each restricted to development folds:

``evaluate-distribution``
    Stage B — the calibration, horizon-sensitivity and Candidate-A-versus-B decisions,
    taken by the rules ADR-030 froze before their evidence existed.

``evaluate-simulation``
    Stage C — the Monte Carlo convergence benchmark and the expected-versus-median VORP
    ranking comparison, over the out-of-fold predictions stage B wrote.

``evaluate-tiers``
    Stage C — tier penalty selection from the frozen grid and the bootstrap stability gate.

``train-production``
    Train the frozen architecture on every allowed season and write a versioned model
    artifact. Runs only after the final holdout has been consumed successfully.

``build-current``
    Build the current season's tier board from that artifact and write the public
    artifacts. Its information cutoff is the build timestamp, not a future draft anchor.

``model-card``
    Generate the intrinsic model card and the tier-method report from the committed
    experiment reports and the model artifact.

Phase 5 adds the market and arbitrage path. Exactly two of its commands touch a vendor
network; everything else reads retained evidence, which is what makes the analysis
reproducible offline and diffable against the commit that captured it:

``snapshot-market`` (network)
    Retrieve every requested MFL cohort plus the player directory and append one immutable
    point-in-time snapshot to the append-only store (ADR-006, ADR-038).

``capture-status`` (network)
    Retrieve and normalize Sleeper's current player map and retain it under the same
    append-only discipline (ADR-043).

``validate-market-history``
    Re-hash every retained file against its manifest and check the store's append-only
    invariants.

``measure-market-cohorts``
    Measure every cohort in a retained snapshot against the published fair board, judge it
    with the rule ADR-039 froze *before* the measurement existed, and select one cohort per
    preset. Offline and reproducible.

``build-arbitrage``
    Compute the deterministic A0 baseline from the published tier artifact and a retained
    snapshot, and write the arbitrage artifact (ADR-040).

``arbitrage-card``
    Generate the arbitrage method card from the artifacts and reports that produced it.

Exit status is 0 when the quality gate passes and 1 when a critical check fails, so CI can
branch on it directly.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import polars as pl

from ffdraft import __version__
from ffdraft.artifacts import validate_artifact_directory
from ffdraft.config import ConfigError, load_app_config
from ffdraft.contracts import CheckStatus, QualityCheck
from ffdraft.features.dictionary import (
    FEATURE_SCHEMA_VERSION,
    dictionary_markdown,
    feature_schema_hash,
    to_records,
)
from ffdraft.leakage import validate_historical_directory
from ffdraft.market.capture import capture_market, cohort_set
from ffdraft.market.snapshot import MARKET_PREFIX, SnapshotStore, verify_store
from ffdraft.modeling import (
    ExperimentConfig,
    FinalEvalAuthorization,
    HoldoutSealError,
    WindowPolicy,
    core_feature_selection,
    experiment_checks,
    load_modeling_dataset,
    run_experiment,
    write_report,
)
from ffdraft.modeling.cards import CardInputs, write_model_card, write_tier_method_report
from ffdraft.modeling.distribution import (
    DistributionConfig,
    run_distribution_study,
    write_distribution_report,
)
from ffdraft.modeling.experiment import run_final_holdout_evaluation
from ffdraft.modeling.production import train_production_model
from ffdraft.paths import repo_root
from ffdraft.pipeline import (
    DEFAULT_FIRST_SEASON,
    DEFAULT_HISTORICAL_DIR,
    build_fixture_artifacts,
    run_historical_build,
)
from ffdraft.pipeline.current import CurrentBuildConfig, run_current_build
from ffdraft.quality import QualityGate
from ffdraft.simulation.study import (
    SimulationStudyConfig,
    load_oof_predictions,
    run_simulation_study,
    write_simulation_report,
)
from ffdraft.tiers.study import TierStudyConfig, run_tier_study, write_tier_report
from ffdraft.timeutil import parse_utc

__all__ = ["main"]

DEFAULT_FIXTURE_DIR = Path("tests/fixtures/pipeline")
DEFAULT_ARTIFACT_DIR = Path("web/public/data")
DEFAULT_EXPERIMENT_DIR = Path("docs/experiments/phase3-intrinsic-baselines")
DEFAULT_DISTRIBUTION_DIR = Path("docs/experiments/phase4-intrinsic-distribution")
DEFAULT_PHASE4_DATA_DIR = Path("data/phase4")
DEFAULT_SIMULATION_DIR = Path("docs/experiments/phase4-simulation-ranking")
DEFAULT_TIER_DIR = Path("docs/experiments/phase4-tier-segmentation")
DEFAULT_HOLDOUT_DIR = Path("docs/experiments/phase4-final-holdout")
DEFAULT_MODEL_DIR = Path("models/production")
DEFAULT_CARD_DIR = Path("models/cards")
#: A checkout of the long-lived `market-data` branch (ADR-038). Defaulted beside the
#: repository rather than inside it: the store is a different branch, not a subdirectory.
DEFAULT_MARKET_STORE = Path("market-data")
DEFAULT_COHORT_DIR = Path("docs/market-cohorts")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        handler = args.handler
    except AttributeError:
        parser.print_help()
        return 2
    try:
        result: int = handler(args)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    except HoldoutSealError as exc:
        # A refusal, not a crash: the seal held, and saying so plainly is the whole point.
        print(f"final holdout is sealed: {exc}", file=sys.stderr)
        return 2
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ffdraft", description=__doc__)
    parser.add_argument("--version", action="version", version=f"ffdraft {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    check = subparsers.add_parser(
        "config-check",
        help="validate configuration and report source policy",
    )
    check.add_argument("--json", action="store_true", help="emit machine-readable output")
    check.set_defaults(handler=_config_check)

    build = subparsers.add_parser(
        "build-fixture-artifacts",
        help="run the network-free fixture pipeline and write artifacts",
    )
    build.add_argument("--fixtures", type=Path, default=None, help="fixture input directory")
    build.add_argument("--out", type=Path, default=None, help="artifact output directory")
    build.add_argument("--build-id", default=None, help="override the deterministic build id")
    build.add_argument("--generated-at", default=None, help="RFC 3339 build timestamp")
    build.add_argument("--git-sha", default=None, help="override the recorded git sha")
    build.set_defaults(handler=_build_fixture)

    validate = subparsers.add_parser(
        "validate-artifacts",
        help="validate generated artifacts against schemas and semantic rules",
    )
    validate.add_argument("directory", type=Path, nargs="?", default=None)
    validate.add_argument("--json", action="store_true", help="emit machine-readable output")
    validate.set_defaults(handler=_validate_artifacts)

    historical = subparsers.add_parser(
        "build-historical",
        help="build the historical modelling dataset (performs network I/O)",
    )
    historical.add_argument("--out", type=Path, default=None, help="output directory")
    historical.add_argument(
        "--first-season",
        type=int,
        default=DEFAULT_FIRST_SEASON,
        help=f"first target season (default {DEFAULT_FIRST_SEASON})",
    )
    historical.add_argument(
        "--last-season",
        type=int,
        required=True,
        help="last target season; must be a completed season with full labels",
    )
    historical.add_argument("--git-sha", default=None, help="code SHA to record in the manifest")
    historical.add_argument("--generated-at", default=None, help="RFC 3339 build timestamp")
    historical.add_argument(
        "--league-preset",
        action="append",
        default=None,
        help="league preset id to build VORP labels for; repeatable (default: launch presets)",
    )
    historical.add_argument(
        "--no-write",
        action="store_true",
        help="build and validate without writing any file",
    )
    historical.add_argument(
        "--skip-independence-check",
        action="store_true",
        help=(
            "skip the rebuild-with-target-season-deleted leakage proof; for iteration only, "
            "never for a dataset anything downstream will use"
        ),
    )
    historical.set_defaults(handler=_build_historical)

    check_historical = subparsers.add_parser(
        "validate-historical",
        help="re-run leakage and semantic audits over a written historical dataset",
    )
    check_historical.add_argument("directory", type=Path, nargs="?", default=None)
    check_historical.add_argument("--json", action="store_true", help="machine-readable output")
    check_historical.set_defaults(handler=_validate_historical)

    evaluate = subparsers.add_parser(
        "evaluate-intrinsic",
        help="run the Phase-3 rolling-origin experiment and write its reports",
    )
    evaluate.add_argument("--data", type=Path, default=None, help="historical dataset directory")
    evaluate.add_argument("--out", type=Path, default=None, help="report output directory")
    evaluate.add_argument(
        "--window",
        action="append",
        choices=[str(policy) for policy in WindowPolicy],
        default=None,
        help="training-window policy; repeatable (default: both)",
    )
    evaluate.add_argument(
        "--model",
        action="append",
        default=None,
        help="model id to run; repeatable (default: B0 B1 Q1)",
    )
    evaluate.add_argument("--seed", type=int, default=None, help="experiment seed")
    evaluate.add_argument(
        "--bootstrap-replicates",
        type=int,
        default=None,
        help="paired bootstrap replicates",
    )
    evaluate.add_argument(
        "--validation-season",
        action="append",
        type=int,
        default=None,
        help="development validation season; repeatable (default: 2020-2024)",
    )
    evaluate.add_argument(
        "--no-diagnostic-folds",
        action="store_true",
        help="skip the W1-only 2017-2019 diagnostic folds",
    )
    evaluate.add_argument(
        "--write-predictions",
        action="store_true",
        help="also write row-level predictions as Parquet for offline inspection",
    )
    evaluate.add_argument("--git-sha", default=None, help="code SHA to record in the report")
    evaluate.add_argument("--generated-at", default=None, help="RFC 3339 report timestamp")
    evaluate.add_argument("--json", action="store_true", help="emit machine-readable output")
    evaluate.add_argument(
        "--final-eval",
        action="store_true",
        help=(
            "evaluate the SEALED final holdout. Requires --confirm-final-eval and "
            "--final-eval-reason. Phase 3 must not use this."
        ),
    )
    evaluate.add_argument(
        "--confirm-final-eval",
        default=None,
        help="the exact confirmation token required to unseal the final holdout",
    )
    evaluate.add_argument(
        "--final-eval-reason",
        default=None,
        help="why the holdout is being consumed; recorded in the report",
    )
    evaluate.set_defaults(handler=_evaluate_intrinsic)

    distribution = subparsers.add_parser(
        "evaluate-distribution",
        help="run the Phase-4 stage-B distribution study and write its reports",
    )
    distribution.add_argument("--data", type=Path, default=None, help="historical dataset dir")
    distribution.add_argument("--out", type=Path, default=None, help="report output directory")
    distribution.add_argument(
        "--predictions-out",
        type=Path,
        default=None,
        help="directory for the promoted architecture's out-of-fold predictions",
    )
    distribution.add_argument("--seed", type=int, default=None, help="study seed")
    distribution.add_argument(
        "--bootstrap-replicates",
        type=int,
        default=None,
        help="paired bootstrap replicates",
    )
    distribution.add_argument(
        "--composition-draws",
        type=int,
        default=None,
        help="Monte Carlo draws used to compose Candidate B's two components",
    )
    distribution.add_argument(
        "--validation-season",
        action="append",
        type=int,
        default=None,
        help="development validation season; repeatable (default: 2020-2024)",
    )
    distribution.add_argument(
        "--no-references",
        action="store_true",
        help="skip the B0 and Q1 reference rows",
    )
    distribution.add_argument("--git-sha", default=None, help="code SHA to record")
    distribution.add_argument("--generated-at", default=None, help="RFC 3339 report timestamp")
    distribution.add_argument("--json", action="store_true", help="machine-readable output")
    distribution.set_defaults(handler=_evaluate_distribution)

    simulation = subparsers.add_parser(
        "evaluate-simulation",
        help="run the Phase-4 Monte Carlo convergence and ranking-statistic study",
    )
    simulation.add_argument("--data", type=Path, default=None, help="historical dataset dir")
    simulation.add_argument(
        "--predictions",
        type=Path,
        default=None,
        help="directory holding the stage-B out-of-fold predictions",
    )
    simulation.add_argument("--out", type=Path, default=None, help="report output directory")
    simulation.add_argument("--seed", type=int, default=None, help="study seed")
    simulation.add_argument("--git-sha", default=None, help="code SHA to record")
    simulation.add_argument("--generated-at", default=None, help="RFC 3339 report timestamp")
    simulation.set_defaults(handler=_evaluate_simulation)

    tiers = subparsers.add_parser(
        "evaluate-tiers",
        help="run the Phase-4 tier penalty selection and stability study",
    )
    tiers.add_argument("--data", type=Path, default=None, help="historical dataset dir")
    tiers.add_argument(
        "--predictions",
        type=Path,
        default=None,
        help="directory holding the stage-B out-of-fold predictions",
    )
    tiers.add_argument("--out", type=Path, default=None, help="report output directory")
    tiers.add_argument(
        "--simulation-report",
        type=Path,
        default=None,
        help="stage-C simulation report the draw count and ranking statistic come from",
    )
    tiers.add_argument("--draws", type=int, default=None, help="override the draw count")
    tiers.add_argument("--statistic", default=None, help="override the ranking statistic")
    tiers.add_argument(
        "--bootstrap-replicates",
        type=int,
        default=None,
        help="tier bootstrap replicates per scenario",
    )
    tiers.add_argument("--seed", type=int, default=None, help="study seed")
    tiers.add_argument("--git-sha", default=None, help="code SHA to record")
    tiers.add_argument("--generated-at", default=None, help="RFC 3339 report timestamp")
    tiers.set_defaults(handler=_evaluate_tiers)

    train = subparsers.add_parser(
        "train-production",
        help="train the frozen architecture and write a versioned model artifact",
    )
    train.add_argument("--data", type=Path, default=None, help="historical dataset directory")
    train.add_argument("--out", type=Path, default=None, help="model artifact root directory")
    train.add_argument(
        "--last-season",
        type=int,
        default=None,
        help="last training season (default: the frozen production window)",
    )
    train.add_argument("--git-sha", default=None, help="code SHA to record in the artifact")
    train.add_argument("--generated-at", default=None, help="RFC 3339 build timestamp")
    train.add_argument(
        "--allow-unsealed",
        action="store_true",
        help=(
            "train through the sealed season. Requires the final holdout to have been "
            "consumed, and the same confirmation token."
        ),
    )
    train.add_argument("--confirm-final-eval", default=None, help="the confirmation token")
    train.add_argument("--final-eval-reason", default=None, help="why the seal is open")
    train.set_defaults(handler=_train_production)

    current = subparsers.add_parser(
        "build-current",
        help="build the current season's tier board and write the public artifacts",
    )
    current.add_argument("--season", type=int, default=None, help="target season")
    current.add_argument("--model", type=Path, default=None, help="production model directory")
    current.add_argument("--out", type=Path, default=None, help="artifact output directory")
    current.add_argument("--as-of", default=None, help="RFC 3339 build timestamp")
    current.add_argument("--build-id", default=None, help="override the deterministic build id")
    current.add_argument("--git-sha", default=None, help="code SHA to record")
    current.add_argument("--draws", type=int, default=None, help="override the draw count")
    current.add_argument("--statistic", default=None, help="override the ranking statistic")
    current.add_argument("--penalty", type=float, default=None, help="override the tier penalty")
    current.add_argument("--no-write", action="store_true", help="build without writing files")
    current.add_argument(
        "--store",
        type=Path,
        default=None,
        help=(
            "market-data checkout supplying the retained Sleeper status capture; without "
            "it the status artifact ships degraded and the board is unaffected (ADR-043)"
        ),
    )
    current.set_defaults(handler=_build_current)

    card = subparsers.add_parser(
        "model-card",
        help="generate the intrinsic model card and the tier-method report",
    )
    card.add_argument("--model", type=Path, default=None, help="production model directory")
    card.add_argument("--out", type=Path, default=None, help="card output directory")
    card.add_argument("--data", type=Path, default=None, help="historical dataset directory")
    card.add_argument("--predictions", type=Path, default=None, help="out-of-fold prediction dir")
    card.add_argument("--git-sha", default=None, help="code SHA to record")
    card.set_defaults(handler=_model_card)

    snapshot = subparsers.add_parser(
        "snapshot-market",
        help="retrieve MFL cohorts and append one point-in-time snapshot (network)",
    )
    snapshot.add_argument("--season", type=int, default=None, help="market season")
    snapshot.add_argument(
        "--store",
        type=Path,
        default=None,
        help="checkout of the market-data branch (ADR-038)",
    )
    snapshot.add_argument(
        "--cohorts",
        default="production",
        help="'production', 'study', or a comma-separated cohort id list",
    )
    snapshot.add_argument("--as-of", default=None, help="RFC 3339 retrieval timestamp")
    snapshot.add_argument("--git-sha", default=None, help="code SHA to record")
    snapshot.add_argument(
        "--pause",
        type=float,
        default=1.0,
        help="seconds between MFL requests; MFL throttles over-limit clients",
    )
    snapshot.add_argument("--no-write", action="store_true", help="fetch without retaining")
    snapshot.set_defaults(handler=_snapshot_market)

    status_capture = subparsers.add_parser(
        "capture-status",
        help="retrieve Sleeper current player status and retain it (network)",
    )
    status_capture.add_argument("--season", type=int, default=None)
    status_capture.add_argument("--store", type=Path, default=None)
    status_capture.add_argument("--as-of", default=None, help="RFC 3339 retrieval timestamp")
    status_capture.add_argument("--git-sha", default=None)
    status_capture.add_argument("--no-write", action="store_true")
    status_capture.set_defaults(handler=_capture_status)

    history = subparsers.add_parser(
        "validate-market-history",
        help="verify the append-only snapshot store against its manifests",
    )
    history.add_argument("store", type=Path, nargs="?", default=None)
    history.add_argument("--season", type=int, default=None)
    history.add_argument("--source", default=None, help="source id to verify")
    history.set_defaults(handler=_validate_market_history)

    cohorts = subparsers.add_parser(
        "measure-market-cohorts",
        help="measure and select MFL cohorts from a retained snapshot (offline)",
    )
    cohorts.add_argument("--season", type=int, default=None)
    cohorts.add_argument("--store", type=Path, default=None)
    cohorts.add_argument("--snapshot", default=None, help="snapshot key; default is latest")
    cohorts.add_argument(
        "--board",
        type=Path,
        default=None,
        help="tier artifact directory supplying the reference fair board",
    )
    cohorts.add_argument("--out", type=Path, default=None, help="report output directory")
    cohorts.add_argument("--git-sha", default=None)
    cohorts.set_defaults(handler=_measure_market_cohorts)

    arbitrage = subparsers.add_parser(
        "build-arbitrage",
        help="build the deterministic A0 arbitrage board from retained prices (offline)",
    )
    arbitrage.add_argument("--season", type=int, default=None)
    arbitrage.add_argument("--store", type=Path, default=None)
    arbitrage.add_argument("--snapshot", default=None, help="snapshot key; default is latest")
    arbitrage.add_argument(
        "--artifacts",
        type=Path,
        default=None,
        help="artifact directory holding tiers.json; also the output directory",
    )
    arbitrage.add_argument(
        "--selection",
        type=Path,
        default=None,
        help="cohort report JSON; default is the newest under docs/market-cohorts",
    )
    arbitrage.add_argument("--as-of", default=None, help="RFC 3339 build timestamp")
    arbitrage.add_argument("--git-sha", default=None)
    arbitrage.add_argument("--no-write", action="store_true")
    arbitrage.set_defaults(handler=_build_arbitrage)

    arbitrage_card = subparsers.add_parser(
        "arbitrage-card",
        help="generate the arbitrage method card from the evidence that produced it",
    )
    arbitrage_card.add_argument("--artifacts", type=Path, default=None)
    arbitrage_card.add_argument("--selection", type=Path, default=None)
    arbitrage_card.add_argument("--out", type=Path, default=None)
    arbitrage_card.add_argument("--git-sha", default=None)
    arbitrage_card.set_defaults(handler=_arbitrage_card)

    dictionary = subparsers.add_parser(
        "feature-dictionary",
        help="print the historical feature dictionary",
    )
    dictionary.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
    )
    dictionary.set_defaults(handler=_feature_dictionary)

    return parser


def _config_check(args: argparse.Namespace) -> int:
    app = load_app_config()
    # Presence only. ADR-017 forbids printing, logging or serializing a secret value.
    presence = app.mfl_client.presence()
    payload = {
        "repo_root": str(app.root),
        "league": {
            "schema_version": app.league.schema_version,
            "default_preset": app.league.default_preset.preset_id,
            "presets": sorted(app.league.presets),
            "scoring_presets": sorted(str(preset) for preset in app.league.scoring),
        },
        "registry": {
            "schema_version": app.registry.schema_version,
            "arbitrage_mode": app.arbitrage_mode,
            "benchmark_only": sorted(app.registry.benchmark_only_sources),
            "policies": {
                source_id: str(entry.policy)
                for source_id, entry in sorted(app.registry.sources.items())
            },
        },
        "mfl_client_secrets_present": presence,
        "mfl_client_registered": app.mfl_client.registered,
        "mfl_client_warnings": list(app.mfl_client.warnings()),
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"repo root            {payload['repo_root']}")
        print(f"league config        v{app.league.schema_version}")
        print(f"default preset       {app.league.default_preset.preset_id}")
        print(f"source registry      v{app.registry.schema_version}")
        print(f"arbitrage mode       {app.arbitrage_mode}")
        print(f"benchmark-only       {', '.join(sorted(app.registry.benchmark_only_sources))}")
        rendered = ", ".join(
            f"{name}={'set' if is_present else 'unset'}" for name, is_present in presence.items()
        )
        print(f"mfl client secrets   {rendered}")
    return 0


def _build_fixture(args: argparse.Namespace) -> int:
    root = repo_root()
    fixtures = args.fixtures or (root / DEFAULT_FIXTURE_DIR)
    out_dir = args.out or (root / DEFAULT_ARTIFACT_DIR)
    generated_at = parse_utc(args.generated_at) if args.generated_at else None

    kwargs = {}
    if args.build_id:
        kwargs["build_id"] = args.build_id
    result = build_fixture_artifacts(
        fixture_dir=fixtures,
        out_dir=out_dir,
        generated_at=generated_at,
        git_sha=args.git_sha,
        **kwargs,
    )
    for path in result.written:
        print(f"wrote {path}")
    for artifact, records in sorted(result.records.items()):
        print(f"  {artifact}: {len(records)} record(s)")
    return _report_gate(result.gate)


def _validate_artifacts(args: argparse.Namespace) -> int:
    directory = args.directory or (repo_root() / DEFAULT_ARTIFACT_DIR)
    gate = validate_artifact_directory(directory)
    if args.json:
        print(json.dumps(gate.to_dict(), indent=2))
        return 0 if gate.passed else 1
    print(f"validating {directory}")
    return _report_gate(gate)


def _build_historical(args: argparse.Namespace) -> int:
    out_dir = args.out or (repo_root() / DEFAULT_HISTORICAL_DIR)
    seasons = tuple(range(args.first_season, args.last_season + 1))
    if not seasons:
        print(
            f"empty season range {args.first_season}-{args.last_season}",
            file=sys.stderr,
        )
        return 2
    generated_at = parse_utc(args.generated_at) if args.generated_at else None
    dataset, written = run_historical_build(
        out_dir=out_dir,
        seasons=seasons,
        generated_at=generated_at,
        git_sha=args.git_sha,
        league_preset_ids=args.league_preset,
        write=not args.no_write,
        verify_target_season_independence=not args.skip_independence_check,
    )
    print(
        f"seasons {seasons[0]}-{seasons[-1]}: "
        f"{dataset.features.height} feature row(s), "
        f"{dataset.fantasy_labels.height} fantasy label(s), "
        f"{dataset.vorp_labels.height} VORP label(s)",
    )
    for path in written:
        print(f"wrote {path}")
    return _report_gate(dataset.gate)


def _validate_historical(args: argparse.Namespace) -> int:
    directory = args.directory or (repo_root() / DEFAULT_HISTORICAL_DIR)
    gate = validate_historical_directory(directory)
    if args.json:
        print(json.dumps(gate.to_dict(), indent=2))
        return 0 if gate.passed else 1
    print(f"validating {directory}")
    return _report_gate(gate)


def _evaluate_intrinsic(args: argparse.Namespace) -> int:
    data_dir = args.data or (repo_root() / DEFAULT_HISTORICAL_DIR)
    out_dir = args.out or (repo_root() / DEFAULT_EXPERIMENT_DIR)
    generated_at = parse_utc(args.generated_at) if args.generated_at else None

    defaults = ExperimentConfig()
    windows = (
        tuple(WindowPolicy(value) for value in args.window) if args.window else defaults.windows
    )
    config = ExperimentConfig(
        windows=windows,
        model_ids=tuple(args.model) if args.model else defaults.model_ids,
        seed=args.seed if args.seed is not None else defaults.seed,
        bootstrap_replicates=(
            args.bootstrap_replicates
            if args.bootstrap_replicates is not None
            else defaults.bootstrap_replicates
        ),
        validation_seasons=(
            tuple(sorted(args.validation_season))
            if args.validation_season
            else defaults.validation_seasons
        ),
        include_w1_diagnostic_folds=not args.no_diagnostic_folds,
    )

    if args.final_eval:
        return _final_holdout_eval(args, data_dir=data_dir, out_dir=out_dir, config=config)

    selection = core_feature_selection()
    dataset = load_modeling_dataset(data_dir, selection=selection)
    print(
        f"modelling frame: {dataset.frame.height} row(s), seasons "
        f"{dataset.seasons[0]}-{dataset.seasons[-1]}; withheld "
        f"{dataset.withheld_rows} sealed row(s) from {list(dataset.withheld_seasons)}",
    )
    print(
        f"feature set {selection.version} ({selection.fingerprint()}): "
        f"{len(selection.included)} input(s), {len(selection.excluded)} excluded",
    )
    result = run_experiment(dataset, config=config)
    written = write_report(
        result,
        out_dir,
        git_sha=args.git_sha,
        generated_at=generated_at,
        write_predictions=args.write_predictions,
    )
    for path in written:
        print(f"wrote {path}")

    gate = QualityGate().extend(experiment_checks(result))
    if args.json:
        print(json.dumps(result.selection, indent=2, sort_keys=True))
    else:
        print(f"training window: {result.window_decision.selected}")
        print(f"promoted model : {result.selection.get('promoted_model') or 'none'}")
        print(f"runtime        : {result.runtime_seconds}s")
    return _report_gate(gate)


def _final_holdout_eval(
    args: argparse.Namespace,
    *,
    data_dir: Path,
    out_dir: Path,
    config: ExperimentConfig,
) -> int:
    """The sealed path. Deliberately verbose and deliberately hard to reach.

    The model set defaults to the permanent baseline plus the *frozen production*
    architecture, not to Phase 3's candidates: the holdout exists to judge what will ship.
    Passing ``--model`` overrides it, which is what the synthetic-data tests do.
    """
    from ffdraft.modeling.frozen import PRODUCTION_MODEL_ID

    if not args.model:
        config = replace(
            config,
            model_ids=(config.criteria.primary_baseline, PRODUCTION_MODEL_ID),
        )
    if not args.confirm_final_eval or not args.final_eval_reason:
        print(
            "--final-eval requires both --confirm-final-eval <token> and "
            "--final-eval-reason <why>; refusing to unseal the final holdout",
            file=sys.stderr,
        )
        return 2
    authorization = FinalEvalAuthorization(
        confirmation=args.confirm_final_eval,
        reason=args.final_eval_reason,
    )
    if len(config.windows) != 1:
        print(
            "the final holdout is evaluated against exactly one frozen training window; "
            "pass a single --window",
            file=sys.stderr,
        )
        return 2
    dataset = load_modeling_dataset(data_dir, authorization=authorization)
    result = run_final_holdout_evaluation(
        dataset,
        authorization=authorization,
        window=config.windows[0],
        config=config,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "final_holdout.json"
    path.write_text(json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {path}")
    print("FINAL HOLDOUT CONSUMED — it is no longer an untouched holdout")
    return _report_gate(QualityGate().extend(result.checks))


def _evaluate_distribution(args: argparse.Namespace) -> int:
    """Phase-4 stage B. Development folds only; the sealed season is dropped at load time."""
    data_dir = args.data or (repo_root() / DEFAULT_HISTORICAL_DIR)
    out_dir = args.out or (repo_root() / DEFAULT_DISTRIBUTION_DIR)
    predictions_dir = args.predictions_out or (repo_root() / DEFAULT_PHASE4_DATA_DIR)
    generated_at = parse_utc(args.generated_at) if args.generated_at else None

    defaults = DistributionConfig()
    config = DistributionConfig(
        window=defaults.window,
        validation_seasons=(
            tuple(sorted(args.validation_season))
            if args.validation_season
            else defaults.validation_seasons
        ),
        seed=args.seed if args.seed is not None else defaults.seed,
        bootstrap_replicates=(
            args.bootstrap_replicates
            if args.bootstrap_replicates is not None
            else defaults.bootstrap_replicates
        ),
        composition_draws=(
            args.composition_draws
            if args.composition_draws is not None
            else defaults.composition_draws
        ),
        include_references=not args.no_references,
    )

    selection = core_feature_selection()
    dataset = load_modeling_dataset(data_dir, selection=selection)
    print(
        f"modelling frame: {dataset.frame.height} row(s), seasons "
        f"{dataset.seasons[0]}-{dataset.seasons[-1]}; withheld "
        f"{dataset.withheld_rows} sealed row(s) from {list(dataset.withheld_seasons)}",
    )
    result = run_distribution_study(dataset, config=config)
    written = write_distribution_report(
        result,
        out_dir,
        git_sha=args.git_sha,
        generated_at=generated_at,
        predictions_dir=predictions_dir,
    )
    for path in written:
        print(f"wrote {path}")

    if args.json:
        print(json.dumps(result.selected, indent=2, sort_keys=True, default=str))
    else:
        print(f"calibration    : {result.calibration_decision.selected}")
        print(f"horizon        : {result.horizon_decision.selected}")
        print(f"candidate      : {result.candidate_decision.selected}")
        print(f"promoted       : {result.selected['model_id']}")
        print(f"runtime        : {result.runtime_seconds}s")
    return _report_gate(QualityGate().extend(result.checks))


def _phase4_inputs(args: argparse.Namespace) -> tuple[Any, Any, Any, Any]:
    """The three tables and the league config every stage-C study reads."""
    import polars as pl

    from ffdraft.modeling.distribution import OOF_PREDICTIONS_FILE

    data_dir = args.data or (repo_root() / DEFAULT_HISTORICAL_DIR)
    predictions_dir = args.predictions or (repo_root() / DEFAULT_PHASE4_DATA_DIR)
    predictions = load_oof_predictions(predictions_dir / OOF_PREDICTIONS_FILE)
    dataset = load_modeling_dataset(data_dir, selection=core_feature_selection())
    realized = pl.read_parquet(data_dir / "labels_vorp.parquet")
    return predictions, dataset.frame, realized, load_app_config().league


def _evaluate_simulation(args: argparse.Namespace) -> int:
    """Phase-4 stage C: draw count and ranking statistic. Development folds only."""
    out_dir = args.out or (repo_root() / DEFAULT_SIMULATION_DIR)
    generated_at = parse_utc(args.generated_at) if args.generated_at else None
    predictions, modelling_frame, realized, league = _phase4_inputs(args)

    defaults = SimulationStudyConfig()
    config = SimulationStudyConfig(
        seed=args.seed if args.seed is not None else defaults.seed,
        second_seed=(args.seed + 1) if args.seed is not None else defaults.second_seed,
    )
    print(
        f"out-of-fold predictions: {predictions.height} row(s), seasons "
        f"{sorted(set(predictions['season'].to_list()))}",
    )
    result = run_simulation_study(
        predictions,
        modelling_frame,
        realized,
        league,
        config=config,
    )
    for path in write_simulation_report(
        result,
        out_dir,
        git_sha=args.git_sha,
        generated_at=generated_at,
    ):
        print(f"wrote {path}")
    print(f"draw count     : {result.draws}")
    print(f"rank statistic : {result.statistic}")
    print(f"runtime        : {result.runtime_seconds}s")
    return _report_gate(QualityGate().extend(result.checks))


def _evaluate_tiers(args: argparse.Namespace) -> int:
    """Phase-4 stage C: tier penalty and stability. Development folds only."""
    out_dir = args.out or (repo_root() / DEFAULT_TIER_DIR)
    report_path = args.simulation_report or (
        repo_root() / DEFAULT_SIMULATION_DIR / "experiment.json"
    )
    generated_at = parse_utc(args.generated_at) if args.generated_at else None

    draws, statistic = args.draws, args.statistic
    if (draws is None or statistic is None) and report_path.is_file():
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        draws = draws if draws is not None else int(payload["selected_draws"])
        statistic = statistic or str(payload["selected_ranking_statistic"])
    if draws is None or statistic is None:
        print(
            "the tier study needs a draw count and a ranking statistic; run "
            "`ffdraft evaluate-simulation` first or pass --draws and --statistic",
            file=sys.stderr,
        )
        return 2

    predictions, modelling_frame, realized, league = _phase4_inputs(args)
    defaults = TierStudyConfig(draws=draws, statistic=statistic)
    config = TierStudyConfig(
        draws=draws,
        statistic=statistic,
        seed=args.seed if args.seed is not None else defaults.seed,
        bootstrap_replicates=(
            args.bootstrap_replicates
            if args.bootstrap_replicates is not None
            else defaults.bootstrap_replicates
        ),
    )
    print(f"tier study: {draws} draws, ranked by {statistic}")
    result = run_tier_study(predictions, modelling_frame, realized, league, config=config)
    for path in write_tier_report(
        result,
        out_dir,
        git_sha=args.git_sha,
        generated_at=generated_at,
    ):
        print(f"wrote {path}")
    print(f"penalty        : {result.penalty_decision.selected}")
    print(f"stability      : {result.stability_decision.selected}")
    print(f"runtime        : {result.runtime_seconds}s")
    return _report_gate(QualityGate().extend(result.checks))


def _production_model_dir(root: Path) -> Path:
    from ffdraft.modeling.frozen import PRODUCTION_SPEC

    return root / PRODUCTION_SPEC.model_version


def _train_production(args: argparse.Namespace) -> int:
    """Train the frozen architecture. The seal still has to be opened deliberately."""
    from ffdraft.modeling.frozen import (
        PRODUCTION_LAST_TRAINING_SEASON,
        PRODUCTION_SPEC,
    )

    data_dir = args.data or (repo_root() / DEFAULT_HISTORICAL_DIR)
    root = args.out or (repo_root() / DEFAULT_MODEL_DIR)
    last_season = args.last_season or PRODUCTION_LAST_TRAINING_SEASON
    generated_at = parse_utc(args.generated_at) if args.generated_at else None

    authorization = None
    if args.allow_unsealed:
        if not args.confirm_final_eval or not args.final_eval_reason:
            print(
                "--allow-unsealed requires both --confirm-final-eval <token> and "
                "--final-eval-reason <why>",
                file=sys.stderr,
            )
            return 2
        authorization = FinalEvalAuthorization(
            confirmation=args.confirm_final_eval,
            reason=args.final_eval_reason,
        )

    dataset = load_modeling_dataset(
        data_dir,
        selection=core_feature_selection(),
        authorization=authorization,
    )
    frame = dataset.frame.filter(pl.col("season") <= last_season)
    seasons = sorted(set(frame.get_column("season").to_list()))
    print(
        f"training {PRODUCTION_SPEC.model_version} on {frame.height} row(s), seasons "
        f"{seasons[0]}-{seasons[-1]}",
    )
    model = train_production_model(
        frame,
        spec=PRODUCTION_SPEC,
        dataset_manifest=dataset.dataset_manifest,
        git_sha=args.git_sha or "unknown",
        generated_at=generated_at,
    )
    out_dir = _production_model_dir(root)
    written = model.save(out_dir)
    print(f"wrote {len(written)} file(s) to {out_dir}")
    print(f"groups: {len(model.groups)}; features: {len(model.features)}")
    return 0


def _build_current(args: argparse.Namespace) -> int:
    """Build the current season's board. The cutoff is the build time, not a future anchor."""
    from ffdraft.modeling.frozen import (
        PRODUCTION_BUILD_CONFIG,
        PRODUCTION_SEASON,
    )

    season = args.season or PRODUCTION_SEASON
    root = repo_root() / DEFAULT_MODEL_DIR
    model_dir = args.model or _production_model_dir(root)
    out_dir = args.out or (repo_root() / DEFAULT_ARTIFACT_DIR)
    as_of = parse_utc(args.as_of) if args.as_of else None

    config = CurrentBuildConfig(
        draws=args.draws if args.draws is not None else PRODUCTION_BUILD_CONFIG.draws,
        ranking_statistic=args.statistic or PRODUCTION_BUILD_CONFIG.ranking_statistic,
        tier_algorithm=PRODUCTION_BUILD_CONFIG.tier_algorithm,
        tier_stability_gate=PRODUCTION_BUILD_CONFIG.tier_stability_gate,
        tier_penalty=(
            args.penalty if args.penalty is not None else PRODUCTION_BUILD_CONFIG.tier_penalty
        ),
        board_depth=PRODUCTION_BUILD_CONFIG.board_depth,
        seed=PRODUCTION_BUILD_CONFIG.seed,
        league_preset_ids=PRODUCTION_BUILD_CONFIG.league_preset_ids,
        scoring_presets=PRODUCTION_BUILD_CONFIG.scoring_presets,
    )
    result = run_current_build(
        season=season,
        model_dir=model_dir,
        out_dir=out_dir,
        config=config,
        as_of=as_of,
        build_id=args.build_id,
        git_sha=args.git_sha,
        status_store=_market_store(args.store) if args.store is not None else None,
        write=not args.no_write,
    )
    print(f"build id       : {result.build_id}")
    print(f"model version  : {result.model_version}")
    print(f"cutoff         : {result.cutoff.rule_version} @ {result.cutoff.anchor_at_utc}")
    for artifact, rows in sorted(result.records.items()):
        print(f"  {artifact}: {len(rows)} record(s)")
    for path in result.written:
        print(f"wrote {path}")
    return _report_gate(result.gate)


def _model_card(args: argparse.Namespace) -> int:
    """Generate the model card and tier-method report from the committed reports."""
    root = repo_root()
    model_dir = args.model or _production_model_dir(root / DEFAULT_MODEL_DIR)
    out_dir = args.out or (root / DEFAULT_CARD_DIR)
    data_dir = args.data or (root / DEFAULT_HISTORICAL_DIR)
    predictions_dir = args.predictions or (root / DEFAULT_PHASE4_DATA_DIR)

    inputs = CardInputs.load(
        model_dir,
        distribution=root / DEFAULT_DISTRIBUTION_DIR / "experiment.json",
        simulation=root / DEFAULT_SIMULATION_DIR / "experiment.json",
        tiers=root / DEFAULT_TIER_DIR / "experiment.json",
        final_holdout=root / DEFAULT_HOLDOUT_DIR / "final_holdout.json",
        oof_predictions=predictions_dir / "oof_predictions.parquet",
        fantasy_labels=data_dir / "labels_fantasy.parquet",
        current_build=out_dir / "current_build.json",
        git_sha=args.git_sha or "unknown",
    )
    written = [*write_model_card(inputs, out_dir), *write_tier_method_report(inputs, out_dir)]
    for path in written:
        print(f"wrote {path}")
    return 0


def _market_store(path: Path | None) -> SnapshotStore:
    """Resolve a store directory.

    The default sits *beside* the repository, not inside it: the store is a separate
    long-lived branch (ADR-038), and a default inside the working tree would invite someone
    to commit a day of captures onto a code branch.
    """
    root = path or (repo_root().parent / DEFAULT_MARKET_STORE)
    return SnapshotStore(root=root, prefix=MARKET_PREFIX)


def _snapshot_market(args: argparse.Namespace) -> int:
    """Retrieve MFL cohorts and append one immutable snapshot. **Network I/O.**"""
    from ffdraft.modeling.frozen import PRODUCTION_SEASON

    season = args.season or PRODUCTION_SEASON
    store = _market_store(args.store)
    result = capture_market(
        season=season,
        store=store,
        cohorts=cohort_set(args.cohorts),
        as_of=parse_utc(args.as_of) if args.as_of else None,
        git_sha=args.git_sha,
        write=not args.no_write,
        pause_seconds=args.pause,
    )
    print(f"snapshot       : {result.snapshot_key}")
    print(f"season         : {result.season}")
    print(f"cohorts        : {len(result.manifest.cohorts)}")
    for cohort in result.manifest.cohorts:
        print(
            f"  {cohort.cohort_id:>18}  rows={cohort.row_count:>4}  "
            f"drafts={cohort.total_drafts}  resolved="
            f"{cohort.resolved_players}/{cohort.resolvable_players}",
        )
    print(f"normalized rows: {len(result.rows)}")
    if result.write is not None:
        verb = "already retained (idempotent)" if result.write.idempotent else "retained"
        print(f"{verb}: {result.write.directory}")
    return _report_gate(result.gate)


def _capture_status(args: argparse.Namespace) -> int:
    """Retrieve Sleeper current status and retain it. **Network I/O.**"""
    from ffdraft.modeling.frozen import PRODUCTION_SEASON
    from ffdraft.status import capture_status, write_status_capture

    season = args.season or PRODUCTION_SEASON
    store = _market_store(args.store)
    gate = QualityGate()
    capture = capture_status(
        season=season,
        as_of=parse_utc(args.as_of) if args.as_of else None,
        git_sha=args.git_sha,
        gate=gate,
    )
    print(f"capture        : {capture.snapshot_key}")
    print(f"rows           : {len(capture.rows)}")
    if not args.no_write:
        for path in write_status_capture(capture, store=store):
            print(f"wrote {path}")
    return _report_gate(gate)


def _validate_market_history(args: argparse.Namespace) -> int:
    """Re-hash the retained store and check its append-only invariants."""
    from ffdraft.modeling.frozen import PRODUCTION_SEASON
    from ffdraft.sources.market import MFL_SOURCE_ID

    store = _market_store(args.store)
    season = args.season or PRODUCTION_SEASON
    source_id = args.source or MFL_SOURCE_ID
    verification = verify_store(store, source_id=source_id, season=season)
    print(f"store          : {store.root}")
    print(f"snapshots      : {verification.snapshots}")
    print(f"files checked  : {verification.files_checked}")
    for problem in verification.problems:
        print(f"  [critical] {problem}")
    print(f"market history : {'pass' if verification.ok else 'fail'}")
    return 0 if verification.ok else 1


def _reference_board(artifacts: Path, league_preset_id: str) -> Any:
    from ffdraft.market.measure import board_from_tier_records

    payload = json.loads((artifacts / "tiers.json").read_text(encoding="utf-8"))
    return board_from_tier_records(payload["records"], league_preset_id=league_preset_id)


def _launch_presets(app: Any) -> list[tuple[str, int]]:
    """Every (scoring preset, league size) the launch build publishes."""
    return sorted(
        {
            (str(scoring), preset.teams)
            for preset in app.league.presets.values()
            for scoring in ("STD", "HALF", "PPR")
        },
    )


def _measure_market_cohorts(args: argparse.Namespace) -> int:
    """Measure, judge and select cohorts from a retained snapshot. Offline."""
    from ffdraft.market.measure import measure_cohorts, report_markdown
    from ffdraft.modeling.frozen import PRODUCTION_SEASON
    from ffdraft.sources.market import MFL_SOURCE_ID
    from ffdraft.timeutil import utc_now

    app = load_app_config()
    season = args.season or PRODUCTION_SEASON
    store = _market_store(args.store)
    key = args.snapshot or store.latest_key(MFL_SOURCE_ID, season)
    if key is None:
        print(f"no retained snapshot for {MFL_SOURCE_ID}/{season} under {store.root}")
        return 1
    snapshot = store.read(MFL_SOURCE_ID, season, key)
    artifacts = args.board or (repo_root() / DEFAULT_ARTIFACT_DIR)
    board = _reference_board(artifacts, app.league.default_preset.preset_id)

    report = measure_cohorts(
        snapshot,
        board=board,
        presets=_launch_presets(app),
        generated_at=utc_now(),
        git_sha=args.git_sha,
    )
    out_dir = args.out or (repo_root() / DEFAULT_COHORT_DIR / key[:10])
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "cohorts.json").write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out_dir / "cohorts.md").write_text(report_markdown(report), encoding="utf-8")
    print(f"snapshot       : {key}")
    print(f"board          : {board.league_preset_id}, {', '.join(board.scoring_presets)}")
    for cohort_id in sorted(report.measurements):
        measurement = report.measurements[cohort_id]
        verdict = report.verdicts[cohort_id]
        print(
            f"  {cohort_id:>18}  priced={measurement.priced_players:>4}  "
            f"drafts={measurement.total_drafts}  top100={measurement.top100_board_coverage:.3f}  "
            f"{'SUFFICIENT' if verdict.sufficient else 'insufficient'}",
        )
    for _, assignment in sorted(report.assignments.items()):
        print(
            f"  {assignment.scoring_preset}/{assignment.league_size}: "
            f"{assignment.cohort.cohort_id} "
            f"({'exact' if assignment.exact else 'approximate'}) — {assignment.reason}",
        )
    print(f"wrote {out_dir / 'cohorts.json'}")
    print(f"wrote {out_dir / 'cohorts.md'}")
    return 0


def _newest_selection(root: Path) -> Path | None:
    candidates = sorted(root.glob("*/cohorts.json"))
    return candidates[-1] if candidates else None


def _build_arbitrage(args: argparse.Namespace) -> int:
    """Build the deterministic A0 arbitrage board. Offline."""
    from ffdraft.modeling.frozen import PRODUCTION_SEASON
    from ffdraft.pipeline.market import ArbitrageBuildRequest, run_arbitrage_build

    season = args.season or PRODUCTION_SEASON
    artifacts = args.artifacts or (repo_root() / DEFAULT_ARTIFACT_DIR)
    selection = args.selection or _newest_selection(repo_root() / DEFAULT_COHORT_DIR)
    if selection is None:
        print(
            "no cohort selection found; run `ffdraft measure-market-cohorts` first "
            "(ADR-039 requires the rule to decide before a board is published)",
        )
        return 1
    result = run_arbitrage_build(
        ArbitrageBuildRequest(
            season=season,
            store=_market_store(args.store),
            snapshot_key=args.snapshot,
            artifacts_dir=artifacts,
            selection_path=selection,
            as_of=parse_utc(args.as_of) if args.as_of else None,
            git_sha=args.git_sha,
            write=not args.no_write,
        ),
    )
    print(f"build id       : {result.build_id}")
    print(f"snapshot       : {result.snapshot_key}")
    print(f"arbitrage mode : {result.arbitrage_mode} ({result.method_version})")
    print(f"records        : {len(result.records)}")
    print(f"confidence     : {result.confidence_counts}")
    print(f"trend          : {'available' if result.trend_available else 'null (no history)'}")
    for path in result.written:
        print(f"wrote {path}")
    return _report_gate(result.gate)


def _arbitrage_card(args: argparse.Namespace) -> int:
    """Generate the arbitrage method card from committed evidence."""
    from ffdraft.arbitrage.card import write_arbitrage_card

    artifacts = args.artifacts or (repo_root() / DEFAULT_ARTIFACT_DIR)
    selection = args.selection or _newest_selection(repo_root() / DEFAULT_COHORT_DIR)
    out_dir = args.out or (repo_root() / DEFAULT_CARD_DIR)
    written = write_arbitrage_card(
        artifacts_dir=artifacts,
        selection_path=selection,
        out_dir=out_dir,
        git_sha=args.git_sha or "unknown",
    )
    for path in written:
        print(f"wrote {path}")
    return 0


def _feature_dictionary(args: argparse.Namespace) -> int:
    if args.format == "json":
        print(json.dumps(to_records(), indent=2, sort_keys=True))
    else:
        print(f"# Feature dictionary ({FEATURE_SCHEMA_VERSION}, {feature_schema_hash()})")
        print()
        print(dictionary_markdown())
    return 0


def _report_gate(gate: QualityGate) -> int:
    failures = [check for check in gate.checks if check.status is CheckStatus.FAIL]
    for check in failures:
        print(f"  [{check.severity}] {check.check_id} ({check.stage}): {_describe(check)}")
    print(
        f"quality gate: {gate.summary()['status']} "
        f"({len(gate.critical_failures)} critical, {len(gate.warnings)} warning)",
    )
    return 0 if gate.passed else 1


def _describe(check: QualityCheck) -> str:
    detail = check.message
    if check.observed:
        detail = f"{detail} — observed: {check.observed}"
    if check.expected:
        detail = f"{detail}; expected: {check.expected}"
    return detail


if __name__ == "__main__":  # pragma: no cover - exercised through the console script
    raise SystemExit(main())
