"""One-way flow for the weekly start/sit models (AGENTS.md section 1, ADR-096, ADR-099).

The weekly model is a decision-layer consumer: it reads the rest-of-season snapshot plus the
week's sportsbook lines. Nothing it produces or reads may flow back into the intrinsic or
rest-of-season models. These tests hold that at three levels: feature names, imports and the
artifact the rest-of-season build publishes.
"""

from __future__ import annotations

import ast
from pathlib import Path

from ffdraft.features.dictionary import intrinsic_feature_names
from ffdraft.quality.forbidden import FORBIDDEN_LINEAGE_SOURCES, forbidden_reason
from ffdraft.ros.dictionary import ros_feature_names
from ffdraft.weekly.frozen import FEATURE_FAMILIES, WEEKLY_FEATURES
from ffdraft.weekly.frozen_v2 import V2_FAMILIES

SRC = Path(__file__).resolve().parents[2] / "src" / "ffdraft"

#: The weekly names derived from a sportsbook line. The rest of the ``game`` family (home,
#: rest, roof) is schedule fact, not market expectation.
LINE_FEATURES = frozenset({"game_total_line", "game_team_margin", "game_team_points"})


def test_every_line_derived_weekly_feature_fails_the_intrinsic_guard() -> None:
    for name in LINE_FEATURES:
        assert forbidden_reason(name) is not None, name


def test_the_weekly_model_reads_no_market_input_but_the_lines() -> None:
    """ADP, ECR and every other crowd-rank proxy stay out of the weekly model too."""
    offenders = {name for name in WEEKLY_FEATURES if forbidden_reason(name) is not None}
    assert offenders == LINE_FEATURES
    assert set(FEATURE_FAMILIES["game"]) >= LINE_FEATURES


def test_the_rest_of_season_feature_set_carries_no_weekly_context() -> None:
    weekly_only = {name for family in ("game", "opponent") for name in FEATURE_FAMILIES[family]}
    assert not weekly_only & set(ros_feature_names())


V2_FEATURES = frozenset(name for names in V2_FAMILIES.values() for name in names)


def test_every_game_day_input_fails_the_intrinsic_guard() -> None:
    """Weather, the injury report and who is missing: decision-layer inputs only (ADR-099)."""
    assert V2_FEATURES
    for name in sorted(V2_FEATURES):
        assert forbidden_reason(name) is not None, name
    for name in ("own_report_final", "opp_report_final"):
        assert forbidden_reason(name) is not None, name


def test_no_upstream_feature_set_carries_a_game_day_input() -> None:
    assert not V2_FEATURES & set(ros_feature_names())
    assert not V2_FEATURES & set(intrinsic_feature_names())
    assert not V2_FEATURES & set(WEEKLY_FEATURES), "v1 itself never reads a v2 family"


def test_the_forecast_providers_can_never_be_intrinsic_lineage() -> None:
    assert {"nws_api", "open_meteo"} <= FORBIDDEN_LINEAGE_SOURCES


#: The game-day modules: only the weekly package and the build that serves it may import them.
GAMEDAY_MODULES = frozenset(
    {
        "ffdraft.weekly.venues",
        "ffdraft.weekly.weather",
        "ffdraft.weekly.forecast",
        "ffdraft.weekly.lineup",
        "ffdraft.weekly.capture",
        "ffdraft.weekly.pit",
        "ffdraft.weekly.gameday",
        "ffdraft.weekly.shadow",
        "ffdraft.weekly.dataset_v2",
        "ffdraft.weekly.frozen_v2",
    },
)


def test_only_the_weekly_layer_and_its_build_import_the_game_day_modules() -> None:
    offenders = [
        str(path.relative_to(SRC))
        for path in sorted(SRC.rglob("*.py"))
        if path.relative_to(SRC).parts[0] not in {"weekly", "pipeline", "cli.py"}
        and _imports(path) & GAMEDAY_MODULES
    ]
    assert offenders == []


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


#: The only places allowed to import the weekly package: itself, the build orchestration that
#: serves it, the artifact layer that validates its records, and the command line.
WEEKLY_CONSUMERS = frozenset({"weekly", "pipeline", "artifacts"})


def test_only_the_orchestration_layer_imports_the_weekly_package() -> None:
    packages = sorted(path.name for path in SRC.iterdir() if (path / "__init__.py").is_file())
    assert {"ros", "modeling", "features", "simulation", "tiers", "opportunity"} <= set(packages)
    offenders = [
        str(path.relative_to(SRC))
        for package in packages
        if package not in WEEKLY_CONSUMERS
        for path in sorted((SRC / package).rglob("*.py"))
        if any(module.startswith("ffdraft.weekly") for module in _imports(path))
    ]
    assert offenders == []


def test_the_weekly_layer_leaves_the_rest_of_season_records_untouched(pipeline_result) -> None:
    """The ROS tiers and the Opportunity Board carry no weekly-only field."""
    weekly_fields = {
        "quantiles",
        "drivers",
        "explanation",
        "game_state",
        "target_week",
        "weather",
        "lineup",
        "typical",
        "this_week",
        *FEATURE_FAMILIES["game"],
        *FEATURE_FAMILIES["opponent"],
        *V2_FEATURES,
    }
    for artifact in ("ros_tiers", "inseason_opportunity"):
        for record in pipeline_result.records[artifact]:
            assert not weekly_fields & set(record), artifact
