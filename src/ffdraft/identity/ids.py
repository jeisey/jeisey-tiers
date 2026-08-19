"""External identifier hygiene.

Phase 0 found Sleeper serving ``" 00-0035057"`` - a valid GSIS id behind a leading space.
That single observation is the whole justification for this module: an untrimmed id fails a
join silently, and a silent join failure is indistinguishable from a player who genuinely
is not in the other dataset. `docs/DATA_SOURCES.md` 13.6 therefore requires trimming *and*
format validation, with malformed values failing closed rather than being passed along.

Two rules hold throughout:

* a value that does not match its namespace's format yields ``None`` plus a reason - it is
  never coerced, truncated or "cleaned up" into something that might match another player;
* numeric identifiers are canonicalised to their shortest decimal form, so an ``Int64``
  column from nflverse and a zero-padded string from a JSON API compare equal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "IdNamespace",
    "NormalizedId",
    "REGISTRY_NAMESPACES",
    "is_team_code",
    "make_player_id",
    "normalize_id",
    "parse_player_id",
    "value_of",
]


class IdNamespace(StrEnum):
    """Identifier namespaces used as canonical-key prefixes and crosswalk column names."""

    GSIS = "gsis"
    ESPN = "espn"
    SLEEPER = "sleeper"
    MFL = "mfl"
    PFR = "pfr"
    SPORTRADAR = "sportradar"
    YAHOO = "yahoo"
    #: Team defence / team aggregate units. Structurally separate so a D/ST can never be
    #: mistaken for a QB/RB/WR/TE (AGENTS.md section 6).
    DST = "dst"


#: Namespaces that may appear in a :class:`~ffdraft.contracts.entities.PlayerCrosswalk`.
REGISTRY_NAMESPACES: tuple[IdNamespace, ...] = (
    IdNamespace.GSIS,
    IdNamespace.ESPN,
    IdNamespace.SLEEPER,
    IdNamespace.MFL,
    IdNamespace.PFR,
    IdNamespace.SPORTRADAR,
    IdNamespace.YAHOO,
)

_GSIS_RE = re.compile(r"^00-\d{7}$")
_NUMERIC_RE = re.compile(r"^\d{1,12}$")
_TEAM_CODE_RE = re.compile(r"^[A-Z]{2,4}$")
_PFR_RE = re.compile(r"^[A-Za-z0-9]{4,12}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{3,63}$")

# Values some upstreams use to mean "absent". Treating them as ids would create a single
# fake player that every id-less record collapses onto - the worst possible join bug.
_NULL_TOKENS = frozenset({"", "na", "n/a", "nan", "none", "null", "-", "0", "00", "false"})


@dataclass(frozen=True, slots=True)
class NormalizedId:
    """The result of normalising one external identifier."""

    namespace: IdNamespace
    value: str | None
    raw: str | None
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.value is not None

    @property
    def absent(self) -> bool:
        """No id was supplied at all - a normal state, not a data-quality problem."""
        return self.raw is None and self.value is None

    @property
    def malformed(self) -> bool:
        """An id was supplied but could not be trusted."""
        return self.value is None and self.raw is not None

    @property
    def quality_flags(self) -> tuple[str, ...]:
        return (self.reason,) if self.reason else ()


def _absent(namespace: IdNamespace) -> NormalizedId:
    return NormalizedId(namespace=namespace, value=None, raw=None)


def normalize_id(namespace: IdNamespace | str, raw: object) -> NormalizedId:
    """Normalise ``raw`` for ``namespace``.

    Accepts the shapes these ids actually arrive in: ``str`` from JSON APIs, ``int`` from
    Polars integer columns, and ``None``/blank/sentinel for absent.
    """
    space = IdNamespace(namespace)
    if raw is None:
        return _absent(space)
    if isinstance(raw, bool):
        # A bool is an int in Python; letting True become "1" would invent player id 1.
        return NormalizedId(space, None, str(raw), f"malformed_{space}_id")
    if isinstance(raw, float):
        text = _float_to_text(raw)
        had_whitespace = False
    else:
        original = str(raw)
        text = original.strip()
        # Only a *string* input can carry stray whitespace; an integer column rendering as
        # "4362628" from 4362628.0 is a dtype artefact, not a data-hygiene finding.
        had_whitespace = isinstance(raw, str) and text != original
    if text is None:
        return _absent(space)
    if text.lower() in _NULL_TOKENS:
        return _absent(space)

    flagged = f"whitespace_trimmed_{space}_id" if had_whitespace else ""
    normalised = _apply_format(space, text)
    if normalised is None:
        return NormalizedId(space, None, text, f"malformed_{space}_id")
    return NormalizedId(space, normalised, text, flagged)


def _float_to_text(raw: float) -> str | None:
    """Polars nullable integer columns can surface as floats; ``12345.0`` is id ``12345``."""
    if raw != raw:  # NaN
        return None
    if float(raw).is_integer():
        return str(int(raw))
    return str(raw).strip()


def _apply_format(namespace: IdNamespace, text: str) -> str | None:
    match namespace:
        case IdNamespace.GSIS:
            return text if _GSIS_RE.match(text) else None
        case IdNamespace.ESPN | IdNamespace.MFL | IdNamespace.YAHOO:
            return _canonical_numeric(text)
        case IdNamespace.SLEEPER:
            # Sleeper keys players numerically and D/ST units by team code ("BUF").
            numeric = _canonical_numeric(text)
            if numeric is not None:
                return numeric
            upper = text.upper()
            return upper if _TEAM_CODE_RE.match(upper) else None
        case IdNamespace.PFR:
            return text if _PFR_RE.match(text) else None
        case IdNamespace.SPORTRADAR:
            return text.lower() if _TOKEN_RE.match(text) else None
        case IdNamespace.DST:
            upper = text.upper()
            return upper if _TEAM_CODE_RE.match(upper) else None
    return None


def _canonical_numeric(text: str) -> str | None:
    """``"04362628"`` and ``4362628`` must compare equal, so strip padding zeros."""
    if not _NUMERIC_RE.match(text):
        return None
    stripped = text.lstrip("0")
    return stripped or None


def value_of(namespace: IdNamespace | str, raw: object) -> str | None:
    """Convenience wrapper returning just the normalised value."""
    return normalize_id(namespace, raw).value


def is_team_code(value: str | None) -> bool:
    """Whether ``value`` looks like a team abbreviation rather than a player id."""
    return bool(value) and bool(_TEAM_CODE_RE.match(str(value).strip().upper()))


def make_player_id(namespace: IdNamespace | str, external_id: str) -> str:
    """Build a namespaced canonical key such as ``gsis:00-0035057`` (ADR-019)."""
    space = IdNamespace(namespace)
    if not external_id:
        raise ValueError(f"cannot mint a {space} player_id from an empty external id")
    if ":" in external_id:
        raise ValueError(f"external id {external_id!r} must not contain ':'")
    return f"{space}:{external_id}"


def parse_player_id(player_id: str) -> tuple[IdNamespace, str]:
    """Split a canonical key back into namespace and external id."""
    namespace, separator, external = player_id.partition(":")
    if not separator or not external:
        raise ValueError(f"{player_id!r} is not a namespaced canonical player id")
    return IdNamespace(namespace), external
