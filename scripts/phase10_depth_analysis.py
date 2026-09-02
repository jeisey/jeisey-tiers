"""Choose the V2 tier depth from the measured board, not from a round number.

`docs/RELEASE2_ROADMAP.md` 10.5 is explicit: *"Do not blindly pick 500 because it is round.
Pick the smallest simple versioned depth with enough headroom based on the measured
market-coverage distribution."* The source populations alone cannot answer that. Fantasy
Football Calculator's deepest ADP is 201.1, which bounds *its* contribution, but the question
is where market-priced players sit in **fair-rank** order — and that is a property of the
join, not of either side.

The joined distribution is already published. `arbitrage.json` carries `fair_rank` and
`market_adp` for every priced player on the live board, which is exactly the pair needed. So
this script reads the project's **own deployed site** rather than reconstructing anything:
no vendor is involved, no store credential is needed, and the numbers are the ones a reader
is actually looking at.

It runs on a runner because the development sandbox's egress policy denies the Pages host as
it denies every other (ADR-009). It writes a report and changes nothing.

What it measures, per (league preset, scoring preset) block:

* the fair rank of the deepest market-priced player — the depth below which no ADP exists;
* how many priced players sit beyond each candidate depth, which is the number a too-shallow
  board would lose;
* the same for the top 300 *by ADP*, which is the population the surface gate protects;
* the board size at each candidate depth, so the cost of the extra rows is visible beside
  the benefit.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from collections import defaultdict
from typing import Any

BASE = "https://jeisey.github.io/jeisey-tiers/data"

#: Simple, versionable depths. Deliberately coarse: a depth chosen to the nearest ten would
#: be fitting the number to today's board, and the roadmap asks for the smallest *simple*
#: depth with headroom rather than the tightest one.
CANDIDATES = (300, 400, 500, 600, 750, 1000)

#: The surface rule's ceiling. FFC's whole population is smaller than this, which is the
#: correct reading: the rule asks for the top of each market.
MARKET_TOP_DEPTH = 300

HEADERS = {
    "User-Agent": "jeisey-tiers phase-10 depth analysis (+https://github.com/jeisey/jeisey-tiers)",
    "Accept": "application/json",
}


def fetch(name: str) -> dict[str, Any]:
    request = urllib.request.Request(f"{BASE}/{name}", headers=HEADERS)  # noqa: S310
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        payload: dict[str, Any] = json.loads(response.read().decode("utf-8"))
    return payload


def section(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def main() -> int:
    print("Phase-10 tier-depth analysis")
    print(f"source: {BASE} (this project's own published artifacts)")

    try:
        arbitrage = fetch("arbitrage.json")
        tiers = fetch("tiers.json")
    except Exception as exc:  # noqa: BLE001 - a measurement reports, it does not raise
        print(f"FAILED to read the published artifacts: {type(exc).__name__}: {exc}")
        return 1

    print(f"build: {arbitrage.get('build_id')}  generated: {arbitrage.get('generated_at_utc')}")

    priced: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in arbitrage.get("records", []):
        key = (str(record["league_preset_id"]), str(record["scoring_preset"]))
        priced[key].append(record)

    published: dict[tuple[str, str], int] = defaultdict(int)
    deepest_published: dict[tuple[str, str], int] = defaultdict(int)
    for record in tiers.get("records", []):
        key = (str(record["league_preset_id"]), str(record["scoring_preset"]))
        published[key] += 1
        deepest_published[key] = max(deepest_published[key], int(record["fair_rank"]))

    section("1. How deep does the market actually reach, in fair-rank order?")
    print(f"  {'block':22} {'priced':>7} {'deepest FR':>11} {'median FR':>10} {'p95 FR':>8}")
    worst_deepest = 0
    for key in sorted(priced):
        ranks = sorted(int(row["fair_rank"]) for row in priced[key])
        deepest = ranks[-1]
        worst_deepest = max(worst_deepest, deepest)
        median = ranks[len(ranks) // 2]
        p95 = ranks[min(len(ranks) - 1, int(len(ranks) * 0.95))]
        print(
            f"  {key[1] + '/' + key[0]:22} {len(ranks):>7} {deepest:>11} {median:>10} {p95:>8}",
        )
    print(f"\n  Deepest market-priced player across every block: fair rank {worst_deepest}")

    section("2. How many priced players would each candidate depth lose?")
    print(f"  {'block':22} " + " ".join(f"{depth:>7}" for depth in CANDIDATES))
    worst_loss: dict[int, int] = dict.fromkeys(CANDIDATES, 0)
    for key in sorted(priced):
        ranks = [int(row["fair_rank"]) for row in priced[key]]
        losses = [sum(1 for rank in ranks if rank > depth) for depth in CANDIDATES]
        for depth, loss in zip(CANDIDATES, losses, strict=True):
            worst_loss[depth] = max(worst_loss[depth], loss)
        print(f"  {key[1] + '/' + key[0]:22} " + " ".join(f"{loss:>7}" for loss in losses))
    print("\n  worst block:            " + " ".join(f"{worst_loss[d]:>7}" for d in CANDIDATES))

    section(f"3. The top {MARKET_TOP_DEPTH} BY ADP — the population the surface gate protects")
    print(f"  {'block':22} " + " ".join(f"{depth:>7}" for depth in CANDIDATES))
    gate_loss: dict[int, int] = dict.fromkeys(CANDIDATES, 0)
    for key in sorted(priced):
        top = sorted(priced[key], key=lambda row: float(row["market_adp"]))[:MARKET_TOP_DEPTH]
        ranks = [int(row["fair_rank"]) for row in top]
        losses = [sum(1 for rank in ranks if rank > depth) for depth in CANDIDATES]
        for depth, loss in zip(CANDIDATES, losses, strict=True):
            gate_loss[depth] = max(gate_loss[depth], loss)
        print(f"  {key[1] + '/' + key[0]:22} " + " ".join(f"{loss:>7}" for loss in losses))
    print("\n  worst block:            " + " ".join(f"{gate_loss[d]:>7}" for d in CANDIDATES))
    print("\n  >>> These are the players a board of that depth would drop while a market was")
    print("  >>> still drafting them in its own top 300. Any non-zero column is a depth the")
    print("  >>> surface rule would have to rescue players from, which is exactly the")
    print("  >>> head(300) blind spot ADR-063 exists to close.")

    section("4. What the extra rows cost")
    for key in sorted(published):
        print(
            f"  {key[1] + '/' + key[0]:22} published {published[key]:>5} rows, "
            f"deepest published fair rank {deepest_published[key]}",
        )
    print("\n  A deeper board is more tier rows, more JSON and more table rows to render.")
    print("  The Phase-4 board published 300 per block across nine blocks.")

    section("5. The smallest simple depth with headroom")
    clean = [depth for depth in CANDIDATES if gate_loss[depth] == 0]
    covering = [depth for depth in CANDIDATES if worst_loss[depth] == 0]
    print(f"  loses no top-{MARKET_TOP_DEPTH}-by-ADP player: {clean or 'none of the candidates'}")
    print(f"  loses no priced player at all:     {covering or 'none of the candidates'}")
    if clean:
        print(f"\n  >>> SMALLEST DEPTH SATISFYING THE SURFACE GATE: {clean[0]}")
    print("  >>> The surface rule still rescues anything beyond it, so a deeper board is")
    print("  >>> about tier COVERAGE, not about correctness. Pick the smallest simple value")
    print("  >>> and let the gate catch the rest.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
