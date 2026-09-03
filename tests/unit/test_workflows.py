"""The Phase-7 workflow invariants, pinned as tests rather than as comments.

Four properties in `.github/` are load-bearing enough that noticing a regression in code
review is not good enough:

1. **Ordinary pull-request CI cannot reach a vendor or the private data repository.** A fork
   that opens a pull request runs `ci.yml`; it must not be able to ask for the retained-store
   credential, and a MyFantasyLeague outage must not turn into a red pull request.
2. **A deploy can only happen downstream of every gate.** Last-known-good is a job graph, and
   a graph is checkable.
3. **Retraining cannot promote or deploy.** The 2025 holdout is spent (ADR-036); a scheduled
   job must not be able to write a production model or publish a page.
4. **The private repository's address exists in exactly one place.** `config/source-registry.
   yaml` records it and `.github/actions/market-data-store` reads it, so a move is one edit
   rather than a search.
5. **The deployed-site smoke observes and never acts.** `live-smoke.yml` was added for the
   Phase-9B release checklist and reads a public URL. It must stay outside the production job
   graph: no `pages:` scope, no store credential, no write anywhere.
6. **The release workflow can create a tag and nothing else.** `release.yml` holds the only
   `contents: write` outside a capture job, so it must not be able to deploy, to touch the
   store, or to tag code that is not on `main`.
7. **Ordinary CI cross-checks the rendered board against the artifact bytes.** That gate used
   to run only against a production build, which is a gate discovering a frontend mistake one
   deploy too late.
"""

from __future__ import annotations

import re

import pytest
import yaml

WORKFLOWS = (
    "ci.yml",
    "daily-refresh.yml",
    "retrain.yml",
    "market-capture.yml",
    "live-smoke.yml",
    "release.yml",
)

#: Hosts a production workflow may contact. Ordinary CI may contact none of them.
VENDOR_HOSTS = (
    "api.myfantasyleague.com",
    "api.sleeper.app",
    "nflverse-data",
)


@pytest.fixture
def workflow_dir(repo_root):
    return repo_root / ".github" / "workflows"


