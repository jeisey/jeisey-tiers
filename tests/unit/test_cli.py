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
