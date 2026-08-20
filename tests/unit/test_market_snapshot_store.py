"""The append-only snapshot store: what it guarantees, and what it refuses.

ADR-038 makes three promises about retained market history, and a promise about immutable
data is worth exactly as much as the test that tries to break it. These tests break it:
they rewrite a retained snapshot with different bytes, corrupt a payload behind its
manifest, hand-edit a manifest to disagree with its own path, and re-run an identical
capture to prove a retried workflow is safe.
"""

from __future__ import annotations

import gzip
import json

import pytest

from ffdraft.market.snapshot import (
    NORMALIZED_FILENAME,
    CohortCapture,
    MarketSnapshotStore,
    SnapshotConflictError,
    SnapshotManifest,
    verify_store,
)
from ffdraft.retention import (
    MANIFEST_FILENAME,
    canonical_json,
    content_hash,
    gzip_bytes,
    parse_snapshot_key,
    snapshot_key,
)
from ffdraft.timeutil import isoformat_utc, parse_utc

SOURCE = "myfantasyleague_adp"
SEASON = 2026


def _rows(price: float = 12.5) -> list[dict[str, object]]:
    return [
        {
            "source_id": SOURCE,
            "season": SEASON,
            "cohort_id": "unfiltered",
            "external_player_id": "6000002",
            "player_id": "gsis:00-0000002",
            "average_pick": price,
            "sample_size": 140,
            "entity_kind": "player",
            "raw_position": "RB",
        },
    ]


def _manifest(moment: str, *, raw: bytes) -> SnapshotManifest:
    stamped = parse_utc(moment)
    return SnapshotManifest(
        manifest_version="1.0",
        source_id=SOURCE,
        season=SEASON,
        snapshot_key=snapshot_key(stamped),
        retrieved_at_utc=isoformat_utc(stamped),
        adapter_version="2.0",
        source_policy_version="mfl-developer-rules/2026-08-17",
        cohorts=(
            CohortCapture(
                cohort_id="unfiltered",
                filters={},
                label="all drafts",
                raw_path="cohorts/unfiltered/adp.raw.json.gz",
                raw_content_hash=content_hash(raw),
                row_count=1,
                response_timestamp="1787231602",
                total_drafts=426,
            ),
        ),
    )


def _write(store: MarketSnapshotStore, moment: str, *, price: float = 12.5):
    raw = gzip_bytes(canonical_json({"adp": {"player": [{"id": "6000002"}]}}))
    return store.write(
        manifest=_manifest(moment, raw=raw),
        normalized_rows=_rows(price),
        raw_payloads={"cohorts/unfiltered/adp.raw.json.gz": raw},
    )


@pytest.fixture
def store(tmp_path) -> MarketSnapshotStore:
    return MarketSnapshotStore(root=tmp_path)


# --------------------------------------------------------------------------------------
# Append
# --------------------------------------------------------------------------------------


def test_a_new_timestamp_appends(store):
    _write(store, "2026-08-20T12:00:00Z")
    _write(store, "2026-08-21T12:00:00Z")
    assert store.keys(SOURCE, SEASON) == ["2026-08-20T12-00-00Z", "2026-08-21T12-00-00Z"]


def test_keys_are_returned_oldest_first(store):
    for moment in ("2026-08-22T09:00:00Z", "2026-08-20T09:00:00Z", "2026-08-21T09:00:00Z"):
        _write(store, moment)
    keys = store.keys(SOURCE, SEASON)
    assert keys == sorted(keys)
    assert [parse_snapshot_key(key) for key in keys] == sorted(
        parse_snapshot_key(key) for key in keys
    )
    assert store.latest_key(SOURCE, SEASON) == "2026-08-22T09-00-00Z"


def test_an_earlier_snapshot_is_untouched_by_a_later_one(store):
    first = _write(store, "2026-08-20T12:00:00Z", price=12.5)
    before = (first.directory / NORMALIZED_FILENAME).read_bytes()
    _write(store, "2026-08-21T12:00:00Z", price=9.0)
    assert (first.directory / NORMALIZED_FILENAME).read_bytes() == before

    snapshot = store.read(SOURCE, SEASON, "2026-08-20T12-00-00Z")
    assert snapshot.rows[0]["average_pick"] == 12.5


# --------------------------------------------------------------------------------------
# Idempotency and refusal
# --------------------------------------------------------------------------------------


def test_an_identical_recapture_is_an_idempotent_no_op(store):
    first = _write(store, "2026-08-20T12:00:00Z")
    assert first.idempotent is False
    again = _write(store, "2026-08-20T12:00:00Z")
    assert again.idempotent is True
    assert store.keys(SOURCE, SEASON) == ["2026-08-20T12-00-00Z"]


