"""Transport policy for nflverse downloads.

**Boundary module.** How a download is *attempted*, never what the payload means.
Normalization, schema checks and identity all stay where they are.

`docs/ARCHITECTURE.md` section 5 scopes an adapter to "fetch, retry/timeout, raw schema
normalization", and every other vendor in this repository honours the retry half: MFL,
Fantasy Football Calculator and FantasyPros each own a bounded, backing-off request loop.
nflverse was the exception. `nflreadpy` fetches GitHub release assets with a plain
:class:`requests.Session` that retries nothing, so the single most critical source in the
project - `config/source-registry.yaml` marks it ``criticality: critical`` - was also the
only one where one unlucky response ended the production refresh.

It did. `daily-refresh` run 43 (2026-09-15, 11:26:26 UTC) failed in the capture job with::

    ConnectionError: Failed to download
    https://github.com/nflverse/nflverse-data/releases/download/players/players.parquet:
    500 Server Error: Internal Server Error

The same URL served 3,386,429 bytes correctly on the first try an hour later, so nothing
was missing: the request was unlucky. What made it likely is the calendar. An
nflverse-data release asset is replaced by delete-then-upload, and in-season the assets
this project reads are rewritten repeatedly through the day - measured that afternoon,
``players.parquet`` was last modified at 13:05 UTC and ``depth_charts_2026.parquet`` at
12:39 UTC, while the static ``combine.parquet`` still carried its March timestamp. Week 1
of the 2026 season completed the night before, which is when that churn starts. A daily
capture at 11:2x UTC now runs inside it, so colliding with a replacement window stopped
being a remote possibility and became a question of how many requests per day.

So this module adds patience, not a fallback. The same URL, asked again, seconds later.
Nothing here can serve a different payload than a first-try success would have: a cache
is not consulted, a mirror is not substituted, and a failure after the budget is spent is
still a failure that stops the deploy (`docs/OPERATIONS.md` section 8).

Deliberately **not** retried: HTTP 404. nflverse publishes per-season files, and asking
for a season that has not been published yet is a legitimate 404 that several loaders can
produce; a 404 on a file that used to exist is a source-contract change, which
`AGENTS.md` section 5 wants loud and immediate. Retrying either one would trade a clear
answer for a slow one. Only 429 and the 5xx family - server-side, transient by
definition - are worth waiting on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:  # pragma: no cover - typing only
    from types import ModuleType

__all__ = [
    "NFLVERSE_RETRY",
    "NflverseRetryPolicy",
    "install_retry_policy",
    "nflverse_loaders",
]


@dataclass(frozen=True, slots=True)
class NflverseRetryPolicy:
    """How many times, how long apart, and for which responses.

    The numbers are mirrored in ``config/source-registry.yaml`` under the nflreadpy entry's
    ``client_settings.retry``, and ``tests/unit/test_nflverse_retry.py`` asserts the two
    agree - `AGENTS.md` section 18 pairs a source adapter with its registry entry, and a
    retry budget nobody can read from the registry is a budget that silently drifts.
    """

    #: Retries *after* the first attempt, so the total request count is ``retries + 1``.
    retries: int = 4
    #: urllib3 sleeps ``backoff_factor * 2 ** (n - 1)`` before retry ``n``, and the first
    #: retry is immediate. At 1.0 that is 0s, 2s, 4s, 8s: ~14 seconds of patience, which
    #: comfortably outlasts the upload of a 3 MB release asset and is invisible against a
    #: 30-minute job timeout.
    backoff_factor: float = 1.0
    #: Server-side and transient. 404 is absent on purpose; see the module docstring.
    retry_statuses: tuple[int, ...] = (429, 500, 502, 503, 504)

    @property
    def max_attempts(self) -> int:
        return self.retries + 1

    def as_adapter(self) -> Any:
        """A :class:`requests.adapters.HTTPAdapter` carrying this policy."""
        from requests.adapters import HTTPAdapter, Retry

        return HTTPAdapter(
            max_retries=Retry(
                total=self.retries,
                # Reads are the only thing nflreadpy does, and a GET is safe to repeat.
                allowed_methods=frozenset({"GET"}),
                status_forcelist=self.retry_statuses,
                backoff_factor=self.backoff_factor,
                # A throttled host states its own terms; honour them over our arithmetic.
                respect_retry_after_header=True,
                # Exhausting the budget on a status must raise rather than hand back the
                # last error response, which `raise_for_status` would then re-describe as
                # a first failure.
                raise_on_status=True,
            ),
        )


#: The policy production uses.
NFLVERSE_RETRY = NflverseRetryPolicy()

_installed: NflverseRetryPolicy | None = None


def install_retry_policy(
    policy: NflverseRetryPolicy = NFLVERSE_RETRY,
    *,
    force: bool = False,
) -> bool:
    """Mount ``policy`` on the session `nflreadpy` downloads through.

    `nflreadpy` keeps one module-level :class:`~nflreadpy.downloader.NflverseDownloader`
    and every loader reaches it through the public ``get_downloader()``; mounting a
    retrying adapter on its ``session`` is the documented way to give a ``requests``
    client a retry budget, and it reaches loaders this repository has not written yet.

    Returns whether this call did the mounting. Idempotent: repeated calls with the same
    policy are a no-op, so the per-call ``nflverse_loaders()`` below costs one comparison.
    """
    global _installed
    if _installed == policy and not force:
        return False

    from nflreadpy.downloader import get_downloader

    session = get_downloader().session
    adapter = policy.as_adapter()
    # Both schemes, although nflverse is HTTPS throughout: a mount that covers only the
    # scheme we expect would silently stop applying if a host ever redirected.
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    _installed = policy
    return True


def nflverse_loaders() -> ModuleType:
    """``nflreadpy``, with this project's retry policy installed.

    Every nflverse download in `ffdraft` goes through here rather than importing
    `nflreadpy` directly, so the policy is a property of the call rather than something a
    new call site has to remember. The import stays inside the function because the
    network-free tests import the modules that call this one.
    """
    import nflreadpy

    install_retry_policy()
    # `nflreadpy` ships no type information, so the module object is untyped here; the
    # cast states what it is rather than letting `Any` leak into every caller's signature.
    return cast("ModuleType", nflreadpy)
