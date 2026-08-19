#!/usr/bin/env python
"""Record upstream schemas for the Phase-2 historical loaders.

Phase 0 recorded schemas for the sources Phase 1 needed
(`tests/fixtures/source_schemas/`), and `tests/contract/test_source_adapters.py` asserts
that every adapter only reads columns that recording actually observed. Phase 2 adds
loaders Phase 0 did not record - weekly player stats, snap counts, schedules, draft picks,
the combine, and a pre-2025 roster season - so this script extends the same evidence base
in the same format.

It writes **schema only**: column name, dtype and null fraction, plus row counts. No source
rows are written, so nothing here redistributes vendor data.

Run it from an environment with egress to the nflverse release hosts (ADR-009):

    uv run python scripts/capture_source_schemas.py

Re-running overwrites the fixtures in place; review the diff before committing, because a
changed fixture is a changed upstream contract.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "source_schemas"

#: Season used for the season-scoped captures. 2024 is the last pre-2025 season, which is
#: the era Phase 2 treats most carefully (ADR-018), and it is fully published.
REFERENCE_SEASON = 2024


def _loaders() -> dict[str, tuple[str, Callable[[], pl.DataFrame]]]:
    import nflreadpy as nfl

    return {
        "nflverse_player_stats_weekly_2024": (
            "load_player_stats(summary_level='week')",
            lambda: nfl.load_player_stats(seasons=[REFERENCE_SEASON], summary_level="week"),
        ),
        "nflverse_snap_counts_2024": (
            "load_snap_counts",
            lambda: nfl.load_snap_counts(seasons=[REFERENCE_SEASON]),
        ),
        "nflverse_schedules": (
            "load_schedules",
            nfl.load_schedules,
        ),
        "nflverse_draft_picks": (
            "load_draft_picks",
            nfl.load_draft_picks,
        ),
        "nflverse_combine": (
            "load_combine",
            nfl.load_combine,
        ),
        "nflverse_rosters_2024": (
            "load_rosters",
            lambda: nfl.load_rosters(seasons=[REFERENCE_SEASON]),
        ),
    }


def dtype_summary(frame: pl.DataFrame) -> list[dict[str, Any]]:
    """Column name/dtype/null-fraction summary, matching the Phase-0 fixture format."""
    rows = frame.height
    summary: list[dict[str, Any]] = []
    for name, dtype in zip(frame.columns, frame.dtypes, strict=True):
        entry: dict[str, Any] = {"name": name, "dtype": str(dtype)}
        if rows:
            entry["null_fraction"] = round(frame[name].null_count() / rows, 4)
        summary.append(entry)
    return summary


def capture(check_id: str, resource: str, frame: pl.DataFrame) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "source_id": "nflreadpy",
        "target": resource,
        "captured_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "record_count": frame.height,
        "columns": dtype_summary(frame),
        "coverage": {},
        "sample_rows": [],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_FIXTURE_DIR)
    parser.add_argument("--only", default="", help="comma-separated check ids to capture")
    args = parser.parse_args(argv)

    wanted = {name.strip() for name in args.only.split(",") if name.strip()}
    args.out.mkdir(parents=True, exist_ok=True)

    failures = 0
    for check_id, (resource, loader) in _loaders().items():
        if wanted and check_id not in wanted:
            continue
        try:
            frame = loader()
        except Exception as exc:  # noqa: BLE001 - the point is to report, not to crash
            print(f"FAIL {check_id}: {type(exc).__name__}: {exc}")
            failures += 1
            continue
        payload = capture(check_id, resource, frame)
        path = args.out / f"{check_id}.schema.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {path.relative_to(REPO_ROOT)} ({frame.height} rows, {frame.width} columns)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
