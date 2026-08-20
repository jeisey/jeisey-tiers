"""The intrinsic/market firewall, enforced by walking the import graph.

`AGENTS.md` section 1 states the core invariant: the intrinsic model estimates football
value without market or expert inputs, arbitrage may consume intrinsic outputs plus market
data, and information never flows the other way. `docs/ARCHITECTURE.md` 3.1 turns that into
a module layout.

A layout is only a convention until something checks it. The failure this catches is
invisible by inspection and catastrophic in effect: a model trained on ADP still produces
plausible tiers, and the arbitrage product silently becomes circular - it would be
measuring the market against itself. So this walks every module under the intrinsic
packages, parses its imports, and follows them transitively. A market import three levels
down fails exactly as loudly as a direct one.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
PACKAGE = SRC / "ffdraft"

#: Packages that produce intrinsic value. Nothing here may reach market data, directly or
#: through any chain of first-party imports.
INTRINSIC_PACKAGES = (
    "ffdraft.features",
    "ffdraft.labels",
    "ffdraft.modeling",
    "ffdraft.simulation",
    "ffdraft.tiers",
    "ffdraft.scoring",
)

#: Modules that *are* market data, or are built on it.
MARKET_MODULES = (
    "ffdraft.market",
    "ffdraft.sources.market",
    "ffdraft.arbitrage",
)


def _module_name(path: Path) -> str:
    relative = path.relative_to(SRC).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _first_party_imports(path: Path) -> set[str]:
    """Every ``ffdraft.*`` module this file imports, at module scope or inside a function.

    Function-local imports count. A deferred import is still an import, and moving one
    inside a function is exactly how a boundary violation would try to hide.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names if alias.name.startswith("ffdraft"))
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.level == 0
            and node.module.startswith("ffdraft")
        ):
            found.add(node.module)
            found.update(
                f"{node.module}.{alias.name}"
                for alias in node.names
                if (SRC / Path(*node.module.split("."), f"{alias.name}.py")).is_file()
            )
    return found


def _graph() -> dict[str, set[str]]:
    return {
        _module_name(path): _first_party_imports(path) for path in sorted(PACKAGE.rglob("*.py"))
    }


def _reachable(start: str, graph: dict[str, set[str]]) -> set[str]:
    seen: set[str] = set()
    queue = [start]
    while queue:
        current = queue.pop()
        for target in graph.get(current, set()):
            if target in seen:
                continue
            seen.add(target)
            queue.append(target)
    return seen


def _is_market(module: str) -> bool:
    return any(module == name or module.startswith(f"{name}.") for name in MARKET_MODULES)


def _modules_under(package: str, graph: Iterable[str]) -> list[str]:
    return sorted(name for name in graph if name == package or name.startswith(f"{package}."))


@pytest.fixture(scope="module")
def graph() -> dict[str, set[str]]:
    return _graph()


def test_the_graph_is_not_empty(graph):
    """A boundary test that silently walks nothing would pass forever."""
    assert len(graph) > 50
    assert "ffdraft.market.cohorts" in graph
    assert "ffdraft.arbitrage.baseline" in graph


@pytest.mark.parametrize("package", INTRINSIC_PACKAGES)
def test_no_intrinsic_module_can_reach_market_data(package, graph):
    """ADR-002/AGENTS.md 1: market data may never enter the intrinsic side."""
    offenders: list[str] = []
    for module in _modules_under(package, graph):
        for reached in sorted(_reachable(module, graph)):
            if _is_market(reached):
                offenders.append(f"{module} -> {reached}")
    assert not offenders, (
        "the intrinsic/market firewall is broken; information may flow intrinsic -> market "
        f"and never the reverse: {offenders}"
    )


def test_arbitrage_may_consume_intrinsic_outputs(graph):
    """The allowed direction is real, not merely permitted in prose.

    Asserting this keeps the test honest: a boundary test that only ever forbids could be
    satisfied by a market layer that touches nothing, which would mean the firewall is
    untested rather than intact.
    """
    reachable = _reachable("ffdraft.pipeline.market", graph)
    assert any(_is_market(module) for module in reachable)
    assert "ffdraft.arbitrage.build" in reachable


def test_the_market_package_is_not_reachable_from_the_production_model(graph):
    """`ProductionModel` serves the board; a market import there would poison inference."""
    for module in ("ffdraft.modeling.production", "ffdraft.modeling.features"):
        assert not any(_is_market(name) for name in _reachable(module, graph)), module


def test_the_intrinsic_current_build_stays_market_free(graph):
    """`build-current` writes the Tier board. It must not depend on a market source at all.

    This is what makes "a market failure cannot invalidate the intrinsic model" structural
    rather than a promise: the Tier build has no code path into market data to fail on.
    """
    reachable = _reachable("ffdraft.pipeline.current", graph)
    assert not any(_is_market(module) for module in reachable), sorted(
        module for module in reachable if _is_market(module)
    )
