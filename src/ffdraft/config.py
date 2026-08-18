"""Configuration loading and validation.

`docs/ARCHITECTURE.md` section 9: YAML is declarative, Python validates it at startup, and
production-critical constants never hide in scripts. Two files are loaded here:

* ``config/league-defaults.yaml`` - scoring presets and league presets;
* ``config/source-registry.yaml`` - the machine-readable source policy registry, which is
  the source-of-truth pair with `docs/DATA_SOURCES.md` (AGENTS.md section 18).

Validation is strict about the parts the pipeline depends on and permissive about the rest.
The registry deliberately carries a lot of human-facing evidence (verified row counts,
licence quotations, known issues); modelling those exactly would turn every documentation
edit into a code change. So the fields code reads are typed and checked, and everything
else is preserved verbatim in :attr:`SourceEntry.extra`.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ffdraft.paths import config_dir, repo_root
from ffdraft.secret import Secret, secret_from_env

__all__ = [
    "AppConfig",
    "ConfigError",
    "LeagueConfig",
    "LeaguePreset",
    "MflClientConfig",
    "Policy",
    "ScoringPreset",
    "ScoringRules",
    "SourceEntry",
    "SourceRegistry",
    "load_app_config",
    "load_league_config",
    "load_source_registry",
]

# The market snapshot contract bounds league size at 4..32; league config must not be able
# to describe a preset that could never be serialized.
MIN_TEAMS = 4
MAX_TEAMS = 32

FLEX_SLOT = "FLEX"


class ConfigError(ValueError):
    """Raised when a configuration file is structurally valid YAML but semantically wrong."""


class ScoringPreset(StrEnum):
    """The three supported scoring presets. PRD section 4 excludes custom scoring from V1."""

    STD = "STD"
    HALF = "HALF"
    PPR = "PPR"


class Policy(StrEnum):
    """Source policy vocabulary, mirroring ``policy_states`` in the registry."""

    PRODUCTION_ALLOWED = "production_allowed"
    ALLOWED_OPTIONAL = "allowed_optional"
    BENCHMARK_ONLY = "benchmark_only"
    VERIFY_BEFORE_USE = "verify_before_use"
    DISABLED = "disabled"
    PAID_OPTIONAL = "paid_optional"

    @property
    def usable_in_production(self) -> bool:
        """Whether a source under this policy may feed a public artifact.

        ``benchmark_only`` is deliberately excluded. ADR-014 permits internal comparison
        against FantasyPros-derived ECR and forbids redistribution; conflating "we may look
        at it" with "we may publish it" is exactly the mistake that gate exists to prevent.
        """
        return self in {Policy.PRODUCTION_ALLOWED, Policy.ALLOWED_OPTIONAL}


# --------------------------------------------------------------------------------------
# League configuration
# --------------------------------------------------------------------------------------


class ScoringRules(BaseModel):
    """Points awarded per statistical event for one scoring preset.

    Yardage fields are *yards per point* divisors as written in the YAML (25.0 passing
    yards per point), not multipliers. The scoring engine in Phase 2 owns the arithmetic;
    this type only guarantees the numbers are present and sane.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    reception: float
    passing_yards_per_point: float = Field(gt=0)
    passing_td: float
    interception: float
    rushing_yards_per_point: float = Field(gt=0)
    rushing_td: float
    receiving_yards_per_point: float = Field(gt=0)
    receiving_td: float
    fumble_lost: float
    two_point_conversion: float


