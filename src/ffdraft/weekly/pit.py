"""Point-in-time evidence for nflverse's injury report (``injury_report_pit_v1``).

The registry note ``injuries_in_season_only`` says the report could not become a model input
until one question was answered: **are a completed week's rows revised later?** A row count
cannot answer it — a revision can keep the count and change a designation — and neither can
one download, which only shows the file as it is today. This module gives the two things
that can:

* :func:`week_digests` — per ``(season, week)``, the row count and a digest of the rows'
  *contents* (every column the weekly layer reads, canonically ordered), plus a digest per
  player, so two captures can be compared row by row;
* :func:`compare_captures` — what changed between an earlier and a later capture of the same
  season, per week: rows added, removed and changed, and which fields changed.

Retained captures (``gameday/nflverse_injuries`` in the private store, one per refresh) make
the comparison prospective: every completed week is captured again every day, so a revision
cannot happen unseen from the day this runs.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import polars as pl

__all__ = [
    "INJURY_PIT_RULE_VERSION",
    "PIT_COLUMNS",
    "compare_captures",
    "week_digests",
]

INJURY_PIT_RULE_VERSION = "injury_report_pit_v1"

#: Every column a weekly reading takes from the report, and the player's name.
PIT_COLUMNS: tuple[str, ...] = (
    "season",
    "week",
    "game_type",
    "team",
    "gsis_id",
    "position",
    "full_name",
    "report_primary_injury",
    "report_secondary_injury",
    "report_status",
    "practice_primary_injury",
    "practice_secondary_injury",
    "practice_status",
)


def _canonical(row: Mapping[str, Any]) -> str:
    return json.dumps(
        {column: row.get(column) for column in PIT_COLUMNS},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _rows(frame: pl.DataFrame) -> Iterable[dict[str, Any]]:
    present = [column for column in PIT_COLUMNS if column in frame.columns]
    for row in frame.select(present).iter_rows(named=True):
        yield {column: row.get(column) for column in PIT_COLUMNS}


def week_digests(raw: pl.DataFrame) -> dict[str, Any]:
    """Per ``season-week``: rows, a content digest and a digest per row key.

    A row key is ``team|gsis_id`` (nflverse publishes one row per player and week, and a
    player traded mid-week can appear under two teams). Rows are digested in key order, so
    the week digest does not depend on file order.
    """
    weeks: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[tuple[str, str]]] = {}
    for row in _rows(raw):
        key = f"{row['season']}-{int(row['week']):02d}"
        row_key = f"{row.get('team')}|{row.get('gsis_id')}"
        grouped.setdefault(key, []).append((row_key, _canonical(row)))
    for key in sorted(grouped):
        rows = sorted(grouped[key])
        weeks[key] = {
            "rows": len(rows),
            "designated": sum(
                1
                for _, text in rows
                if json.loads(text).get("report_status") in ("Out", "Doubtful", "Questionable")
            ),
            "digest": _sha("\n".join(text for _, text in rows))[:32],
            "row_digests": {row_key: _sha(text)[:16] for row_key, text in rows},
        }
    return {"rule": INJURY_PIT_RULE_VERSION, "columns": list(PIT_COLUMNS), "weeks": weeks}


def compare_captures(
    earlier: Mapping[str, Any],
    later: Mapping[str, Any],
    *,
    weeks: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Per week present in both: identical, or which rows were added, removed or changed."""
    first = earlier.get("weeks", {})
    second = later.get("weeks", {})
    keys = sorted(set(first) & set(second)) if weeks is None else list(weeks)
    report: dict[str, Any] = {}
    for key in keys:
        a = first.get(key)
        b = second.get(key)
        if a is None or b is None:
            report[key] = {"status": "missing", "earlier": a is not None, "later": b is not None}
            continue
        if a["digest"] == b["digest"]:
            report[key] = {"status": "identical", "rows": a["rows"]}
            continue
        rows_a: Mapping[str, str] = a["row_digests"]
        rows_b: Mapping[str, str] = b["row_digests"]
        report[key] = {
            "status": "revised",
            "rows_earlier": a["rows"],
            "rows_later": b["rows"],
            "added": sorted(set(rows_b) - set(rows_a)),
            "removed": sorted(set(rows_a) - set(rows_b)),
            "changed": sorted(k for k in set(rows_a) & set(rows_b) if rows_a[k] != rows_b[k]),
        }
    return {
        "rule": INJURY_PIT_RULE_VERSION,
        "weeks": report,
        "identical": sum(1 for value in report.values() if value["status"] == "identical"),
        "revised": sum(1 for value in report.values() if value["status"] == "revised"),
    }
