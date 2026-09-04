"""The Phase-11 command surface.

Parser-level assertions only: the commands that perform network I/O or fit models are covered
by their own tests. What matters here is that the seal cannot be opened by accident and that a
sealed run cannot overwrite the report that justified the freeze.
"""

from __future__ import annotations

import json

import pytest

from ffdraft.cli import main
from ffdraft.ros.experiment import RosExperimentConfig
from ffdraft.ros.report import write_ros_report


@pytest.mark.parametrize(
    "command",
    [
        "build-ros-dataset",
        "evaluate-ros",
        "evaluate-ros-value",
        "ros-attribution",
        "ros-model-card",
    ],
)
def test_every_phase_eleven_command_is_registered(command: str, capsys) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main([command, "--help"])
    assert exit_info.value.code == 0
    assert command in capsys.readouterr().out


def test_the_final_eval_needs_both_the_token_and_a_reason(capsys) -> None:
    assert main(["evaluate-ros", "--final-eval"]) == 2
    assert "refusing to unseal" in capsys.readouterr().err


def test_the_in_season_dictionary_is_printable(capsys) -> None:
    assert main(["feature-dictionary", "--ros"]) == 0
    output = capsys.readouterr().out
    assert "Rest-of-season feature dictionary" in output
    assert "`ppg_to_date`" in output


def test_the_in_season_dictionary_is_also_machine_readable(capsys) -> None:
    assert main(["feature-dictionary", "--ros", "--format", "json"]) == 0
    records = json.loads(capsys.readouterr().out)
    assert {record["name"] for record in records} >= {"through_week", "games_to_date"}
    assert all(
        record["availability"] in {"cutoff_derived", "in_season_to_date"} for record in records
    )


def test_a_sealed_run_writes_a_different_file_from_the_development_run(tmp_path) -> None:
    """The report that justified the freeze must survive the run that consumed the holdout."""

    class _Stub:
        def __init__(self, label: str) -> None:
            self.config = RosExperimentConfig(label=label)

        def to_dict(self) -> dict[str, object]:
            return {"label": self.config.label}

    # `write_ros_report` only reads `config.label` and the serializers; a stub keeps this a
    # naming test rather than a forty-minute experiment.
    import ffdraft.ros.report as report_module

    original_json, original_markdown = report_module.to_json, report_module.to_markdown
    report_module.to_json = lambda result: json.dumps(result.to_dict())  # type: ignore[assignment]
    report_module.to_markdown = lambda result: str(result.to_dict())  # type: ignore[assignment]
    try:
        development = write_ros_report(_Stub("development"), tmp_path)  # type: ignore[arg-type]
        final = write_ros_report(_Stub("final_holdout"), tmp_path)  # type: ignore[arg-type]
    finally:
        report_module.to_json, report_module.to_markdown = original_json, original_markdown

    assert {path.name for path in development} == {"experiment.json", "experiment.md"}
    assert {path.name for path in final} == {"final_holdout.json", "final_holdout.md"}
