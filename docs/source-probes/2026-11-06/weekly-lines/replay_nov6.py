"""Replay the 2026-11-06T12:32:07Z build with the upstream blank and one retained capture (ADR-117).

Usage (from the repository root):
    NFLREADPY_CACHE=filesystem NFLREADPY_CACHE_DIR=<cache> \\
    uv run python docs/source-probes/2026-11-06/weekly-lines/replay_nov6.py <out> <store> fixed

`fixed` writes one capture from the pre-blank rows into <store> first; `blank-only` does not.
"""

import json
import sys
from pathlib import Path

import polars as pl

REPO = Path(__file__).resolve().parents[4]
out_dir, store_dir, mode = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]

from ffdraft.sources import nflverse_http  # noqa: E402

ODDS = [
    "away_moneyline",
    "home_moneyline",
    "spread_line",
    "away_spread_odds",
    "home_spread_odds",
    "total_line",
    "under_odds",
    "over_odds",
]
real_loaders = nflverse_http.nflverse_loaders


def patched_loaders():
    module = real_loaders()

    class Wrapper:
        def __getattr__(self, name):
            return getattr(module, name)

        def load_schedules(self, *args, **kwargs):
            frame = module.load_schedules(*args, **kwargs)
            frame = frame if isinstance(frame, pl.DataFrame) else pl.DataFrame(frame)
            blank = (
                (pl.col("season") == 2026) & (pl.col("week") == 9) & pl.col("home_score").is_null()
            )
            return frame.with_columns(
                [
                    pl.when(blank).then(None).otherwise(pl.col(c)).alias(c)
                    for c in ODDS
                    if c in frame.columns
                ]
            )

    return Wrapper()



for module in list(sys.modules.values()):
    if getattr(module, "nflverse_loaders", None) is real_loaders:
        module.nflverse_loaders = patched_loaders

if mode == "fixed":
    from ffdraft.retention import SnapshotStore
    from ffdraft.timeutil import parse_utc
    from ffdraft.weekly.capture import LINES_SOURCE_ID, GamedayCapture, write_gameday_capture
    from ffdraft.weekly.lines import line_capture_rows

    fixture = json.loads((REPO / "tests/fixtures/weekly/schedule_lines_2026w09.json").read_text())
    before = pl.DataFrame(fixture["before"]["rows"], infer_schema_length=None)
    at = parse_utc("2026-11-05T22:53:00Z")
    rows, details = line_capture_rows(before, season=2026, now=at)
    write_gameday_capture(
        GamedayCapture(
            source_id=LINES_SOURCE_ID, season=2026, observed_at_utc=at, rows=rows, details=details
        ),
        store=SnapshotStore(root=store_dir, prefix=""),
    )

from ffdraft.cli import main  # noqa: E402

sys.exit(
    main(
        [
            "build-ros",
            "--season",
            "2026",
            "--as-of",
            "2026-11-06T12:32:07Z",
            "--through-week",
            "8",
            "--out",
            str(out_dir),
            "--store",
            str(store_dir),
        ]
    )
)
