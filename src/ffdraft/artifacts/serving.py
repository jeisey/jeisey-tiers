"""The serving layout: what the browser actually downloads (ADR-098).

The public artifacts (``tiers.json``, ``ros_tiers.json`` ...) are the contract and the source
of truth. They are also far too large to hand to a reader who looks at one block of one view:
a cold visit used to download all fourteen of them, about 2.7 MB compressed and 24 MB of JSON
to parse, whichever tab was open. This module derives, from those artifacts and nothing else,
the files the site serves instead:

* **slices** — one artifact's records for one league × scoring block (or one scoring preset,
  or the whole artifact when it has no block), column-major, with per-slice constants lifted
  into a header and ``display_name`` resolved through one player dictionary;
* **card shards** — for one block and one bucket of players, every per-player record a player
  card reads, so opening a card fetches one small file instead of whole artifacts;
* **the manifest** — ``data/manifest.json``, the one fixed URL: every served file by content
  hash, each source artifact's envelope, and both metadata objects inline.

**Derived, never a second source of truth.** Every served file is a pure function of the
artifacts beside it. ``validate_serving_layout`` re-derives the whole layout from the
artifacts, requires the files on disk to be byte-identical to it, and then decodes every
slice with an independent decoder and requires each decoded record to serialize exactly as
the matching record of its full artifact does. A slice that is not exactly its subset cannot
pass validation, so it cannot be deployed.

**Content-addressed.** A served file's name carries the first 16 hex digits of its SHA-256.
GitHub Pages resets every file's ``Last-Modified``/``ETag`` on every deploy (docs/OPERATIONS.md
section 17), so HTTP revalidation re-downloads unchanged bytes after each deploy; a URL that
names its own content lets the page keep an immutable copy (the Cache API) and skip the
network entirely for anything that did not change. Build identity (``build_id``) therefore
never appears inside a served file: it lives in the manifest, and a slice whose rows did not
change keeps its name across builds.

No value is rounded, re-expressed or recomputed here: every number is the artifact's own
double, written with the same shortest round-trip representation (docs/DATA_CONTRACTS.md
section 21 states the per-field precision policy this implies).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ffdraft.artifacts.spec import ARTIFACT_SPECS, BUILD_METADATA_FILENAME
from ffdraft.contracts import QualityCheck

__all__ = [
    "CARD_BUCKETS",
    "CARD_SECTIONS",
    "FAMILIES",
    "MANIFEST_FILENAME",
    "SERVE_DIRNAME",
    "SERVING_FORMAT",
    "Family",
    "ServingLayout",
    "build_serving_layout",
    "bucket_of",
    "decode_table",
    "package_serving",
    "serving_report",
    "validate_serving_layout",
]

#: The layout contract. The frontend refuses a manifest whose major version it does not know,
#: exactly as it refuses an artifact envelope (docs/DATA_CONTRACTS.md section 13).
SERVING_FORMAT = "serving_v1"
SERVING_VERSION = "1.0"
MANIFEST_FILENAME = "manifest.json"
SERVE_DIRNAME = "serve"
ROS_BUILD_METADATA_FILENAME = "ros_build_metadata.json"

#: Players per card shard = published players / buckets. Sixty-four keeps the largest shard near
#: 13 kB compressed on the 2026 board while the manifest stays small (ADR-098 measurements).
CARD_BUCKETS = 64

#: Hex digits of SHA-256 in a served file's name and in the manifest. 64 bits: an integrity
#: check and a cache key, never a security boundary.
HASH_DIGITS = 16

Partition = Literal["block", "scoring", "all"]


@dataclass(frozen=True, slots=True)
class Family:
    """One kind of served slice: an artifact, how it is partitioned, and which fields."""

    name: str
    artifact: str
    partition: Partition
    #: When set, the only fields served (in artifact order). ``player_id`` must be among them.
    only: tuple[str, ...] | None = None
    #: Fields left out. Mutually exclusive with ``only``.
    exclude: tuple[str, ...] = ()
    #: A family of the same partition whose rows may supply fields this one duplicates.
    join: str | None = None


#: Every slice family the site loads, and why each is shaped the way it is (the dependency
#: map in docs/ARCHITECTURE.md section 14 names the views that read each one).
FAMILIES: tuple[Family, ...] = (
    Family("tiers", "tiers", "block"),
    Family("arbitrage", "arbitrage", "block"),
    # Draft boards badge every row, so the whole (small) status artifact is one slice.
    Family("player_status", "player_status", "all"),
    Family("ros_tiers", "ros_tiers", "block"),
    # The opportunity board copies eight intrinsic fields and a few identity fields from the
    # ROS board. A row whose copies equal the ROS row of the same block serves them once, from
    # the ROS slice; any row that differs in any of them serves its own values.
    Family("inseason_opportunity", "inseason_opportunity", "block", join="ros_tiers"),
    # What a player card's cohort strips read from every row of the block: the share and
    # transaction fields, and nothing a card could mistake for the board (ADR-098).
    Family(
        "inseason_opportunity_cohort",
        "inseason_opportunity",
        "block",
        only=(
            "league_preset_id",
            "scoring_preset",
            "player_id",
            "position",
            "add_count",
            "drop_count",
            "snap_share_last3",
            "target_share_last3",
        ),
    ),
    Family("weekly_projections", "weekly_projections", "scoring"),
    Family("team_matchups", "team_matchups", "all"),
    Family("behavior_trend_series", "behavior_trend_series", "all"),
    # Observed role. The Opportunity Board and Pick of the Week read whole records (a role
    # reading walks the weekly series); a card's cohort strip reads three fields of every
    # player, which is all a card opened from the ROS board has to add.
    Family("player_usage", "player_usage", "all"),
    Family(
        "player_usage_cohort",
        "player_usage",
        "all",
        only=("player_id", "position", "touchdown_points_share", "pass_epa_per_dropback"),
    ),
    Family("player_headshots", "player_headshots", "all"),
)

#: What one card shard carries: every per-player record a card reads, per artifact, with the
#: partition that selects the rows for the shard's block.
CARD_SECTIONS: tuple[tuple[str, Partition], ...] = (
    ("tiers", "block"),
    ("arbitrage", "block"),
    ("market_trend_series", "block"),
    ("projections", "scoring"),
    ("player_status", "all"),
    ("player_headshots", "all"),
    ("ros_tiers", "block"),
    ("inseason_opportunity", "block"),
    ("weekly_projections", "scoring"),
    ("player_usage", "all"),
    ("behavior_trend_series", "all"),
)

#: Artifacts whose rows name a player, in the order the dictionary takes a name from.
_NAMED_ARTIFACTS = (
    "ros_tiers",
    "inseason_opportunity",
    "weekly_projections",
    "player_usage",
    "tiers",
    "arbitrage",
    "projections",
    "player_status",
)

#: Record fields that carry the build's identity rather than content. They are restored from
#: the envelope in the manifest, which is what keeps an unchanged slice's name stable.
_ENVELOPE_FIELDS = ("build_id",)

#: Fields a joined row never takes from the source: keys, identity and constants of each side.
_NEVER_JOINED = frozenset(
    {
        "schema_version",
        "build_id",
        "league_preset_id",
        "scoring_preset",
        "player_id",
        "season",
        "through_week",
        "surface_reasons",
        "quality_flags",
        "outside_tier_board",
    },
)


# ------------------------------------------------------------------------------ primitives


def _dumps(payload: Any) -> str:
    """The one serialization every served file uses: compact, UTF-8, no NaN, stable order."""
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _canonical(value: Any) -> str:
    """How two JSON values are compared: their serialization, key order included.

    ``==`` on parsed JSON is not strict enough — ``True == 1`` and ``1 == 1.0`` in Python —
    and a slice that turned a boolean into an integer would change what the page renders.
    """
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:HASH_DIGITS]


def bucket_of(player_id: str, buckets: int = CARD_BUCKETS) -> int:
    """FNV-1a (32-bit) over the id's UTF-8 bytes, modulo ``buckets``.

    The browser computes the same function (``web/src/data/serving.ts``) to find a player's
    card shard without a lookup table; the two are pinned together by a shared test vector.
    """
    value = 0x811C9DC5
    for byte in player_id.encode("utf-8"):
        value ^= byte
        value = (value * 0x01000193) & 0xFFFFFFFF
    return value % buckets


def block_key(record: Mapping[str, Any]) -> str:
    return f"{record['league_preset_id']}.{record['scoring_preset']}"


def _partition_key(record: Mapping[str, Any], partition: Partition) -> str:
    if partition == "block":
        return block_key(record)
    if partition == "scoring":
        return str(record["scoring_preset"])
    return "all"


def _select_fields(fields: Sequence[str], family: Family) -> list[str]:
    if family.only is not None:
        return [name for name in fields if name in family.only]
    return [name for name in fields if name not in family.exclude]


def _field_order(records: Sequence[Mapping[str, Any]]) -> list[str]:
    """Every key, in first-appearance order. Records of one artifact share one order."""
    seen: dict[str, None] = {}
    for record in records:
        for key in record:
            seen.setdefault(key, None)
    return list(seen)


# --------------------------------------------------------------------------------- tables


def encode_table(
    records: Sequence[Mapping[str, Any]],
    *,
    fields: Sequence[str],
    envelope: Mapping[str, Any],
    names: Mapping[str, str] | None,
    join: tuple[str, Sequence[str], Mapping[str, Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Records → one column-major table. The inverse is :func:`decode_table`.

    ``join`` is ``(family, fields, source_rows_by_player)``: a row whose value in every one of
    ``fields`` equals the source row of the same player serves none of them.
    """
    count = len(records)
    table: dict[str, Any] = {"count": count, "fields": list(fields)}

    joined = [False] * count
    join_fields: list[str] = []
    if join is not None:
        join_family, candidate_fields, source = join
        join_fields = [name for name in candidate_fields if name in fields]
        for index, record in enumerate(records):
            other = source.get(str(record.get("player_id")))
            if other is None or not join_fields:
                continue
            joined[index] = all(
                name in record
                and name in other
                and _canonical(record[name]) == _canonical(other[name])
                for name in join_fields
            )
        if any(joined):
            table["join"] = {
                "family": join_family,
                "fields": join_fields,
                "rows": "".join("1" if flag else "0" for flag in joined),
            }
        else:
            join_fields = []

    absent: dict[str, list[int]] = {}
    constants: dict[str, Any] = {}
    from_envelope: list[str] = []
    columns: dict[str, list[Any]] = {}
    nested: dict[str, Any] = {}
    names_field: str | None = None
    for name in fields:
        missing = [index for index, record in enumerate(records) if name not in record]
        if missing:
            absent[name] = missing
        # A joined row contributes nothing of its own to a joined field.
        own_rows = [index for index in range(count) if not (joined[index] and name in join_fields)]
        present = [records[index][name] for index in own_rows if name in records[index]]
        if (
            name in _ENVELOPE_FIELDS
            and present
            and len(present) == len(own_rows)
            and all(_canonical(value) == _canonical(envelope.get(name)) for value in present)
        ):
            from_envelope.append(name)
            continue
        if (
            name == "display_name"
            and names is not None
            and not missing
            and all(
                joined[index]
                and name in join_fields
                or names.get(str(record.get("player_id"))) == record[name]
                for index, record in enumerate(records)
            )
        ):
            names_field = name
            continue
        values = [
            None if name not in record or (joined[index] and name in join_fields) else record[name]
            for index, record in enumerate(records)
        ]
        # A field whose every value is an object with one key sequence is served as one
        # column per leaf: numbers sit beside numbers, which is most of what gzip needs.
        shape = (
            _shape(values)
            if not missing and name not in join_fields and len(present) == count
            else None
        )
        if shape is not None:
            nested[name] = shape
            for path, leaf in _leaves(name, shape, values):
                _place(path, leaf, count, constants, columns)
            continue
        if count > 1 and present and len(present) == len(own_rows):
            first = _canonical(present[0])
            if all(_canonical(value) == first for value in present[1:]):
                constants[name] = present[0]
                continue
        columns[name] = values
    if absent:
        table["absent"] = absent
    if from_envelope:
        table["envelope"] = from_envelope
    if names_field is not None:
        table["names"] = names_field
    if nested:
        table["nested"] = nested
    if constants:
        table["constants"] = constants
    table["columns"] = columns
    return table