class LeaguePreset(BaseModel):
    """One supported league shape."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    preset_id: str
    teams: int = Field(ge=MIN_TEAMS, le=MAX_TEAMS)
    starters: Mapping[str, int]
    flex_eligible: tuple[str, ...]
    bench: int = Field(ge=0)
    is_default: bool = False

    @model_validator(mode="after")
    def _check_slots(self) -> Self:
        if any(count < 0 for count in self.starters.values()):
            raise ValueError(f"{self.preset_id}: negative starter count")
        if self.starters.get(FLEX_SLOT, 0) and not self.flex_eligible:
            raise ValueError(f"{self.preset_id}: FLEX slots declared with no eligible positions")
        for position in self.flex_eligible:
            if position not in self.starters:
                raise ValueError(
                    f"{self.preset_id}: flex-eligible {position} has no dedicated starter slot",
                )
        return self

    @property
    def starting_slots(self) -> int:
        """Total starting slots, FLEX included. Drives the Phase-4 replacement baseline."""
        return sum(self.starters.values())


class LeagueConfig(BaseModel):
    """Parsed ``config/league-defaults.yaml``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str
    season_mode: str
    core_positions: tuple[str, ...]
    optional_positions: tuple[str, ...]
    scoring: Mapping[ScoringPreset, ScoringRules]
    presets: Mapping[str, LeaguePreset]
    optional_presets: Mapping[str, LeaguePreset]
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _check_presets(self) -> Self:
        if not self.presets:
            raise ValueError("league config declares no launch presets")
        defaults = [preset_id for preset_id, preset in self.presets.items() if preset.is_default]
        if len(defaults) != 1:
            raise ValueError(f"expected exactly one default league preset, found {defaults}")
        known = set(self.core_positions) | set(self.optional_positions) | {FLEX_SLOT}
        for preset in (*self.presets.values(), *self.optional_presets.values()):
            unknown = set(preset.starters) - known
            if unknown:
                raise ValueError(f"{preset.preset_id}: unknown starter slots {sorted(unknown)}")
            ineligible = set(preset.flex_eligible) - set(self.core_positions)
            if ineligible:
                raise ValueError(
                    f"{preset.preset_id}: flex-eligible positions outside core: "
                    f"{sorted(ineligible)}",
                )
        missing = set(ScoringPreset) - set(self.scoring)
        if missing:
            raise ValueError(f"scoring presets missing from config: {sorted(missing)}")
        return self

    @property
    def default_preset(self) -> LeaguePreset:
        return next(preset for preset in self.presets.values() if preset.is_default)

    def preset(self, preset_id: str) -> LeaguePreset:
        """Return a launch or optional preset by id."""
        try:
            return self.presets.get(preset_id) or self.optional_presets[preset_id]
        except KeyError as exc:
            known = sorted({*self.presets, *self.optional_presets})
            raise ConfigError(f"unknown league preset {preset_id!r}; known: {known}") from exc


def _parse_preset(preset_id: str, raw: Mapping[str, Any]) -> LeaguePreset:
    body = dict(raw)
    return LeaguePreset(
        preset_id=preset_id,
        teams=int(body["teams"]),
        starters={str(k): int(v) for k, v in dict(body["starters"]).items()},
        flex_eligible=tuple(str(p) for p in body.get("flex_eligible", ())),
        bench=int(body.get("bench", 0)),
        is_default=bool(body.get("default", False)),
    )


