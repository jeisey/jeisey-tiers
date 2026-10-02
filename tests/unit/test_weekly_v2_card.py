"""The committed weekly-startsit-v2 card is what the generator produces from the evidence."""

from __future__ import annotations

import json
from pathlib import Path

from ffdraft.weekly.card_v2 import write_weekly_v2_card
from ffdraft.weekly.weather import load_error_model

_VOLATILE = {"generated_at_utc", "git_sha"}


def test_the_committed_v2_card_matches_the_committed_evidence(
    repo_root: Path, tmp_path: Path
) -> None:
    reports = repo_root / "docs" / "experiments" / "weekly-startsit-v2"
    write_weekly_v2_card(
        report_path=reports / "experiment.json",
        model_dir=repo_root / "models" / "shadow" / "weekly-startsit-v2",
        out_dir=tmp_path,
        weather_parameters_digest=load_error_model().digest,
        git_sha="test",
    )
    fresh = json.loads((tmp_path / "weekly-startsit-v2.json").read_text(encoding="utf-8"))
    committed = json.loads(
        (repo_root / "models" / "cards" / "weekly-startsit-v2.json").read_text(encoding="utf-8"),
    )
    assert {k: v for k, v in fresh.items() if k not in _VOLATILE} == {
        k: v for k, v in committed.items() if k not in _VOLATILE
    }, "regenerate with `uv run ffdraft weekly-v2-model-card`"
    assert committed["status"].startswith("SHADOW")
    assert committed["selected_families"] == ["lineup"]
    assert committed["shadow_artifact"]["boosters"] == 84
    # Every family's measured value is on the card, selected or not.
    assert set(committed["development"]["incremental_value_over_v1"]) == {
        "weather",
        "lineup",
        "defense",
    }
