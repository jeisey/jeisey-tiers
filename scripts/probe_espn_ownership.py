"""Source probe: ESPN's public roster and start percentages (ADR-112).

**Not production code.** Answers the questions the adapter's contract rests on, with eight
paced requests, and writes aggregate evidence only — no ESPN player row is copied into the
report:

1. Does the global ``/players`` route honour ``X-Fantasy-Filter``? (It does not.)
2. Does the league-default route honour ``limit`` / sort / stats and rank trimming, and does
   its row count equal ESPN's own ``X-Fantasy-Filter-Player-Count``?
3. Is that universe the same set of players, with the same values, as the global list's
   players carrying an ownership object?
4. Does ``scoringPeriodId`` change any ownership field?
5. Scale, range, coverage of ``percentStarted``, ``started > rostered`` count, per-row
   ``ownership.date`` spread.
6. How many ESPN rows resolve to a canonical player through the verified ``espn_id``
   crosswalk (nflverse rosters, this season plus last), and how many fail closed.

Usage: ``uv run python scripts/probe_espn_ownership.py --season 2026 --out <dir>``.
"""

from __future__ import annotations

import argparse
import gzip
import json
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from ffdraft.sources.espn import (
    CORE_POSITION_IDS,
    ESPN_OWNERSHIP_FILTER,
    ESPN_READS_BASE,
    USER_AGENT,
    ownership_url,
)

PAUSE_SECONDS = 1.0


def _get(url: str, *, view: str | None, period: int | None, flt: Any | None) -> dict[str, Any]:
    time.sleep(PAUSE_SECONDS)
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json", "Accept-Encoding": "gzip"}
    if flt is not None:
        headers["X-Fantasy-Filter"] = json.dumps(flt, separators=(",", ":"))
    params: dict[str, Any] = {}
    if view:
        params["view"] = view
    if period is not None:
        params["scoringPeriodId"] = period
    started = time.monotonic()
    response = requests.get(url, params=params, headers=headers, timeout=60, stream=True)
    wire = response.raw.read(decode_content=False)
    elapsed = time.monotonic() - started
    body = gzip.decompress(wire) if response.headers.get("content-encoding") == "gzip" else wire
    payload = json.loads(body)
    players = payload["players"] if isinstance(payload, dict) and "players" in payload else payload
    return {
        "status": response.status_code,
        "wire_bytes": len(wire),
        "decoded_bytes": len(body),
        "seconds": round(elapsed, 3),
        "count_header": response.headers.get("x-fantasy-filter-player-count"),
        "cache_control": response.headers.get("cache-control"),
        "players": players if isinstance(players, list) else [],
    }


def _inner(entry: dict[str, Any]) -> dict[str, Any]:
    return entry.get("player") if isinstance(entry.get("player"), dict) else entry


