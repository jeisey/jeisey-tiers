"""The ESPN ownership adapter, offline (ADR-112).

Every behaviour the 2026-10-17 probe established is pinned here against synthetic payloads:
the response envelope, the percent scale, missing and invalid fields, duplicate ids, the
completeness rule that catches an ignored filter or a truncated list, and the bounded,
retried transfer. No test here touches the network.
"""

from __future__ import annotations

import gzip
import json
import math
from datetime import UTC, datetime
from typing import Any

import pytest

from ffdraft.sources import espn
from ffdraft.sources.base import SourceFetchError
from ffdraft.sources.espn import (
    ESPN_REQUEST_LIMIT,
    EspnFetch,
    EspnOwnershipAdapter,
    completeness_problems,
    fetch_espn_current_period,
    fetch_espn_ownership,
)

NOW = datetime(2026, 10, 17, 19, 0, tzinfo=UTC)
MS = int(datetime(2026, 10, 17, 18, 30, tzinfo=UTC).timestamp() * 1000)


def _player(espn_id: Any, *, position: int = 2, **ownership: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"percentOwned": 12.34, "percentStarted": 5.6, "date": MS}
    body.update(ownership)
    return {
        "id": espn_id,
        "player": {
            "id": espn_id,
            "fullName": f"Player {espn_id}",
            "defaultPositionId": position,
            "ownership": {k: v for k, v in body.items() if v is not _DROP},
            # Vendor content the adapter must discard.
            "draftRanksByRankType": {"PPR": {"rank": 1}},
            "stats": [{"stats": {"1": 2}}],
        },
    }


_DROP = object()


def _normalize(players: list[dict[str, Any]]):
    return EspnOwnershipAdapter().normalize(players, retrieved_at=NOW)


def test_wrapped_and_bare_entries_normalize_to_the_same_row():
    wrapped = _normalize([_player(4429795)]).frame.to_dicts()
    bare = _normalize([_player(4429795)["player"]]).frame.to_dicts()
    assert wrapped == bare
    row = wrapped[0]
    assert row["external_player_id"] == "4429795"
    assert row["percent_rostered"] == 12.34
    assert row["percent_started"] == 5.6
    assert row["source_updated_at_utc"] == datetime(2026, 10, 17, 18, 30, tzinfo=UTC)
    assert row["snapshot_at_utc"] == NOW


def test_only_ownership_and_provenance_fields_survive():
    columns = set(_normalize([_player(1)]).frame.columns)
    assert columns == {
        "source_id",
        "external_player_id",
        "position_id",
        "full_name",
        "percent_rostered",
        "percent_started",
        "espn_percent_change",
        "league_type",
        "source_updated_at_utc",
        "snapshot_at_utc",
        "quality_flags",
    }
    assert not {"averageDraftPosition", "auctionValueAverage", "draftRanksByRankType"} & columns


def test_kickers_defenses_and_rows_without_ownership_are_not_core_rows():
    batch = _normalize(
        [
            _player(1, position=5),
            _player(2, position=16),
            {"id": 3, "player": {"id": 3, "defaultPositionId": 3}},
            _player(4, position=4),
        ],
    )
    assert batch.frame["external_player_id"].to_list() == ["4"]
    assert batch.metadata.detail["espn_rows_without_ownership"] == "1"


def test_a_missing_start_share_is_null_never_zero():
    batch = _normalize([_player(7, percentStarted=_DROP)])
    row = batch.frame.to_dicts()[0]
    assert row["percent_rostered"] == 12.34
    assert row["percent_started"] is None
    assert "espn_rows_without_percent_started" in batch.metadata.warning_codes


def test_zero_is_a_valid_reading():
    row = _normalize([_player(8, percentOwned=0, percentStarted=0.0)]).frame.to_dicts()[0]
    assert row["percent_rostered"] == 0.0
    assert row["percent_started"] == 0.0
    assert row["quality_flags"] == ""


