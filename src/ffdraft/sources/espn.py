"""ESPN's public roster and start percentages (ADR-112).

**What this reads, and the one request it makes.** ESPN's fantasy read API is reachable
without a login. The 2026-10-17 probe (`docs/source-probes/2026-10-17/espn-ownership/`)
measured two routes and this adapter uses the one whose filters are honoured:

* ``/seasons/{season}/players`` — the global list. It **ignores** the ``X-Fantasy-Filter``
  header's contents: with the header it returns all 11,618 players (45 MB decoded for the
  full view), without it 50. Not used.
* ``/seasons/{season}/segments/0/leaguedefaults/3?view=kona_player_info`` — the league-default
  universe. It **honours** ``limit``, ``sortPercOwned`` and the stats/rank filters, and it
  reports its universe size in ``X-Fantasy-Filter-Player-Count``. Its QB/RB/WR/TE/K/DST
  universe was identical to the global list's set of players carrying an ownership object
  (1,052 of 1,052, zero value disagreements), so nothing a waiver reader could want is lost.

``filterStatsForSourceIds`` and ``filterRanksForScoringPeriodIds`` with values no row has
make ESPN drop the stats and per-period ranks *server side*: 463 kB on the wire for the whole
universe instead of ~11 MB. That is the network optimisation; trimming fields after download
would not be one.

**Completeness is checked against ESPN's own count.** The response is refused when the rows
returned differ from ``X-Fantasy-Filter-Player-Count`` or reach the requested ``limit``: a
truncated list would silently lose exactly the low-rostered players a waiver reader wants.

**Period is not a parameter.** ``scoringPeriodId`` 0, 1, 5, 6, 7 and omitted returned
byte-identical ownership for every player, so no period is requested and none is claimed.
The season endpoint's ``currentScoringPeriod`` is retrieved separately and recorded as the
period ESPN *reported as current at retrieval* — context, not a statement of which week's
lineups ``percentStarted`` counts.

**Kept and discarded.** Only ``percentOwned``, ``percentStarted``, ``percentChange`` (retained
privately; its window is not stated by ESPN), ``leagueType`` and ``date`` are normalized,
plus the id, position and a diagnostics-only name. ADP, auction values, draft ranks,
projections, stats and editorial outlooks never leave this module.
"""

from __future__ import annotations

import gzip
import json
import math
import time
import zlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ffdraft.contracts import ESPN_OWNERSHIP_CONTRACT, QualityCheck, SourceBatch
from ffdraft.contracts.enums import Severity
from ffdraft.identity.ids import IdNamespace, normalize_id
from ffdraft.sources.base import BaseSourceAdapter, SourceConfig, SourceFetchError
from ffdraft.sources.nflverse import FlagCounter
from ffdraft.timeutil import utc_now

__all__ = [
    "CORE_POSITION_IDS",
    "ESPN_LEAGUE_DEFAULT_ID",
    "ESPN_OWNERSHIP_FILTER",
    "ESPN_REQUEST_LIMIT",
    "ESPN_SOURCE_ID",
    "ESPN_VIEW",
    "EspnFetch",
    "EspnOwnershipAdapter",
    "completeness_problems",
    "fetch_espn_current_period",
    "fetch_espn_ownership",
    "ownership_url",
]

ESPN_SOURCE_ID = "espn_fantasy_ownership"
ESPN_READS_BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/"
#: Any league default works (1, 3, 5 and 6 returned identical ids and values; 2 and 4 404).
ESPN_LEAGUE_DEFAULT_ID = 3
ESPN_VIEW = "kona_player_info"
#: Well above the measured 1,052-player universe. Reaching it means the list was cut off.
ESPN_REQUEST_LIMIT = 2000
#: The filter actually sent. ``99`` is a value no stat source or scoring period has, which is
#: how ESPN is asked to omit those arrays; every key here was measured as honoured.
ESPN_OWNERSHIP_FILTER: Mapping[str, Any] = {
    "players": {
        "limit": ESPN_REQUEST_LIMIT,
        "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
        "filterStatsForSourceIds": {"value": [99]},
        "filterRanksForScoringPeriodIds": {"value": [99]},
    },
}
#: ESPN ``defaultPositionId`` -> the positions this product publishes.
CORE_POSITION_IDS: Mapping[int, str] = {1: "QB", 2: "RB", 3: "WR", 4: "TE"}