def _shape(values: Sequence[Any]) -> dict[str, Any] | None:
    """The shared key tree of a list of objects, or None when they do not share one.

    A leaf is ``None``. Keys holding a dot are never flattened, so a leaf path is unambiguous.
    """
    if not values or not all(isinstance(value, dict) for value in values):
        return None
    keys = list(values[0])
    if not keys or any(list(value) != keys for value in values[1:]) or any("." in k for k in keys):
        return None
    return {key: _shape([value[key] for value in values]) for key in keys}


def _leaves(
    prefix: str,
    shape: Mapping[str, Any],
    values: Sequence[Any],
) -> Iterable[tuple[str, list[Any]]]:
    for key, sub in shape.items():
        path = f"{prefix}.{key}"
        column = [value[key] for value in values]
        if sub is None:
            yield path, column
        else:
            yield from _leaves(path, sub, column)


def _place(
    path: str,
    values: list[Any],
    count: int,
    constants: dict[str, Any],
    columns: dict[str, list[Any]],
) -> None:
    if count > 1:
        first = _canonical(values[0])
        if all(_canonical(value) == first for value in values[1:]):
            constants[path] = values[0]
            return
    columns[path] = values


def _rebuild(
    prefix: str,
    shape: Mapping[str, Any],
    index: int,
    constants: Mapping[str, Any],
    columns: Mapping[str, list[Any]],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, sub in shape.items():
        path = f"{prefix}.{key}"
        if sub is not None:
            out[key] = _rebuild(path, sub, index, constants, columns)
        elif path in constants:
            out[key] = constants[path]
        else:
            out[key] = columns[path][index]
    return out


def decode_table(
    table: Mapping[str, Any],
    *,
    envelope: Mapping[str, Any],
    names: Mapping[str, str],
    join_source: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """One table → records, independently of the encoder (it reads only the file's words).

    The browser's decoder (``web/src/data/serving.ts``) implements exactly this, and the
    golden test in ``web/tests/serving.test.ts`` decodes files this module wrote.
    """
    count = int(table["count"])
    fields: list[str] = list(table["fields"])
    absent = {name: set(rows) for name, rows in table.get("absent", {}).items()}
    constants: Mapping[str, Any] = table.get("constants", {})
    envelope_fields = set(table.get("envelope", ()))
    names_field = table.get("names")
    columns: Mapping[str, list[Any]] = table.get("columns", {})
    nested: Mapping[str, Any] = table.get("nested", {})
    join = table.get("join")
    join_fields = set(join["fields"]) if join else set()
    join_rows: str = join["rows"] if join else ""
    if join and join_source is None:
        raise ValueError(f"table joins {join['family']} but no source rows were given")

    records: list[dict[str, Any]] = []
    for index in range(count):
        values: dict[str, Any] = {}
        joined = bool(join) and join_rows[index] == "1"
        for name in fields:
            if index in absent.get(name, ()):
                continue
            if name in nested:
                values[name] = _rebuild(name, nested[name], index, constants, columns)
            elif name in constants:
                values[name] = constants[name]
            elif name in envelope_fields:
                values[name] = envelope[name]
            elif name == names_field:
                values[name] = None  # filled once player_id is known
            else:
                values[name] = columns[name][index]
        if joined:
            source = (join_source or {})[str(values["player_id"])]
            for name in join_fields:
                values[name] = source[name]
        if (
            names_field is not None
            and names_field in values
            and not (joined and names_field in join_fields)
        ):
            values[names_field] = names[str(values["player_id"])]
        records.append({name: values[name] for name in fields if name in values})
    return records


# --------------------------------------------------------------------------------- layout


@dataclass(slots=True)
class ServingLayout:
    """Everything :func:`package_serving` writes, in memory."""

    manifest: dict[str, Any]
    #: served path (relative to the data directory) → bytes
    files: dict[str, bytes] = field(default_factory=dict)
    #: served path → (family or ``card``, partition, the source rows each table stands for)
    provenance: dict[str, Any] = field(default_factory=dict)


def _load_sources(
    directory: Path,
) -> tuple[dict[str, Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    envelopes: dict[str, Mapping[str, Any]] = {}
    for artifact, spec in ARTIFACT_SPECS.items():
        path = directory / spec.json_filename
        if path.is_file():
            envelopes[artifact] = json.loads(path.read_text(encoding="utf-8"))
    metadata: dict[str, Mapping[str, Any]] = {}
    for key, filename in (
        ("build_metadata", BUILD_METADATA_FILENAME),
        ("ros_build_metadata", ROS_BUILD_METADATA_FILENAME),
    ):
        path = directory / filename
        if path.is_file():
            metadata[key] = json.loads(path.read_text(encoding="utf-8"))
    return envelopes, metadata


def _served_artifacts() -> list[str]:
    served = {family.artifact for family in FAMILIES} | {name for name, _ in CARD_SECTIONS}
    return [artifact for artifact in ARTIFACT_SPECS if artifact in served]


def _player_names(envelopes: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    names: dict[str, str] = {}
    for artifact in _NAMED_ARTIFACTS:
        for record in envelopes.get(artifact, {}).get("records", ()):
            name = record.get("display_name")
            player = record.get("player_id")
            if isinstance(name, str) and isinstance(player, str):
                names.setdefault(player, name)
    return dict(sorted(names.items()))


def _envelope_header(envelope: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in envelope.items() if key != "records"}


def _encode_file(payload: Mapping[str, Any]) -> bytes:
    return (_dumps(payload) + "\n").encode("utf-8")


def build_serving_layout(
    envelopes: Mapping[str, Mapping[str, Any]],
    metadata: Mapping[str, Mapping[str, Any]],
    *,
    buckets: int = CARD_BUCKETS,
) -> ServingLayout:
    """Derive the whole served layout from the artifacts. Pure and deterministic."""
    served = [artifact for artifact in _served_artifacts() if artifact in envelopes]
    names = _player_names(envelopes)
    manifest: dict[str, Any] = {
        "format": SERVING_FORMAT,
        "version": SERVING_VERSION,
        "card_buckets": buckets,
        "artifacts": {artifact: _envelope_header(envelopes[artifact]) for artifact in served},
    }
    for key in ("build_metadata", "ros_build_metadata"):
        if key in metadata:
            manifest[key] = metadata[key]
    layout = ServingLayout(manifest=manifest)
    entries: dict[str, str] = {}

    def add(key: str, payload: Mapping[str, Any], provenance: Any) -> None:
        data = _encode_file(payload)
        digest = _digest(data)
        path = f"{SERVE_DIRNAME}/{key}.{digest}.json"
        layout.files[path] = data
        layout.provenance[path] = provenance
        entries[key] = digest

    add("players", {"format": SERVING_FORMAT, "names": names}, ("players", "all", None))

    # Rows of every block-partitioned family, keyed for the join and the card shards.
    partitioned: dict[str, dict[str, list[Mapping[str, Any]]]] = {}
    for artifact in served:
        records = list(envelopes[artifact].get("records", ()))
        for partition in ("block", "scoring", "all"):
            groups: dict[str, list[Mapping[str, Any]]] = {}
            try:
                for record in records:
                    groups.setdefault(_partition_key(record, partition), []).append(record)
            except KeyError:
                continue
            partitioned[f"{artifact}|{partition}"] = groups

    for family in FAMILIES:
        if family.artifact not in envelopes:
            continue
        envelope = envelopes[family.artifact]
        groups = partitioned.get(f"{family.artifact}|{family.partition}", {})
        all_fields = _field_order(list(envelope.get("records", ())))
        fields = _select_fields(all_fields, family)
        for key in sorted(groups):
            rows = [{name: row[name] for name in fields if name in row} for row in groups[key]]
            join = None
            if family.join is not None:
                join_family = next(item for item in FAMILIES if item.name == family.join)
                source_rows = partitioned.get(
                    f"{join_family.artifact}|{family.partition}",
                    {},
                ).get(key)
                if source_rows is not None:
                    source_fields = set(_field_order(source_rows))
                    join_fields = [
                        name
                        for name in fields
                        if name in source_fields and name not in _NEVER_JOINED
                    ]
                    by_player = {str(row["player_id"]): row for row in source_rows}
                    join = (family.join, join_fields, by_player)
            table = encode_table(rows, fields=fields, envelope=envelope, names=names, join=join)
            payload = {
                "format": SERVING_FORMAT,
                "family": family.name,
                "artifact": family.artifact,
                "partition": key,
                **table,
            }
            add(f"{family.name}/{key}", payload, (family.name, key, rows))

    # Card shards: one per block and bucket that holds anyone.
    blocks = sorted(
        {
            key
            for artifact, partition in CARD_SECTIONS
            if partition == "block"
            for key in partitioned.get(f"{artifact}|block", {})
        },
    )
    for block in blocks:
        scoring = block.split(".", 1)[1]
        sections_rows: dict[str, list[Mapping[str, Any]]] = {}
        for artifact, partition in CARD_SECTIONS:
            if artifact not in envelopes:
                continue
            groups = partitioned.get(f"{artifact}|{partition}", {})
            key = block if partition == "block" else scoring if partition == "scoring" else "all"
            sections_rows[artifact] = list(groups.get(key, ()))
        by_bucket: dict[int, dict[str, list[Mapping[str, Any]]]] = {}
        for artifact, section_rows in sections_rows.items():
            for row in section_rows:
                bucket = bucket_of(str(row["player_id"]), buckets)
                by_bucket.setdefault(bucket, {}).setdefault(artifact, []).append(row)
        for bucket in sorted(by_bucket):
            sections: dict[str, Any] = {}
            provenance: dict[str, list[Mapping[str, Any]]] = {}
            for artifact, _ in CARD_SECTIONS:
                card_rows = by_bucket[bucket].get(artifact)
                if not card_rows:
                    continue
                envelope = envelopes[artifact]
                fields = _field_order(list(envelope.get("records", ())))
                sections[artifact] = encode_table(
                    card_rows,
                    fields=fields,
                    envelope=envelope,
                    names=names,
                )
                provenance[artifact] = card_rows
            payload = {
                "format": SERVING_FORMAT,
                "family": "card",
                "partition": f"{block}/{bucket:02d}",
                "sections": sections,
            }
            add(
                f"card/{block}/{bucket:02d}", payload, ("card", f"{block}/{bucket:02d}", provenance)
            )

    manifest["files"] = dict(sorted(entries.items()))
    return layout


def _manifest_bytes(manifest: Mapping[str, Any]) -> bytes:
    return _encode_file(manifest)


def package_serving(directory: Path, *, buckets: int = CARD_BUCKETS) -> ServingLayout:
    """Write the served layout beside the artifacts in ``directory``, replacing any old one.

    Staged into a sibling directory and moved into place, and the manifest — the only file
    a page reads by a fixed name — is written last, so a failure part-way leaves the previous
    manifest pointing at the previous files rather than at a half-written set.
    """
    envelopes, metadata = _load_sources(directory)
    layout = build_serving_layout(envelopes, metadata, buckets=buckets)
    stage = directory / f".{SERVE_DIRNAME}.staging"
    if stage.exists():
        shutil.rmtree(stage)
    for path, data in layout.files.items():
        target = stage / Path(path).relative_to(SERVE_DIRNAME)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    final = directory / SERVE_DIRNAME
    if final.exists():
        shutil.rmtree(final)
    os.replace(stage, final)
    manifest_path = directory / MANIFEST_FILENAME
    tmp = directory / f".{MANIFEST_FILENAME}.tmp"
    tmp.write_bytes(_manifest_bytes(layout.manifest))
    os.replace(tmp, manifest_path)
    return layout


# ------------------------------------------------------------------------------ validation


def _fail(check_id: str, message: str, observed: str = "", expected: str = "") -> QualityCheck:
    return QualityCheck.fail(
        check_id,
        stage="artifacts.serving",
        message=message,
        observed=observed,
        expected=expected,
    )


def _decode_served(
    layout: ServingLayout,
    path: str,
    data: bytes,
    decoded_families: Mapping[str, list[dict[str, Any]]],
) -> tuple[str, list[str]]:
    """Decode one served file independently and compare it with the rows it stands for."""
    problems: list[str] = []
    payload = json.loads(data.decode("utf-8"))
    names = json.loads(layout.files[_players_path(layout)].decode("utf-8"))["names"]
    artifacts = layout.manifest["artifacts"]
    kind, partition, expected = layout.provenance[path]
    if kind == "players":
        return kind, problems
    if kind == "card":
        for artifact, rows in expected.items():
            table = payload["sections"].get(artifact)
            if table is None:
                problems.append(f"{path}: section {artifact} missing")
                continue
            decoded = decode_table(table, envelope=artifacts[artifact], names=names)
            problems.extend(_compare(path, artifact, decoded, rows))
        extra = set(payload["sections"]) - set(expected)
        if extra:
            problems.append(f"{path}: unexpected sections {sorted(extra)}")
        return kind, problems
    join_source = None
    join = payload.get("join")
    if join is not None:
        join_source = {
            str(row["player_id"]): row
            for row in decoded_families.get(f"{join['family']}/{partition}", [])
        }
    decoded = decode_table(
        payload,
        envelope=artifacts[payload["artifact"]],
        names=names,
        join_source=join_source,
    )
    problems.extend(_compare(path, payload["artifact"], decoded, expected))
    return kind, problems


def _players_path(layout: ServingLayout) -> str:
    return f"{SERVE_DIRNAME}/players.{layout.manifest['files']['players']}.json"


def _compare(
    path: str,
    artifact: str,
    decoded: Sequence[Mapping[str, Any]],
    expected: Sequence[Mapping[str, Any]],
) -> list[str]:
    if len(decoded) != len(expected):
        return [f"{path}: {artifact} decodes to {len(decoded)} rows, expected {len(expected)}"]
    problems = []
    for index, (got, want) in enumerate(zip(decoded, expected, strict=True)):
        if _canonical(got) != _canonical(want):
            problems.append(f"{path}: {artifact} row {index} ({want.get('player_id')}) differs")
            if len(problems) >= 5:
                break
    return problems


def validate_serving_layout(
    directory: Path,
    envelopes: Mapping[str, Mapping[str, Any]],
    *,
    required: bool = False,
) -> list[QualityCheck]:
    """Prove the served layout on disk is exactly the one the artifacts beside it imply.

    Four things, each a critical failure: the manifest is missing while required; the manifest
    or any served file differs by one byte from a fresh derivation (stale or tampered); a file
    the manifest names is missing or another file sits in ``serve/`` unnamed; a slice does not
    decode to exactly its artifact's matching records.
    """
    manifest_path = directory / MANIFEST_FILENAME
    if not manifest_path.is_file():
        if required:
            return [
                _fail(
                    "serving.manifest_missing",
                    "the site cannot load without data/manifest.json",
                    observed="absent",
                    expected="`ffdraft package-site-data` run after the last artifact write",
                ),
            ]
        return []

    _, metadata = _load_sources(directory)
    layout = build_serving_layout(envelopes, metadata, buckets=_declared_buckets(manifest_path))
    checks: list[QualityCheck] = []
    on_disk = manifest_path.read_bytes()
    if on_disk != _manifest_bytes(layout.manifest):
        checks.append(
            _fail(
                "serving.manifest_stale",
                "data/manifest.json is not the manifest these artifacts imply; re-run "
                "`ffdraft package-site-data` after the last artifact write",
                observed=hashlib.sha256(on_disk).hexdigest()[:HASH_DIGITS],
                expected=hashlib.sha256(_manifest_bytes(layout.manifest)).hexdigest()[:HASH_DIGITS],
            ),
        )

    serve_dir = directory / SERVE_DIRNAME
    present = (
        {path.relative_to(directory).as_posix() for path in serve_dir.rglob("*") if path.is_file()}
        if serve_dir.is_dir()
        else set()
    )
    missing = sorted(set(layout.files) - present)
    extra = sorted(present - set(layout.files))
    if missing:
        checks.append(
            _fail(
                "serving.file_missing",
                "the manifest names served files that are not on disk",
                observed=", ".join(missing[:5]) + (" …" if len(missing) > 5 else ""),
                expected="every named file present",
            ),
        )
    if extra:
        checks.append(
            _fail(
                "serving.file_unlisted",
                "serve/ holds files no manifest names (a stale or foreign layout)",
                observed=", ".join(extra[:5]) + (" …" if len(extra) > 5 else ""),
                expected="exactly the files the manifest names",
            ),
        )
    differing = [
        path
        for path in sorted(set(layout.files) & present)
        if (directory / path).read_bytes() != layout.files[path]
    ]
    if differing:
        checks.append(
            _fail(
                "serving.file_differs",
                "a served file is not byte-identical to its derivation from the artifacts",
                observed=", ".join(differing[:5]),
                expected="byte-identical",
            ),
        )

    # The lossless proof: decode every table without the encoder's help.
    decoded_families: dict[str, list[dict[str, Any]]] = {}
    problems: list[str] = []
    ordered = sorted(
        layout.files,
        key=lambda path: (layout.provenance[path][0] != "ros_tiers", path),
    )
    names = json.loads(layout.files[_players_path(layout)].decode("utf-8"))["names"]
    for path in ordered:
        try:
            kind, found = _decode_served(layout, path, layout.files[path], decoded_families)
            problems.extend(found)
            if kind not in ("players", "card"):
                payload = json.loads(layout.files[path].decode("utf-8"))
                if payload.get("join") is None:
                    decoded_families[f"{kind}/{payload['partition']}"] = decode_table(
                        payload,
                        envelope=layout.manifest["artifacts"][payload["artifact"]],
                        names=names,
                    )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            problems.append(f"{path}: does not decode ({type(exc).__name__}: {exc})")
    problems.extend(_coverage_problems(layout, envelopes))
    problems.extend(_schema_problems(layout))
    if problems:
        checks.append(
            _fail(
                "serving.slice_not_subset",
                "a served file does not decode to exactly its artifact's matching records",
                observed="; ".join(problems[:5]) + (" …" if len(problems) > 5 else ""),
                expected="every decoded record serializes exactly as its source record",
            ),
        )
    if not checks:
        checks.append(
            QualityCheck.ok(
                "serving.layout_exact",
                stage="artifacts.serving",
                message=(
                    f"{len(layout.files)} served files, each byte-identical to its derivation "
                    "and each decoding to exactly its artifact subset"
                ),
            ),
        )
    return checks


def _coverage_problems(
    layout: ServingLayout,
    envelopes: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """Every source record is served by its family (and each card row by exactly one shard)."""
    problems: list[str] = []
    for family in FAMILIES:
        envelope = envelopes.get(family.artifact)
        if envelope is None:
            continue
        served = sum(
            len(provenance[2])
            for provenance in layout.provenance.values()
            if provenance[0] == family.name
        )
        total = len(envelope.get("records", ()))
        if served != total:
            problems.append(f"{family.name}: {served} of {total} records served")
    return problems


def _schema_problems(layout: ServingLayout) -> list[str]:
    """The manifest and every served file against `schemas/serving_*.schema.json`."""
    from ffdraft.artifacts.schemas import validator_for

    problems = [
        f"manifest.json: {error.message}"
        for error in validator_for("serving_manifest").iter_errors(layout.manifest)
    ]
    file_validator = validator_for("serving_file")
    for path, data in layout.files.items():
        for error in file_validator.iter_errors(json.loads(data.decode("utf-8"))):
            problems.append(f"{path}: {error.message}")
            break
    return problems


def _declared_buckets(manifest_path: Path) -> int:
    try:
        declared = json.loads(manifest_path.read_text(encoding="utf-8")).get("card_buckets")
    except (OSError, ValueError):
        return CARD_BUCKETS
    return declared if isinstance(declared, int) and declared > 0 else CARD_BUCKETS


# --------------------------------------------------------------------------------- report


#: GitHub Pages compresses JSON, JavaScript and CSS with zlib at level 5: re-compressing the
#: served artifacts at level 5 reproduces the ``Content-Length`` the edge sent, to the byte
#: (docs/OPERATIONS.md section 17). Every size this project reports uses the same level.
PAGES_GZIP_LEVEL = 5


def gzip_size(data: bytes) -> int:
    """Bytes on the wire when GitHub Pages serves ``data`` (level-5 gzip, no filename)."""
    return len(gzip.compress(data, compresslevel=PAGES_GZIP_LEVEL, mtime=0))


def serving_report(directory: Path) -> dict[str, Any]:
    """Raw and gzip sizes of the served layout, by family, for the refresh summary."""
    manifest_path = directory / MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    families: dict[str, dict[str, int]] = {}
    for key, digest in manifest["files"].items():
        data = (directory / SERVE_DIRNAME / f"{key}.{digest}.json").read_bytes()
        family = key.split("/", 1)[0]
        entry = families.setdefault(family, {"files": 0, "raw": 0, "gzip": 0, "max_gzip": 0})
        size = gzip_size(data)
        entry["files"] += 1
        entry["raw"] += len(data)
        entry["gzip"] += size
        entry["max_gzip"] = max(entry["max_gzip"], size)
    manifest_bytes = manifest_path.read_bytes()
    return {
        "manifest": {"raw": len(manifest_bytes), "gzip": gzip_size(manifest_bytes)},
        "families": dict(sorted(families.items())),
        "files": len(manifest["files"]),
    }


def iter_family_keys(manifest: Mapping[str, Any], family: str) -> Iterable[str]:
    prefix = f"{family}/"
    return (key for key in manifest["files"] if key.startswith(prefix))