def load_league_config(path: Path | None = None) -> LeagueConfig:
    """Load and validate ``config/league-defaults.yaml``."""
    source = path or (config_dir() / "league-defaults.yaml")
    raw = _read_yaml_mapping(source)
    positions = dict(raw.get("positions", {}))
    try:
        return LeagueConfig(
            schema_version=str(raw["schema_version"]),
            season_mode=str(raw["season_mode"]),
            core_positions=tuple(str(p) for p in positions.get("core", ())),
            optional_positions=tuple(str(p) for p in positions.get("optional_later", ())),
            scoring={
                ScoringPreset(name): ScoringRules(**rules)
                for name, rules in dict(raw["scoring_presets"]).items()
            },
            presets={
                preset_id: _parse_preset(preset_id, body)
                for preset_id, body in dict(raw["league_presets"]).items()
            },
            optional_presets={
                preset_id: _parse_preset(preset_id, body)
                for preset_id, body in dict(raw.get("optional_presets", {})).items()
            },
            notes=tuple(str(note) for note in raw.get("notes", ())),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError(f"{source}: {exc}") from exc


# --------------------------------------------------------------------------------------
# Source registry
# --------------------------------------------------------------------------------------


class SourceEntry(BaseModel):
    """One source's policy record.

    Only the fields the pipeline actually branches on are typed. Everything else - verified
    row counts, licence quotations, known issues - stays in :attr:`extra` so the registry
    can keep serving as human-readable evidence without every documentation edit becoming a
    schema migration.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str
    policy: Policy
    criticality: str = "optional"
    verified: bool = False
    verified_at: str | None = None
    roles: tuple[str, ...] = ()
    permitted_roles: tuple[str, ...] = ()
    forbidden_roles: tuple[str, ...] = ()
    non_commercial_only: bool = False
    redistribution_permitted: bool = True
    client_settings: Mapping[str, Any] = Field(default_factory=dict)
    extra: Mapping[str, Any] = Field(default_factory=dict, repr=False)

    @property
    def may_reach_public_artifacts(self) -> bool:
        """Whether rows from this source may be serialized into a public artifact."""
        return (
            self.policy.usable_in_production
            and self.redistribution_permitted
            and "public_artifact_field" not in self.forbidden_roles
            and "public_redistribution" not in self.forbidden_roles
        )

    @property
    def may_feed_intrinsic_model(self) -> bool:
        """Whether this source may supply an intrinsic-model feature (ADR-002)."""
        return self.policy.usable_in_production and "intrinsic_feature" not in self.forbidden_roles


class SourceRegistry(BaseModel):
    """Parsed ``config/source-registry.yaml``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str
    policy_states: tuple[str, ...]
    decisions: Mapping[str, Any]
    sources: Mapping[str, SourceEntry]

    @model_validator(mode="after")
    def _check(self) -> Self:
        declared = set(self.policy_states)
        unknown = {str(entry.policy) for entry in self.sources.values()} - declared
        if unknown:
            raise ValueError(f"policies outside the declared vocabulary: {sorted(unknown)}")
        mode = self.decisions.get("arbitrage_mode")
        feasible = bool(self.decisions.get("arbitrage_ml_historical_feasible"))
        if (mode == "ml") != feasible:
            raise ValueError(
                f"arbitrage_mode={mode!r} contradicts "
                f"arbitrage_ml_historical_feasible={feasible!r}",
            )
        return self

    def source(self, source_id: str) -> SourceEntry:
        try:
            return self.sources[source_id]
        except KeyError as exc:
            raise ConfigError(
                f"unknown source {source_id!r}; known: {sorted(self.sources)}",
            ) from exc

    @property
    def arbitrage_mode(self) -> str:
        """``baseline`` or ``ml``. ADR-010 fixes this at ``baseline`` for V1."""
        return str(self.decisions.get("arbitrage_mode", "baseline"))

    @property
    def benchmark_only_sources(self) -> frozenset[str]:
        """Sources permitted for internal comparison only (ADR-014)."""
        return frozenset(
            source_id
            for source_id, entry in self.sources.items()
            if entry.policy is Policy.BENCHMARK_ONLY
        )


_TYPED_SOURCE_FIELDS = frozenset(
    {
        "policy",
        "criticality",
        "verified",
        "verified_at",
        "roles",
        "permitted_roles",
        "forbidden_roles",
        "non_commercial_only",
        "redistribution_permitted",
        "client_settings",
    },
)


def load_source_registry(path: Path | None = None) -> SourceRegistry:
    """Load and validate ``config/source-registry.yaml``."""
    source = path or (config_dir() / "source-registry.yaml")
    raw = _read_yaml_mapping(source)
    try:
        sources = {}
        for source_id, body in dict(raw["sources"]).items():
            fields = dict(body)
            typed = {key: fields[key] for key in _TYPED_SOURCE_FIELDS & set(fields)}
            for key in ("roles", "permitted_roles", "forbidden_roles"):
                if key in typed:
                    typed[key] = tuple(str(role) for role in typed[key])
            sources[source_id] = SourceEntry(
                source_id=source_id,
                extra={k: v for k, v in fields.items() if k not in _TYPED_SOURCE_FIELDS},
                **typed,
            )
        return SourceRegistry(
            schema_version=str(raw["schema_version"]),
            policy_states=tuple(str(state) for state in raw["policy_states"]),
            decisions=dict(raw.get("decisions", {})),
            sources=sources,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError(f"{source}: {exc}") from exc


# --------------------------------------------------------------------------------------
# MyFantasyLeague developer-client identity (ADR-017)
# --------------------------------------------------------------------------------------

# Used when no registered client User-Agent is configured. MFL asks clients to identify
# themselves; a descriptive UA with a contact URL is the honest fallback, and it is what the
# Phase-0 probe sent.
FALLBACK_USER_AGENT = (
    "jeisey-tiers/0.1 "
    "(+https://github.com/jeisey/jeisey-tiers; non-commercial fantasy research) "
    "python-requests"
)

UNREGISTERED_USER_AGENT_WARNING = "unregistered_user_agent"


@dataclass(frozen=True)
class MflClientConfig:
    """MFL developer-client identity, read from environment secrets.

    Two rules from ADR-017 are enforced structurally rather than by convention:

    * the public ADP export is unauthenticated, so :attr:`username` and :attr:`password`
      exist for MFL's *league* endpoints (which V1 does not call) and no code path on the
      ADP request may read them - :meth:`request_headers` returns a User-Agent and nothing
      else;
    * values are :class:`~ffdraft.secret.Secret`, so they cannot be printed, logged or
      JSON-serialized by accident. Only :meth:`request_headers` reveals one, at the point
      of transmission.
    """

    user_agent: Secret | None = None
    client_name: Secret | None = None
    username: Secret | None = None
    password: Secret | None = None
    fallback_user_agent: str = FALLBACK_USER_AGENT

    USER_AGENT_ENV = "MFL_API_USER_AGENT"
    CLIENT_NAME_ENV = "MFL_API_CLIENT_NAME"
    USERNAME_ENV = "MFL_API_USERNAME"
    PASSWORD_ENV = "MFL_API_PASSWORD"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> MflClientConfig:
        """Build from the environment. Absent secrets are normal and never raise."""
        env = os.environ if environ is None else environ
        return cls(
            user_agent=secret_from_env(cls.USER_AGENT_ENV, env),
            client_name=secret_from_env(cls.CLIENT_NAME_ENV, env),
            username=secret_from_env(cls.USERNAME_ENV, env),
            password=secret_from_env(cls.PASSWORD_ENV, env),
        )

    @classmethod
    def offline(cls) -> MflClientConfig:
        """An explicitly credential-free configuration for fixtures and network-free tests.

        Tests use this rather than :meth:`from_env` so a developer's real environment can
        never change a test outcome, and so no test run reads a provisioned secret.
        """
        return cls()

    @property
    def registered(self) -> bool:
        """Whether a registered developer-client User-Agent is configured."""
        return self.user_agent is not None

    def request_headers(self) -> dict[str, str]:
        """Headers for a public MFL request.

        Deliberately only ``User-Agent`` and ``Accept``. No ``Authorization``, no cookie,
        no credential parameter: the ADP export is public, and coupling it to a login would
        break a path that provably does not need one.
        """
        agent = self.user_agent.reveal() if self.user_agent else self.fallback_user_agent
        return {"User-Agent": agent, "Accept": "application/json, */*;q=0.5"}

    def warnings(self) -> tuple[str, ...]:
        """Warning codes for the source metadata contract (`docs/DATA_SOURCES.md` 11)."""
        return () if self.registered else (UNREGISTERED_USER_AGENT_WARNING,)

    def presence(self) -> dict[str, bool]:
        """Which secrets are configured. Presence only - never values."""
        return {
            self.USER_AGENT_ENV: self.user_agent is not None,
            self.CLIENT_NAME_ENV: self.client_name is not None,
            self.USERNAME_ENV: self.username is not None,
            self.PASSWORD_ENV: self.password is not None,
        }


# --------------------------------------------------------------------------------------
# Bundle
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class AppConfig:
    """Everything the pipeline needs to start up, validated."""

    root: Path
    league: LeagueConfig
    registry: SourceRegistry
    mfl_client: MflClientConfig

    @property
    def arbitrage_mode(self) -> str:
        return self.registry.arbitrage_mode


def load_app_config(
    *,
    root: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> AppConfig:
    """Load every configuration file and the client identity, validating as we go."""
    base = root or repo_root()
    return AppConfig(
        root=base,
        league=load_league_config(base / "config" / "league-defaults.yaml"),
        registry=load_source_registry(base / "config" / "source-registry.yaml"),
        mfl_client=MflClientConfig.from_env(environ),
    )


@lru_cache(maxsize=1)
def _cached_app_config() -> AppConfig:
    return load_app_config()


def _read_yaml_mapping(path: Path) -> Mapping[str, Any]:
    if not path.is_file():
        raise ConfigError(f"missing configuration file: {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, Mapping):
        raise ConfigError(f"{path}: expected a YAML mapping, got {type(loaded).__name__}")
    return loaded
