"""Workflow security boundaries, asserted over EVERY workflow and composite action.

`tests/unit/test_workflows.py` pins the production job graph of six named workflows, and
`tests/integration/test_failure_drills.py` pins the Phase-8 credential drills. This module
adds the boundaries the 2026-10-02 review (`docs/SECURITY_REVIEW_2026-10-02.md`) found worth
proving structurally, and it reads every file under `.github/` rather than a list, so a new
workflow is covered the day it lands:

1. no trigger that runs with this repository's secrets on behalf of someone without write
   access (`pull_request_target`, `workflow_run`, comment/issue events);
2. a job that names a secret is never reachable from `pull_request`, declares its own
   `permissions:`, and elevates only where the allow-list says it must;
3. `MARKET_DATA_REPO_TOKEN` enters a job only as the `token:` of the shared store action, and
   the credential persists into the checkout only in a job that pushes;
4. no dispatch input, event payload or ref name is expanded inline into a shell (`run:`) — it
   reaches the shell through `env:` (script injection, SR-02);
5. no secret can reach the frontend build (`VITE_*` or the build step's environment);
6. the Pages artifact is `web/dist` and nothing else; no workflow artifact uploads the store;
7. only official `actions/*` or local actions are used, and a credentialed job never restores a
   cache by prefix (`restore-keys`), so a cache hit is always an exact-key hit.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

GITHUB_DIR = Path(__file__).resolve().parents[2] / ".github"
WORKFLOW_FILES = sorted((GITHUB_DIR / "workflows").glob("*.yml"))
ACTION_FILES = sorted((GITHUB_DIR / "actions").glob("*/action.yml"))

STORE_SECRET = "MARKET_DATA_REPO_TOKEN"
STORE_ACTION = "./.github/actions/market-data-store"

#: Triggers that hand this repository's secrets or write token to code or data controlled by
#: someone who cannot push here.
FORBIDDEN_TRIGGERS = {
    "pull_request_target",
    "workflow_run",
    "issue_comment",
    "issues",
    "discussion",
    "discussion_comment",
    "pull_request_review",
    "pull_request_review_comment",
    "fork",
    "watch",
}

#: The only triggers a job that names a secret may run under: each needs write access.
SECRET_SAFE_TRIGGERS = {"workflow_dispatch", "schedule", "push"}

#: Job-level write scopes that are deliberate, by (workflow, job). Anything else is `read`.
ALLOWED_WRITES: dict[tuple[str, str], set[str]] = {
    ("daily-refresh.yml", "deploy"): {"pages", "id-token"},
    ("weekly-v2-prospective.yml", "look"): {"issues"},
    ("release.yml", "release"): {"contents"},
    ("phase10-linkage.yml", "link"): {"contents"},
    ("source-probe.yml", "probe"): {"contents"},
    ("source-probe-weather.yml", "probe"): {"contents"},
}

#: Contexts an actor without push access can influence, or that a writer can make arbitrary
#: (a branch name may contain `$(...)`). None may be expanded inline into a shell.
UNTRUSTED_CONTEXT = re.compile(
    r"\$\{\{[^}]*\b(inputs\.|github\.event\.|github\.head_ref|github\.ref_name)",
)


def _load(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    # PyYAML (YAML 1.1) reads the `on:` key as boolean True.
    if True in document:
        document["on"] = document.pop(True)
    return document


def _triggers(workflow: dict[str, Any]) -> set[str]:
    on = workflow.get("on")
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return set(on)
    return set(on or {})


def _steps(path: Path) -> Iterator[tuple[str, dict[str, Any]]]:
    """Every step of a workflow (as ``job id``) or a composite action (as ``"composite"``)."""
    document = _load(path)
    if "jobs" in document:
        for job_id, job in document["jobs"].items():
            for step in job.get("steps") or []:
                yield job_id, step
    else:
        for step in document.get("runs", {}).get("steps") or []:
            yield "composite", step


def _uses_secret(node: Any) -> bool:
    """Whether a job names a repository secret (the ephemeral `github.token` is not one)."""
    text = yaml.safe_dump(node)
    return re.search(r"secrets\.(?!GITHUB_TOKEN\b)[A-Z0-9_]+", text) is not None


def _workflows() -> list[tuple[Path, dict[str, Any]]]:
    return [(path, _load(path)) for path in WORKFLOW_FILES]


def test_every_workflow_and_action_is_covered():
    assert len(WORKFLOW_FILES) >= 12, [p.name for p in WORKFLOW_FILES]
    assert [p.parent.name for p in ACTION_FILES] == ["market-data-store"]


@pytest.mark.parametrize("path", WORKFLOW_FILES, ids=lambda p: p.name)
def test_no_workflow_runs_privileged_on_behalf_of_an_outsider(path: Path):
    forbidden = _triggers(_load(path)) & FORBIDDEN_TRIGGERS
    assert not forbidden, f"{path.name} uses {sorted(forbidden)}"


@pytest.mark.parametrize("path", WORKFLOW_FILES, ids=lambda p: p.name)
def test_every_workflow_defaults_to_read_only(path: Path):
    permissions = _load(path).get("permissions")
    assert permissions == {"contents": "read"}, f"{path.name}: top-level {permissions!r}"


def test_a_job_that_names_a_secret_cannot_be_reached_from_a_pull_request():
    for path, workflow in _workflows():
        triggers = _triggers(workflow)
        for job_id, job in workflow["jobs"].items():
            if not _uses_secret(job):
                continue
            assert triggers <= SECRET_SAFE_TRIGGERS, (
                f"{path.name}:{job_id} names a secret and runs on {sorted(triggers)}"
            )
            # Explicit, so a later top-level change cannot silently widen a credentialed job.
            assert "permissions" in job, f"{path.name}:{job_id} names a secret without permissions"


def test_job_write_scopes_are_exactly_the_allow_listed_ones():
    seen: set[tuple[str, str]] = set()
    for path, workflow in _workflows():
        for job_id, job in workflow["jobs"].items():
            permissions = job.get("permissions") or {}
            assert isinstance(permissions, dict), f"{path.name}:{job_id}: {permissions!r}"
            writes = {scope for scope, level in permissions.items() if level == "write"}
            allowed = ALLOWED_WRITES.get((path.name, job_id), set())
            assert writes == allowed, f"{path.name}:{job_id} writes {sorted(writes)}"
            if writes:
                seen.add((path.name, job_id))
    assert seen == set(ALLOWED_WRITES), "an allow-listed writer no longer exists; prune the list"


def test_the_store_token_enters_a_job_only_through_the_shared_action():
    for path in [*WORKFLOW_FILES, *ACTION_FILES]:
        for job_id, step in _steps(path):
            if f"secrets.{STORE_SECRET}" not in yaml.safe_dump(step):
                continue
            assert step.get("uses") == STORE_ACTION, f"{path.name}:{job_id} {step.get('name')}"
            assert step["with"]["token"] == f"${{{{ secrets.{STORE_SECRET} }}}}"
            assert "run" not in step and "env" not in step


def test_the_store_credential_persists_only_in_a_job_that_pushes():
    for path, workflow in _workflows():
        for job_id, job in workflow["jobs"].items():
            steps = job.get("steps") or []
            stores = [step for step in steps if step.get("uses") == STORE_ACTION]
            if not stores:
                continue
            pushes = any("git push" in str(step.get("run", "")) for step in steps)
            for store in stores:
                # Explicit either way: the action's default is "false", but a reader of the job
                # should not have to know that to see whether a credential survives.
                persist = store["with"].get("persist-credentials")
                assert persist in ('"true"', "true", '"false"', "false"), (
                    f"{path.name}:{job_id} leaves persist-credentials implicit"
                )
                if str(persist).strip('"') == "true":
                    assert pushes, f"{path.name}:{job_id} keeps a store credential and never pushes"
                else:
                    assert not pushes, f"{path.name}:{job_id} pushes without a credential"


@pytest.mark.parametrize("path", [*WORKFLOW_FILES, *ACTION_FILES], ids=lambda p: p.name)
def test_no_untrusted_context_is_expanded_inline_into_a_shell(path: Path):
    """SR-02. `${{ inputs.x }}` inside `run:` is pasted into the script before bash parses it.

    Through `env:` the same value is data. Dispatch needs write access, so this is defence in
    depth — but the jobs it protects hold the store credential or `contents: write`.
    """
    offenders = [
        f"{job_id}: {step.get('name') or step.get('run', '')[:40]!r}"
        for job_id, step in _steps(path)
        if "run" in step and UNTRUSTED_CONTEXT.search(str(step["run"]))
    ]
    assert not offenders, f"{path.name}: {offenders}"


@pytest.mark.parametrize("name", ["daily-refresh.yml", "market-capture.yml", "phase10-linkage.yml"])
def test_a_season_input_is_validated_before_it_becomes_a_step_output(name: str):
    """Step outputs derived from a dispatch input are expanded inline by later `run:` blocks."""
    steps = {step.get("id"): step for _, step in _steps(GITHUB_DIR / "workflows" / name)}
    planner = next(step for step in steps.values() if "INPUT_SEASON" in (step.get("env") or {}))
    script = planner["run"]
    assert "=~ ^[0-9]{4}$" in script, f"{name}: season is not validated"
    assert script.index("=~ ^[0-9]{4}$") < script.index('"season=${season}"')


def test_no_secret_can_reach_the_frontend_build():
    for path, workflow in _workflows():
        for key, value in (workflow.get("env") or {}).items():
            assert "secrets." not in str(value), f"{path.name}: workflow env {key}"
        for job_id, job in workflow["jobs"].items():
            for key, value in (job.get("env") or {}).items():
                assert "secrets." not in str(value), f"{path.name}:{job_id} job env {key}"
            for step in job.get("steps") or []:
                env = step.get("env") or {}
                for key, value in env.items():
                    if key.startswith("VITE_"):
                        assert "secrets." not in str(value), f"{path.name}:{job_id} {key}"
                run = str(step.get("run", ""))
                if "npm run build" in run or "vite build" in run or "npm ci" in run:
                    assert not any("secrets." in str(v) for v in env.values()), (
                        f"{path.name}:{job_id} builds the frontend with a secret in scope"
                    )


def test_the_pages_artifact_is_web_dist_and_only_web_dist():
    uploads = [
        (path.name, job_id, step)
        for path in WORKFLOW_FILES
        for job_id, step in _steps(path)
        if str(step.get("uses", "")).startswith("actions/upload-pages-artifact@")
    ]
    assert len(uploads) == 1, uploads
    name, job_id, step = uploads[0]
    assert (name, job_id) == ("daily-refresh.yml", "build")
    assert step["with"]["path"] == "web/dist"


def test_no_workflow_artifact_uploads_the_store_or_the_workspace():
    for path in WORKFLOW_FILES:
        for job_id, step in _steps(path):
            if not str(step.get("uses", "")).startswith("actions/upload-artifact@"):
                continue
            paths = [line.strip() for line in str(step["with"]["path"]).splitlines()]
            for entry in paths:
                assert entry and entry not in {".", "./", "*", "**"}, f"{path.name}:{job_id}"
                assert "market-data" not in entry, f"{path.name}:{job_id} uploads {entry}"
                assert ".git" not in entry.split("/"), f"{path.name}:{job_id} uploads {entry}"


def test_only_official_or_local_actions_are_used():
    """The repository convention (docs/SECURITY_LICENSE.md section 4): GitHub's own actions
    at a major tag, plus the local store action. A community action would need a SHA pin and
    a review, which this assertion forces to happen deliberately."""
    for path in [*WORKFLOW_FILES, *ACTION_FILES]:
        for job_id, step in _steps(path):
            uses = step.get("uses")
            if uses is None:
                continue
            assert uses.startswith(("actions/", "./.github/actions/")), (
                f"{path.name}:{job_id} uses {uses}"
            )


def test_a_credentialed_job_never_restores_a_cache_by_prefix():
    for path, workflow in _workflows():
        for job_id, job in workflow["jobs"].items():
            if not _uses_secret(job):
                continue
            for step in job.get("steps") or []:
                if str(step.get("uses", "")).startswith("actions/cache"):
                    assert "restore-keys" not in (step.get("with") or {}), f"{path.name}:{job_id}"
