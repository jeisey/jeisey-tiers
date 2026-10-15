"""YOLO's net-add gate, measured on a build before the rule was frozen (ADR-110 §6).

For each position in one league block this prints the gate's funnel:

* the positive-net-add pool (Opportunity rows with ``behavior_available`` and
  ``net_add_count > 0``);
* the bar: the ceiling of the pool's median (linear interpolation, ``quantileAt``);
* how many reach the bar;
* how many of those also have a rising role;
* how many of those have a distribution for the target week.

The 75th-percentile bar, the rejected alternative, is printed beside it.

The role test here mirrors the Opportunity Board's ``role`` predicate for this measurement only:
an upward change, at display precision, in the position's leading metric of ``role_change_v1``.
The page itself uses ``passesFilter(candidate, "role")``.

Usage (a directory holding a build's ``inseason_opportunity.json``, ``player_usage.json`` and
``weekly_projections.json``)::

    uv run python docs/experiments/win-my-matchup-2026-10-15/yolo_coverage.py <dir> \
        [--block redraft-12] [--scoring PPR]
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

POOL_MINIMUM = 5
LEADING_METRIC = {"QB": "pass_attempts", "RB": "snap_share", "WR": "snap_share", "TE": "snap_share"}


def load_records(directory: Path, name: str) -> list[dict[str, Any]]:
    with (directory / name).open(encoding="utf-8") as handle:
        records: list[dict[str, Any]] = json.load(handle)["records"]
    return records


def quantile_linear(sorted_values: list[float], q: float) -> float:
    """Type-7 quantile, as ``quantileAt`` on the page."""
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    low, high = sorted_values[lower], sorted_values[upper]
    return low + (position - lower) * (high - low)


def role_rising(usage: dict[str, Any] | None, position: str) -> bool:
    """An upward change in the leading role metric, at the precision the board prints."""
    if usage is None or usage.get("appearances", 0) == 0:
        return False
    metric = LEADING_METRIC[position]
    change = (usage.get("role_changes") or {}).get(metric)
    if change is None or change.get("earlier") is None or change.get("change") is None:
        return False
    value = float(change["change"])
    shown = round(abs(value)) if metric == "pass_attempts" else round(abs(value) * 100)
    return shown > 0 and value > 0


def positive_net_adds(row: dict[str, Any]) -> float | None:
    count = row.get("net_add_count")
    if not row.get("behavior_available") or not isinstance(count, int | float) or count <= 0:
        return None
    return float(count)


def funnel(
    rows: list[dict[str, Any]],
    usage: dict[str, dict[str, Any]],
    weekly: dict[str, dict[str, Any]],
    position: str,
    q: float,
) -> str:
    at_position = [row for row in rows if row["position"] == position]
    pool = sorted(c for row in at_position if (c := positive_net_adds(row)) is not None)
    if len(pool) < POOL_MINIMUM:
        return f"{position}: pool {len(pool)} (< {POOL_MINIMUM}: no bar, none qualify)"
    bar = math.ceil(quantile_linear(pool, q))
    high = [row for row in at_position if (c := positive_net_adds(row)) is not None and c >= bar]
    rising = [row for row in high if role_rising(usage.get(row["player_id"]), position)]
    playable = [
        row
        for row in rising
        if (week := weekly.get(row["player_id"])) is not None
        and week.get("quantiles") is not None
        and week.get("game_state") == "upcoming"
    ]
    return (
        f"{position}: pool {len(pool)} · bar {bar:,} · at or above {len(high)}"
        f" · rising {len(rising)} · with a distribution {len(playable)}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("directory", type=Path)
    parser.add_argument("--block", default="redraft-12")
    parser.add_argument("--scoring", default="PPR")
    args = parser.parse_args()

    opportunity = load_records(args.directory, "inseason_opportunity.json")
    usage = {row["player_id"]: row for row in load_records(args.directory, "player_usage.json")}
    weekly = {
        row["player_id"]: row
        for row in load_records(args.directory, "weekly_projections.json")
        if row["scoring_preset"] == args.scoring
    }
    rows = [
        row
        for row in opportunity
        if row["league_preset_id"] == args.block and row["scoring_preset"] == args.scoring
    ]
    for q, label in ((0.5, "median bar (the rule)"), (0.75, "75th-percentile bar (rejected)")):
        print(f"{args.block} {args.scoring}, {label}:")
        for position in ("QB", "RB", "WR", "TE"):
            print("  " + funnel(rows, usage, weekly, position, q))


if __name__ == "__main__":
    main()
