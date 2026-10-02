"""A real-sized artifact set with no real data in it: the size model the budget gate runs on.

The payload budgets (ADR-098) are about the 2026 board's *size* — 500 rows a block, nine
blocks, 1,069 players, week-by-week series — and the committed fixtures are sixteen rows. A
budget checked against them would pass forever. Production artifacts cannot be committed
(AGENTS.md section 15), and CI cannot read the private store, so CI builds this instead:

* every **count** comes from ``config/size-model.json``, measured on the production week-4
  artifacts of 2026-09-30 (rows per block, points per series, markets per row);
* every **record shape** comes from the committed golden artifacts, cloned — so every field,
  nesting and optional key the page reads is present;
* every **number** is the template's, perturbed by a seeded generator and written at the
  template's own published precision, so the bytes carry about as much entropy as real ones;
* the two share fields the board publishes at full double precision are drawn at full
  precision, as the real ones are.

It is deterministic (one seed) and is packaged by the production packager. ADR-098 records how
closely its served sizes track the real build's, family by family. It is **not** a model of
football: no number in it means anything, and nothing reads it except the budget gate.

Usage::

    uv run python scripts/size_model.py --out web/dist-size-model/data
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ffdraft.artifacts import records_to_csv  # noqa: E402
from ffdraft.artifacts.serving import package_serving  # noqa: E402
from ffdraft.artifacts.spec import ARTIFACT_SPECS  # noqa: E402

GOLDEN = ROOT / "tests" / "fixtures" / "artifacts"
PROFILE = ROOT / "config" / "size-model.json"

TEAMS = [
    "ARI",
    "ATL",
    "BAL",
    "BUF",
    "CAR",
    "CHI",
    "CIN",
    "CLE",
    "DAL",
    "DEN",
    "DET",
    "GB",
    "HOU",
    "IND",
    "JAX",
    "KC",
    "LAC",
    "LAR",
    "LV",
    "MIA",
    "MIN",
    "NE",
    "NO",
    "NYG",
    "NYJ",
    "PHI",
    "PIT",
    "SEA",
    "SF",
    "TB",
    "TEN",
    "WAS",
]
FIRST = [
    "Aaron",
    "Adam",
    "Alex",
    "Amari",
    "Andre",
    "Anthony",
    "Austin",
    "Bijan",
    "Brandon",
    "Brian",
    "Bryce",
    "Caleb",
    "Calvin",
    "Cameron",
    "Chase",
    "Chris",
    "Christian",
    "Cole",
    "Cooper",
    "Dallas",
    "Dalton",
    "Daniel",
    "Darius",
    "David",
    "DeAndre",
    "Derrick",
    "Devin",
    "Drake",
    "Elijah",
    "Garrett",
    "George",
    "Isaiah",
    "Jahmyr",
    "Jake",
    "Jalen",
    "Jameson",
    "Jaylen",
    "Jerry",
    "Jonathan",
    "Jordan",
    "Josh",
    "Justin",
    "Keenan",
    "Kenneth",
    "Kyle",
    "Kyren",
    "Lamar",
    "Malik",
    "Marvin",
    "Michael",
    "Nico",
    "Patrick",
    "Puka",
    "Rashee",
    "Rhamondre",
    "Saquon",
    "Tank",
    "Tee",
    "Travis",
    "Trey",
    "Tyreek",
    "Zay",
]
LAST = [
    "Achane",
    "Adams",
    "Allen",
    "Andrews",
    "Barkley",
    "Bowers",
    "Brown",
    "Burrow",
    "Chase",
    "Cook",
    "Davis",
    "Diggs",
    "Etienne",
    "Evans",
    "Flowers",
    "Gibbs",
    "Godwin",
    "Hall",
    "Harris",
    "Henry",
    "Higgins",
    "Hill",
    "Hurts",
    "Irving",
    "Jackson",
    "Jacobs",
    "Jefferson",
    "Jones",
    "Kelce",
    "Kincaid",
    "Kirk",
    "LaPorta",
    "Lamb",
    "London",
    "Mahomes",
    "Mason",
    "McBride",
    "McCaffrey",
    "McConkey",
    "Metcalf",
    "Mixon",
    "Moore",
    "Nabers",
    "Olave",
    "Pacheco",
    "Pickens",
    "Pittman",
    "Purdy",
    "Rice",
    "Ridley",
    "Robinson",
    "Samuel",
    "Smith",
    "Stroud",
    "Sutton",
    "Swift",
    "Taylor",
    "Thomas",
    "Walker",
    "Warren",
    "Williams",
    "Wilson",
    "Worthy",
    "Young",
]
SUFFIXES = ("", "", "", "", "", "", " Jr.", " II", " III")


def _decimals(value: float) -> int:
    text = repr(value)
    if "e" in text or "." not in text:
        return 0
    return min(4, len(text.split(".")[1]))


class Perturb:
    def __init__(self, seed: int) -> None:
        self.random = random.Random(seed)
        self.shares = [self.random.random() for _ in range(240)]
        self.pools: dict[str, list[float]] = {}
        #: The published precision of the artifact being cloned (``published_decimals``).
        self.decimals = 0

    def number(self, key: str, value: Any) -> Any:
        # A zero stays a zero: real boards are full of them (a quarterback's target share, a
        # driver that did not move), and noise on a zero would invent entropy they do not have.
        if isinstance(value, bool) or value is None or value == 0:
            return value
        if isinstance(value, int):
            if key.endswith("rank") or key in {"week", "latest_week", "season", "through_week"}:
                return value
            # Most players on a board draw no waiver transactions on a given day.
            if key in {"add_count", "drop_count", "net_add_count"} and self.random.random() < 0.7:
                return 0
            return max(0, round(value * self.random.uniform(0.5, 1.5)))
        if isinstance(value, float):
            if key.endswith("_share_last3"):
                # Full double precision, as published, from a pool about the size of the real
                # board's distinct values (a share over three games takes few values).
                return self.shares[self.random.randrange(len(self.shares))]
            scaled = value * self.random.uniform(0.6, 1.4) + self.random.gauss(
                0, 0.03 * (abs(value) + 1)
            )
            return round(scaled, max(1, _decimals(value), self.decimals))
        return value

    def pool(self, name: str, size: int, digits: int) -> float:
        """A value from a small fixed pool: for fields the real board repeats heavily."""
        values = self.pools.setdefault(
            name, [round(self.random.random(), digits) for _ in range(size)]
        )
        return values[self.random.randrange(size)]

    def walk(self, key: str, value: Any) -> Any:
        if isinstance(value, dict):
            return {k: self.walk(k, v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.walk(key, item) for item in value]
        return self.number(key, value)

    def series(self, template: list[Any], length: int) -> list[Any]:
        if not template:
            return []
        return [self.walk("point", template[index % len(template)]) for index in range(length)]


def _players(count: int, rng: random.Random) -> list[dict[str, str]]:
    seen: set[str] = set()
    players = []
    positions = ["QB"] * 6 + ["RB"] * 24 + ["WR"] * 33 + ["TE"] * 34
    while len(players) < count:
        player_id = f"gsis:00-00{rng.randrange(20000, 45000):05d}"
        if player_id in seen:
            continue
        seen.add(player_id)
        # Real names barely repeat; a surname built from two syllable halves keeps them apart.
        surname = rng.choice(LAST) + rng.choice(LAST).lower()[: rng.randrange(0, 4)]
        name = f"{rng.choice(FIRST)} {surname}{rng.choice(SUFFIXES)}"
        players.append(
            {
                "player_id": player_id,
                "display_name": name,
                "team": rng.choice(TEAMS),
                "position": rng.choice(positions),
                "espn": str(rng.randrange(2_000_000, 5_200_000)),
            },
        )
    return players


def _envelope(artifact: str) -> dict[str, Any]:
    return json.loads((GOLDEN / ARTIFACT_SPECS[artifact].json_filename).read_text("utf-8"))


def _identity(record: dict[str, Any], player: Mapping[str, str]) -> dict[str, Any]:
    out = dict(record)
    out["player_id"] = player["player_id"]
    if "display_name" in out:
        out["display_name"] = player["display_name"]
    if "team" in out:
        out["team"] = player["team"]
    if "current_team" in out:
        out["current_team"] = player["team"]
    if "position" in out:
        out["position"] = player["position"]
    return out


def build(out: Path, seed: int = 20260930) -> None:
    profile = json.loads(PROFILE.read_text("utf-8"))
    rng = random.Random(seed)
    perturb = Perturb(seed)
    players = _players(profile["players"], rng)
    blocks = [(league, scoring) for league in profile["leagues"] for scoring in profile["scorings"]]
    records: dict[str, list[dict[str, Any]]] = {artifact: [] for artifact in ARTIFACT_SPECS}
    templates = {artifact: _envelope(artifact)["records"] for artifact in ARTIFACT_SPECS}

    decimals = profile.get("published_decimals", {})
    shared: dict[tuple[str, str], Any] = {}

    def clone(artifact: str, index: int, player: Mapping[str, str]) -> dict[str, Any]:
        template = templates[artifact][index % len(templates[artifact])]
        perturb.decimals = int(decimals.get(artifact, 0))
        cloned = perturb.walk(artifact, template)
        perturb.decimals = 0
        # A team's next game is one object for every player on it, as it is on the real board.
        for field in ("game", "opponent"):
            if artifact == "weekly_projections" and field in cloned:
                cloned[field] = shared.setdefault((field, player["team"]), cloned[field])
        return _identity(cloned, player)

    def ranked(rows: list[dict[str, Any]], *fields: str) -> None:
        for field in fields:
            for rank, row in enumerate(rows, start=1):
                if field in row:
                    row[field] = rank

    counts = profile["counts"]
    for league, scoring in blocks:
        for artifact, key in (
            ("tiers", "tiers_per_block"),
            ("ros_tiers", "ros_per_block"),
            ("arbitrage", "arbitrage_per_block"),
            ("market_trend_series", "trend_series_per_block"),
        ):
            rows = []
            for index in range(counts[key]):
                row = clone(artifact, index, players[index % len(players)])
                row["league_preset_id"], row["scoring_preset"] = league, scoring
                if artifact == "market_trend_series":
                    row["points"] = perturb.series(row["points"], profile["trend_points"])
                if artifact == "arbitrage":
                    row["markets"] = perturb.series(row.get("markets") or [], profile["markets"])
                rows.append(row)
            ranked(rows, "fair_rank", "ros_fair_rank", "position_rank", "ros_position_rank")
            records[artifact].extend(rows)
        # The Opportunity Board copies its ROS row's intrinsic fields exactly, as the real one
        # does, so the served join has the same shape; a few surfaced rows carry their own.
        ros_rows = records["ros_tiers"][-counts["ros_per_block"] :]
        opportunity = []
        for index in range(counts["opportunity_per_block"]):
            row = clone("inseason_opportunity", index, players[index % len(players)])
            row["league_preset_id"], row["scoring_preset"] = league, scoring
            if index < len(ros_rows):
                source = ros_rows[index]
                for field, value in source.items():
                    if field in row and field not in {
                        "surface_reasons",
                        "quality_flags",
                        "schema_version",
                    }:
                        row[field] = value
            opportunity.append(row)
        records["inseason_opportunity"].extend(opportunity)

    for scoring in profile["scorings"]:
        for artifact, key in (
            ("projections", "projections_per_scoring"),
            ("weekly_projections", "weekly_per_scoring"),
        ):
            for index in range(counts[key]):
                row = clone(artifact, index, players[index % len(players)])
                row["scoring_preset"] = scoring
                records[artifact].append(row)

    for artifact, key in (
        ("player_usage", "usage"),
        ("behavior_trend_series", "behavior"),
        ("player_status", "status"),
        ("player_headshots", "headshots"),
    ):
        for index in range(counts[key]):
            player = players[index % len(players)]
            row = clone(artifact, index, player)
            if artifact == "player_usage":
                row["weeks"] = perturb.series(row["weeks"], profile["usage_weeks"])
                # The real board repeats these heavily (164 distinct shares, 39 EPA values on
                # 606 rows): a share of touchdown points over a few games takes few values.
                share = perturb.pool("touchdown_share", 160, 4)
                row["touchdown_points_share"] = dict.fromkeys(row["touchdown_points_share"], share)
                row["pass_epa_per_dropback"] = (
                    perturb.pool("epa", 40, 3) if row["position"] == "QB" else None
                )
            if artifact == "behavior_trend_series":
                row["points"] = perturb.series(row["points"], profile["behavior_points"])
            if artifact == "player_headshots":
                row["provider_player_id"] = player["espn"]
                row["image_url"] = (
                    f"https://a.espncdn.com/i/headshots/nfl/players/full/{player['espn']}.png"
                )
            records[artifact].append(row)
    records["team_matchups"] = [
        {**template, "team": TEAMS[index]}
        for index, template in enumerate(templates["team_matchups"] * 2)
    ][: len(TEAMS)]
    # ADR-099: one game-day context per team, every team playing (the worst case), each a
    # perturbed copy of a fixture team so forecasts and listed players carry real entropy.
    context_templates = templates["weekly_context"]
    records["weekly_context"] = [
        {
            **perturb.walk("weekly_context", context_templates[index % len(context_templates)]),
            "team": team,
        }
        for index, team in enumerate(TEAMS)
    ]

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for artifact, rows in records.items():
        if not rows:
            continue
        spec = ARTIFACT_SPECS[artifact]
        envelope = _envelope(artifact)
        ordered = spec.sorted_records(rows)
        envelope["records"] = list(ordered)
        envelope["record_count"] = len(ordered)
        (out / spec.json_filename).write_text(json.dumps(envelope, indent=2) + "\n", "utf-8")
        if spec.csv_filename:
            (out / spec.csv_filename).write_text(records_to_csv(artifact, ordered), "utf-8")
    for name in ("build_metadata.json", "ros_build_metadata.json"):
        shutil.copy(GOLDEN / name, out / name)
    package_serving(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260930)
    args = parser.parse_args()
    build(args.out, args.seed)
    print(f"size model written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