#: Bounded transfer. The measured response is 463 kB compressed / 2.5 MB decoded; these caps
#: are an order of magnitude above it and far below the 45 MB an ignored filter produces.
MAX_WIRE_BYTES = 8_000_000
MAX_DECODED_BYTES = 40_000_000
#: Attempts for one request, and the backoff before each retry (seconds).
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (2.0, 4.0)
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
#: ESPN's stamp may lead our clock by a little; more than this is a defect, not drift.
FUTURE_TOLERANCE = timedelta(minutes=10)

USER_AGENT = (
    "jeisey-tiers/0.1 (+https://github.com/jeisey/jeisey-tiers; non-commercial fantasy research)"
)
_LICENSE = "espn-owner-decision/2026-10-17"


def ownership_url(season: int) -> str:
    return f"{ESPN_READS_BASE}{season}/segments/0/leaguedefaults/{ESPN_LEAGUE_DEFAULT_ID}"


@dataclass(frozen=True, slots=True)
class EspnFetch:
    """One ownership retrieval: the decoded rows plus everything measured about getting them."""

    players: tuple[Mapping[str, Any], ...]
    universe_count: int | None
    wire_bytes: int
    decoded_bytes: int
    duration_ms: int
    attempts: int
    url: str

    def request_record(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "view": ESPN_VIEW,
            "league_default_id": ESPN_LEAGUE_DEFAULT_ID,
            "x_fantasy_filter": dict(ESPN_OWNERSHIP_FILTER),
            "scoring_period_requested": None,
            "universe_count_header": self.universe_count,
            "rows_returned": len(self.players),
            "wire_bytes": self.wire_bytes,
            "decoded_bytes": self.decoded_bytes,
            "duration_ms": self.duration_ms,
            "attempts": self.attempts,
        }


Transport = Callable[[str, Mapping[str, str], float], Any]


def _default_transport(url: str, headers: Mapping[str, str], timeout: float) -> Any:
    import requests

    return requests.get(url, headers=dict(headers), timeout=timeout, stream=True)


def _read_bounded(response: Any) -> tuple[bytes, int]:
    """The decoded body and the bytes read off the wire, refusing anything over the caps."""
    declared = response.headers.get("content-length")
    if declared is not None and str(declared).isdigit() and int(declared) > MAX_WIRE_BYTES:
        raise SourceFetchError(f"declared body {declared} B exceeds {MAX_WIRE_BYTES} B")
    chunks: list[bytes] = []
    wire = 0
    raw = response.raw
    while True:
        chunk = raw.read(65536, decode_content=False)
        if not chunk:
            break
        wire += len(chunk)
        if wire > MAX_WIRE_BYTES:
            raise SourceFetchError(f"body exceeded {MAX_WIRE_BYTES} B on the wire")
        chunks.append(chunk)
    body = b"".join(chunks)
    encoding = str(response.headers.get("content-encoding") or "").lower()
    if encoding == "gzip":
        inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
        decoded = inflater.decompress(body, MAX_DECODED_BYTES + 1)
        if len(decoded) > MAX_DECODED_BYTES or inflater.unconsumed_tail:
            raise SourceFetchError(f"decoded body exceeded {MAX_DECODED_BYTES} B")
        return decoded, wire
    if encoding not in {"", "identity"}:
        raise SourceFetchError(f"unsupported content-encoding {encoding!r}")
    if len(body) > MAX_DECODED_BYTES:
        raise SourceFetchError(f"decoded body exceeded {MAX_DECODED_BYTES} B")
    return body, wire


class _PermanentFetchError(SourceFetchError):
    """A 4xx other than 429: ESPN answered, and the answer was no. Never retried."""


def _get(
    url: str,
    *,
    headers: Mapping[str, str],
    timeout: float,
    transport: Transport,
    sleep: Callable[[float], None],
) -> tuple[Any, bytes, int, int]:
    """GET with bounded retries. Returns ``(response, body, wire_bytes, attempts)``.

    Retried: a transport failure, a timeout, 429 and 5xx. Not retried: any other non-200
    (a refused filter answers 400, which a second identical request cannot change) and a body
    over the byte caps (the same request returns the same body).
    """
    last: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = transport(url, headers, timeout)
            status = int(response.status_code)
            if status == 200:
                body, wire = _read_bounded(response)
                return response, body, wire, attempt
            if status not in RETRY_STATUSES:
                raise _PermanentFetchError(f"{ESPN_SOURCE_ID}: {url} answered HTTP {status}")
            last = SourceFetchError(f"HTTP {status}")
        except SourceFetchError:
            raise
        except Exception as exc:  # noqa: BLE001 - transport failures are retried, then typed
            last = exc
        if attempt < MAX_ATTEMPTS:
            sleep(BACKOFF_SECONDS[min(attempt - 1, len(BACKOFF_SECONDS) - 1)])
    raise SourceFetchError(f"{ESPN_SOURCE_ID}: {url} failed after {MAX_ATTEMPTS} attempts: {last}")


