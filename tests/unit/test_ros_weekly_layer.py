"""``build-ros`` withholds a weekly layer the pre-deploy validator would refuse (ADR-096).

Found on the live 2026 week-4 build: a weekly-shape defect passed the build's own gate and
would have failed ``validate-artifacts`` in daily-refresh.yml, blocking the deploy of every
board. The weekly layer is an enrichment; its defects must cost it alone.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import polars as pl
import pytest

import ffdraft.weekly.serve as serve_module
from ffdraft.pipeline.ros import _weekly_layer
from ffdraft.quality import QualityGate
from ffdraft.weekly.serve import WeeklyServeResult


def _run(monkeypatch: pytest.MonkeyPatch, app_config: Any, records: list[dict[str, Any]]):
    monkeypatch.setattr(
        serve_module,
        "build_weekly_projection_records",
        lambda **_: WeeklyServeResult(
            records,
            {
                "target_week": 9,
                "records": len(records),
                "upcoming": len(records),
                "kicked_off": 0,
                "bye": 0,
                "lines_pending": 0,
                "injury_reports_matched": 0,
            },
        ),
    )
    gate = QualityGate()
    published, metadata = _weekly_layer(
        model_dir=None,
        snapshot_frame=pl.DataFrame(),
        opportunity_records=[],
        roster=pl.DataFrame(),
        loaded=SimpleNamespace(
            sources=SimpleNamespace(weekly_stats=pl.DataFrame(), schedule=pl.DataFrame())
        ),
        settings=app_config,
        season=2026,
        cutoff=SimpleNamespace(through_week=8),
        build_id="test",
        as_of=datetime(2026, 11, 3, tzinfo=UTC),
        gate=gate,
        injuries=None,
        allow_fetch=False,
    )
    return published, metadata, gate


def test_an_invalid_weekly_record_withholds_the_layer_and_nothing_else(
    monkeypatch: pytest.MonkeyPatch,
    app_config: Any,
    pipeline_result: Any,
) -> None:
    records = [dict(row) for row in pipeline_result.records["weekly_projections"]]
    pending = next(row for row in records if row["game_state"] == "lines_pending")
    pending["game"] = {**pending["game"], "total_line": 44.5, "team_margin": 3.0}
    published, metadata, gate = _run(monkeypatch, app_config, records)
    assert published == [] and metadata is None
    assert gate.passed  # a warning, never a critical
    check = next(
        check for check in gate.checks if check.check_id == "ros.weekly_projections_invalid"
    )
    assert "weekly.record_shape" in check.observed


def test_valid_weekly_records_are_published(
    monkeypatch: pytest.MonkeyPatch,
    app_config: Any,
    pipeline_result: Any,
) -> None:
    records = [dict(row) for row in pipeline_result.records["weekly_projections"]]
    published, metadata, gate = _run(monkeypatch, app_config, records)
    assert len(published) == len(records)
    assert metadata is not None and metadata["lines_pending"] == 0
    assert not any(check.check_id == "ros.weekly_projections_invalid" for check in gate.checks)


def test_the_weekly_metadata_the_layer_writes_is_the_published_contract(
    monkeypatch: pytest.MonkeyPatch,
    app_config: Any,
    pipeline_result: Any,
) -> None:
    """Every key ``_weekly_layer`` adds (explanation, context, the shadow summary) is in the
    schema: ``ros_build_metadata.weekly`` forbids unknown keys, and the fixture build does not
    reach the shadow path, so this is where a missing schema entry would show (ADR-099)."""
    import json

    import jsonschema

    from ffdraft.paths import repo_root

    records = [dict(row) for row in pipeline_result.records["weekly_projections"]]
    _, metadata, _ = _run(monkeypatch, app_config, records)
    assert metadata is not None
    published = {key: value for key, value in metadata.items() if not key.startswith("_")}
    assert published["shadow"]["model_version"] == "weekly-startsit-v2"
    assert published["shadow"]["status"] == "absent"
    root = json.loads(
        (repo_root() / "schemas" / "ros_build_metadata.schema.json").read_text(encoding="utf-8")
    )
    schema = {"$defs": root.get("$defs", {}), **root["properties"]["weekly"]}
    jsonschema.validate(json.loads(json.dumps(published, default=str)), schema)
