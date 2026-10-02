"""The Trade tab's simulation fixture is reproducible and is what the page is tested against.

`web/tests/trade.test.ts` measures the browser's package floor/ceiling approximation
(ADR-100 §5) against `web/tests/fixtures/trade-simulation.json`. That evidence is only worth
something if the file is exactly what the generator produces from the repository's own draw
loop, so this regenerates it and compares the bytes.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "trade_package_fixture.py"
FIXTURE = ROOT / "web" / "tests" / "fixtures" / "trade-simulation.json"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("trade_package_fixture", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_committed_fixture_is_the_generators_output() -> None:
    module = _load()
    assert module.render(module.build()) == FIXTURE.read_text(encoding="utf-8")


def test_fixture_is_internally_consistent() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    players = {row["player_id"]: row for row in payload["players"]}
    levels = ("ros_vorp_p10", "ros_vorp_p25", "ros_vorp_p50", "ros_vorp_p75", "ros_vorp_p90")
    for row in players.values():
        values = [row[key] for key in levels]
        assert values == sorted(values)
        assert row["ros_expected_vorp"] > 0
    for package in payload["packages"]:
        assert len(set(package["ids"])) == len(package["ids"])
        assert package["p10"] <= package["p90"]
        # Expectations add, whatever the dependence: the package mean is the members' sum.
        total = sum(players[i]["ros_expected_vorp"] for i in package["ids"])
        assert np.isclose(package["mean"], total, atol=5e-3)
        if len(package["ids"]) == 1:
            only = players[package["ids"][0]]
            assert package["p10"] == only["ros_vorp_p10"]
            assert package["p90"] == only["ros_vorp_p90"]
