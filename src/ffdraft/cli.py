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
from ffdraft.paths import repo_root
from ffdraft.pipeline import build_fixture_artifacts
from ffdraft.quality import QualityGate
from ffdraft.timeutil import parse_utc

__all__ = ["main"]

DEFAULT_FIXTURE_DIR = Path("tests/fixtures/pipeline")
DEFAULT_ARTIFACT_DIR = Path("web/public/data")


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