def fetch_espn_ownership(
    season: int,
    *,
    timeout: float = 30.0,
    transport: Transport | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> EspnFetch:
    """The one ownership request. **Network I/O.** Raises on any incomplete response."""
    url = f"{ownership_url(season)}?view={ESPN_VIEW}"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Fantasy-Filter": json.dumps(ESPN_OWNERSHIP_FILTER, separators=(",", ":")),
    }
    started = time.monotonic()
    response, body, wire, attempts = _get(
        url,
        headers=headers,
        timeout=timeout,
        transport=transport or _default_transport,
        sleep=sleep,
    )
    duration = int(round((time.monotonic() - started) * 1000))
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise SourceFetchError(f"{ESPN_SOURCE_ID}: response is not JSON: {exc}") from exc
    if not isinstance(payload, Mapping) or not isinstance(payload.get("players"), list):
        raise SourceFetchError(f"{ESPN_SOURCE_ID}: response has no `players` list")
    header = response.headers.get("x-fantasy-filter-player-count")
    count = int(header) if header is not None and str(header).strip().isdigit() else None
    fetched = EspnFetch(
        players=tuple(payload["players"]),
        universe_count=count,
        wire_bytes=wire,
        decoded_bytes=len(body),
        duration_ms=duration,
        attempts=attempts,
        url=url,
    )
    problems = completeness_problems(fetched)
    if problems:
        raise SourceFetchError(f"{ESPN_SOURCE_ID}: incomplete response: {'; '.join(problems)}")
    return fetched


def completeness_problems(fetched: EspnFetch) -> list[str]:
    """Why a response cannot be trusted to be the whole universe. Empty when it can."""
    problems: list[str] = []
    rows = len(fetched.players)
    if rows == 0:
        problems.append("no players returned")
    if rows >= ESPN_REQUEST_LIMIT:
        problems.append(f"{rows} rows reached the requested limit {ESPN_REQUEST_LIMIT}")
    if fetched.universe_count is None:
        problems.append("X-Fantasy-Filter-Player-Count header missing")
    elif fetched.universe_count != rows:
        problems.append(f"{rows} rows returned but ESPN counts {fetched.universe_count}")
    return problems


