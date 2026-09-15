"""The nflverse transport policy: bounded patience, and only for transient responses.

`daily-refresh` run 43 (2026-09-15) lost the production refresh to a single HTTP 500 on
``players.parquet``; the same URL served correctly minutes later. These tests pin the
behaviour that makes that survivable and, just as importantly, the behaviour that must not
change with it - a 404 still fails on the first answer, and the budget is finite.

Every test here runs against a loopback server. Nothing reaches a third party, so none of
this is a `live` test (`docs/TEST_STRATEGY.md` section 2.4).
"""

from __future__ import annotations

import io
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import polars as pl
import pytest
import requests
import yaml

from ffdraft.paths import repo_root
from ffdraft.sources.nflverse_http import (
    NFLVERSE_RETRY,
    NflverseRetryPolicy,
    install_retry_policy,
    nflverse_loaders,
)

# The real backoff is ~14 seconds of sleeping, which is the point in production and
# unacceptable in a unit test. Only the waiting is turned off; the counting is not.
IMPATIENT = NflverseRetryPolicy(backoff_factor=0.0)


class _Scripted(BaseHTTPRequestHandler):
    """Answers with the next status in ``statuses``, repeating the last one forever."""

    statuses: list[int] = []
    seen: list[str] = []
    body: bytes = b"payload"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's spelling
        index = min(len(type(self).seen), len(type(self).statuses) - 1)
        type(self).seen.append(self.path)
        status = type(self).statuses[index]
        body = type(self).body if status == 200 else b"nope"
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        """Silence the default stderr access log."""


@pytest.fixture
def scripted_server():
    """Start a loopback server whose reply sequence each test declares."""

    def start(statuses: list[int]) -> tuple[str, type[_Scripted]]:
        handler = type(
            "ScriptedOnce",
            (_Scripted,),
            {"statuses": statuses, "seen": [], "body": b"payload"},
        )
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append((server, thread))
        return f"http://{server.server_address[0]}:{server.server_address[1]}/asset", handler

    servers: list[tuple[ThreadingHTTPServer, threading.Thread]] = []
    yield start
    for server, thread in servers:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _session(policy: NflverseRetryPolicy = IMPATIENT) -> requests.Session:
    session = requests.Session()
    adapter = policy.as_adapter()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def test_a_transient_500_is_survived(scripted_server) -> None:
    """Two 500s then a 200: exactly the shape of run 43's failure, now a success."""
    url, handler = scripted_server([500, 500, 200])

    response = _session().get(url, timeout=5)

    assert response.status_code == 200
    assert response.content == b"payload"
    assert len(handler.seen) == 3


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_every_declared_transient_status_is_retried(scripted_server, status: int) -> None:
    url, handler = scripted_server([status, 200])

    assert _session().get(url, timeout=5).status_code == 200
    assert len(handler.seen) == 2


def test_the_budget_is_finite(scripted_server) -> None:
    """A host that is genuinely down still fails, after a countable number of attempts."""
    url, handler = scripted_server([503])

    with pytest.raises(requests.exceptions.RetryError):
        _session().get(url, timeout=5)

    assert len(handler.seen) == IMPATIENT.max_attempts


def test_a_404_is_answered_once(scripted_server) -> None:
    """nflverse publishes per-season files; an unpublished season is a fact, not a blip.

    Retrying it would turn every legitimate "not released yet" into a stall, and would
    delay the one signal that says a source contract moved.
    """
    url, handler = scripted_server([404, 200])

    assert _session().get(url, timeout=5).status_code == 404
    assert len(handler.seen) == 1


def test_the_policy_reaches_nflreadpys_own_session() -> None:
    """The mount lands on the session every nflverse loader downloads through."""
    from nflreadpy.downloader import get_downloader

    install_retry_policy(NFLVERSE_RETRY, force=True)
    session = get_downloader().session

    for scheme in ("https://", "http://"):
        retries = session.get_adapter(scheme).max_retries
        assert retries.total == NFLVERSE_RETRY.retries
        assert tuple(retries.status_forcelist) == NFLVERSE_RETRY.retry_statuses
        assert retries.backoff_factor == NFLVERSE_RETRY.backoff_factor
        assert 404 not in retries.status_forcelist


def test_installing_twice_is_a_no_op() -> None:
    install_retry_policy(NFLVERSE_RETRY, force=True)
    assert install_retry_policy(NFLVERSE_RETRY) is False


def test_the_loader_accessor_hands_back_a_configured_nflreadpy() -> None:
    """Call sites ask for loaders, not for a module plus a reminder to configure it."""
    from nflreadpy.downloader import get_downloader

    nflreadpy = nflverse_loaders()

    assert hasattr(nflreadpy, "load_players")
    mounted = get_downloader().session.get_adapter("https://").max_retries
    assert mounted.total == NFLVERSE_RETRY.retries


