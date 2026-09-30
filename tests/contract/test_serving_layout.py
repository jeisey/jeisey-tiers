"""The served layout is derived, exact, and fails closed when it is not (ADR-098).

Every served file is a function of the artifacts beside it. These tests pin the four ways
that can stop being true — a stale manifest, a tampered file, a stray file, a slice that is
not its subset — and the encoding cases a real board exercises: rows missing an optional
field, a joined row that differs from its source, nested objects, a boolean that must not
become an integer, and build identity kept out of the served bytes.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from ffdraft.artifacts import validate_artifact_directory
from ffdraft.artifacts.serving import (
    CARD_BUCKETS,
    MANIFEST_FILENAME,
    SERVE_DIRNAME,
    bucket_of,
    build_serving_layout,
    decode_table,
    encode_table,
    package_serving,
    validate_serving_layout,
)
from ffdraft.paths import repo_root

GOLDEN = repo_root() / "tests" / "fixtures" / "artifacts"


def _critical_ids(directory: Path, *, required: bool = True) -> set[str]:
    gate = validate_artifact_directory(directory, require_serving=required)
    return {check.check_id for check in gate.checks if check.blocking}


def _envelopes(directory: Path) -> dict[str, Any]:
    from ffdraft.artifacts.serving import _load_sources

    envelopes, _ = _load_sources(directory)
    return envelopes


@pytest.fixture
def site(tmp_path: Path) -> Path:
    directory = tmp_path / "data"
    shutil.copytree(GOLDEN, directory)
    package_serving(directory)
    return directory


def test_golden_bundle_packages_and_validates(site: Path) -> None:
    assert _critical_ids(site) == set()
    manifest = json.loads((site / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert manifest["format"] == "serving_v1"
    assert manifest["card_buckets"] == CARD_BUCKETS
    # Both metadata objects travel inline, verbatim.
    assert manifest["build_metadata"] == json.loads(
        (site / "build_metadata.json").read_text(encoding="utf-8"),
    )
    assert manifest["ros_build_metadata"] == json.loads(
        (site / "ros_build_metadata.json").read_text(encoding="utf-8"),
    )
    for key, digest in manifest["files"].items():
        assert (site / SERVE_DIRNAME / f"{key}.{digest}.json").is_file(), key


def test_missing_manifest_is_critical_only_when_required(tmp_path: Path) -> None:
    directory = tmp_path / "data"
    shutil.copytree(GOLDEN, directory)
    (directory / MANIFEST_FILENAME).unlink()
    shutil.rmtree(directory / SERVE_DIRNAME)
    assert "serving.manifest_missing" in _critical_ids(directory, required=True)
    assert _critical_ids(directory, required=False) == set()


def test_a_stale_manifest_is_critical(site: Path) -> None:
    path = site / "tiers.json"
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["records"][0]["expected_points"] = envelope["records"][0]["expected_points"] + 1
    path.write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")
    critical = _critical_ids(site)
    assert "serving.manifest_stale" in critical
    assert "serving.file_unlisted" in critical  # the old tiers slice is no longer named


def test_a_tampered_slice_is_critical(site: Path) -> None:
    manifest = json.loads((site / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    key = next(key for key in manifest["files"] if key.startswith("ros_tiers/"))
    path = site / SERVE_DIRNAME / f"{key}.{manifest['files'][key]}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    column = payload["columns"]["ros_fair_rank"]
    column[0], column[1] = column[1], column[0]
    path.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    assert "serving.file_differs" in _critical_ids(site)


def test_a_stray_file_is_critical(site: Path) -> None:
    (site / SERVE_DIRNAME / "tiers" / "stale.0000000000000000.json").write_text("{}\n")
    assert "serving.file_unlisted" in _critical_ids(site)


def test_a_missing_file_is_critical(site: Path) -> None:
    victim = next((site / SERVE_DIRNAME / "card").rglob("*.json"))
    victim.unlink()
    assert "serving.file_missing" in _critical_ids(site)


def test_an_encoder_that_drops_a_row_is_caught_by_the_decode_proof(
    site: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The byte comparison alone would bless a wrong encoder; the independent decode does not."""
    import ffdraft.artifacts.serving as serving

    original = serving.encode_table

    def lossy(records: Any, **kwargs: Any) -> dict[str, Any]:
        return original(list(records)[:-1] if len(records) > 1 else records, **kwargs)

    monkeypatch.setattr(serving, "encode_table", lossy)
    envelopes = _envelopes(site)
    checks = validate_serving_layout(site, envelopes, required=True)
    assert "serving.slice_not_subset" in {check.check_id for check in checks if check.blocking}


def test_build_identity_never_enters_a_served_file(tmp_path: Path) -> None:
    """A rebuild whose rows did not change keeps every slice name: only the manifest moves."""
    first = tmp_path / "a"
    second = tmp_path / "b"
    shutil.copytree(GOLDEN, first)
    shutil.copytree(GOLDEN, second)
    for name in ("tiers.json", "ros_tiers.json", "inseason_opportunity.json"):
        path = second / name
        envelope = json.loads(path.read_text(encoding="utf-8"))
        envelope["build_id"] = "rebuilt-20990101T000000Z"
        envelope["generated_at_utc"] = "2099-01-01T00:00:00Z"
        for record in envelope["records"]:
            record["build_id"] = "rebuilt-20990101T000000Z"
        path.write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")
    one = package_serving(first)
    two = package_serving(second)
    assert set(one.files) == set(two.files)
    assert one.manifest["artifacts"]["tiers"] != two.manifest["artifacts"]["tiers"]
    for data in two.files.values():
        assert b"rebuilt-2099" not in data


