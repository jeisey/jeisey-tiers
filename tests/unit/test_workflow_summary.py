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


def test_the_lines_capture_fact_is_passed_and_printed(repo_root: Path) -> None:
    """ADR-117: the schedule-lines capture outcome reaches the summary."""
    assert "lines_capture" in _passed_facts(repo_root)
    assert "lines_capture" in {key for key, _ in workflow_summary.RUN_FACTS}


def test_a_week_without_lines_is_impossible_to_miss(tmp_path: Path) -> None:
    """ADR-117: the 2026-11-06 refresh deployed 1,437 lines-pending records and said nothing."""
    import json

    weekly = {
        "target_week": 9,
        "lines_pending": 1437,
        "lines": {
            "rule_version": "pregame_line_reuse_v1",
            "max_age_hours": 48,
            "schedule_retrieved_at_utc": "2026-11-06T12:32:07Z",
            "target_games": 15,
            "from_schedule": 1,
            "from_retained": 0,
            "unlined": 14,
            "unlined_game_ids": ["2026_09_ARI_SEA", "2026_09_CIN_ATL"],
            "retained": [],
            "captures_read": [],
        },
    }
    (tmp_path / "ros_build_metadata.json").write_text(json.dumps({"weekly": weekly}))
    text = "\n".join(workflow_summary._weekly_lines_section(tmp_path))
    assert "Start/Sit lines (week 9)" in text
    assert "**14 game(s) had no line at all**" in text and "1437" in text
    weekly["lines"].update(from_retained=14, unlined=0, unlined_game_ids=[])
    weekly["lines"]["retained"] = [{"game_id": "x", "observed_at_utc": "2026-11-05T22:53:00Z"}]
    weekly["lines_pending"] = 0
    (tmp_path / "ros_build_metadata.json").write_text(json.dumps({"weekly": weekly}))
    text = "\n".join(workflow_summary._weekly_lines_section(tmp_path))
    assert "newest retained pregame lines were used (observed 2026-11-05T22:53:00Z)" in text
    assert "had no line at all" not in text