def test_gzip_and_json_are_deterministic_so_a_retry_can_be_recognised(store):
    """Idempotency only works if identical data produces identical bytes."""
    first = _write(store, "2026-08-20T12:00:00Z")
    payload = (first.directory / NORMALIZED_FILENAME).read_bytes()
    assert gzip_bytes(canonical_json(_rows())) == payload


def test_a_differing_rewrite_fails_closed_and_writes_nothing(store):
    result = _write(store, "2026-08-20T12:00:00Z", price=12.5)
    before = (result.directory / NORMALIZED_FILENAME).read_bytes()
    with pytest.raises(SnapshotConflictError, match="immutable"):
        _write(store, "2026-08-20T12:00:00Z", price=99.0)
    assert (result.directory / NORMALIZED_FILENAME).read_bytes() == before


def test_a_conflict_leaves_every_other_file_untouched(store):
    """The check runs over the whole file set before any of it is written."""
    result = _write(store, "2026-08-20T12:00:00Z")
    raw_path = result.directory / "cohorts/unfiltered/adp.raw.json.gz"
    before = {path: path.read_bytes() for path in (raw_path, result.directory / MANIFEST_FILENAME)}
    with pytest.raises(SnapshotConflictError):
        _write(store, "2026-08-20T12:00:00Z", price=1.0)
    for path, payload in before.items():
        assert path.read_bytes() == payload


# --------------------------------------------------------------------------------------
# Content hashes and verification
# --------------------------------------------------------------------------------------


def test_the_manifest_round_trips(store):
    result = _write(store, "2026-08-20T12:00:00Z")
    written = json.loads((result.directory / MANIFEST_FILENAME).read_text())
    manifest = SnapshotManifest.from_dict(written)
    assert manifest.to_dict() == written
    assert manifest.normalized_row_count == 1
    assert manifest.cohort("unfiltered").total_drafts == 426


def test_the_manifest_never_claims_a_data_as_of_time(store):
    """MFL's response timestamp is generation time; promoting it would invent freshness."""
    result = _write(store, "2026-08-20T12:00:00Z")
    written = json.loads((result.directory / MANIFEST_FILENAME).read_text())
    assert written["source_as_of_utc"] is None
    assert written["cohorts"][0]["response_timestamp"] == "1787231602"


def test_verification_passes_on_an_untouched_store(store):
    _write(store, "2026-08-20T12:00:00Z")
    _write(store, "2026-08-21T12:00:00Z")
    verification = verify_store(store, source_id=SOURCE, season=SEASON)
    assert verification.ok
    assert verification.snapshots == 2
    # Per snapshot: the manifest, the normalized payload and one cohort's raw payload.
    # This fixture declares no player directory, so a real capture checks one more.
    assert verification.files_checked == 6


def test_tampering_with_a_retained_payload_is_detected(store):
    result = _write(store, "2026-08-20T12:00:00Z")
    target = result.directory / NORMALIZED_FILENAME
    target.write_bytes(gzip_bytes(canonical_json(_rows(price=1.0))))

    verification = verify_store(store, source_id=SOURCE, season=SEASON)
    assert not verification.ok
    assert any(NORMALIZED_FILENAME in problem for problem in verification.problems)

    with pytest.raises(SnapshotConflictError, match="content hash"):
        store.read(SOURCE, SEASON, "2026-08-20T12-00-00Z")


def test_tampering_with_a_raw_payload_is_detected(store):
    result = _write(store, "2026-08-20T12:00:00Z")
    (result.directory / "cohorts/unfiltered/adp.raw.json.gz").write_bytes(gzip.compress(b"{}"))
    verification = verify_store(store, source_id=SOURCE, season=SEASON)
    assert not verification.ok
    assert any("adp.raw.json.gz" in problem for problem in verification.problems)


def test_a_manifest_that_disagrees_with_its_own_path_is_detected(store):
    result = _write(store, "2026-08-20T12:00:00Z")
    path = result.directory / MANIFEST_FILENAME
    payload = json.loads(path.read_text())
    payload["retrieved_at_utc"] = "2026-08-19T12:00:00Z"
    path.write_text(json.dumps(payload))
    verification = verify_store(store, source_id=SOURCE, season=SEASON)
    assert any("disagrees with the path" in problem for problem in verification.problems)


def test_a_manifest_naming_a_missing_file_is_detected(store):
    result = _write(store, "2026-08-20T12:00:00Z")
    (result.directory / "cohorts/unfiltered/adp.raw.json.gz").unlink()
    verification = verify_store(store, source_id=SOURCE, season=SEASON)
    assert any("missing file" in problem for problem in verification.problems)