def test_the_opportunity_slice_joins_its_ros_rows(site: Path) -> None:
    manifest = json.loads((site / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    keys = [key for key in manifest["files"] if key.startswith("inseason_opportunity/")]
    assert keys
    joined = 0
    for key in keys:
        payload = json.loads(
            (site / SERVE_DIRNAME / f"{key}.{manifest['files'][key]}.json").read_text(),
        )
        join = payload.get("join")
        if join is None:
            continue
        joined += join["rows"].count("1")
        assert join["family"] == "ros_tiers"
        assert "ros_fair_rank" in join["fields"]
        assert "ros_expected_vorp" in join["fields"]
    assert joined > 0


# ------------------------------------------------------------------------ encoding cases


def _roundtrip(
    records: list[dict[str, Any]],
    *,
    names: dict[str, str] | None = None,
    envelope: dict[str, Any] | None = None,
    join: Any = None,
    join_source: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    envelope = envelope or {"build_id": "b1"}
    fields = list(dict.fromkeys(key for record in records for key in record))
    table = encode_table(records, fields=fields, envelope=envelope, names=names, join=join)
    decoded = decode_table(
        json.loads(json.dumps(table)),
        envelope=envelope,
        names=names or {},
        join_source=join_source,
    )
    assert [json.dumps(row) for row in decoded] == [json.dumps(row) for row in records]
    return table


def test_rows_missing_an_optional_field_stay_missing() -> None:
    table = _roundtrip(
        [
            {"player_id": "a", "x": 1.5, "y": None},
            {"player_id": "b", "x": 2.5},
            {"player_id": "c", "x": 2.5, "y": 3},
        ],
    )
    assert table["absent"] == {"y": [1]}


def test_booleans_and_integers_are_not_interchangeable() -> None:
    table = _roundtrip([{"player_id": "a", "flag": True}, {"player_id": "b", "flag": 1}])
    assert "flag" in table["columns"]


def test_constants_nested_objects_and_envelope_identity() -> None:
    table = _roundtrip(
        [
            {
                "build_id": "b1",
                "player_id": "a",
                "season": 2026,
                "q": {"q10": 1.25, "q50": 3.5},
                "list": [1, 2],
            },
            {
                "build_id": "b1",
                "player_id": "b",
                "season": 2026,
                "q": {"q10": 2.0, "q50": 3.5},
                "list": [],
            },
        ],
    )
    assert table["envelope"] == ["build_id"]
    assert table["constants"]["season"] == 2026
    assert table["constants"]["q.q50"] == 3.5
    assert table["columns"]["q.q10"] == [1.25, 2.0]
    assert table["nested"] == {"q": {"q10": None, "q50": None}}


def test_names_resolve_through_the_dictionary_only_when_every_row_agrees() -> None:
    names = {"a": "Alpha", "b": "Beta"}
    agreed = _roundtrip(
        [{"player_id": "a", "display_name": "Alpha"}, {"player_id": "b", "display_name": "Beta"}],
        names=names,
    )
    assert agreed.get("names") == "display_name"
    assert "display_name" not in agreed["columns"]
    disagreed = _roundtrip(
        [{"player_id": "a", "display_name": "Alpha"}, {"player_id": "b", "display_name": "B."}],
        names=names,
    )
    assert "names" not in disagreed
    assert disagreed["columns"]["display_name"] == ["Alpha", "B."]


def test_a_row_that_differs_from_its_join_source_serves_its_own_values() -> None:
    source = {
        "a": {"player_id": "a", "rank": 1, "value": 10.5},
        "b": {"player_id": "b", "rank": 2, "value": 9.0},
    }
    records = [
        {"player_id": "a", "rank": 1, "value": 10.5, "adds": 3},
        {"player_id": "b", "rank": 2, "value": 9.25, "adds": 0},
        {"player_id": "c", "rank": 7, "value": 1.0, "adds": 90},
    ]
    table = _roundtrip(
        records,
        join=("ros_tiers", ["rank", "value"], source),
        join_source=source,
    )
    assert table["join"]["rows"] == "100"
    assert table["columns"]["value"] == [None, 9.25, 1.0]


def test_the_bucket_function_matches_the_browser() -> None:
    """The same vectors are asserted in web/tests/serving.test.ts."""
    vectors = {
        "": 0x811C9DC5 % 64,
        "gsis:00-0038542": 1525704982 % 64,
        "gsis:00-0023459": 3737496805 % 64,
    }
    for player_id, expected in vectors.items():
        assert bucket_of(player_id, 64) == expected


def test_layout_is_deterministic() -> None:
    from ffdraft.artifacts.serving import _load_sources

    envelopes, metadata = _load_sources(GOLDEN)
    one = build_serving_layout(envelopes, metadata)
    two = build_serving_layout(envelopes, metadata)
    assert one.files == two.files
    assert one.manifest == two.manifest