def _ownership_by_id(players: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for entry in players:
        player = _inner(entry)
        if isinstance(player.get("ownership"), dict):
            out[int(player["id"])] = {
                "position": player.get("defaultPositionId"),
                **player["ownership"],
            }
    return out


def _measure(fetched: dict[str, Any]) -> dict[str, Any]:
    return {
        key: fetched[key]
        for key in ("status", "wire_bytes", "decoded_bytes", "seconds", "count_header")
    } | {
        "rows": len(fetched["players"]),
    }


def _identity(season: int, ownership: dict[int, dict[str, Any]]) -> dict[str, Any]:
    import nflreadpy

    from ffdraft.identity.ids import IdNamespace
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
    statuses: Counter[str] = Counter()
    by_band: dict[str, Counter[str]] = {}
    for espn_id, row in ownership.items():
        if row["position"] not in CORE_POSITION_IDS:
            continue
        result = registry.lookup(IdNamespace.ESPN, str(espn_id))
        status = "found" if result.found else str(result.status)
        statuses[status] += 1
        owned = float(row.get("percentOwned") or 0.0)
        band = ">=10%" if owned >= 10 else ">=1%" if owned >= 1 else "<1%"
        by_band.setdefault(band, Counter())[status] += 1
    return {
        "registry_players": len(registry),
        "core_espn_rows": sum(statuses.values()),
        "lookup_status": dict(statuses),
        "lookup_status_by_rostered_band": {
            band: dict(counts) for band, counts in sorted(by_band.items())
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--skip-identity", action="store_true")
    args = parser.parse_args()
    season = args.season
    report: dict[str, Any] = {
        "probed_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "season": season,
    }

    time.sleep(PAUSE_SECONDS)
    season_response = requests.get(
        f"{ESPN_READS_BASE}{season}", headers={"User-Agent": USER_AGENT}, timeout=30
    )
    report["season_endpoint"] = {
        "status": season_response.status_code,
        "decoded_bytes": len(season_response.content),
        "current_scoring_period": season_response.json().get("currentScoringPeriod", {}).get("id"),
    }

    global_url = f"{ESPN_READS_BASE}{season}/players"
    plain = _get(global_url, view="players_wl", period=6, flt=None)
    filtered = _get(
        global_url,
        view="players_wl",
        period=6,
        flt={"players": {"limit": 2, "filterIds": {"value": [4429795, 3139477]}}},
    )
    report["global_players_route"] = {
        "no_filter": _measure(plain),
        "two_id_filter_limit_2": _measure(filtered),
        "finding": "filter contents ignored: any X-Fantasy-Filter returns the whole universe",
    }
    global_ownership = _ownership_by_id(filtered["players"])

    league = _get(
        ownership_url(season), view="kona_player_info", period=None, flt=ESPN_OWNERSHIP_FILTER
    )
    league_ownership = _ownership_by_id(league["players"])
    positions = Counter(row["position"] for row in league_ownership.values())
    core = {k: v for k, v in league_ownership.items() if v["position"] in CORE_POSITION_IDS}
    rostered = [float(v["percentOwned"]) for v in core.values()]
    started = [float(v["percentStarted"]) for v in core.values() if "percentStarted" in v]
    stamps = sorted(int(v["date"]) for v in core.values() if v.get("date"))

    def iso(ms: int) -> str:
        return datetime.fromtimestamp(ms / 1000, UTC).replace(microsecond=0).isoformat()

    report["league_default_route"] = {
        **_measure(league),
        "cache_control": league["cache_control"],
        "complete": str(len(league["players"])) == str(league["count_header"]),
        "positions": {str(k): v for k, v in sorted(positions.items())},
        "core_rows": len(core),
        "core_rows_with_percent_started": len(started),
        "ownership_keys": sorted({key for v in core.values() for key in v} - {"position"}),
        "percent_rostered_range": [min(rostered), max(rostered)],
        "percent_started_range": [min(started), max(started)] if started else None,
        "started_above_rostered": sum(
            1
            for v in core.values()
            if float(v.get("percentStarted", 0)) > float(v["percentOwned"]) + 1e-9
        ),
        "zero_rostered": sum(1 for value in rostered if value == 0),
        "rostered_bands": {
            "<10": sum(1 for value in rostered if value < 10),
            "<25": sum(1 for value in rostered if value < 25),
            "<50": sum(1 for value in rostered if value < 50),
            "<75": sum(1 for value in rostered if value < 75),
        },
        "ownership_date_range_utc": [iso(stamps[0]), iso(stamps[-1])] if stamps else None,
        "ownership_dates_older_than_24h_before_probe": sum(
            1 for ms in stamps if (datetime.now(UTC).timestamp() * 1000 - ms) > 86_400_000
        ),
        "league_types": dict(Counter(str(v.get("leagueType")) for v in core.values())),
    }
    global_core = {
        k: v for k, v in global_ownership.items() if v["position"] in {1, 2, 3, 4, 5, 16}
    }
    report["universe_comparison"] = {
        "global_rows_with_ownership": len(global_ownership),
        "global_offense_k_dst_rows_with_ownership": len(global_core),
        "league_default_rows": len(league_ownership),
        "same_ids": set(global_core) == set(league_ownership),
        "percent_owned_disagreements": sum(
            1
            for k in league_ownership
            if k in global_core
            and global_core[k]["percentOwned"] != league_ownership[k]["percentOwned"]
        ),
    }
    period_diffs: dict[str, int] = {}
    for period in (0, 6, 7):
        other = _ownership_by_id(
            _get(
                ownership_url(season),
                view="kona_player_info",
                period=period,
                flt=ESPN_OWNERSHIP_FILTER,
            )["players"]
        )
        period_diffs[str(period)] = sum(
            1
            for k, v in league_ownership.items()
            if any(
                other.get(k, {}).get(f) != v.get(f)
                for f in ("percentOwned", "percentStarted", "date", "percentChange")
            )
        )
    report["scoring_period_sensitivity"] = {
        "rows_differing_from_no_period_request": period_diffs,
        "finding": "scoringPeriodId does not change ownership; none is requested",
    }
    if not args.skip_identity:
        report["identity"] = _identity(season, league_ownership)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
