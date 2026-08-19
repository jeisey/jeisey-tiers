"""CLI behaviour.

Exit status is the contract CI depends on: 0 when the gate passes, 1 when a critical check
fails. A command that prints failures and exits 0 would make a red build look green.
"""

from __future__ import annotations

import json

from ffdraft.cli import main


def test_config_check_reports_policy_without_printing_secret_values(capsys, monkeypatch):
    monkeypatch.setenv("MFL_API_USER_AGENT", "registered-client/1.0")
    monkeypatch.setenv("MFL_API_PASSWORD", "hunter2")

    assert main(["config-check", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["registry"]["arbitrage_mode"] == "baseline"
    assert payload["mfl_client_secrets_present"]["MFL_API_USER_AGENT"] is True
    assert payload["mfl_client_registered"] is True
    serialized = json.dumps(payload)
    assert "hunter2" not in serialized
    assert "registered-client/1.0" not in serialized


def test_config_check_human_output_lists_the_benchmark_only_source(capsys):
    assert main(["config-check"]) == 0
    out = capsys.readouterr().out
    assert "fantasypros_ecr_via_dynastyprocess" in out
    assert "baseline" in out


def test_build_then_validate_round_trip(tmp_path, capsys):
    assert main(["build-fixture-artifacts", "--out", str(tmp_path)]) == 0
    capsys.readouterr()
    assert main(["validate-artifacts", str(tmp_path)]) == 0


def test_validating_a_missing_directory_fails(tmp_path, capsys):
    assert main(["validate-artifacts", str(tmp_path / "nope")]) == 1
    assert "directory does not exist" in capsys.readouterr().out


def test_validating_a_corrupted_artifact_fails(tmp_path, capsys):
    assert main(["build-fixture-artifacts", "--out", str(tmp_path)]) == 0
    capsys.readouterr()

    payload = json.loads((tmp_path / "tiers.json").read_text())
    # Two players now share fair rank 1, which no JSON Schema can catch.
    payload["records"][1]["fair_rank"] = payload["records"][0]["fair_rank"]
    (tmp_path / "tiers.json").write_text(json.dumps(payload))

    assert main(["validate-artifacts", str(tmp_path)]) == 1
    assert "tier.duplicate_fair_rank" in capsys.readouterr().out


def test_no_subcommand_prints_help(capsys):
    assert main([]) == 2
    assert "usage: ffdraft" in capsys.readouterr().out


def test_feature_dictionary_renders_markdown(capsys):
    from ffdraft.features.dictionary import FEATURE_SCHEMA_VERSION, feature_schema_hash

    assert main(["feature-dictionary"]) == 0
    out = capsys.readouterr().out
    assert FEATURE_SCHEMA_VERSION in out
    assert feature_schema_hash() in out
    assert "`depth_rank_at_anchor`" in out


def test_feature_dictionary_renders_json(capsys):
    assert main(["feature-dictionary", "--format", "json"]) == 0
    records = json.loads(capsys.readouterr().out)
    assert any(record["name"] == "prev1_fantasy_ppg_ppr" for record in records)
    assert all("availability" in record for record in records)


def test_validate_historical_reports_a_missing_dataset(tmp_path, capsys):
    assert main(["validate-historical", str(tmp_path / "nope")]) == 1
    assert "leakage.dataset_missing" in capsys.readouterr().out


def test_validate_historical_passes_on_a_written_dataset(tmp_path, capsys, monkeypatch):
    """The written dataset comes from the fixture pipeline, so no network is involved."""
    from pathlib import Path

    from ffdraft.config import load_app_config
    from ffdraft.features.sources import FIXTURE_TARGET_SEASONS, load_fixture_sources
    from ffdraft.pipeline import build_historical_dataset, write_historical_dataset
    from ffdraft.quality.thresholds import HistoricalThresholds

    fixtures = Path(__file__).resolve().parents[1] / "fixtures" / "historical"
    dataset = build_historical_dataset(
        load_fixture_sources(fixtures).sources,
        config=load_app_config(environ={}),
        seasons=FIXTURE_TARGET_SEASONS,
        thresholds=HistoricalThresholds.fixture(),
        verify_target_season_independence=False,
    )
    write_historical_dataset(dataset, tmp_path)
    capsys.readouterr()
    assert main(["validate-historical", str(tmp_path)]) == 0


def test_build_historical_requires_a_last_season(capsys):
    import pytest

    with pytest.raises(SystemExit):
        main(["build-historical"])