def _code(path) -> str:
    """The workflow with its comment lines removed.

    These tests are about what a workflow *does*, and every file here explains in prose what
    it deliberately does not do. Scanning the comments too would make a file fail for
    documenting the very property under test.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if not line.lstrip().startswith("#"))


def _load(path):
    # `on:` is parsed by PyYAML 1.1 semantics as the boolean True; read it back either way.
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if True in document:
        document["on"] = document.pop(True)
    return document


@pytest.fixture
def workflows(workflow_dir):
    return {name: _load(workflow_dir / name) for name in WORKFLOWS}


# --- 1. Pull-request CI is vendor-independent and store-independent ------------------------


def test_ci_never_reads_the_retained_store_credential(workflow_dir):
    """A pull request from anywhere runs ci.yml. It must not be able to reach private data."""
    text = _code(workflow_dir / "ci.yml")
    assert "MARKET_DATA_REPO_TOKEN" not in text
    assert "market-data-store" not in text


def test_ci_contacts_no_vendor(workflow_dir):
    text = _code(workflow_dir / "ci.yml")
    for host in VENDOR_HOSTS:
        assert host not in text, f"ci.yml references {host}; PR CI must stay offline"
    for command in ("snapshot-market", "capture-status", "build-current", "build-historical"):
        assert command not in text, f"ci.yml runs {command}, which needs live vendor access"


def test_ci_is_read_only_everywhere(workflows):
    ci = workflows["ci.yml"]
    assert ci["permissions"] == {"contents": "read"}
    for name, job in ci["jobs"].items():
        permissions = job.get("permissions")
        assert permissions in (None, {"contents": "read"}), (
            f"ci.yml job {name} elevates permissions to {permissions}"
        )


def test_ci_cannot_deploy(workflows):
    ci = workflows["ci.yml"]
    assert "pages" not in yaml.safe_dump(ci.get("permissions", {}))
    for job in ci["jobs"].values():
        assert "pages" not in yaml.safe_dump(job.get("permissions") or {})


def test_ci_verifies_the_rendered_board_against_the_artifact_bytes(workflow_dir):
    """The board-versus-bytes check has to run where the change is made, not in production.

    `verify:board` lived only in `daily-refresh.yml` and `live-smoke.yml` until the
    2026-09-03 refresh failed on it: Phase 10 inserted three arbitrage columns, the verifier
    was still counting cells, and nothing between the pull request and the production build
    could have caught it. Both builds are named here because only the matured-market fixture
    carries a non-null `market_trend` - dropping it would leave the Trend column unexercised
    while the step still looked present.
    """
    text = _code(workflow_dir / "ci.yml")
    assert "verify:board" in text, "ci.yml no longer cross-checks the rendered board"
    assert "web/dist-matured" in text, (
        "ci.yml runs verify:board only against the launch-condition build, where every "
        "market_trend is null, so the Trend column would go unchecked"
    )


def test_no_workflow_uses_pull_request_target(workflow_dir):
    """docs/SECURITY_LICENSE.md section 3: never run untrusted code with a write token."""
    for path in workflow_dir.glob("*.yml"):
        assert "pull_request_target" not in _code(path), path.name


# --- 2. The daily refresh's last-known-good job graph --------------------------------------


def test_deploy_is_downstream_of_capture_and_build(workflows):
    jobs = workflows["daily-refresh.yml"]["jobs"]
    assert jobs["build"]["needs"] == "capture"
    assert jobs["deploy"]["needs"] == "build"
    # Nothing may reorder these into one job: the point is that a failed gate leaves the
    # deploy job unreached rather than half-run.
    assert "deploy-pages" not in yaml.safe_dump(jobs["build"])
    assert "upload-pages-artifact" not in yaml.safe_dump(jobs["deploy"])


def test_only_the_deploy_job_holds_a_pages_scope(workflows):
    jobs = workflows["daily-refresh.yml"]["jobs"]
    assert workflows["daily-refresh.yml"]["permissions"] == {"contents": "read"}
    assert jobs["deploy"]["permissions"] == {
        "contents": "read",
        "pages": "write",
        "id-token": "write",
    }
    for name in ("capture", "build", "report"):
        assert jobs[name]["permissions"] == {"contents": "read"}, name


def test_the_deploy_job_uses_the_pages_environment(workflows):
    deploy = workflows["daily-refresh.yml"]["jobs"]["deploy"]
    assert deploy["environment"]["name"] == "github-pages"


def test_the_capture_job_needs_no_write_scope_on_this_repository(workflows):
    """It writes to a different repository, through a token scoped to that repository."""
    capture = workflows["daily-refresh.yml"]["jobs"]["capture"]
    assert capture["permissions"] == {"contents": "read"}


def test_a_production_refresh_is_never_cancelled(workflows):
    """Cancelling between commit and push would drop a validated snapshot on the floor."""
    concurrency = workflows["daily-refresh.yml"]["concurrency"]
    assert concurrency["group"] == "production-refresh"
    assert concurrency["cancel-in-progress"] is False
    deploy = workflows["daily-refresh.yml"]["jobs"]["deploy"]["concurrency"]
    assert deploy["cancel-in-progress"] is False


def test_the_daily_schedule_is_off_the_hour_in_new_york(workflows):
    schedule = workflows["daily-refresh.yml"]["on"]["schedule"]
    assert len(schedule) == 1
    entry = schedule[0]
    minute, hour = entry["cron"].split()[:2]
    assert (minute, hour) == ("17", "7"), entry["cron"]
    assert minute != "0", "an on-the-hour schedule is the one GitHub documents as delayed"
    assert entry["timezone"] == "America/New_York"


def test_the_forced_failure_flag_is_unreachable_from_the_schedule(workflow_dir):
    text = _code(workflow_dir / "daily-refresh.yml")
    assert "force_validation_failure" in text
    guard = "github.event_name == 'workflow_dispatch' && inputs.force_validation_failure == true"
    assert guard in text, "the proof step must assert the dispatch event, not only the input"


def test_the_refresh_does_not_retrain(workflow_dir):
    """Daily = capture + inference + market comparison + build. Never training."""
    text = _code(workflow_dir / "daily-refresh.yml")
    for command in ("train-production", "evaluate-intrinsic", "build-historical"):
        assert command not in text, f"daily-refresh.yml runs {command}"


# --- 3. Retraining cannot promote or deploy -------------------------------------------------


def test_retrain_cannot_deploy_or_promote(workflows, workflow_dir):
    retrain = workflows["retrain.yml"]
    assert retrain["permissions"] == {"contents": "read"}
    for name, job in retrain["jobs"].items():
        assert job["permissions"] == {"contents": "read"}, name
    text = _code(workflow_dir / "retrain.yml")
    for forbidden in ("deploy-pages", "upload-pages-artifact", "configure-pages", "pages: write"):
        assert forbidden not in text, f"retrain.yml references {forbidden}"
    # `train-production` refuses to run without a confirmation token and a written reason.
    # That token must never become a repository secret, so the command must never be
    # *invoked* here. The workflow's summary is free to name it — telling a reader what the
    # promotion path is happens to be the point — so the check is on the invocation form
    # every other command in these workflows uses.
    assert "uv run ffdraft train-production" not in text
    assert "RELEASE-FINAL-HOLDOUT" not in text
    assert "git push" not in text


def test_retrain_is_gated_on_evidence_not_on_the_calendar(workflows):
    candidate = workflows["retrain.yml"]["jobs"]["candidate"]
    assert candidate["needs"] == "gate"
    assert "needs.gate.outputs.should_retrain == 'true'" in candidate["if"]


# --- 3b. The deployed-site smoke observes and never acts ------------------------------------


def test_live_smoke_cannot_deploy_or_write(workflows, workflow_dir):
    """It reads a public URL. Nothing about that needs a scope beyond `contents: read`."""
    smoke = workflows["live-smoke.yml"]
    assert smoke["permissions"] == {"contents": "read"}
    for name, job in smoke["jobs"].items():
        permissions = job.get("permissions") or {}
        assert "pages" not in permissions, f"live-smoke.yml job {name} asks for a pages scope"
        assert "write" not in yaml.safe_dump(permissions), (
            f"live-smoke.yml job {name} elevates permissions to {permissions}"
        )
    text = _code(workflow_dir / "live-smoke.yml")
    for forbidden in ("deploy-pages", "upload-pages-artifact", "configure-pages", "git push"):
        assert forbidden not in text, f"live-smoke.yml references {forbidden}"


def test_live_smoke_needs_no_credential_and_no_vendor(workflow_dir):
    """Everything it compares against is downloaded from the public site itself."""
    text = _code(workflow_dir / "live-smoke.yml")
    assert "MARKET_DATA_REPO_TOKEN" not in text
    assert "secrets." not in text
    for host in VENDOR_HOSTS:
        assert host not in text, f"live-smoke.yml references {host}"


def test_live_smoke_is_not_in_the_production_job_graph(workflows):
    """It gates nothing, so it must not be scheduled and must not be `needs:`-ed by a deploy."""
    smoke = workflows["live-smoke.yml"]
    assert set(smoke["on"]) == {"workflow_dispatch"}, (
        "live-smoke.yml must run only on dispatch; a schedule would make an observation "
        "look like a gate"
    )
    for workflow in ("daily-refresh.yml", "ci.yml"):
        assert "live-smoke" not in yaml.safe_dump(workflows[workflow])


# --- 3c. The release workflow tags merged code, and does nothing else -----------------------


def test_release_cannot_deploy_or_build(workflows, workflow_dir):
    """It creates a ref and a release. It must not be able to publish a site or a model."""
    release = workflows["release.yml"]
    assert release["permissions"] == {"contents": "read"}
    job = release["jobs"]["release"]
    assert job["permissions"] == {"contents": "write"}, (
        "release.yml's one job needs exactly contents: write — nothing more"
    )
    text = _code(workflow_dir / "release.yml")
    for forbidden in (
        "deploy-pages",
        "upload-pages-artifact",
        "configure-pages",
        "MARKET_DATA_REPO_TOKEN",
        "snapshot-market",
        "capture-status",
        "build-current",
        "train-production",
    ):
        assert forbidden not in text, f"release.yml references {forbidden}"


def test_release_refuses_a_commit_that_is_not_on_main(workflow_dir):
    """The guard that makes an SHA input safe: a tag may only ever name merged code."""
    text = _code(workflow_dir / "release.yml")
    assert "git merge-base --is-ancestor" in text
    assert "origin/main" in text
    # And it must never move an existing tag.
    assert 'git rev-parse -q --verify "refs/tags/${TAG}"' in text
    assert "fetch-depth: 0" in text, "reachability cannot be checked on a shallow clone"


def test_release_is_dispatch_only(workflows):
    """A schedule or a push trigger would make a tag an accident rather than a decision."""
    assert set(workflows["release.yml"]["on"]) == {"workflow_dispatch"}


# --- 4. One address for the private store ---------------------------------------------------


def test_the_private_repository_literal_lives_only_in_the_registry(repo_root):
    literal = "jeisey-tiers-market-data"
    offenders = []
    for path in sorted((repo_root / ".github").rglob("*.yml")):
        if literal in _code(path):
            offenders.append(path.relative_to(repo_root).as_posix())
    assert offenders == [], (
        f"the store address is duplicated in {offenders}; it belongs in "
        "config/source-registry.yaml, which .github/actions/market-data-store reads"
    )


def test_every_store_checkout_goes_through_the_shared_action(workflow_dir):
    for path in sorted(workflow_dir.glob("*.yml")):
        text = _code(path)
        if "MARKET_DATA_REPO_TOKEN" not in text:
            continue
        # The token may appear only as an input to the shared action, never in a shell block
        # that could build an authenticated URL.
        for match in re.finditer(r"MARKET_DATA_REPO_TOKEN", text):
            line_start = text.rfind("\n", 0, match.start()) + 1
            line = text[line_start : text.find("\n", match.start())]
            assert line.strip().startswith("token:"), (
                f"{path.name} uses MARKET_DATA_REPO_TOKEN outside the shared action: {line!r}"
            )
        assert "./.github/actions/market-data-store" in text, path.name


def test_the_shared_action_reads_the_registry_rather_than_a_literal(repo_root):
    action = repo_root / ".github" / "actions" / "market-data-store" / "action.yml"
    text = _code(action)
    assert "market_history_repository" in text
    assert "market_history_branch" in text
    assert "jeisey-tiers-market-data" not in text
