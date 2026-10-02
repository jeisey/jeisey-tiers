"""The Trade tab's richer-simulation fixture (ADR-100 §5).

The page approximates a two- or three-player package's floor and ceiling from each member's
five published VORP quantiles and expectation (`ros_package_quantiles_v1`). This script makes
the evidence that approximation is measured against, using the repository's **own** draw loop:

1. a synthetic universe of QB/RB/WR/TE players whose remaining-season points are drawn the way
   rest-of-season outcomes behave — a number of remaining games played, each a skewed (gamma)
   score — independently per player, as `mc_quantile_sampler_v1` draws them;
2. :func:`ffdraft.simulation.vorp.simulate_vorp` with the in-season
   :func:`ffdraft.ros.value.allocate_with_bench` rule on the default league preset, so every
   draw re-allocates the league and re-derives the rostered-depth replacement level — the one
   cross-player dependence production VORP has;
3. the published fields exactly as production rounds them (4 decimals), and for a fixed set of
   packages the **true** P10 and P90 of the summed VORP draws, plus the same quantiles with each
   member's draws shuffled independently (which isolates the independence assumption).

Synthetic, deterministic and offline: no model, no network, no real player. The output is the
committed `web/tests/fixtures/trade-simulation.json`, read by `web/tests/trade.test.ts`.

    uv run python scripts/trade_package_fixture.py [--out PATH] [--draws N]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from ffdraft.config import load_league_config
from ffdraft.ros.value import allocate_with_bench
from ffdraft.simulation.vorp import SimulationConfig, simulate_vorp

GENERATOR_VERSION = "trade_package_fixture_v1"
SEED = 20261002
DRAWS = 4000
REMAINING_WEEKS = 9
#: Universe by position: enough depth below every rostered-depth replacement level.
UNIVERSE = {"QB": 40, "RB": 90, "WR": 120, "TE": 50}
#: Points per game for the best and the deepest player of each position (PPR-like scale).
PPG_RANGE = {"QB": (24.0, 9.0), "RB": (21.0, 3.0), "WR": (20.0, 3.0), "TE": (15.0, 2.0)}
PAIRS = 160
TRIPLES = 160
SINGLES = 20
LEVELS = (0.1, 0.25, 0.5, 0.75, 0.9)

DEFAULT_OUT = Path(__file__).resolve().parents[1] / "web/tests/fixtures/trade-simulation.json"


def _universe(rng: np.random.Generator) -> list[dict[str, Any]]:
    players: list[dict[str, Any]] = []
    for position, count in UNIVERSE.items():
        top, bottom = PPG_RANGE[position]
        for rank in range(count):
            share = rank / max(1, count - 1)
            players.append(
                {
                    "player_id": f"gsis:00-9{position_code(position)}{rank:05d}",
                    "position": position,
                    # A smooth depth curve with jitter, so neighbours genuinely overlap.
                    "ppg": float(top + (bottom - top) * share**0.7) * float(rng.uniform(0.9, 1.1)),
                    "availability": float(rng.uniform(0.62, 0.97)),
                    "shape": float(rng.uniform(1.6, 6.0)),
                },
            )
    return players


def position_code(position: str) -> int:
    return {"QB": 1, "RB": 2, "WR": 3, "TE": 4}[position]


def _point_draws(players: list[dict[str, Any]], rng: np.random.Generator, draws: int) -> np.ndarray:
    out = np.empty((len(players), draws), dtype=np.float64)
    for index, player in enumerate(players):
        games = rng.binomial(REMAINING_WEEKS, player["availability"], draws)
        shape = player["shape"]
        scale = player["ppg"] / shape
        # A sum of `games` independent gammas of one shape is one gamma of `games × shape`.
        totals = np.where(games > 0, rng.gamma(np.maximum(games, 1) * shape, scale), 0.0)
        out[index] = totals
    return out


def _round(value: float) -> float:
    return round(float(value), 4)


def build(draws: int = DRAWS) -> dict[str, Any]:
    rng = np.random.default_rng(SEED)
    players = _universe(rng)
    points = _point_draws(players, rng, draws)
    league = load_league_config()
    preset = league.preset("redraft-12")
    projections = pl.DataFrame(
        {
            "player_id": [player["player_id"] for player in players],
            "position": [player["position"] for player in players],
        },
    )
    config = SimulationConfig(
        draws=draws,
        seed=SEED,
        model_version=GENERATOR_VERSION,
        scoring_preset="PPR",
    )
    result = simulate_vorp(
        projections,
        preset=preset,
        config=config,
        bounds={},
        points=points,
        keep_draws=True,
        allocate=allocate_with_bench,
    )
    vorp = result.vorp_draws
    if vorp is None or np.isnan(vorp).any():
        raise RuntimeError("every draw must have a replacement level at every position")
    summary = result.players

    records: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(summary.iter_rows(named=True)):
        records[row["player_id"]] = {
            "index": index,
            "player_id": row["player_id"],
            "position": row["position"],
            "ros_expected_vorp": _round(row["expected_vorp"]),
            "ros_vorp_p10": _round(row["p10_vorp"]),
            "ros_vorp_p25": _round(row["p25_vorp"]),
            "ros_vorp_p50": _round(row["p50_vorp"]),
            "ros_vorp_p75": _round(row["p75_vorp"]),
            "ros_vorp_p90": _round(row["p90_vorp"]),
            "ros_expected_points": _round(row["expected_points"]),
        }

    # Packages are drawn from players a manager could actually target: positive expectation.
    positive = sorted(
        (record for record in records.values() if record["ros_expected_vorp"] > 0),
        key=lambda record: (-record["ros_expected_vorp"], record["player_id"]),
    )
    pick = np.random.default_rng(SEED + 1)
    shuffle = np.random.default_rng(SEED + 2)
    independent = np.array([shuffle.permutation(row) for row in vorp])

    packages: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for size, count in ((1, SINGLES), (2, PAIRS), (3, TRIPLES)):
        made = 0
        while made < count:
            chosen = pick.choice(len(positive), size=size, replace=False)
            ids = tuple(sorted(positive[int(index)]["player_id"] for index in chosen))
            if ids in seen:
                continue
            seen.add(ids)
            rows = [records[player_id]["index"] for player_id in ids]
            joint = vorp[rows].sum(axis=0)
            indep = independent[rows].sum(axis=0)
            packages.append(
                {
                    "ids": list(ids),
                    "same_position": len({records[i]["position"] for i in ids}) == 1,
                    "mean": _round(joint.mean()),
                    "p10": _round(np.quantile(joint, 0.1)),
                    "p90": _round(np.quantile(joint, 0.9)),
                    "p10_independent": _round(np.quantile(indep, 0.1)),
                    "p90_independent": _round(np.quantile(indep, 0.9)),
                },
            )
            made += 1

    used = sorted({player_id for package in packages for player_id in package["ids"]})
    return {
        "generator_version": GENERATOR_VERSION,
        "seed": SEED,
        "draws": draws,
        "league_preset_id": preset.preset_id,
        "replacement_rule": "rostered_depth",
        "remaining_weeks": REMAINING_WEEKS,
        "note": (
            "Synthetic universe drawn through the production VORP draw loop "
            "(simulate_vorp + allocate_with_bench). Package p10/p90 are quantiles of the summed "
            "joint VORP draws; *_independent shuffle each member's draws first."
        ),
        "players": [{k: v for k, v in records[i].items() if k != "index"} for i in used],
        "packages": packages,
    }


def render(payload: dict[str, Any]) -> str:
    """One record per line: compact, and a regenerated fixture diffs line by line."""
    head = {k: v for k, v in payload.items() if k not in ("players", "packages")}
    lines = [json.dumps(head)[:-1] + ","]
    for name in ("players", "packages"):
        rows = [json.dumps(row, separators=(",", ":")) for row in payload[name]]
        lines.append(f'"{name}":[')
        lines.append(",\n".join(rows))
        lines.append("]," if name == "players" else "]")
    lines.append("}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--draws", type=int, default=DRAWS)
    args = parser.parse_args()
    payload = build(args.draws)
    args.out.write_text(render(payload), encoding="utf-8")
    print(
        f"wrote {args.out}: {len(payload['players'])} players, {len(payload['packages'])} packages"
    )


if __name__ == "__main__":
    main()