def test_an_empty_store_verifies_vacuously(store):
    verification = verify_store(store, source_id=SOURCE, season=SEASON)
    assert verification.ok
    assert verification.snapshots == 0


# --------------------------------------------------------------------------------------
# Keys
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "moment",
    ["2026-08-20T12:00:00Z", "2026-01-01T00:00:00Z", "2026-12-31T23:59:59Z"],
)
def test_snapshot_keys_round_trip(moment):
    key = snapshot_key(parse_utc(moment))
    assert parse_snapshot_key(key) == parse_utc(moment)


@pytest.mark.parametrize("key", ["", "not-a-key", "2026-08-20T12:00:00Z", "20260820T120000Z"])
def test_a_malformed_key_is_rejected_rather_than_guessed(key):
    with pytest.raises(ValueError, match="snapshot key"):
        parse_snapshot_key(key)


def test_a_directory_that_is_not_a_snapshot_key_is_ignored(store):
    _write(store, "2026-08-20T12:00:00Z")
    (store.season_dir(SOURCE, SEASON) / "scratch").mkdir()
    assert store.keys(SOURCE, SEASON) == ["2026-08-20T12-00-00Z"]


# --------------------------------------------------------------------------------------
# Status captures share the mechanism and get their own verification
# --------------------------------------------------------------------------------------


def _status_capture(moment: str):
    from ffdraft.status.capture import StatusCapture

    stamped = parse_utc(moment)
    return StatusCapture(
        source_id="sleeper",
        season=SEASON,
        snapshot_key=snapshot_key(stamped),
        observed_at_utc=stamped,
        adapter_version="1.1",
        source_policy_version="sleeper-non-commercial/2026-08-17",
        rows=[
            {
                "source_id": "sleeper",
                "external_player_id": "5000004",
                "observed_at_utc": isoformat_utc(stamped),
                "injury_status": "Questionable",
            },
        ],
    )


def test_a_status_capture_appends_and_verifies(tmp_path):
    from ffdraft.retention import SnapshotStore
    from ffdraft.status.capture import (
        read_status_capture,
        verify_status_store,
        write_status_capture,
    )

    store = SnapshotStore(root=tmp_path, prefix="market")
    write_status_capture(_status_capture("2026-08-20T12:00:00Z"), store=store)
    write_status_capture(_status_capture("2026-08-21T12:00:00Z"), store=store)

    captures, files, problems = verify_status_store(store, season=SEASON)
    assert (captures, files, problems) == (2, 4, ())

    latest = read_status_capture(store, season=SEASON)
    assert latest is not None
    assert latest.snapshot_key == "2026-08-21T12-00-00Z"
    assert latest.rows[0]["injury_status"] == "Questionable"


def test_a_differing_status_rewrite_fails_closed(tmp_path):
    from ffdraft.retention import SnapshotStore
    from ffdraft.status.capture import write_status_capture

    store = SnapshotStore(root=tmp_path, prefix="market")
    write_status_capture(_status_capture("2026-08-20T12:00:00Z"), store=store)

    conflicting = _status_capture("2026-08-20T12:00:00Z")
    conflicting.rows[0]["injury_status"] = "Out"
    with pytest.raises(SnapshotConflictError, match="immutable"):
        write_status_capture(conflicting, store=store)


def test_tampering_with_a_status_capture_is_detected(tmp_path):
    from ffdraft.retention import SnapshotStore
    from ffdraft.status.capture import (
        STATUS_NORMALIZED_FILENAME,
        read_status_capture,
        verify_status_store,
        write_status_capture,
    )

    store = SnapshotStore(root=tmp_path, prefix="market")
    write_status_capture(_status_capture("2026-08-20T12:00:00Z"), store=store)
    target = (
        tmp_path
        / "status"
        / "sleeper"
        / str(SEASON)
        / "2026-08-20T12-00-00Z"
        / STATUS_NORMALIZED_FILENAME
    )
    target.write_bytes(gzip_bytes(canonical_json([{"injury_status": "Out"}])))

    _captures, _files, problems = verify_status_store(store, season=SEASON)
    assert any("hashes to" in problem for problem in problems)
    with pytest.raises(SnapshotConflictError, match="hashes to"):
        read_status_capture(store, season=SEASON)


def test_an_absent_status_capture_is_none_rather_than_an_error(tmp_path):
    from ffdraft.retention import SnapshotStore
    from ffdraft.status.capture import read_status_capture

    assert read_status_capture(SnapshotStore(root=tmp_path, prefix="market"), season=SEASON) is None
