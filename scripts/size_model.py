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
from datetime import datetime, timedelta
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


#: ADR-114: how a board's rows split across Sleeper's two top-100 lists. Most board players are
#: in neither (the 2026-10-21 probe: 856 of 987 mapped players in neither, 29 in both); a board
#: is weighted to the top of the player pool, so its share in a list is higher than that.
BEHAVIOR_SIDE_SPLIT = (("neither", 0.70), ("both", 0.15), ("add", 0.10), ("drop", 0.05))
BEHAVIOR_FEED_FLOORS = {"add": 9_546, "drop": 17_444}


def _behavior_sides(row: dict[str, Any], rng: random.Random) -> None:
    """Give a cloned Opportunity row a consistent per-side state, as production publishes it."""
    if not row.get("behavior_available"):
        return
    draw = rng.random()
    kind = "neither"
    for name, share in BEHAVIOR_SIDE_SPLIT:
        if draw < share:
            kind = name
            break
        draw -= share
    observed = {"add": kind in {"both", "add"}, "drop": kind in {"both", "drop"}}
    for side in ("add", "drop"):
        if observed[side]:
            floor = BEHAVIOR_FEED_FLOORS[side]
            row[f"{side}_state"] = "observed"
            row[f"{side}_count"] = floor + rng.randrange(0, 40 * floor)
            row[f"{side}_count_max"] = None
            row[f"{side}_rank"] = rng.randrange(1, 101)
        else:
            row[f"{side}_state"] = "not_in_feed"
            row[f"{side}_count"] = None
            row[f"{side}_count_max"] = BEHAVIOR_FEED_FLOORS[side]
            row[f"{side}_rank"] = None
    adds, drops = row["add_count"], row["drop_count"]
    row["net_add_count"] = None if adds is None or drops is None else adds - drops


#: ADR-114: which sides a retained series carries. A series exists only for a player one feed
#: carried, so it is in both, or the add list only, or the drop list only — about a third of
#: sides unobserved, as on the live 2026-10-21 series (1,099 of 3,200 sides had been zero-filled).
BEHAVIOR_SERIES_SPLIT = (("both", 0.35), ("add", 0.35), ("drop", 0.30))


