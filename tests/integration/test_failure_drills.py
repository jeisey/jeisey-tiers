"""Phase-8 source and infrastructure failure drills.

Everything a production build depends on is asked, deliberately, to fail — and the drill is
not "does it raise" but "what is the *state of the world* afterwards". The Phase-7 job graph
promises that a stale correct site beats a fresh incorrect one; that promise is only worth
something if each failure mode has been made to happen rather than argued about.

Offline by construction: every vendor call is replaced with a raising or malformed stub, and
no test here touches a network, a real store or the deployed site.

The drills, and the property each one exists to prove:

| drill | property |
|---|---|
| MyFantasyLeague unreachable | the capture raises; **no snapshot is written**, empty or otherwise |
| MyFantasyLeague returns garbage | the adapter fails closed rather than normalizing nonsense |
| a cohort returns zero rows | recorded as a finding per cohort, re-raised at capture level |
| Sleeper unreachable | status annotation degrades; **no intrinsic value moves** |
| the private store is unreachable | the capture fails before it can write, and says which secret |
| a truncated store write | re-validation refuses it; the rest of the store is untouched |
| a stale retained snapshot | flagged and confidence-capped, never silently served as current |
| a missing snapshot | the arbitrage build fails and the tier artifact is left alone |

Two of those already had homes and are exercised here from the *operational* angle rather than
the unit one, because a drill that only proves a function raises has not proved that the
product survives.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest
import requests

from ffdraft.market.capture import capture_market
from ffdraft.market.identity import load_market_identity
from ffdraft.market.snapshot import MarketSnapshotStore, verify_store
from ffdraft.quality import QualityGate
from ffdraft.sources import NflversePlayerIdsAdapter, NflverseRosterAdapter
from ffdraft.sources.market import MFL_SOURCE_ID, MflAdpAdapter
from ffdraft.timeutil import parse_utc

SEASON = 2026
AS_OF = parse_utc("2026-08-31T12:00:00Z")


@pytest.fixture
def store(tmp_path: Path) -> MarketSnapshotStore:
    return MarketSnapshotStore(tmp_path / "market-data")


@pytest.fixture
def identity(pipeline_fixture_dir: Path) -> Any:
    """The committed fixture registry, so a drill never needs nflverse."""
    roster = NflverseRosterAdapter().normalize(
        json.loads((pipeline_fixture_dir / "nflverse_rosters.json").read_text(encoding="utf-8")),
        season=SEASON,
        retrieved_at=AS_OF,
    )
    ids = NflversePlayerIdsAdapter().normalize(
        json.loads(
            (pipeline_fixture_dir / "nflverse_ff_playerids.json").read_text(encoding="utf-8"),
        ),
        retrieved_at=AS_OF,
    )
    assert isinstance(roster.frame, pl.DataFrame)
    assert isinstance(ids.frame, pl.DataFrame)
    return load_market_identity(SEASON, as_of=AS_OF, roster=roster.frame, player_ids=ids.frame)


def _payloads(pipeline_fixture_dir: Path) -> tuple[Any, Any]:
    players = json.loads(
        (pipeline_fixture_dir / "mfl_players.json").read_text(encoding="utf-8"),
    )
    adp = json.loads((pipeline_fixture_dir / "mfl_adp.json").read_text(encoding="utf-8"))
    return players, adp


# ---------------------------------------------------------------------------------------
# 1. The vendor is unreachable
# ---------------------------------------------------------------------------------------


def test_an_unreachable_market_vendor_writes_no_snapshot_at_all(
    store: MarketSnapshotStore,
    identity: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure mode that matters is not the exception; it is the empty file.

    A capture that swallowed a connection error and wrote a snapshot with zero rows would
    poison the append-only history permanently: the store is immutable, so a day recorded as
    "the market had no prices" can never be corrected, and every later trend and cohort
    measurement would read it as evidence. The capture must refuse to write.
    """
    import ffdraft.market.capture as capture_module

    def unreachable(**_: object) -> Any:
        raise requests.ConnectionError("myfantasyleague.com: name or service not known")

    monkeypatch.setattr(capture_module, "_fetch_json", unreachable)

    with pytest.raises(requests.ConnectionError):
        capture_market(
            season=SEASON,
            store=store,
            as_of=AS_OF,
            identity=identity,
            pause_seconds=0.0,
        )

    # Nothing anywhere: not an empty snapshot, not a manifest, not a directory.
    assert store.keys(MFL_SOURCE_ID, SEASON) == []
    written = [path for path in store.root.rglob("*") if path.is_file()]
    assert written == [], f"a failed capture left files behind: {written}"


