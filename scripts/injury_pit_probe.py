"""Capture nflverse's injury report for one season and compare it with an earlier capture.

The probe ``injuries_in_season_only`` asked for (docs/DATA_SOURCES.md §20.3,
``injury_report_pit_v1``): are a completed week's rows revised after the fact? One download
cannot say. Two captures of the same file, hours or days apart, compared row by row
(:func:`ffdraft.weekly.pit.compare_captures`), can — for the interval between them. The
production refresh retains one capture per run (``ffdraft capture-injury-report``) so the
comparison continues prospectively; this script is the standalone version the probe record
is made with.

    uv run python scripts/injury_pit_probe.py --season 2026 --label T1 \\
        --out docs/source-probes/2026-10-01/injuries \\
        --compare docs/source-probes/2026-10-01/injuries/injuries_2026_T0.json
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from ffdraft.weekly.pit import INJURY_PIT_RULE_VERSION, PIT_COLUMNS, compare_captures, week_digests

URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_{season}.parquet"
)
USER_AGENT = "jeisey-tiers injury PIT probe (https://github.com/jeisey/jeisey-tiers)"


def capture(season: int, label: str) -> dict[str, object]:
    url = URL.format(season=season)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        body = response.read()
        last_modified = response.headers.get("Last-Modified")
    retrieved = datetime.now(UTC).replace(microsecond=0)
    frame = pl.read_parquet(io.BytesIO(body))
    return {
        "capture": {
            "label": label,
            "source_url": url,
            "retrieved_at_utc": retrieved.isoformat().replace("+00:00", "Z"),
            "http_last_modified": last_modified,
            "file_sha256": hashlib.sha256(body).hexdigest(),
            "rows": frame.height,
        },
        "rule": INJURY_PIT_RULE_VERSION,
        "columns": [column for column in PIT_COLUMNS if column in frame.columns],
        "weeks": week_digests(frame)["weeks"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--compare", type=Path, default=None)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    document = capture(args.season, args.label)
    path = args.out / f"injuries_{args.season}_{args.label}.json"
    path.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(document["capture"]))
    if args.compare is not None:
        earlier = json.loads(args.compare.read_text(encoding="utf-8"))
        comparison = {
            "rule": INJURY_PIT_RULE_VERSION,
            "earlier": earlier["capture"],
            "later": document["capture"],
            "comparison": compare_captures(earlier, document),
        }
        out = (
            args.out / f"injuries_{args.season}_{earlier['capture']['label']}_vs_{args.label}.json"
        )
        out.write_text(json.dumps(comparison, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(comparison["comparison"], sort_keys=True)[:2000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