def _behavior_series_sides(row: dict[str, Any], rng: random.Random) -> None:
    """ADR-114's per-side points, counts and spans, derived from the record's own points as
    production derives them — never perturbed independently, which would price random floats."""
    draw = rng.random()
    kind = "both"
    for name, share in BEHAVIOR_SERIES_SPLIT:
        if draw < share:
            kind = name
            break
        draw -= share
    points = row["points"]
    for point in points:
        if kind == "drop":
            point["add_count"] = None
        if kind == "add":
            point["drop_count"] = None
        adds, drops = point.get("add_count"), point.get("drop_count")
        point["net_add_count"] = None if adds is None or drops is None else adds - drops
    row["observations"] = len(points)
    for side, field in (("add", "add_count"), ("net", "net_add_count")):
        seen = [point for point in points if point.get(field) is not None]
        row[f"{side}_observations"] = len(seen)
        row[f"{side}_span_days"] = row["span_days"] if len(seen) == len(points) else 0.0
    if kind != "both":
        row["net_trend"] = None
    if kind == "drop":
        row["add_trend"] = None


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
            fixed = {"week", "latest_week", "season", "through_week", "target_week"}
            if key.endswith("rank") or key in fixed:
                return value
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
            _behavior_sides(row, perturb.random)
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

    # ADR-105: every appearing player per scoring preset, ranked within his position.
    for scoring in profile["scorings"]:
        rows = []
        for index in range(counts["actuals_per_scoring"]):
            row = clone("season_actuals", index, players[index % len(players)])
            row["scoring_preset"] = scoring
            rows.append(row)
        for position in ("QB", "RB", "WR", "TE"):
            ranked(
                [row for row in rows if row["position"] == position and row["games_played"] > 0],
                "season_position_rank",
            )
        records["season_actuals"].extend(rows)

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
                # ADR-104: the drive rail carries one entry per played week, so it grows with
                # the season exactly as the role series does.
                breadth = row.get("drive_breadth")
                if breadth:
                    breadth["weeks"] = perturb.series(breadth["weeks"], profile["usage_weeks"])
                # The real board repeats these heavily (164 distinct shares, 39 EPA values on
                # 606 rows): a share of touchdown points over a few games takes few values.
                share = perturb.pool("touchdown_share", 160, 4)
                row["touchdown_points_share"] = dict.fromkeys(row["touchdown_points_share"], share)
                row["pass_epa_per_dropback"] = (
                    perturb.pool("epa", 40, 3) if row["position"] == "QB" else None
                )
            if artifact == "behavior_trend_series":
                row["points"] = perturb.series(row["points"], profile["behavior_points"])
                _behavior_series_sides(row, perturb.random)
            if artifact == "player_headshots":
                row["provider_player_id"] = player["espn"]
                row["image_url"] = (
                    f"https://a.espncdn.com/i/headshots/nfl/players/full/{player['espn']}.png"
                )
            records[artifact].append(row)
    # ADR-112: one ESPN record per Opportunity Board player, preset-independent, and a series
    # at the steady state of a full 28-day window — one read a day, the same read instants for
    # every player (they are the same captures), values at ESPN's two decimals.
    espn_template = templates["espn_ownership"]
    measured = next(
        row for row in espn_template if row["rostered_change_7d"]["state"] == "measured"
    )
    for index in range(counts["espn_ownership"]):
        player = players[index % len(players)]
        row = _identity(perturb.walk("espn_ownership", measured), player)
        row["espn_id"] = player["espn"]
        row["observed_at_utc"] = measured["observed_at_utc"]
        records["espn_ownership"].append(row)
    series_template = next(
        row for row in templates["espn_ownership_series"] if row["observations"] > 2
    )
    newest = series_template["points"][-1]["observed_at_utc"]
    anchor_at = datetime.fromisoformat(newest.replace("Z", "+00:00"))
    instants = [
        (anchor_at - timedelta(days=offset)).isoformat().replace("+00:00", "Z")
        for offset in range(profile["espn_points"] - 1, -1, -1)
    ]
    for index in range(counts["espn_series"]):
        player = players[index % len(players)]
        row = _identity(dict(series_template), player)
        row["espn_id"] = player["espn"]
        points = []
        level = round(rng.uniform(0.0, 99.0), 2)
        for instant in instants:
            level = round(min(100.0, max(0.0, level + rng.uniform(-1.5, 1.5))), 2)
            points.append(
                {
                    "observed_at_utc": instant,
                    "espn_updated_at_utc": instant,
                    "espn_current_period": series_template["points"][-1]["espn_current_period"],
                    "percent_rostered": level,
                    "percent_started": round(level * rng.uniform(0.2, 0.9), 2),
                },
            )
        row["points"] = points
        row["observations"] = len(points)
        row["captures_in_window"] = len(points)
        row["span_hours"] = float((len(points) - 1) * 24)
        records["espn_ownership_series"].append(row)
    # ADR-107: every appearing player's whole tree, one reading per metric of his position (a
    # complete golden tree per position, cloned), and one presence record per board player
    # with no appearance. The definitions do not grow with the board: they are the golden ones.
    trees: dict[str, list[dict[str, Any]]] = {}
    for record in templates["player_skill_tree"]:
        if record["state"] == "no_appearances":
            continue
        tree = [
            row for row in templates["player_skill_tree"] if row["player_id"] == record["player_id"]
        ]
        if len(tree) > len(trees.get(record["position"], [])):
            trees[record["position"]] = tree
    absent = next(row for row in templates["player_skill_tree"] if row["state"] == "no_appearances")
    tree_players = [player for player in players if player["position"] in trees]
    for index in range(counts["skill_tree_players"]):
        player = tree_players[index % len(tree_players)]
        # The board's deepest players are the ones with no appearance yet, never its leaders.
        if index >= counts["skill_tree_players"] - counts["skill_tree_without_appearance"]:
            records["player_skill_tree"].append(_identity(dict(absent), player))
            continue
        games = rng.randrange(1, 9)
        for template in trees[player["position"]]:
            row = _identity(perturb.walk("player_skill_tree", template), player)
            # A year is not a measurement: the combine season is copied, never perturbed.
            row["games"], row["source_season"] = games, template["source_season"]
            records["player_skill_tree"].append(row)
    records["skill_tree_definitions"] = list(templates["skill_tree_definitions"])

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

    # ADR-113: recent form, every player who appeared in the six-week span plus every board
    # player, per scoring preset. The golden fixture holds no badge, so a share of windows is
    # given a badge verdict with two role readings — the heaviest a window gets on a real board.
    badge = {
        "category": "takeover",
        "reason": "takeover_role",
        "games": [6, 7, 8],
        "streak": 3,
        "role": [
            {
                "metric": "target_share",
                "games": 3,
                "level": 0.214,
                "baseline": 0.131,
                "baseline_games": 5,
                "passed": "substantial",
            },
            {
                "metric": "snap_share",
                "games": 3,
                "level": 0.782,
                "baseline": 0.604,
                "baseline_games": 5,
                "passed": "increase",
            },
        ],
    }
    # Last, on its own stream, so adding it leaves every other artifact's generated bytes
    # unchanged.
    recent_rng = random.Random(seed + 113)
    for scoring in profile["scorings"]:
        for index in range(counts["recent_per_scoring"]):
            row = clone("recent_form", index, players[index % len(players)])
            row["scoring_preset"] = scoring
            for window in row["windows"].values():
                if recent_rng.random() < profile.get("recent_badge_share", 0.08):
                    window["breakout"] = {
                        **badge,
                        "category": recent_rng.choice(["takeover", "sneaking", "eyebrow"]),
                    }
            records["recent_form"].append(row)

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
