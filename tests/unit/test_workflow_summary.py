"""The refresh summary prints every run fact daily-refresh.yml passes it.

``RUN_FACTS`` is an allow-list, so a fact the workflow passes and the list does not name is
parsed and dropped without a word. That is how the season, the rest-of-season board and,
with ADR-096, the weekly start/sit layer would all go missing from the one page an operator
reads after a run.
"""

from __future__ import annotations

import re
from pathlib import Path

import workflow_summary


def _passed_facts(repo_root: Path) -> set[str]:
    text = (repo_root / ".github" / "workflows" / "daily-refresh.yml").read_text(encoding="utf-8")
    return set(re.findall(r'--fact "([a-z_]+)=', text))


def test_every_fact_the_refresh_passes_is_printed(repo_root: Path) -> None:
    named = {key for key, _ in workflow_summary.RUN_FACTS}
    passed = _passed_facts(repo_root)
    assert {"weekly_rows", "weekly_target_week", "ros_rows", "product_mode"} <= passed
    # ADR-099's game-day facts.
    assert {
        "refresh_kind",
        "forecast_capture",
        "injury_capture",
        "weekly_context_rows",
        "weekly_explained",
        "shadow_status",
        "shadow_rows",
        "shadow_retained",
    } <= passed
    assert passed - named == set()


def test_the_weekly_facts_render_even_with_no_build(tmp_path: Path) -> None:
    text = workflow_summary.render(
        tmp_path,
        None,
        {"weekly_rows": "0", "weekly_target_week": "not published", "product_mode": "in_season"},
        "Daily refresh — failure",
    )
    assert "| Start/Sit projections | `0` |" in text
    assert "| Start/Sit week | `not published` |" in text
    assert "| Product mode | `in_season` |" in text