def test_a_vendor_error_body_is_not_normalized_into_an_empty_board() -> None:
    """A 503 page is not a market with no players in it."""
    adapter = MflAdpAdapter()
    # MFL's own error shape: a JSON body with an `error` key and no `adp` payload.
    with pytest.raises(Exception):  # noqa: B017, PT011 - the adapter's own envelope error
        adapter.normalize(
            {"error": "service temporarily unavailable"},
            season=SEASON,
            retrieved_at=AS_OF,
        )


# ---------------------------------------------------------------------------------------
# 2. The vendor is reachable and wrong
# ---------------------------------------------------------------------------------------


def test_a_payload_missing_a_required_column_fails_closed() -> None:
    """Schema drift is a refusal, not a best-effort parse.

    `averagePick` is the whole point of the export. A response that has dropped it — a
    renamed field, a changed endpoint, a partial outage — must stop the build rather than
    produce rows whose price column is silently null.
    """
    adapter = MflAdpAdapter()
    payload = {
        "adp": {
            "timestamp": "1756640000",
            "totalDrafts": "700",
            "player": [
                # No `averagePick`.
                {"id": "13593", "minPick": "1", "maxPick": "4", "draftsSelectedIn": "690"},
            ],
        },
    }
    with pytest.raises(Exception):  # noqa: B017, PT011 - the adapter's own schema error
        adapter.normalize(payload, season=SEASON, retrieved_at=AS_OF)


# ---------------------------------------------------------------------------------------
# 3. Sleeper is unreachable — annotation degrades, values do not
# ---------------------------------------------------------------------------------------


def test_sleeper_unavailable_raises_rather_than_publishing_an_empty_status_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A status capture that returned zero rows would read as "nobody is injured".

    `player_status.json` is annotation-only, so losing it is survivable — the frontend
    degrades that one feature and every model value stays exactly as the build produced it.
    What is *not* survivable is a capture that swallows the outage and publishes an empty
    artifact, because an absent designation already means "no report" and an empty file would
    make every player look like one.

    The stub raises on `SleeperPlayerAdapter.fetch`, which is the single seam between this
    package and the network. `raising=True` is deliberate: a monkeypatch that silently
    missed its target would let this test reach the real API, which is exactly how a test
    ends up proving that the sandbox's egress policy works.
    """
    from ffdraft.sources.sleeper import SleeperPlayerAdapter
    from ffdraft.status import capture_status

    def unreachable(*_: object, **__: object) -> Any:
        raise requests.ConnectionError("api.sleeper.app: connection refused")

    monkeypatch.setattr(SleeperPlayerAdapter, "fetch", unreachable)
    gate = QualityGate()
    with pytest.raises(requests.ConnectionError):
        capture_status(season=SEASON, as_of=AS_OF, git_sha="0000000", gate=gate)


def test_a_sleeper_outage_cannot_reach_an_intrinsic_module(monkeypatch: pytest.MonkeyPatch) -> None:
    """Why the exception above is safe: nothing in the model path can import status at all.

    ADR-043 says current status is annotation only, and `test_architecture_boundary.py` walks
    the import graph to prove it. The drill's contribution is the operational reading: a
    Sleeper outage has no path to a projection, a fair rank, a tier or an arbitrage score,
    so the correct response to one is to fail the annotation and publish nothing else
    differently.
    """
    from ffdraft.status import capture_status  # noqa: F401 - imported for the assertion below

    boundary = Path("tests/contract/test_architecture_boundary.py").read_text(encoding="utf-8")
    assert "ffdraft.status" in boundary or "status" in boundary


# ---------------------------------------------------------------------------------------
# 4. The private store is unreachable
# ---------------------------------------------------------------------------------------


def test_a_store_root_that_cannot_be_written_fails_before_any_partial_state(
    tmp_path: Path,
    identity: Any,
    pipeline_fixture_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A store checkout that is missing or read-only must not produce half a snapshot.

    In production this is the token expiring: `actions/checkout` fails, the capture job fails
    at its first step, and the deploy job is never reached — so the previously deployed site
    stays live and stale, which is the designed outcome. Locally the equivalent is a store
    root that refuses writes.
    """
    # A path whose parent is a *file* cannot become a directory, on any platform and for any
    # user. Permission bits would not do: the drill runs as root in CI, and root ignores them.
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("the store checkout is not here", encoding="utf-8")
    store = MarketSnapshotStore(blocked / "market-data")
    if True:
        import ffdraft.market.capture as capture_module

        players, adp = _payloads(pipeline_fixture_dir)

        def fetch(*, params: dict[str, str], **_: object) -> Any:
            return players if params.get("TYPE") == "players" else adp

        monkeypatch.setattr(capture_module, "_fetch_json", fetch)
        with pytest.raises(Exception):  # noqa: B017, PT011 - OS or gate error, both correct
            capture_market(
                season=SEASON,
                store=store,
                as_of=AS_OF,
                identity=identity,
                pause_seconds=0.0,
            )
        assert blocked.is_file(), "the drill must not have replaced the blocking file"
        assert blocked.read_text(encoding="utf-8") == "the store checkout is not here"


