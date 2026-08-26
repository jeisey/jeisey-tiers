"""Source probe: Fantasy Football Calculator ADP.

**Not production code, and not a dependency of anything.** This is the check `AGENTS.md`
section 5 requires before a source marked `verify_before_use` can become a production
dependency, and `docs/DATA_SOURCES.md` section 13 is where its results get written down.
It runs on a GitHub runner because the development sandbox's egress policy denies this host
(ADR-053), and it prints its findings to the job log rather than retaining anything.

It answers, in order of how much they matter:

1. **Is there a joinable player id?** `AGENTS.md` section 6 forbids a production join that
   depends solely on normalized names. If FFC publishes only name/team/position, that
   settles the question before anyone writes an adapter — so this is measured first and
   reported loudest.
2. What the schema actually is, field by field, with null fractions.
3. Whether all twelve `format x teams` cohorts exist for the target season, and how deep
   and how well-sampled each one is.
4. Whether a data-as-of time is published (MFL does not, which is why `market_quote`
   carries a retrieval time and a source timestamp separately).
5. What `robots.txt` says, recorded verbatim for the terms review.

**What it deliberately does not do:** retain any payload, print player rows, or write to
the store. The log is world-readable on a public repository, and the terms of this source
have not been reviewed yet. Schema, counts and derived statistics only.
"""

from __future__ import annotations

import sys
import time
from collections import Counter
from typing import Any

import requests

BASE = "https://fantasyfootballcalculator.com"
JSON_PATH = "/api/v1/adp/{fmt}"
CSV_PATH = "/adp/csv/{fmt}.csv"
FORMATS = ("standard", "ppr", "half-ppr")
TEAM_SIZES = (8, 10, 12, 14)
SEASON = 2026

#: ADR-017's rule for MFL applies here too: identify the client, send nothing else.
HEADERS = {
    "User-Agent": (
        "jeisey-tiers source probe (+https://github.com/jeisey/jeisey-tiers); "
        "one-off feasibility check, not a production client"
    ),
    "Accept": "application/json",
}

#: Any of these appearing on a player row would be a real id bridge. Ordered by how useful
#: each is to this project: the canonical registry indexes espn/sleeper/pfr/sportradar/yahoo,
#: so those join directly; the rest would need their own crosswalk.
ID_FIELDS = (
    "gsis_id",
    "espn_id",
    "sleeper_id",
    "pfr_id",
    "sportradar_id",
    "yahoo_id",
    "mfl_id",
    "fantasypros_id",
    "player_id",
    "id",
)

PAUSE_SECONDS = 1.5


def get(url: str, *, accept: str | None = None) -> requests.Response:
    headers = dict(HEADERS)
    if accept:
        headers["Accept"] = accept
    time.sleep(PAUSE_SECONDS)
    return requests.get(url, headers=headers, timeout=30)


