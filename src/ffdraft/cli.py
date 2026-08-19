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
    reach it without ``--final-eval`` *and* the exact confirmation token, and Phase 3 never
    runs that path.

Exit status is 0 when the quality gate passes and 1 when a critical check fails, so CI can
branch on it directly.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

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
from ffdraft.modeling.experiment import run_final_holdout_evaluation
from ffdraft.paths import repo_root
from ffdraft.pipeline import (
    DEFAULT_FIRST_SEASON,
    DEFAULT_HISTORICAL_DIR,
    build_fixture_artifacts,
    run_historical_build,
)
from ffdraft.quality import QualityGate
from ffdraft.timeutil import parse_utc

__all__ = ["main"]

DEFAULT_FIXTURE_DIR = Path("tests/fixtures/pipeline")
DEFAULT_ARTIFACT_DIR = Path("web/public/data")
DEFAULT_EXPERIMENT_DIR = Path("docs/experiments/phase3-intrinsic-baselines")


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
    """The sealed path. Deliberately verbose and deliberately hard to reach."""
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
