"""Configuration loading, validation and secret handling."""

from __future__ import annotations

import json

import pytest
import yaml

from ffdraft.config import (
    ConfigError,
    MflClientConfig,
    Policy,
    ScoringPreset,
    load_league_config,
    load_source_registry,
)
from ffdraft.secret import Secret, secret_from_env


def test_league_config_parses_every_launch_preset(app_config):
    league = app_config.league
    assert set(league.presets) == {"redraft-10", "redraft-12", "redraft-14"}
    assert league.default_preset.preset_id == "redraft-12"
    assert league.default_preset.teams == 12
    assert league.default_preset.starting_slots == 8
    assert set(league.scoring) == set(ScoringPreset)


def test_scoring_presets_differ_only_in_reception_value(app_config):
    """PRD section 4: V1 supports STD/HALF/PPR and nothing custom."""
    scoring = app_config.league.scoring
    assert scoring[ScoringPreset.STD].reception == 0.0
    assert scoring[ScoringPreset.HALF].reception == 0.5
    assert scoring[ScoringPreset.PPR].reception == 1.0
    for other in ("passing_td", "rushing_td", "receiving_td", "interception", "fumble_lost"):
        values = {getattr(rules, other) for rules in scoring.values()}
        assert len(values) == 1, f"{other} should not vary by scoring preset"


def test_unknown_preset_raises_a_configuration_error(app_config):
    with pytest.raises(ConfigError, match="unknown league preset"):
        app_config.league.preset("redraft-99")


def test_league_config_rejects_two_defaults(tmp_path):
    path = tmp_path / "league.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0",
                "season_mode": "redraft",
                "positions": {"core": ["QB", "RB", "WR", "TE"], "optional_later": []},
                "scoring_presets": {
                    name: {
                        "reception": 1.0,
                        "passing_yards_per_point": 25.0,
                        "passing_td": 4.0,
                        "interception": -2.0,
                        "rushing_yards_per_point": 10.0,
                        "rushing_td": 6.0,
                        "receiving_yards_per_point": 10.0,
                        "receiving_td": 6.0,
                        "fumble_lost": -2.0,
                        "two_point_conversion": 2.0,
                    }
                    for name in ("STD", "HALF", "PPR")
                },
                "league_presets": {
                    "a": {
                        "teams": 12,
                        "default": True,
                        "starters": {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1},
                        "flex_eligible": ["RB", "WR", "TE"],
                        "bench": 5,
                    },
                    "b": {
                        "teams": 10,
                        "default": True,
                        "starters": {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1},
                        "flex_eligible": ["RB", "WR", "TE"],
                        "bench": 5,
                    },
                },
            },
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="exactly one default"):
        load_league_config(path)


def test_registry_policy_helpers_match_the_recorded_decisions(app_config):
    registry = app_config.registry
    assert registry.arbitrage_mode == "baseline"
    assert registry.source("nflreadpy").policy is Policy.PRODUCTION_ALLOWED
    assert registry.source("fantasycalc").policy is Policy.DISABLED
    assert registry.benchmark_only_sources == {"fantasypros_ecr_via_dynastyprocess"}


def test_benchmark_only_source_cannot_reach_public_or_intrinsic_layers(app_config):
    """ADR-014 as amended: approved for internal comparison, nothing more."""
    ecr = app_config.registry.source("fantasypros_ecr_via_dynastyprocess")
    assert ecr.policy is Policy.BENCHMARK_ONLY
    assert ecr.may_reach_public_artifacts is False
    assert ecr.may_feed_intrinsic_model is False
    assert ecr.redistribution_permitted is False
    assert "internal_benchmark" in ecr.permitted_roles


def test_registry_rejects_a_mode_that_contradicts_the_feasibility_flag(tmp_path):
    path = tmp_path / "registry.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0",
                "policy_states": ["production_allowed"],
                "decisions": {
                    "arbitrage_mode": "ml",
                    "arbitrage_ml_historical_feasible": False,
                },
                "sources": {"x": {"policy": "production_allowed"}},
            },
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="contradicts"):
        load_source_registry(path)


# --------------------------------------------------------------------------------------
# Secrets (ADR-017 / docs/SECURITY_LICENSE.md section 2)
# --------------------------------------------------------------------------------------


def test_secret_never_reveals_itself_through_repr_str_or_json():
    secret = Secret("super-secret-agent/1.0", env_var="MFL_API_USER_AGENT")
    assert "super-secret" not in repr(secret)
    assert "super-secret" not in str(secret)
    assert "super-secret" not in f"{secret}"
    assert "MFL_API_USER_AGENT" in repr(secret)
    with pytest.raises(TypeError):
        json.dumps({"ua": secret})
    assert secret.reveal() == "super-secret-agent/1.0"


def test_secret_equality_compares_provenance_not_value():
    a = Secret("one", env_var="MFL_API_USER_AGENT")
    b = Secret("two", env_var="MFL_API_USER_AGENT")
    assert a == b, "equality must not be usable to probe the value"


def test_missing_or_blank_environment_variable_yields_no_secret():
    assert secret_from_env("MFL_API_USER_AGENT", {}) is None
    assert secret_from_env("MFL_API_USER_AGENT", {"MFL_API_USER_AGENT": "   "}) is None


def test_adp_request_sends_only_the_user_agent_never_credentials():
    """The public ADP export is unauthenticated; coupling it to a login would be a bug."""
    client = MflClientConfig.from_env(
        {
            "MFL_API_USER_AGENT": "registered-client/1.0",
            "MFL_API_CLIENT_NAME": "jeisey-tiers",
            "MFL_API_USERNAME": "someone",
            "MFL_API_PASSWORD": "hunter2",
        },
    )
    headers = client.request_headers()
    assert headers["User-Agent"] == "registered-client/1.0"
    assert set(headers) == {"User-Agent", "Accept"}
    serialized = json.dumps(headers)
    assert "someone" not in serialized
    assert "hunter2" not in serialized
    assert client.registered is True
    assert client.warnings() == ()


def test_absent_user_agent_degrades_rather_than_failing():
    client = MflClientConfig.offline()
    headers = client.request_headers()
    assert "jeisey-tiers" in headers["User-Agent"]
    assert client.registered is False
    assert client.warnings() == ("unregistered_user_agent",)


def test_presence_reports_names_and_booleans_only():
    client = MflClientConfig.from_env({"MFL_API_PASSWORD": "hunter2"})
    presence = client.presence()
    assert presence == {
        "MFL_API_USER_AGENT": False,
        "MFL_API_CLIENT_NAME": False,
        "MFL_API_USERNAME": False,
        "MFL_API_PASSWORD": True,
    }
    assert "hunter2" not in json.dumps(presence)


def test_registry_records_the_secret_names_not_values(repo_root):
    registry = yaml.safe_load(
        (repo_root / "config" / "source-registry.yaml").read_text(encoding="utf-8"),
    )
    settings = registry["sources"]["myfantasyleague_adp"]["client_settings"]
    assert settings["user_agent_env"] == MflClientConfig.USER_AGENT_ENV
    assert settings["client_name_env"] == MflClientConfig.CLIENT_NAME_ENV
    assert settings["username_env"] == MflClientConfig.USERNAME_ENV
    assert settings["password_env"] == MflClientConfig.PASSWORD_ENV
    assert settings["credentials_used_by_adp_adapter"] is False
    assert registry["sources"]["myfantasyleague_adp"]["public_adp_requires_authentication"] is False