@pytest.mark.parametrize("bad", [-0.01, 100.01, math.nan, math.inf, "50", True, None])
def test_out_of_range_or_non_numeric_percentages_are_nulled_and_flagged(bad):
    row = _normalize([_player(9, percentOwned=bad, percentStarted=bad)]).frame.to_dicts()[0]
    assert row["percent_rostered"] is None
    assert row["percent_started"] is None
    assert "invalid_percent_rostered" in row["quality_flags"]
    assert "invalid_percent_started" in row["quality_flags"]


def test_the_bounds_themselves_are_valid():
    rows = _normalize([_player(10, percentOwned=100, percentStarted=0)]).frame.to_dicts()
    assert rows[0]["percent_rostered"] == 100.0


def test_identical_duplicates_collapse_and_conflicting_ones_fail_closed():
    batch = _normalize(
        [_player(11), _player(11), _player(12, percentOwned=1.0), _player(12, percentOwned=2.0)],
    )
    assert batch.frame["external_player_id"].to_list() == ["11"]
    assert batch.metadata.detail["espn_conflicting_duplicate_ids"] == "1"
    assert batch.metadata.detail["espn_identical_duplicate_ids"] == "1"


def test_malformed_ids_are_dropped():
    batch = _normalize([_player("abc"), _player(None), _player(13)])
    assert batch.frame["external_player_id"].to_list() == ["13"]
    assert batch.metadata.detail["espn_rows_without_valid_id"] == "2"


def test_a_source_stamp_in_the_future_is_nulled():
    future = int(datetime(2026, 10, 18, tzinfo=UTC).timestamp() * 1000)
    row = _normalize([_player(14, date=future)]).frame.to_dicts()[0]
    assert row["source_updated_at_utc"] is None
    assert "source_date_in_future" in row["quality_flags"]


def test_semantic_check_warns_when_started_exceeds_rostered():
    adapter = EspnOwnershipAdapter()
    batch = adapter.normalize([_player(15, percentOwned=1.0, percentStarted=2.0)], retrieved_at=NOW)
    ids = [check.check_id for check in adapter.semantic_checks(batch)]
    assert "espn.started_above_rostered" in ids


# ------------------------------------------------------------------------------ transfer


class _Raw:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def read(self, size: int, decode_content: bool = False) -> bytes:
        del decode_content
        chunk, self.body = self.body[:size], self.body[size:]
        return chunk


class _Response:
    def __init__(self, status: int, payload: Any, headers: dict[str, str] | None = None) -> None:
        self.status_code = status
        body = gzip.compress(json.dumps(payload).encode("utf-8"), mtime=0)
        self.headers = {"content-encoding": "gzip", **(headers or {})}
        self.raw = _Raw(body)


def _universe(count: int) -> dict[str, Any]:
    return {"players": [_player(index + 1) for index in range(count)]}


def _transport(*responses: Any):
    calls: list[dict[str, Any]] = []
    queue = list(responses)

    def send(url: str, headers: Any, timeout: float) -> Any:
        calls.append({"url": url, "headers": dict(headers), "timeout": timeout})
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    send.calls = calls  # type: ignore[attr-defined]
    return send


def test_one_request_with_the_verified_filter_and_a_complete_universe():
    transport = _transport(
        _Response(200, _universe(3), {"x-fantasy-filter-player-count": "3"}),
    )
    fetched = fetch_espn_ownership(2026, transport=transport, sleep=lambda _: None)
    assert len(fetched.players) == 3
    assert fetched.universe_count == 3
    assert fetched.attempts == 1
    assert fetched.wire_bytes > 0 and fetched.decoded_bytes > fetched.wire_bytes / 10
    (call,) = transport.calls  # type: ignore[attr-defined]
    assert "/segments/0/leaguedefaults/3?view=kona_player_info" in call["url"]
    assert "scoringPeriodId" not in call["url"]
    sent = json.loads(call["headers"]["X-Fantasy-Filter"])
    assert sent["players"]["limit"] == ESPN_REQUEST_LIMIT
    assert sent["players"]["filterStatsForSourceIds"] == {"value": [99]}
    assert "jeisey-tiers" in call["headers"]["User-Agent"]
    assert "Cookie" not in call["headers"]