def section(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def describe_fields(rows: list[dict[str, Any]]) -> list[tuple[str, str, float]]:
    """Field name, observed python types, null fraction — the shape of a schema fixture."""
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


#: The publisher's own terms for this endpoint. Fetched so the wording is recorded in a run
#: log verbatim rather than transcribed by hand.
TERMS_URL = "https://help.fantasyfootballcalculator.com/article/42-adp-rest-api"


def probe_terms() -> None:
    section("0. Published terms for the ADP REST API")
    print(f"source: {TERMS_URL}")
    try:
        response = get(TERMS_URL, accept="text/html")
        print(f"status {response.status_code}  bytes={len(response.content)}")
        # Crude, deliberately: this records the sentences that carry the obligations, so a
        # reader of the log sees the grant rather than a summary of it.
        text = response.text
        for token in ("free for personal", "attribution", "too frequently", "once per day"):
            index = text.lower().find(token)
            if index >= 0:
                excerpt = " ".join(text[max(0, index - 220) : index + 220].split())
                print(f"  ...{excerpt}...")
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED: {exc}")
        print("  Terms could not be fetched. Do not proceed on a remembered summary.")


def probe_robots() -> None:
    section("1. robots.txt, recorded verbatim for the terms review")
    try:
        response = get(f"{BASE}/robots.txt", accept="text/plain")
        print(f"status {response.status_code}")
        body = response.text.strip()
        print(body[:2000] if body else "(empty)")
    except Exception as exc:  # noqa: BLE001 - a probe reports, it does not raise
        print(f"FAILED: {exc}")


def probe_one(fmt: str, teams: int) -> dict[str, Any] | None:
    url = f"{BASE}{JSON_PATH.format(fmt=fmt)}?teams={teams}&year={SEASON}&position=all"
    try:
        response = get(url)
    except Exception as exc:  # noqa: BLE001
        print(f"  {fmt:9} teams={teams:<3} FAILED: {exc}")
        return None
    if response.status_code != 200:
        print(f"  {fmt:9} teams={teams:<3} http {response.status_code}")
        return None
    try:
        payload = response.json()
    except ValueError:
        print(
            f"  {fmt:9} teams={teams:<3} http 200 but body is not JSON "
            f"({response.headers.get('content-type')})"
        )
        return None
    players = payload.get("players") if isinstance(payload, dict) else None
    meta = {k: v for k, v in payload.items() if k != "players"} if isinstance(payload, dict) else {}
    count = len(players) if isinstance(players, list) else 0
    print(f"  {fmt:9} teams={teams:<3} http 200  players={count:<5} meta={meta}")
    return {"format": fmt, "teams": teams, "payload": payload, "players": players or []}


def main() -> int:
    print(f"Fantasy Football Calculator probe — season {SEASON}")
    print(f"base: {BASE}")
    print("Requests are paced at 1.5s and total fewer than twenty.")

    probe_terms()
    probe_robots()

    section("2. Cohort coverage: does every format x teams exist for this season?")
    results = []
    for fmt in FORMATS:
        for teams in TEAM_SIZES:
            got = probe_one(fmt, teams)
            if got:
                results.append(got)

    if not results:
        print("\nNo cohort returned usable JSON. Nothing further can be measured.")
        return 1

    section("3. Top-level envelope keys (the first successful cohort)")
    first = results[0]
    envelope = first["payload"]
    if isinstance(envelope, dict):
        for key, value in envelope.items():
            if key == "players":
                print(f"  players: list[{len(value)}]")
            else:
                print(f"  {key}: {value!r}")

    section("4. Player-row schema — field, types, null fraction")
    rows = first["players"]
    print(f"(measured over {len(rows)} rows of {first['format']} / {first['teams']}-team)")
    for name, types, nulls in describe_fields(rows):
        print(f"  {name:24} {types:20} null={nulls:.3f}")

    section("5. THE DECIDING QUESTION — is there a joinable player id?")
    present = [f for f in ID_FIELDS if any(f in row for row in rows)]
    print(f"  id-like fields present: {present or 'NONE'}")
    for field in present:
        values = [row.get(field) for row in rows if row.get(field) not in (None, "")]
        distinct = len(set(map(str, values)))
        print(
            f"    {field:16} populated={len(values)}/{len(rows)} distinct={distinct} "
            f"sample_type={type(values[0]).__name__ if values else 'n/a'}"
        )
    if not present:
        print("  >>> No id field. Per AGENTS.md section 6 a name-only join cannot resolve a")
        print("  >>> production record, so FFC could only ever be a benchmark, not a price")
        print("  >>> source, unless an id appears elsewhere in the payload.")
    else:
        print("  >>> An id field exists. Whether it BRIDGES to gsis is the next question;")
        print("  >>> an FFC-internal id that maps to nothing is not a bridge.")

    section("6. Do those ids reach our canonical registry?")
    try:
        from ffdraft.identity.ids import IdNamespace
        from ffdraft.market.identity import load_market_identity

        identity = load_market_identity(SEASON)
        registry = identity.registry
        print(f"  registry players: {len(registry.players)}")
        for field, namespace in (
            ("gsis_id", IdNamespace.GSIS),
            ("espn_id", IdNamespace.ESPN),
            ("sleeper_id", IdNamespace.SLEEPER),
        ):
            if field not in present:
                continue
            hits = sum(
                1
                for row in rows
                if row.get(field) and registry.lookup(namespace, str(row[field])).status == "found"
            )
            print(f"  {field}: {hits}/{len(rows)} resolve through the registry")

        # Name matching is a DIAGNOSTIC. It never resolves a production record (ADR-019).
        # Reported only to size the gap an id bridge would have to close.
        by_name = Counter()
        for row in rows:
            name = str(row.get("name") or "").strip()
            if name and registry.name_candidates(name):
                by_name["matched"] += 1
            elif name:
                by_name["unmatched"] += 1
        print(f"  DIAGNOSTIC ONLY, never a production join — name lookups: {dict(by_name)}")
    except Exception as exc:  # noqa: BLE001
        print(f"  registry comparison unavailable: {type(exc).__name__}: {exc}")

    section("7. Depth and sample size per cohort")
    print(
        f"  {'format':10} {'teams':>5} {'rows':>6} {'deepest adp':>12} {'min drafts':>11} "
        f"{'max drafts':>11}"
    )
    for got in results:
        players = got["players"]
        adps = [p.get("adp") for p in players if isinstance(p.get("adp"), int | float)]
        picks = [
            p.get("times_drafted")
            for p in players
            if isinstance(p.get("times_drafted"), int | float)
        ]
        print(
            f"  {got['format']:10} {got['teams']:>5} {len(players):>6} "
            f"{max(adps) if adps else 0:>12.1f} {min(picks) if picks else 0:>11} "
            f"{max(picks) if picks else 0:>11}"
        )

    section("8. Is a data-as-of time published?")
    # Scan one level down as well: FFC nests the aggregation window under `meta`, and a
    # top-level-only scan reported "none" when the answer was in fact yes.
    flat: dict[str, Any] = {}
    if isinstance(envelope, dict):
        for key, value in envelope.items():
            if key == "players":
                continue
            if isinstance(value, dict):
                flat.update({f"{key}.{k}": v for k, v in value.items()})
            else:
                flat[key] = value
    stamp_keys = [
        k
        for k in flat
        if any(tok in k.lower() for tok in ("date", "time", "updated", "as_of", "stamp"))
    ]
    print(f"  temporal keys (envelope and one level down): {stamp_keys or 'NONE'}")
    for key in stamp_keys:
        print(f"    {key} = {flat[key]!r}")
    if not stamp_keys:
        print("  >>> Like MFL, no data-as-of time. Retrieval time and source time must stay")
        print("  >>> separate fields (AGENTS.md section 5).")
    else:
        print("  >>> A window IS published. It is a source window, not a retrieval time, and")
        print("  >>> the two must stay separate fields (AGENTS.md section 5).")

    section("9. CSV variant — same data, different transport?")
    csv_url = f"{BASE}{CSV_PATH.format(fmt='half-ppr')}?teams=12&position=all"
    try:
        response = get(csv_url, accept="text/csv")
        header = response.text.splitlines()[0] if response.text else "(empty)"
        ctype = response.headers.get("content-type")
        print(f"  status {response.status_code}  content-type={ctype}")
        print(f"  header row: {header}")
        print("  NOTE: the CSV path takes no `year`, so it is whatever season the site")
        print("  considers current. The JSON path takes an explicit year and is therefore")
        print("  the reproducible one; a retained snapshot must pin the season.")
    except Exception as exc:  # noqa: BLE001
        print(f"  FAILED: {exc}")

    section("10. DOES `teams` DO ANYTHING? per-player comparison, not just totals")
    for fmt in FORMATS:
        cohorts = {got["teams"]: got["players"] for got in results if got["format"] == fmt}
        if len(cohorts) < 2:
            continue
        sizes = sorted(cohorts)
        base_size = sizes[0]
        base = {row.get("player_id"): row for row in cohorts[base_size]}
        for size in sizes[1:]:
            other = {row.get("player_id"): row for row in cohorts[size]}
            shared = set(base) & set(other)
            differing = [
                pid
                for pid in shared
                if base[pid].get("adp") != other[pid].get("adp")
                or base[pid].get("times_drafted") != other[pid].get("times_drafted")
            ]
            verdict = "DIFFERENT" if differing else "byte-identical"
            print(
                f"  {fmt:9} teams={base_size} vs teams={size}: "
                f"shared={len(shared):4} rows differing on adp/times_drafted={len(differing):4} "
                f"-> {verdict}"
            )
    print("  >>> If every comparison is byte-identical, `teams` is accepted and ignored, and")
    print("  >>> a cohort built on it would be the unfiltered aggregate wearing a label")
    print("  >>> (the rule config/source-registry.yaml already applies to MFL's CUTOFF).")

    print("\nProbe complete. Nothing was retained.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
