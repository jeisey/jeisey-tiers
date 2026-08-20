"""Status metadata annotates a board. It can never change one (ADR-043).

This is the test that makes "annotation only" a fact instead of an intention. It mutates
every field of every status row a build can see — injury designation, body part, notes,
practice participation, depth-chart order, the lot — rebuilds, and asserts the tier,
projection and arbitrage artifacts come out **byte-identical**.

Why bytes rather than "the ranks look the same": the intrinsic model was validated on
`intrinsic_core_v1` and on nothing else. A current-state field has no development-era
support and could not have been validated, so the guarantee that matters is that it has no
path into a prediction at all — not that it happens to move it a little.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ffdraft.pipeline import build_fixture_artifacts
from ffdraft.pipeline.fixture_pipeline import load_fixture_inputs, run_fixture_pipeline

#: Artifacts whose numbers come from the model. None of them may move.
MODEL_ARTIFACTS = ("tiers.json", "tiers.csv", "projections.json", "projections.csv")
#: The arbitrage board is market x intrinsic. Status is not an input to either.
MARKET_ARTIFACTS = ("arbitrage.json", "arbitrage.csv", "market_snapshot.json")


def _mutate_status(payload: dict) -> dict:
    """Rewrite every status field a build reads, without touching identity."""
    mutated = copy.deepcopy(payload)
    for index, record in enumerate(mutated.values()):
        record["status"] = "Injured Reserve"
        record["injury_status"] = "Out"
        record["injury_body_part"] = "Achilles"
        record["injury_notes"] = f"Fabricated note {index}"
        record["injury_start_date"] = "2026-08-01"
        record["practice_participation"] = "Did Not Participate"
        record["practice_description"] = "Did not practice all week"
        record["depth_chart_order"] = 9
    return mutated


@pytest.fixture
def inputs(pipeline_fixture_dir: Path):
    return load_fixture_inputs(pipeline_fixture_dir)


def _build(tmp_path: Path, fixture_dir: Path, app_config, name: str) -> Path:
    out = tmp_path / name
    build_fixture_artifacts(
        fixture_dir=fixture_dir,
        out_dir=out,
        config=app_config,
        git_sha="0000000",
    )
    return out


def _write_fixture_dir(source: Path, target: Path, sleeper: dict) -> Path:
    target.mkdir(parents=True, exist_ok=True)
    for path in source.glob("*.json"):
        target.joinpath(path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    target.joinpath("sleeper_players.json").write_text(
        json.dumps(sleeper, indent=2),
        encoding="utf-8",
    )
    return target


def test_changing_every_injury_field_cannot_move_a_model_number(
    tmp_path,
    pipeline_fixture_dir,
    app_config,
    inputs,
):
    baseline = _build(tmp_path, pipeline_fixture_dir, app_config, "baseline")
    mutated_dir = _write_fixture_dir(
        pipeline_fixture_dir,
        tmp_path / "mutated-fixtures",
        _mutate_status(inputs.sleeper_players),
    )
    mutated = _build(tmp_path, mutated_dir, app_config, "mutated")

    for name in MODEL_ARTIFACTS:
        assert (baseline / name).read_bytes() == (mutated / name).read_bytes(), name


def test_changing_every_injury_field_cannot_move_an_arbitrage_score(
    tmp_path,
    pipeline_fixture_dir,
    app_config,
    inputs,
):
    baseline = _build(tmp_path, pipeline_fixture_dir, app_config, "baseline")
    mutated_dir = _write_fixture_dir(
        pipeline_fixture_dir,
        tmp_path / "mutated-fixtures",
        _mutate_status(inputs.sleeper_players),
    )
    mutated = _build(tmp_path, mutated_dir, app_config, "mutated")

    for name in MARKET_ARTIFACTS:
        assert (baseline / name).read_bytes() == (mutated / name).read_bytes(), name


def test_the_status_artifact_itself_does_change(
    tmp_path,
    pipeline_fixture_dir,
    app_config,
    inputs,
):
    """The negative tests above would pass trivially if nothing read the fixture at all."""
    baseline = _build(tmp_path, pipeline_fixture_dir, app_config, "baseline")
    mutated_dir = _write_fixture_dir(
        pipeline_fixture_dir,
        tmp_path / "mutated-fixtures",
        _mutate_status(inputs.sleeper_players),
    )
    mutated = _build(tmp_path, mutated_dir, app_config, "mutated")

    before = json.loads((baseline / "player_status.json").read_text())["records"]
    after = json.loads((mutated / "player_status.json").read_text())["records"]
    assert before != after
    # Players the Sleeper map does not carry keep null annotations either way; the ones it
    # does carry must all have moved.
    annotated = [record for record in after if record["sleeper_status"] is not None]
    assert annotated
    assert {record["injury_status"] for record in annotated} == {"Out"}
    assert all(record["practice_description"] for record in annotated)


def test_no_status_field_appears_in_a_tier_or_arbitrage_record(app_config, pipeline_fixture_dir):
    """A cheaper, structural version of the same guarantee: the fields are not even there."""
    result = run_fixture_pipeline(load_fixture_inputs(pipeline_fixture_dir), config=app_config)
    status_only = {
        "sleeper_status",
        "injury_status",
        "injury_body_part",
        "injury_notes",
        "injury_start_date",
        "practice_participation",
        "practice_description",
        "depth_chart_order",
    }
    for artifact in ("tiers", "arbitrage", "projections"):
        for record in result.records[artifact]:
            assert not status_only & set(record), artifact


def test_the_status_artifact_is_keyed_once_per_player(app_config, pipeline_fixture_dir):
    """Nine tier rows per player; one status row. That is the point of the artifact."""
    result = run_fixture_pipeline(load_fixture_inputs(pipeline_fixture_dir), config=app_config)
    status = result.records["player_status"]
    ids = [record["player_id"] for record in status]
    assert len(ids) == len(set(ids))

    tier_ids = {record["player_id"] for record in result.records["tiers"]}
    assert set(ids) == tier_ids
    assert len(result.records["tiers"]) > len(status)


def test_a_failed_gsis_cross_check_leaves_the_player_without_sleeper_data(
    app_config,
    pipeline_fixture_dir,
):
    """ADR-019: a failed cross-check is fatal for the record, not something to average over.

    The player keeps his status row and his board position; he just carries no Sleeper
    annotation, and the build says so.
    """
    result = run_fixture_pipeline(load_fixture_inputs(pipeline_fixture_dir), config=app_config)
    # Sleeper 5000014 reports a gsis_id belonging to a different canonical player, so the
    # cross-check fails and Teodor Vargas gets no Sleeper annotation - while Sol Marchetti,
    # whose id was the one falsely claimed, keeps his own.
    by_id = {record["player_id"]: record for record in result.records["player_status"]}
    conflicted = by_id["gsis:00-0000014"]
    assert conflicted["sleeper_status"] is None
    assert conflicted["injury_status"] is None
    assert "sleeper_record_missing" in conflicted["quality_flags"]
    assert by_id["gsis:00-0000010"]["sleeper_status"] == "Active"
    assert any(check.check_id == "status.sleeper_gsis_conflict" for check in result.gate.checks)
