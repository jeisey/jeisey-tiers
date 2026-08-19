"""UTC time helpers.

Every timestamp that crosses a module boundary in this project is timezone-aware UTC. A
naive datetime is a bug: `docs/DATA_CONTRACTS.md` section 3 makes anchor comparisons
(`feature_available_at <= anchor_at`) a leakage control, and comparing a naive value to an
aware one raises at best and silently compares wall-clock strings at worst.
"""

from __future__ import annotations

from datetime import UTC, datetime

__all__ = ["ensure_utc", "isoformat_utc", "parse_utc", "utc_now"]


def utc_now() -> datetime:
    """Current time, timezone-aware UTC."""
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Return ``value`` as timezone-aware UTC, rejecting naive datetimes.

    Naive input is rejected rather than assumed to be UTC. An assumption here would be
    invisible and wrong exactly when it matters - a source that publishes local timestamps.
    """
    if value.tzinfo is None:
        raise ValueError(f"naive datetime {value!r}: timestamps must carry a timezone")
    return value.astimezone(UTC)


def isoformat_utc(value: datetime) -> str:
    """Serialize as RFC 3339 with a ``Z`` suffix, second precision."""
    return ensure_utc(value).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_utc(value: str) -> datetime:
    """Parse an RFC 3339 timestamp into timezone-aware UTC."""
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp {value!r} has no timezone offset")
    return parsed.astimezone(UTC)
