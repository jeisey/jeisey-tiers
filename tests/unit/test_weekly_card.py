"""The committed weekly model card is what the generator produces from the committed evidence."""

from __future__ import annotations

import json
from pathlib import Path

from ffdraft.weekly.card import write_weekly_card

_VOLATILE = {"generated_at_utc", "git_sha"}


def test_the_committed_card_matches_the_committed_evidence(repo_root: Path, tmp_path: Path) -> None:
    reports = repo_root / "docs" / "experiments" / "weekly-startsit"
    write_weekly_card(
        development_path=reports / "experiment.json",
        final_path=reports / "final_holdout.json",
        model_dir=repo_root / "models" / "production" / "weekly-startsit-v1",
        out_dir=tmp_path,
        git_sha="test",
    )
    fresh = json.loads((tmp_path / "weekly-startsit-v1.json").read_text(encoding="utf-8"))
    committed = json.loads(
        (repo_root / "models" / "cards" / "weekly-startsit-v1.json").read_text(encoding="utf-8"),
    )
    assert {k: v for k, v in fresh.items() if k not in _VOLATILE} == {
        k: v for k, v in committed.items() if k not in _VOLATILE
    }, "regenerate with `uv run ffdraft weekly-model-card`"
    assert committed["production_status"].startswith("ACCEPTED")
    assert committed["production_fit"]["boosters"] == 84
