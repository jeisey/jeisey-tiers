"""Archival point-in-time evidence for nflverse's injury report, 2017 onward (ADR-099).

Each season's ``injuries_<season>.parquet`` carries, through 2024, a ``date_modified`` per row.
A row modified after its team's kickoff that week is a row a pregame reader could not have
seen in that form. This script counts them per season, from local copies of the files and
the schedule, and writes the record docs/DATA_SOURCES.md §20.3 cites. It is evidence about
the archive's own timestamps, which is the best a single present-day download can give; the
retained captures (``capture-injury-report``) are the prospective check.

    uv run python scripts/injury_archive_pit.py --schedules schedules.parquet \\
        --injuries injuries_2017.parquet ... injuries_2026.parquet \\
        --out docs/source-probes/2026-10-01/injuries/archive_pit.json
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl

EASTERN = ZoneInfo("America/New_York")


def _kickoffs(schedules: pl.DataFrame) -> pl.DataFrame:
    """One row per (season, week, team) with the game's kickoff in UTC."""
    rows: list[dict[str, Any]] = []
    for game in schedules.iter_rows(named=True):
        if not game.get("gameday") or not game.get("gametime"):
            continue
        local = datetime.strptime(f"{game['gameday']} {game['gametime']}", "%Y-%m-%d %H:%M")
        kickoff = local.replace(tzinfo=EASTERN).astimezone(UTC)
        for team in (game["home_team"], game["away_team"]):
            rows.append(
                {
                    "season": int(game["season"]),
                    "week": int(game["week"]),
                    "team": str(team),
                    "kickoff_utc": kickoff,
                },
            )
    return pl.DataFrame(
        rows,
        schema={
            "season": pl.Int64,
            "week": pl.Int64,
            "team": pl.String,
            "kickoff_utc": pl.Datetime("us", "UTC"),
        },
    )


def season_record(injuries: pl.DataFrame, kickoffs: pl.DataFrame) -> dict[str, Any]:
    season = int(injuries.get_column("season").max())  # type: ignore[arg-type]
    record: dict[str, Any] = {"season": season, "rows": injuries.height}
    if "date_modified" not in injuries.columns:
        record["date_modified"] = "absent"
        return record
    joined = injuries.with_columns(
        pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64)
    ).join(kickoffs, on=["season", "week", "team"], how="left")
    timed = joined.filter(pl.col("kickoff_utc").is_not_null())
    late = timed.filter(pl.col("date_modified") > pl.col("kickoff_utc"))
    lateness = (late.get_column("date_modified") - late.get_column("kickoff_utc")).dt.total_hours()
    designated = late.filter(pl.col("report_status").is_in(["Out", "Doubtful", "Questionable"]))
    record.update(
        {
            "date_modified": "present",
            "rows_with_kickoff": timed.height,
            "rows_without_kickoff": joined.height - timed.height,
            "modified_after_kickoff": late.height,
            "modified_after_kickoff_with_game_status": designated.height,
            "max_hours_after_kickoff": None if late.is_empty() else int(lateness.max()),  # type: ignore[arg-type]
            "weeks_affected": sorted({int(value) for value in late.get_column("week")}),
            "latest_date_modified": str(joined.get_column("date_modified").max()),
        },
    )
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schedules", type=Path, required=True)
    parser.add_argument("--injuries", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    kickoffs = _kickoffs(pl.read_parquet(args.schedules))
    seasons = [
        season_record(pl.read_parquet(path), kickoffs)
        for path in sorted(args.injuries, key=lambda path: path.name)
    ]
    document = {
        "rule": "injury_report_pit_v1",
        "question": (
            "Was each row of the archived report last modified before its team's kickoff that week?"
        ),
        "seasons": seasons,
        "with_timestamps": sum(1 for s in seasons if s["date_modified"] == "present"),
        "modified_after_kickoff_total": sum(
            int(s.get("modified_after_kickoff", 0)) for s in seasons
        ),
        "rows_with_timestamps_total": sum(int(s.get("rows_with_kickoff", 0)) for s in seasons),
    }
    args.out.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(document, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