def test_an_ignored_filter_is_refused_not_trimmed():
    """The global route returns everything and says 0: completeness catches it."""
    transport = _transport(
        _Response(200, _universe(5), {"x-fantasy-filter-player-count": "0"}),
    )
    with pytest.raises(SourceFetchError, match="incomplete"):
        fetch_espn_ownership(2026, transport=transport, sleep=lambda _: None)


def test_a_truncated_list_is_refused():
    transport = _transport(
        _Response(200, _universe(4), {"x-fantasy-filter-player-count": "9"}),
    )
    with pytest.raises(SourceFetchError, match="ESPN counts 9"):
        fetch_espn_ownership(2026, transport=transport, sleep=lambda _: None)


def test_a_missing_count_header_or_a_limit_hit_is_incomplete():
    base = {"universe_count": None, "wire_bytes": 1, "decoded_bytes": 1, "duration_ms": 1}
    fetched = EspnFetch(players=({"id": 1},), attempts=1, url="u", **base)
    assert any("header missing" in problem for problem in completeness_problems(fetched))
    full = EspnFetch(
        players=tuple({"id": i} for i in range(ESPN_REQUEST_LIMIT)),
        attempts=1,
        url="u",
        **{**base, "universe_count": ESPN_REQUEST_LIMIT},
    )
    assert any("reached the requested limit" in problem for problem in completeness_problems(full))


def test_a_503_is_retried_with_backoff_then_succeeds():
    sleeps: list[float] = []
    transport = _transport(
        _Response(503, {}),
        ConnectionError("reset"),
        _Response(200, _universe(2), {"x-fantasy-filter-player-count": "2"}),
    )
    fetched = fetch_espn_ownership(2026, transport=transport, sleep=sleeps.append)
    assert fetched.attempts == 3
    assert sleeps == [2.0, 4.0]


def test_a_400_is_never_retried():
    sleeps: list[float] = []
    transport = _transport(_Response(400, {"messages": ["Filter: invalid"]}))
    with pytest.raises(SourceFetchError, match="HTTP 400"):
        fetch_espn_ownership(2026, transport=transport, sleep=sleeps.append)
    assert sleeps == []


def test_three_failures_raise_after_bounded_attempts():
    transport = _transport(TimeoutError("t"), TimeoutError("t"), TimeoutError("t"))
    with pytest.raises(SourceFetchError, match="after 3 attempts"):
        fetch_espn_ownership(2026, transport=transport, sleep=lambda _: None)
    assert len(transport.calls) == 3  # type: ignore[attr-defined]


def test_a_body_over_the_wire_cap_is_refused(monkeypatch):
    monkeypatch.setattr(espn, "MAX_WIRE_BYTES", 64)
    transport = _transport(
        _Response(200, _universe(50), {"x-fantasy-filter-player-count": "50"}),
    )
    with pytest.raises(SourceFetchError, match="on the wire"):
        fetch_espn_ownership(2026, transport=transport, sleep=lambda _: None)


def test_a_body_over_the_decoded_cap_is_refused(monkeypatch):
    monkeypatch.setattr(espn, "MAX_DECODED_BYTES", 1000)
    transport = _transport(
        _Response(200, _universe(50), {"x-fantasy-filter-player-count": "50"}),
    )
    with pytest.raises(SourceFetchError, match="decoded body exceeded"):
        fetch_espn_ownership(2026, transport=transport, sleep=lambda _: None)


def test_the_current_period_is_context_and_its_failure_is_none():
    ok = _transport(_Response(200, {"currentScoringPeriod": {"id": 6}}))
    assert fetch_espn_current_period(2026, transport=ok, sleep=lambda _: None) == 6
    nonsense = _transport(_Response(200, {"currentScoringPeriod": {"id": "six"}}))
    assert fetch_espn_current_period(2026, transport=nonsense, sleep=lambda _: None) is None
    down = _transport(_Response(404, {}))
    assert fetch_espn_current_period(2026, transport=down, sleep=lambda _: None) is None
