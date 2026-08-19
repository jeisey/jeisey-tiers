"""The historical modelling-dataset build.

One entry point orchestrates the whole Phase-2 pipeline:

    sources -> anchors -> eligibility -> features -> labels -> VORP -> quality gate

:func:`build_historical_dataset` is pure with respect to I/O: it takes already-normalized
frames, so the integration tests drive the entire pipeline from fixtures with no network.
:func:`run_historical_build` adds the fetch and the write, and is what the CLI calls.

**Reproducibility is a property of the manifest, not a promise.** Every build writes
``build_manifest.json`` recording the code SHA, the config versions, the feature schema
hash, the season windows, the row counts and a content hash of each table. Two builds of the
same source releases produce the same hashes; a differing hash means an input moved, which
is exactly what a reproducibility claim has to be able to detect.

Outputs are Parquet because the modelling tables are typed and columnar, and they are
written outside version control (`AGENTS.md` section 15): the dataset is reproducible from
code plus source releases, so committing it would trade review clarity for nothing.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

from ffdraft.anchors import DRAFT_ANCHOR_RULE_VERSION, SeasonAnchor, anchors_to_frame
from ffdraft.config import AppConfig, load_app_config
from ffdraft.contracts import QualityCheck, frame_content_hash
from ffdraft.features.build import HistoricalSources, build_feature_table
from ffdraft.features.dictionary import (
    FEATURE_SCHEMA_VERSION,
    feature_lineage,
    feature_schema_hash,
    intrinsic_feature_names,
)
from ffdraft.features.report import HistoricalQualityReport, build_quality_report
from ffdraft.features.sources import LoadedSources, load_historical_sources, season_windows
from ffdraft.labels import build_fantasy_labels, build_vorp_labels
from ffdraft.leakage import audit_historical_features, audit_target_season_independence
from ffdraft.quality import (
    QualityGate,
    audit_intrinsic_feature_names,
    audit_intrinsic_source_lineage,
)
from ffdraft.quality.thresholds import HistoricalThresholds
from ffdraft.scoring.engine import SCORING_ENGINE_VERSION, reconcile_with_upstream
from ffdraft.timeutil import isoformat_utc, utc_now

__all__ = [
    "DATASET_VERSION",
    "DEFAULT_FIRST_SEASON",
    "DEFAULT_HISTORICAL_DIR",
    "HistoricalDataset",
    "build_historical_dataset",
    "default_target_seasons",
    "run_historical_build",
    "write_historical_dataset",
]

#: Bump when the dataset's construction changes in a way that makes an existing build stale.
DATASET_VERSION = "historical_v1"

#: Earliest target season. Snap counts begin in 2013 upstream, so 2014 is the first season
#: whose *previous-season* snap share exists - and prior-season role is ADR-018's proxy for
#: depth in every pre-2025 season, so a target season without it would be missing the whole
#: role family.
DEFAULT_FIRST_SEASON = 2014

DEFAULT_HISTORICAL_DIR = Path("data/historical")

_FEATURES_FILE = "features.parquet"
_FANTASY_LABELS_FILE = "labels_fantasy.parquet"
_VORP_LABELS_FILE = "labels_vorp.parquet"
_ANCHORS_FILE = "anchors.parquet"
_EXCLUSIONS_FILE = "excluded_rows.parquet"
_REPORT_JSON = "quality_report.json"
_REPORT_MARKDOWN = "quality_report.md"
_MANIFEST_FILE = "build_manifest.json"
_DICTIONARY_FILE = "feature_dictionary.md"


def default_target_seasons(last_completed_season: int) -> tuple[int, ...]:
    """Target seasons from :data:`DEFAULT_FIRST_SEASON` through the last labelled season."""
    if last_completed_season < DEFAULT_FIRST_SEASON:
        raise ValueError(
            f"last completed season {last_completed_season} precedes the first supported "
            f"target season {DEFAULT_FIRST_SEASON}",
        )
    return tuple(range(DEFAULT_FIRST_SEASON, last_completed_season + 1))


@dataclass
class HistoricalDataset:
    """Everything one historical build produced."""

    features: pl.DataFrame
    fantasy_labels: pl.DataFrame
    vorp_labels: pl.DataFrame
    anchors: dict[int, SeasonAnchor]
    exclusions: pl.DataFrame
    report: HistoricalQualityReport
    gate: QualityGate
    manifest: dict[str, Any] = field(default_factory=dict)

    @property
    def seasons(self) -> tuple[int, ...]:
        return tuple(sorted(self.anchors))

    def tables(self) -> dict[str, pl.DataFrame]:
        return {
            _FEATURES_FILE: self.features,
            _FANTASY_LABELS_FILE: self.fantasy_labels,
            _VORP_LABELS_FILE: self.vorp_labels,
            _ANCHORS_FILE: anchors_to_frame(self.anchors),
            _EXCLUSIONS_FILE: self.exclusions,
        }


def build_historical_dataset(
    sources: HistoricalSources,
    *,
    config: AppConfig,
    seasons: Sequence[int],
    generated_at: datetime | None = None,
    git_sha: str | None = None,
    league_preset_ids: Sequence[str] | None = None,
    upstream_checks: Sequence[QualityCheck] = (),
    source_metadata: Sequence[Mapping[str, Any]] = (),
    verify_target_season_independence: bool = True,
    thresholds: HistoricalThresholds | None = None,
) -> HistoricalDataset:
    """Run the full Phase-2 pipeline over already-normalized source frames.

    ``verify_target_season_independence`` rebuilds every season with its own statistics
    deleted and asserts the table is unchanged - the constructive proof of leakage rules 1
    and 6. It roughly triples build time and defaults to on, because a dataset that has not
    been proved leakage-free is not a dataset this project ships.
    """
    built_at = generated_at or utc_now()

    result = build_feature_table(sources, config=config, seasons=seasons)
    eligible = result.features.select("season", "player_id", "gsis_id", "position")
    fantasy_labels = build_fantasy_labels(eligible, sources.weekly_stats, config.league.scoring)
    vorp_labels = build_vorp_labels(
        fantasy_labels,
        config.league,
        preset_ids=league_preset_ids,
    )

    checks: list[QualityCheck] = [*upstream_checks, *result.checks]
    # The forbidden-feature audit runs over the *built* model-input set and its declared
    # lineage, not over an aspirational list, so adding a market-derived column would fail
    # the build rather than a code review (ADR-002).
    checks.extend(audit_intrinsic_feature_names(intrinsic_feature_names()))
    checks.extend(
        audit_intrinsic_source_lineage(feature_lineage(), registry=config.registry),
    )
    checks.extend(reconcile_with_upstream(sources.weekly_stats, config.league.scoring))
    checks.extend(
        audit_historical_features(
            result.features,
            registry=config.registry,
            anchors=result.anchors,
        ),
    )
    if verify_target_season_independence:
        checks.extend(
            audit_target_season_independence(sources, config=config, seasons=seasons),
        )

    report = build_quality_report(
        features=result.features,
        fantasy_labels=fantasy_labels,
        vorp_labels=vorp_labels,
        anchors=result.anchors,
        exclusions=result.exclusions,
        config=config,
        generated_at=built_at,
        dataset_version=DATASET_VERSION,
        upstream_checks=checks,
        source_metadata=source_metadata,
        thresholds=thresholds,
    )

    gate = QualityGate().extend(report.checks)
    dataset = HistoricalDataset(
        features=result.features,
        fantasy_labels=fantasy_labels,
        vorp_labels=vorp_labels,
        anchors=result.anchors,
        exclusions=result.exclusions,
        report=report,
        gate=gate,
    )
    dataset.manifest = _manifest(
        dataset,
        config=config,
        generated_at=built_at,
        git_sha=git_sha,
        seasons=seasons,
    )
    return dataset


def _manifest(
    dataset: HistoricalDataset,
    *,
    config: AppConfig,
    generated_at: datetime,
    git_sha: str | None,
    seasons: Sequence[int],
) -> dict[str, Any]:
    windows = season_windows(seasons)
    return {
        "dataset_version": DATASET_VERSION,
        "generated_at_utc": isoformat_utc(generated_at),
        "git_sha": git_sha or "unknown",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_schema_hash": feature_schema_hash(),
        "scoring_engine_version": SCORING_ENGINE_VERSION,
        "feature_cutoff_rule_version": DRAFT_ANCHOR_RULE_VERSION,
        "league_config_version": config.league.schema_version,
        "source_registry_version": config.registry.schema_version,
        "season_windows": windows.describe(),
        "row_counts": {name: frame.height for name, frame in dataset.tables().items()},
        "content_hashes": {
            name: frame_content_hash(frame) for name, frame in dataset.tables().items()
        },
        "quality_gate": dataset.gate.summary(),
    }


def write_historical_dataset(dataset: HistoricalDataset, out_dir: Path) -> list[Path]:
    """Write the tables, the report and the manifest. Nothing is written if the gate failed.

    Same rule as the public artifacts (`docs/OPERATIONS.md` section 8): a failed critical
    check leaves whatever was there before intact, so a bad run cannot replace a good
    dataset with a broken one.
    """
    dataset.gate.raise_if_blocked()
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, frame in dataset.tables().items():
        path = out_dir / name
        frame.write_parquet(path, compression="zstd")
        written.append(path)

    from ffdraft.features.dictionary import dictionary_markdown

    for name, text in (
        (_REPORT_JSON, dataset.report.to_json()),
        (_REPORT_MARKDOWN, dataset.report.to_markdown()),
        (_MANIFEST_FILE, json.dumps(dataset.manifest, indent=2, sort_keys=True) + "\n"),
        (
            _DICTIONARY_FILE,
            "# Feature dictionary\n\n"
            f"Schema `{FEATURE_SCHEMA_VERSION}` (`{feature_schema_hash()}`).\n\n"
            + dictionary_markdown()
            + "\n",
        ),
    ):
        path = out_dir / name
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written


def run_historical_build(
    *,
    out_dir: Path,
    seasons: Sequence[int],
    config: AppConfig | None = None,
    generated_at: datetime | None = None,
    git_sha: str | None = None,
    league_preset_ids: Sequence[str] | None = None,
    write: bool = True,
    verify_target_season_independence: bool = True,
) -> tuple[HistoricalDataset, list[Path]]:
    """Fetch, build, validate and (unless ``write`` is false) persist the dataset."""
    app = config or load_app_config()
    loaded: LoadedSources = load_historical_sources(target_seasons=seasons, as_of=generated_at)
    dataset = build_historical_dataset(
        loaded.sources,
        config=app,
        seasons=seasons,
        generated_at=generated_at,
        git_sha=git_sha,
        league_preset_ids=league_preset_ids,
        upstream_checks=loaded.checks,
        source_metadata=loaded.metadata_records(),
        verify_target_season_independence=verify_target_season_independence,
    )
    written = write_historical_dataset(dataset, out_dir) if write else []
    return dataset, written


def load_historical_dataset(directory: Path) -> dict[str, pl.DataFrame]:
    """Read a previously written dataset back, for validation and inspection."""
    tables: dict[str, pl.DataFrame] = {}
    for name in (
        _FEATURES_FILE,
        _FANTASY_LABELS_FILE,
        _VORP_LABELS_FILE,
        _ANCHORS_FILE,
        _EXCLUSIONS_FILE,
    ):
        path = directory / name
        if path.is_file():
            tables[name] = pl.read_parquet(path)
    return tables
