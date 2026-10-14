"""The Skill Tree's served layout and its Next Gen Stats adapter (ADR-107).

* Readings are served once, split by the card's player bucket; definitions are split by
  position. Neither travels in a card shard, so opening a card fetches nothing new.
* Every served table decodes to exactly the golden artifact's records.
* The NGS adapter normalizes the three files to one contract and keeps week 0 as the summary.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from ffdraft.artifacts.serving import (
    CARD_SECTIONS,
    FAMILIES,
    bucket_of,
    build_serving_layout,
    decode_table,
)
from ffdraft.sources.nextgen import (
    NflverseNextGenReceivingAdapter,
    NflverseNextGenRushingAdapter,
)

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "artifacts"


def _envelope(name: str) -> dict:
    return json.loads((GOLDEN / f"{name}.json").read_text(encoding="utf-8"))


def test_skill_tree_files_are_bucketed_and_never_in_a_card_shard():
    families = {family.name: family for family in FAMILIES}
    assert families["skill_tree"].partition == "bucket"
    assert families["skill_tree_definitions"].partition == "position"
    assert all(
        artifact not in {"player_skill_tree", "skill_tree_definitions"}
        for artifact, _ in CARD_SECTIONS
    )
    manifest = json.loads((GOLDEN / "manifest.json").read_text(encoding="utf-8"))
    keys = sorted(manifest["files"])
    assert {
        "skill_tree_definitions/QB",
        "skill_tree_definitions/RB",
        "skill_tree_definitions/WR",
        "skill_tree_definitions/TE",
    } <= set(keys)
    tree = _envelope("player_skill_tree")
    buckets = manifest["card_buckets"]
    for record in tree["records"]:
        assert f"skill_tree/{bucket_of(record['player_id'], buckets):02d}" in manifest["files"]
    for key in keys:
        if key.startswith("card/"):
            path = next((GOLDEN / "serve" / "card").rglob(f"{key.split('/')[-1]}.*.json"))
            assert (
                "player_skill_tree" not in json.loads(path.read_text(encoding="utf-8"))["sections"]
            )


def test_every_served_skill_tree_table_decodes_to_its_records():
    envelopes = {
        name: _envelope(name)
        for name in ("player_skill_tree", "skill_tree_definitions", "ros_tiers", "tiers")
    }
    layout = build_serving_layout(envelopes, {}, buckets=64)
    decoded: list[dict] = []
    definitions: list[dict] = []
    for data in layout.files.values():
        payload = json.loads(data)
        if payload.get("family") == "skill_tree":
            header = {k: v for k, v in envelopes["player_skill_tree"].items() if k != "records"}
            decoded += decode_table(payload, envelope=header, names={})
        if payload.get("family") == "skill_tree_definitions":
            header = {
                k: v for k, v in envelopes["skill_tree_definitions"].items() if k != "records"
            }
            definitions += decode_table(payload, envelope=header, names={})
            assert {
                row["position"] for row in decode_table(payload, envelope=header, names={})
            } == {payload["partition"]}

    def key(row: dict) -> str:
        return json.dumps(row, sort_keys=True)

    assert sorted(map(key, decoded)) == sorted(map(key, envelopes["player_skill_tree"]["records"]))
    assert sorted(map(key, definitions)) == sorted(
        map(key, envelopes["skill_tree_definitions"]["records"])
    )


def test_the_ngs_adapters_normalize_to_one_contract():
    raw = pl.DataFrame(
        {
            "season": [2026, 2026, 2026],
            "season_type": ["REG", "REG", "POST"],
            "week": [0, 5, 19],
            "player_gsis_id": ["00-0000001", "00-0000001", "00-0000001"],
            "player_position": ["WR", "WR", "WR"],
            "targets": [30, 6, 4],
            "receptions": [20, 4, 3],
            "avg_separation": [3.1, 3.4, None],
            "avg_cushion": [6.0, 5.5, 5.0],
            "avg_yac_above_expectation": [1.2, 0.4, -0.1],
        },
    )
    frame = NflverseNextGenReceivingAdapter().normalize(raw).frame
    assert frame.height == 3
    assert frame.filter(pl.col("week") == 0)["volume"].to_list() == [30.0]
    assert frame["avg_separation"].null_count() == 1  # missing stays missing
    assert set(frame["stat_type"].to_list()) == {"receiving"}
    rushing = NflverseNextGenRushingAdapter().normalize(
        pl.DataFrame(
            {
                "season": [2026],
                "season_type": ["REG"],
                "week": [0],
                "player_gsis_id": ["bad id"],
                "player_position": ["RB"],
                "rush_attempts": [40],
                "rush_yards_over_expected_per_att": [0.3],
            },
        ),
    )
    assert rushing.frame.is_empty()  # an unusable id is dropped and counted, never guessed