def fetch_espn_current_period(
    season: int,
    *,
    timeout: float = 15.0,
    transport: Transport | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int | None:
    """``currentScoringPeriod.id`` from the season endpoint, or ``None``. **Network I/O.**

    Context only: the period ESPN reported as current when the percentages were read. A
    failure here never fails a capture; the reading is simply recorded as unknown.
    """
    try:
        _, body, _, _ = _get(
            f"{ESPN_READS_BASE}{season}",
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=timeout,
            transport=transport or _default_transport,
            sleep=sleep,
        )
        payload = json.loads(body)
        period = payload.get("currentScoringPeriod", {}).get("id")
        return int(period) if isinstance(period, int) and 0 <= period <= 25 else None
    except (SourceFetchError, ValueError, AttributeError, TypeError):
        return None


def _percent(value: Any) -> float | None:
    """A finite percentage in [0, 100], or ``None``. Booleans are not numbers here."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0.0 or number > 100.0:
        return None
    return number


def _stamp(value: Any) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(float(value) / 1000.0, tz=UTC).replace(microsecond=0)
    except (OverflowError, OSError, ValueError):
        return None


class EspnOwnershipAdapter(BaseSourceAdapter):
    """League-default ``kona_player_info`` -> one ownership row per core ESPN player."""

    source_id = ESPN_SOURCE_ID
    resource = "GET /seasons/{season}/segments/0/leaguedefaults/3?view=kona_player_info"
    adapter_version = "1.0"
    contract = ESPN_OWNERSHIP_CONTRACT
    recorded_schema_fixture = "espn_leaguedefaults_kona_player_info"
    license_policy_version = _LICENSE
    #: QB/RB/WR/TE rows on 2026-10-17: 962. Fewer than this is a thin payload.
    min_expected_records = 500

    def normalize(
        self,
        players: Sequence[Mapping[str, Any]],
        *,
        retrieved_at: datetime | None = None,
    ) -> SourceBatch:
        """Pure. ``players`` is the response's ``players`` list, wrapped or bare."""
        observed_at = (retrieved_at or utc_now()).astimezone(UTC).replace(microsecond=0)
        flags = FlagCounter()
        candidates: dict[str, list[dict[str, Any]]] = {}
        for entry in players:
            player = entry.get("player") if isinstance(entry.get("player"), Mapping) else entry
            if not isinstance(player, Mapping):
                flags.note("espn_rows_not_an_object")
                continue
            position_id = player.get("defaultPositionId")
            if not isinstance(position_id, int) or position_id not in CORE_POSITION_IDS:
                continue
            ownership = player.get("ownership")
            if not isinstance(ownership, Mapping):
                flags.note("espn_rows_without_ownership")
                continue
            identity = normalize_id(IdNamespace.ESPN, player.get("id", entry.get("id")))
            if identity.value is None:
                flags.note("espn_rows_without_valid_id")
                continue
            row_flags: list[str] = [identity.reason] if identity.reason else []
            rostered = _percent(ownership.get("percentOwned"))
            if rostered is None:
                row_flags.append("invalid_percent_rostered")
                flags.note("espn_invalid_percent_rostered")
            started: float | None = None
            if "percentStarted" in ownership:
                started = _percent(ownership.get("percentStarted"))
                if started is None:
                    row_flags.append("invalid_percent_started")
                    flags.note("espn_invalid_percent_started")
            else:
                flags.note("espn_rows_without_percent_started")
            updated = _stamp(ownership.get("date"))
            if updated is not None and updated > observed_at + FUTURE_TOLERANCE:
                row_flags.append("source_date_in_future")
                flags.note("espn_source_date_in_future")
                updated = None
            league_type = ownership.get("leagueType")
            change = ownership.get("percentChange")
            candidates.setdefault(identity.value, []).append(
                {
                    "source_id": self.source_id,
                    "external_player_id": identity.value,
                    "position_id": position_id,
                    "full_name": str(player.get("fullName") or "").strip() or None,
                    "percent_rostered": rostered,
                    "percent_started": started,
                    "espn_percent_change": (
                        float(change)
                        if isinstance(change, int | float)
                        and not isinstance(change, bool)
                        and math.isfinite(float(change))
                        else None
                    ),
                    "league_type": (
                        int(league_type)
                        if isinstance(league_type, int) and not isinstance(league_type, bool)
                        else None
                    ),
                    "source_updated_at_utc": updated,
                    "snapshot_at_utc": observed_at,
                    "quality_flags": ",".join(dict.fromkeys(row_flags)),
                },
            )

        rows: list[dict[str, Any]] = []
        for external_id in sorted(candidates):
            versions = candidates[external_id]
            distinct = {json.dumps(version, default=str, sort_keys=True) for version in versions}
            if len(distinct) > 1:
                # Two different readings for one id: neither is trustworthy (fail closed).
                flags.note("espn_conflicting_duplicate_ids")
                continue
            if len(versions) > 1:
                flags.note("espn_identical_duplicate_ids", len(versions) - 1)
            rows.append(versions[0])

        return self.build_batch(
            self.contract.build(rows),
            retrieved_at=observed_at,
            warning_codes=flags.codes,
            detail={**flags.detail},
        )

    def fetch(self, *, as_of: datetime, config: SourceConfig) -> SourceBatch:
        fetched = fetch_espn_ownership(config.season, timeout=config.timeout_seconds)
        return self.normalize(fetched.players, retrieved_at=as_of)

    def semantic_checks(self, batch: SourceBatch) -> Sequence[QualityCheck]:
        """Ownership is never a model feature; a start share above the roster share is odd."""
        if batch.frame.is_empty():
            return ()
        checks: list[QualityCheck] = [
            QualityCheck.ok(
                "espn.ownership_is_not_a_feature",
                stage=self.source_id,
                message=(
                    "ESPN roster/start percentages are retained for the in-season "
                    "research surfaces only and never reach an intrinsic or ROS feature"
                ),
                observed=f"{batch.frame.height} row(s)",
            ),
        ]
        both = batch.frame.drop_nulls(["percent_rostered", "percent_started"])
        above = both.filter(both["percent_started"] > both["percent_rostered"] + 1e-9).height
        if above:
            checks.append(
                QualityCheck.fail(
                    "espn.started_above_rostered",
                    stage=self.source_id,
                    message=(
                        "rows where ESPN's start percentage exceeds its roster percentage; "
                        "the probe saw none, so the denominators may have changed"
                    ),
                    observed=str(above),
                    expected="0",
                    severity=Severity.WARNING,
                ),
            )
        return checks


def gzip_json(payload: Any) -> bytes:
    """Test helper: how ESPN's body arrives on the wire."""
    return gzip.compress(json.dumps(payload).encode("utf-8"), mtime=0)