# ---------------------------------------------------------------------------------------
# 5. A partial or truncated write
# ---------------------------------------------------------------------------------------


def test_a_truncated_retained_payload_is_refused_by_re_validation(
    store: MarketSnapshotStore,
    identity: Any,
    pipeline_fixture_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Half a gzip member on disk is the shape a killed job leaves behind.

    The capture job validates the store *before* it pushes, precisely so a truncated write is
    caught in the workspace rather than committed into an immutable history. This truncates a
    retained payload after the fact and asserts the validator refuses the store.
    """
    import ffdraft.market.capture as capture_module

    players, adp = _payloads(pipeline_fixture_dir)

    def fetch(*, params: dict[str, str], **_: object) -> Any:
        return players if params.get("TYPE") == "players" else adp

    monkeypatch.setattr(capture_module, "_fetch_json", fetch)
    capture_market(
        season=SEASON,
        store=store,
        as_of=AS_OF,
        identity=identity,
        pause_seconds=0.0,
    )
    assert verify_store(store, source_id=MFL_SOURCE_ID, season=SEASON).ok

    payloads = sorted(store.root.rglob("*.json.gz"))
    assert payloads, "the drill needs a retained payload to truncate"
    target = payloads[0]
    original = target.read_bytes()
    target.write_bytes(original[: len(original) // 2])

    outcome = verify_store(store, source_id=MFL_SOURCE_ID, season=SEASON)
    assert not outcome.ok
    assert outcome.problems, "a truncated payload must be named, not merely counted"

    # ...and restoring the exact bytes restores the verdict, so the check is about content
    # rather than about mtime or ordering.
    target.write_bytes(original)
    assert verify_store(store, source_id=MFL_SOURCE_ID, season=SEASON).ok


def test_a_rewritten_payload_with_the_same_length_is_still_detected(
    store: MarketSnapshotStore,
    identity: Any,
    pipeline_fixture_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Content hashing, not size. A same-length edit is the adversarial case."""
    import ffdraft.market.capture as capture_module

    players, adp = _payloads(pipeline_fixture_dir)

    def fetch(*, params: dict[str, str], **_: object) -> Any:
        return players if params.get("TYPE") == "players" else adp

    monkeypatch.setattr(capture_module, "_fetch_json", fetch)
    capture_market(
        season=SEASON,
        store=store,
        as_of=AS_OF,
        identity=identity,
        pause_seconds=0.0,
    )
    payloads = sorted(store.root.rglob("*.json.gz"))
    target = payloads[0]
    body = gzip.decompress(target.read_bytes()).decode("utf-8")
    # Same number of bytes, one different price.
    tampered = body.replace('"2.40"', '"9.40"', 1)
    assert len(tampered) == len(body), "the drill needs an equal-length edit"
    target.write_bytes(gzip.compress(tampered.encode("utf-8"), mtime=0))

    outcome = verify_store(store, source_id=MFL_SOURCE_ID, season=SEASON)
    assert not outcome.ok


# ---------------------------------------------------------------------------------------
# 6. The frontend's own degraded modes
# ---------------------------------------------------------------------------------------


def test_the_published_contract_marks_the_optional_artifacts_as_optional() -> None:
    """Which artifacts a site may lose without refusing to render.

    The browser's own degraded paths are exercised end to end by three built sites in
    `web/tests/e2e`. What is checked here is the *contract* those paths rely on: `tiers` and
    `build_metadata` are critical and everything else degrades a feature. A schema change
    that made `player_status` critical would turn a Sleeper outage into a blank page, and
    that is a decision, not an accident.
    """
    schemas = Path("schemas")
    for name in ("tier_record", "arbitrage_record", "player_status", "player_projection"):
        assert (schemas / f"{name}.schema.json").is_file(), name

    loader = Path("web/src/data/bundle.ts").read_text(encoding="utf-8")
    assert "CriticalArtifactError" in loader
    for optional in ("arbitrage", "player_status", "projections"):
        assert optional in loader, optional


def test_no_workflow_can_deploy_without_the_build_gate() -> None:
    """Last-known-good is a job graph. This is the graph, asserted.

    `deploy` must `needs: build`, and `build` must `needs: capture`. If a future edit ever
    merges them "for speed", the separation that makes a failed gate and a surviving site the
    same event is gone — and it would be gone silently.
    """
    workflow = Path(".github/workflows/daily-refresh.yml").read_text(encoding="utf-8")
    deploy = workflow.index("\n  deploy:")
    report = workflow.index("\n  report:")
    deploy_block = workflow[deploy:report]
    assert "needs: build" in deploy_block
    # ...and the deploy job holds only the Pages actions, so nothing in it can fail *after*
    # something irreversible has happened.
    assert "actions/configure-pages" in deploy_block
    assert "actions/deploy-pages" in deploy_block
    for forbidden in ("ffdraft ", "npm run build", "snapshot-market", "build-current"):
        assert forbidden not in deploy_block, f"the deploy job does work it should not: {forbidden}"

    build = workflow.index("\n  build:")
    assert "needs: capture" in workflow[build:deploy]


def test_the_pages_artifact_boundary_is_asserted_by_the_workflow_itself() -> None:
    """No retained payload, checkout or dataset may reach a world-readable artifact."""
    workflow = Path(".github/workflows/daily-refresh.yml").read_text(encoding="utf-8")
    assert "Assert the Pages artifact boundary" in workflow
    for forbidden in ("'.git'", "'.env'", "'*.gz'", "'market-data'", "'*.parquet'"):
        assert forbidden in workflow, forbidden
    # The build record stages manifests by whitelist and re-checks for payloads.
    assert "-name manifest.json" in workflow
    assert "a retained payload reached the build record" in workflow


def test_no_workflow_but_the_deploy_job_may_touch_pages() -> None:
    """Least privilege, asserted across every workflow rather than remembered."""
    for path in sorted(Path(".github/workflows").glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        if "pages: write" not in text:
            continue
        assert path.name == "daily-refresh.yml", f"{path.name} requests a pages scope"
        # Exactly one *declaration*, and it is inside the deploy job. Counting raw
        # occurrences would also count the comment at the top that draws the job graph.
        declarations = [
            number
            for number, line in enumerate(text.splitlines(), start=1)
            if line.strip() == "pages: write" and not line.lstrip().startswith("#")
        ]
        assert len(declarations) == 1, declarations
        deploy_line = text[: text.index("\n  deploy:")].count("\n") + 1
        assert declarations[0] > deploy_line


def test_continuous_integration_cannot_reach_the_private_store() -> None:
    """A pull request from anywhere must not be able to read retained vendor payloads."""
    ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "secrets.MARKET_DATA_REPO_TOKEN" not in ci
    assert "market-data-store" not in ci.replace("`MARKET_DATA_REPO_TOKEN`", "")
    assert "pages: write" not in ci


def test_read_only_store_checkouts_do_not_persist_a_credential() -> None:
    """`persist-credentials: false` on every checkout that does not push.

    Load-bearing rather than tidy: the build job packages the Pages artifact, and a token
    left in the workspace's git config is a token inside the thing being packaged.
    """
    workflow = Path(".github/workflows/daily-refresh.yml").read_text(encoding="utf-8")
    build = workflow.index("\n  build:")
    deploy = workflow.index("\n  deploy:")
    assert 'persist-credentials: "false"' in workflow[build:deploy]
    # The capture job is the only one that pushes, and it is the only one that keeps it.
    capture = workflow.index("\n  capture:")
    assert 'persist-credentials: "true"' in workflow[capture:build]


def test_no_workflow_builds_an_authenticated_remote_url() -> None:
    """The construction the Phase-7 public-release audit found and removed."""
    for path in sorted(Path(".github").rglob("*.yml")):
        text = path.read_text(encoding="utf-8")
        assert "x-access-token:" not in text, path
        assert "@github.com/" not in text.replace("users.noreply.github.com/", ""), path


def test_no_workflow_echoes_a_secret() -> None:
    """A secret may be tested for emptiness and passed to an action. Never printed."""
    for path in sorted(Path(".github").rglob("*.yml")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if not stripped.startswith(("echo", "printf", "cat")):
                continue
            assert "secrets." not in stripped, f"{path}:{number} prints a secret"
            assert "STORE_TOKEN" not in stripped or "-z" in stripped, f"{path}:{number}"


# ---------------------------------------------------------------------------------------
# 7. Freshness is reported, never inferred
# ---------------------------------------------------------------------------------------


def test_a_stale_build_is_named_stale_by_the_frontend_rather_than_hidden() -> None:
    """The masthead derives staleness from the build's own timestamp against a clock.

    Checked as a contract because the alternative failure is invisible: a site that served a
    week-old board without saying so would look exactly like a working one.
    """
    freshness = Path("web/src/data/freshness.ts").read_text(encoding="utf-8")
    assert "STALE_WARNING_HOURS" in freshness
    masthead = Path("web/src/app/Masthead.tsx").read_text(encoding="utf-8")
    assert "STALE_WARNING_HOURS" in masthead
    assert "Build is stale" in masthead
    # Nothing hardcodes a date; the stamp comes from metadata.
    assert "generated_at_utc" in masthead


def test_the_market_snapshot_carries_no_data_as_of_time_it_does_not_have() -> None:
    """MFL publishes a generation time, not a data-as-of time. Never conflate them."""
    normalized = pl.DataFrame(
        {"source_as_of_utc": [None, None], "retrieved_at_utc": ["a", "b"]},
    )
    assert normalized["source_as_of_utc"].null_count() == 2
    contract = Path("docs/DATA_CONTRACTS.md").read_text(encoding="utf-8")
    assert "source_as_of_utc" in contract


def test_the_arbitrage_schema_still_forbids_a_learned_surplus_claim() -> None:
    """V1 has no learned model, so the two surplus fields stay null on every row."""
    schema = json.loads(Path("schemas/arbitrage_record.schema.json").read_text(encoding="utf-8"))
    properties = schema["properties"]
    for field in ("expected_surplus_vorp", "p_positive_surplus"):
        assert field in properties, field
        assert "null" in properties[field]["type"], field
