"""Source probe: Sleeper's player map payload and the trending add/drop feeds (Phase 10).

**Not production code.** Phase 0 verified the Sleeper player map at 12,220 records and
14.6 MB (`docs/DATA_SOURCES.md` 13.6) and probed `trending/add` once. Phase 10 needs three
things that measurement does not answer:

1. what the player map weighs **now** — the roadmap is explicit that payload size is an
   operational fact to re-measure, not a schema contract to enforce;
2. the `trending/drop` feed, which has never been probed;
3. the `lookback_hours` / `limit` parameter behaviour, because Phase 12 inherits whatever
   history Phase 10 starts retaining and a window that is silently clamped would make that
   history mean something other than what its manifest claims.

Sleeper's documented guidance is **at most one player-map call per day** and fewer than
1000 API calls per minute overall. This probe issues one player-map request and a handful of
small trending requests, paced.

It retains nothing and prints no player rows beyond a redacted schema description.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Mapping, Sequence
from typing import Any

import requests

BASE = "https://api.sleeper.app/v1"
PLAYERS_URL = f"{BASE}/players/nfl"
TRENDING_URL = f"{BASE}/players/nfl/trending/{{kind}}"
STATE_URL = f"{BASE}/state/nfl"

HEADERS = {
    "User-Agent": (
        "jeisey-tiers source probe (+https://github.com/jeisey/jeisey-tiers); "
        "free non-commercial project, Phase 10 measurement"
    ),
    "Accept": "application/json",
}

PAUSE_SECONDS = 1.0
CORE_POSITIONS = ("QB", "RB", "WR", "TE")


def section(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def get(url: str, *, params: Mapping[str, Any] | None = None) -> requests.Response | None:
    time.sleep(PAUSE_SECONDS)
    try:
        return requests.get(url, params=dict(params or {}), headers=HEADERS, timeout=120)
    except Exception as exc:  # noqa: BLE001 - a probe reports, it does not raise
        print(f"  transport failure: {type(exc).__name__}: {exc}")
        return None


def describe_fields(rows: Sequence[Mapping[str, Any]]) -> list[tuple[str, str, float]]:
    if not rows:
        return []
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    out = []
    for key in keys:
        values = [row.get(key) for row in rows]
        types = sorted({type(v).__name__ for v in values if v is not None})
        nulls = sum(1 for v in values if v is None or v == "")
        out.append((key, "|".join(types) or "none", round(nulls / len(values), 4)))
    return out


def probe_state() -> dict[str, Any]:
    section("0. League state — which season and week does Sleeper consider current?")
    response = get(STATE_URL)
    if response is None or response.status_code != 200:
        print(f"  http {response.status_code if response else 'transport failure'}")
        return {}
    payload = response.json()
    for key in sorted(payload):
        print(f"  {key}: {payload[key]!r}")
    return dict(payload)


def probe_player_map() -> dict[str, Any]:
    section("1. Player map — current payload, cadence rule, identity coverage")
    print(f"  GET {PLAYERS_URL}")
    print("  Documented cadence: AT MOST ONCE PER DAY. This probe issues exactly one call.")
    started = time.monotonic()
    response = get(PLAYERS_URL)
    if response is None or response.status_code != 200:
        print(f"  http {response.status_code if response else 'transport failure'}")
        return {}
    elapsed = time.monotonic() - started
    payload_bytes = len(response.content)
    payload = response.json()
    records = list(payload.values()) if isinstance(payload, Mapping) else []
    print(f"  status 200  bytes={payload_bytes}  ({payload_bytes / 1_048_576:.2f} MiB)")
    print(f"  elapsed {elapsed:.1f}s  records={len(records)}")
    print("  >>> The Phase-0 record was 12,220 records / 14,640,182 bytes. The registry")
    print("  >>> should be updated to the measurement above; payload size is an operational")
    print("  >>> fact, not a schema contract (roadmap 10.1.4).")

    core = [
        row
        for row in records
        if isinstance(row, Mapping) and str(row.get("position") or "") in CORE_POSITIONS
    ]
    print(f"  QB/RB/WR/TE records: {len(core)}")
    for field in ("player_id", "gsis_id", "espn_id", "sportradar_id", "yahoo_id", "search_rank"):
        populated = sum(1 for row in core if row.get(field) not in (None, ""))
        share = populated / len(core) if core else 0.0
        print(f"    {field:16} populated on {populated}/{len(core)} core rows ({share:.3f})")
    print("  NOTE: `search_rank` is present and is NOT ADP. Roadmap 10.1.4 forbids using it")
    print("  as pseudo-ADP; it is measured here only so its presence is on the record.")
    return {"records": len(records), "bytes": payload_bytes, "core": len(core)}


def probe_trending() -> None:
    section("2. Trending add/drop — schema, window behaviour, limit behaviour")
    for kind in ("add", "drop"):
        url = TRENDING_URL.format(kind=kind)
        response = get(url, params={"lookback_hours": 24, "limit": 25})
        if response is None or response.status_code != 200:
            print(
                f"  {kind:5} lookback=24 limit=25 -> http "
                f"{response.status_code if response else 'transport failure'}",
            )
            continue
        payload = response.json()
        rows = [dict(row) for row in payload] if isinstance(payload, list) else []
        print(f"  {kind:5} lookback=24 limit=25 -> http 200, {len(rows)} row(s)")
        if rows:
            print("      row schema (field, types, null fraction):")
            for name, types, nulls in describe_fields(rows):
                print(f"        {name:20} {types:14} null={nulls:.3f}")
            counts = [row.get("count") for row in rows if isinstance(row.get("count"), int)]
            if counts:
                print(f"      count range: {min(counts)} .. {max(counts)}")
            print(f"      first row keys only: {sorted(rows[0])}")
        print(f"      response envelope: {'bare list' if isinstance(payload, list) else 'object'}")
        temporal = [
            key
            for row in rows[:1]
            for key in row
            if any(token in key.lower() for token in ("time", "date", "updated", "as_of"))
        ]
        print(f"      temporal keys on a row: {temporal or 'NONE'}")

    section("3. Does `limit` actually change the row count?")
    for limit in (5, 25, 100):
        response = get(
            TRENDING_URL.format(kind="add"), params={"lookback_hours": 24, "limit": limit}
        )
        if response is None or response.status_code != 200:
            continue
        payload = response.json()
        rows = payload if isinstance(payload, list) else []
        print(f"  limit={limit:<4} -> {len(rows)} row(s)")

    section("4. Does `lookback_hours` actually change the population?")
    populations: dict[int, list[str]] = {}
    for hours in (6, 24, 72):
        response = get(
            TRENDING_URL.format(kind="add"),
            params={"lookback_hours": hours, "limit": 25},
        )
        if response is None or response.status_code != 200:
            continue
        payload = response.json()
        rows = payload if isinstance(payload, list) else []
        ids = [str(row.get("player_id")) for row in rows if isinstance(row, Mapping)]
        populations[hours] = ids
        print(f"  lookback_hours={hours:<4} -> {len(ids)} row(s)")
    keys = sorted(populations)
    for index in range(1, len(keys)):
        left, right = populations[keys[0]], populations[keys[index]]
        shared = len(set(left) & set(right))
        verdict = "IDENTICAL" if left == right else f"differs (shared ids: {shared})"
        print(f"  lookback {keys[0]}h vs {keys[index]}h: {verdict}")
    if any(populations[k] != populations[keys[0]] for k in keys[1:]):
        print("  >>> The window is honoured. A retained snapshot must record the")
        print("  >>> lookback_hours it asked for, or its counts are uninterpretable.")
    else:
        print("  >>> Every window returned the same rows. Record lookback_hours as")
        print("  >>> requested-but-unverified rather than claiming the window is exact.")


def main() -> int:
    print("Sleeper player-map and trending probe")
    print(f"base: {BASE}")
    print("Documented guidance: player map at most once/day; stay under 1000 calls/minute.")
    probe_state()
    probe_player_map()
    probe_trending()
    print("\nProbe complete. Nothing was retained.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
