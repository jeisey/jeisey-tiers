"""Source probe: can Sleeper's trending add/drop feeds be read completely? (ADR-114)

**Not production code.** The production capture asks for ``lookback_hours=24&limit=100``.
The 2026-09-02 probe checked ``limit`` at 5, 25 and 100 only, so it never asked whether a
deeper read exists. This probe asks, with evidence rather than status codes:

1. **The limit ceiling.** For ``limit`` in 25 … 5000, how many distinct ids come back, and
   are the id sets identical above 100?
2. **The prefix property.** Is the ``limit=25`` answer the top 25 of the ``limit=100``
   answer? That is what makes "absent from the feed" mean "below the feed's smallest count".
3. **Undocumented parameters.** Sleeper documents ``lookback_hours`` and ``limit`` only
   (https://docs.sleeper.com/#trending-players). Each candidate pagination or filter
   parameter is sent beside a fresh baseline, and it is reported as working **only if it
   changes the returned population** beyond the baseline-to-baseline drift. An HTTP 200
   proves nothing: an ignored parameter also answers 200.
4. **Windows.** Whether other ``lookback_hours`` values lift the ceiling. They are never
   combined: a 6-hour and a 24-hour count are different quantities.
5. **Our universe.** How many canonical QB/RB/WR/TE players (nflverse rosters, the
   configured season plus the one before, the same spine the builds use) carry a verified
   ``sleeper_id``, and how many of them each feed observed — add, drop, both, neither.

Paced at one request per second, far under Sleeper's documented 1000 calls/minute. It
retains nothing beyond aggregates: ``report.json`` holds counts and overlaps, no player rows.

    uv run python scripts/probe_sleeper_trending_coverage.py --season 2026 --out <dir>
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

BASE = "https://api.sleeper.app/v1/players/nfl/trending"
HEADERS = {
    "User-Agent": (
        "jeisey-tiers source probe (+https://github.com/jeisey/jeisey-tiers); "
        "free non-commercial project, trending coverage measurement"
    ),
    "Accept": "application/json",
}
PAUSE_SECONDS = 1.0
LIMITS = (25, 100, 101, 250, 500, 1000, 5000)
WINDOWS = (1, 6, 12, 24, 48, 168)

#: Candidate parameters, none documented. Values chosen so a working one would visibly move
#: the population: page two, the tail after the last id, one position, an old season.
CANDIDATES: tuple[tuple[str, dict[str, Any]], ...] = (
    ("offset=100", {"offset": 100}),
    ("page=2", {"page": 2}),
    ("skip=100", {"skip": 100}),
    ("start=100", {"start": 100}),
    ("cursor=<last id>", {"cursor": "__LAST__"}),
    ("after=<last id>", {"after": "__LAST__"}),
    ("position=TE", {"position": "TE"}),
    ("season=2024", {"season": 2024}),
    ("week=1", {"week": 1}),
    ("order=asc", {"order": "asc"}),
    ("sort=asc", {"sort": "asc"}),
    ("min_count=1", {"min_count": 1}),
)


def _get(kind: str, params: dict[str, Any]) -> dict[str, Any]:
    time.sleep(PAUSE_SECONDS)
    started = time.monotonic()
    try:
        response = requests.get(f"{BASE}/{kind}", params=params, headers=HEADERS, timeout=60)
    except requests.RequestException as exc:
        return {"status": None, "error": type(exc).__name__, "ids": [], "counts": []}
    elapsed = time.monotonic() - started
    try:
        payload = response.json()
    except ValueError:
        payload = None
    rows = payload if isinstance(payload, list) else []
    ids = [str(row.get("player_id")) for row in rows if isinstance(row, dict)]
    counts = [int(row.get("count") or 0) for row in rows if isinstance(row, dict)]
    return {
        "status": response.status_code,
        "bytes": len(response.content),
        "elapsed_s": round(elapsed, 3),
        "ids": ids,
        "counts": counts,
    }


def _shape(result: dict[str, Any]) -> dict[str, Any]:
    ids, counts = result["ids"], result["counts"]
    return {
        "status": result["status"],
        "bytes": result.get("bytes"),
        "rows": len(ids),
        "distinct_ids": len(set(ids)),
        "sorted_descending": counts == sorted(counts, reverse=True),
        "max_count": max(counts) if counts else None,
        "min_count": min(counts) if counts else None,
    }


def probe_limits(kind: str) -> dict[str, Any]:
    results = {limit: _get(kind, {"lookback_hours": 24, "limit": limit}) for limit in LIMITS}
    reference = set(results[100]["ids"])
    top25 = results[25]["ids"]
    return {
        "by_limit": {
            str(limit): {
                **_shape(result),
                "same_id_set_as_limit_100": set(result["ids"]) == reference,
                "shared_with_limit_100": len(set(result["ids"]) & reference),
            }
            for limit, result in results.items()
        },
        "limit_25_is_prefix_of_limit_100": top25 == results[100]["ids"][: len(top25)],
        "limit_25_ids_inside_limit_100": len(set(top25) & reference),
    }


def probe_candidates(kind: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    drift: list[int] = []
    for label, params in CANDIDATES:
        before = _get(kind, {"lookback_hours": 24, "limit": 100})
        last = before["ids"][-1] if before["ids"] else ""
        sent = {key: (last if value == "__LAST__" else value) for key, value in params.items()}
        probe = _get(kind, {"lookback_hours": 24, "limit": 100, **sent})
        after = _get(kind, {"lookback_hours": 24, "limit": 100})
        baseline_overlap = len(set(before["ids"]) & set(after["ids"]))
        drift.append(100 - baseline_overlap)
        shared = max(
            len(set(probe["ids"]) & set(before["ids"])),
            len(set(probe["ids"]) & set(after["ids"])),
        )
        new_ids = len(set(probe["ids"]) - set(before["ids"]) - set(after["ids"]))
        out[label] = {
            **_shape(probe),
            "shared_with_bracketing_baseline": shared,
            "ids_in_neither_baseline": new_ids,
            "baseline_to_baseline_overlap": baseline_overlap,
            # Changed the population: more ids differ than the two baselines differ from
            # each other. Count drift alone moves a handful of ids at the 100th place.
            "changes_population": (100 - shared) > (100 - baseline_overlap) + 2,
        }
    return {"candidates": out, "max_baseline_drift_ids": max(drift) if drift else None}


def probe_windows(kind: str) -> dict[str, Any]:
    return {
        str(hours): _shape(_get(kind, {"lookback_hours": hours, "limit": 1000}))
        for hours in WINDOWS
    }


def probe_universe(season: int) -> dict[str, Any]:
    import nflreadpy

    from ffdraft.identity.ids import IdNamespace
    from ffdraft.identity.registry import LookupStatus
    from ffdraft.sources.nflverse import NflverseRosterAdapter
    from ffdraft.status.employment import build_identity_registry

    adapter = NflverseRosterAdapter()
    now = datetime.now(UTC)
    current = adapter.normalize(
        nflreadpy.load_rosters(seasons=[season]), season=season, retrieved_at=now
    ).frame
    prior = adapter.normalize(
        nflreadpy.load_rosters(seasons=[season - 1]), season=season - 1, retrieved_at=now
    ).frame
    registry = build_identity_registry(current, [prior])
    core = {
        player_id: player
        for player_id, player in registry.players.items()
        if str(player.position) in {"QB", "RB", "WR", "TE"}
    }
    with_sleeper = {pid: p for pid, p in core.items() if p.crosswalk.sleeper_id}
    ambiguous = {
        pid
        for pid, p in with_sleeper.items()
        if registry.lookup(IdNamespace.SLEEPER, str(p.crosswalk.sleeper_id)).status
        is LookupStatus.AMBIGUOUS
    }
    mapped = {
        str(p.crosswalk.sleeper_id): pid for pid, p in with_sleeper.items() if pid not in ambiguous
    }
    adds = _get("add", {"lookback_hours": 24, "limit": 100})["ids"]
    drops = _get("drop", {"lookback_hours": 24, "limit": 100})["ids"]
    add_hit = {mapped[i] for i in adds if i in mapped}
    drop_hit = {mapped[i] for i in drops if i in mapped}
    feed_unresolved = Counter(
        kind
        for kind, ids in (("add", adds), ("drop", drops))
        for external in ids
        if external not in mapped
    )
    universe = set(mapped.values())
    return {
        "registry_players": len(registry),
        "core_players": len(core),
        "core_with_sleeper_id": len(with_sleeper),
        "core_without_sleeper_id": len(core) - len(with_sleeper),
        "core_ambiguous_sleeper_id": len(ambiguous),
        "mapped_universe": len(universe),
        "feed_rows_unresolved": dict(feed_unresolved),
        "universe_add_observed": len(add_hit),
        "universe_drop_observed": len(drop_hit),
        "universe_both_observed": len(add_hit & drop_hit),
        "universe_add_only": len(add_hit - drop_hit),
        "universe_drop_only": len(drop_hit - add_hit),
        "universe_neither": len(universe - add_hit - drop_hit),
        "universe_both_share": round(len(add_hit & drop_hit) / len(universe), 4)
        if universe
        else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    started = datetime.now(UTC).replace(microsecond=0)
    report: dict[str, Any] = {
        "probe": "sleeper-trending-coverage",
        "started_at_utc": started.isoformat().replace("+00:00", "Z"),
        "documented_parameters": ["lookback_hours (default 24)", "limit (default 25)"],
        "documentation": "https://docs.sleeper.com/#trending-players",
    }
    for kind in ("add", "drop"):
        report[f"{kind}_limits"] = probe_limits(kind)
        report[f"{kind}_windows_at_limit_1000"] = probe_windows(kind)
    report["add_candidate_parameters"] = probe_candidates("add")
    report["universe"] = probe_universe(args.season)
    report["finished_at_utc"] = (
        datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