def test_the_registry_states_the_same_budget_the_code_applies() -> None:
    """`AGENTS.md` section 18: a source adapter and its registry entry move together."""
    registry = yaml.safe_load(
        (repo_root() / "config" / "source-registry.yaml").read_text(encoding="utf-8"),
    )
    declared = registry["sources"]["nflreadpy"]["client_settings"]["retry"]

    assert declared["retries"] == NFLVERSE_RETRY.retries
    assert declared["backoff_factor"] == NFLVERSE_RETRY.backoff_factor
    assert tuple(declared["retry_statuses"]) == NFLVERSE_RETRY.retry_statuses
    assert declared["never_retried"] == [404]
    assert not set(declared["never_retried"]) & set(NFLVERSE_RETRY.retry_statuses)


def test_no_module_imports_nflreadpy_around_the_policy() -> None:
    """A direct `import nflreadpy` is a download with no retry budget, so there are none.

    The accessor is only a policy if it is the single way in; `ffdraft.sources.nflverse_http`
    is where the import lives, and Phase-0's `scripts/source_probe.py` is deliberately
    outside it because a probe measures raw upstream behaviour.
    """
    package = repo_root() / "src" / "ffdraft"
    offenders = [
        path.relative_to(repo_root())
        for path in package.rglob("*.py")
        if path.name != "nflverse_http.py"
        and any(
            line.strip() in {"import nflreadpy", "import nflreadpy as nfl"}
            for line in path.read_text(encoding="utf-8").splitlines()
        )
    ]

    assert offenders == []


# --------------------------------------------------------------------------------------
# The production call path
#
# Everything above proves the policy, mounted on a session, behaves. This proves the
# session it is mounted on is the one `nflreadpy.load_*` actually downloads through, by
# driving `NflverseDownloader.download` against a loopback server that reproduces run 43:
# 500, 500, then the parquet. Pointing the downloader's own `BASE_URLS` at that server is
# the only way to exercise the real path without a vendor.
# --------------------------------------------------------------------------------------


@pytest.fixture
def borrowed_downloader():
    """`nflreadpy`'s global downloader, pointed at a local base URL and put back after."""
    from nflreadpy.config import get_config, update_config
    from nflreadpy.downloader import get_downloader

    downloader = get_downloader()
    original_urls = downloader.BASE_URLS
    original_session = downloader.session
    # `update_config` accepts either the enum or its string, and hands back whichever it
    # was last given, so the restore normalizes rather than assuming one shape.
    original_cache = str(getattr(get_config().cache_mode, "value", get_config().cache_mode))
    # A cached frame would answer the second request without a download, which is the
    # opposite of what this test is measuring.
    update_config(cache_mode="off")
    try:
        yield downloader
    finally:
        downloader.BASE_URLS = original_urls
        downloader.session = original_session
        update_config(cache_mode=original_cache)
        install_retry_policy(NFLVERSE_RETRY, force=True)


def test_run_43_would_have_survived(scripted_server, borrowed_downloader) -> None:
    """The failure of 2026-09-15, replayed through the real loader path."""
    payload = io.BytesIO()
    pl.DataFrame({"gsis_id": ["00-0000001"], "display_name": ["Proof Player"]}).write_parquet(
        payload,
    )
    url, handler = scripted_server([500, 500, 200])
    handler.body = payload.getvalue()
    base, _, _ = url.rpartition("/")
    borrowed_downloader.BASE_URLS = dict(
        borrowed_downloader.BASE_URLS,
        **{"nflverse-data": f"{base}/"},
    )

    # Unmounted, exactly as `nflreadpy` ships it: the first 500 is the last word, and the
    # error is the one run 43 died on.
    borrowed_downloader.session = requests.Session()
    with pytest.raises(ConnectionError, match="500 Server Error"):
        borrowed_downloader.download("nflverse-data", "players/players")
    assert len(handler.seen) == 1

    handler.seen.clear()
    install_retry_policy(IMPATIENT, force=True)
    frame = borrowed_downloader.download("nflverse-data", "players/players")

    assert frame.to_dicts() == [{"gsis_id": "00-0000001", "display_name": "Proof Player"}]
    assert len(handler.seen) == 3


def test_a_spent_budget_still_stops_the_capture(scripted_server, borrowed_downloader) -> None:
    """Patience is not a fallback: a source that is really down still fails the job.

    `docs/OPERATIONS.md` section 8 depends on this. The refresh must not learn to publish
    something else when nflverse is unavailable - it must stop, so the previous site stays.
    """
    url, handler = scripted_server([503])
    base, _, _ = url.rpartition("/")
    borrowed_downloader.BASE_URLS = dict(
        borrowed_downloader.BASE_URLS,
        **{"nflverse-data": f"{base}/"},
    )
    install_retry_policy(IMPATIENT, force=True)

    with pytest.raises(ConnectionError, match="Max retries exceeded"):
        borrowed_downloader.download("nflverse-data", "players/players")

    assert len(handler.seen) == IMPATIENT.max_attempts
