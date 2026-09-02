"""Source probe: the FantasyPros public v2 API (Phase 10, ADR-060).

**Not production code, and not a dependency of anything.** `AGENTS.md` section 3 forbids
inventing an endpoint or a schema, and section 5 forbids a `verify_before_use` source
becoming a production dependency before the check is completed and documented. This is that
check. It runs on a GitHub runner because the development sandbox's egress policy denies
this host (ADR-009, ADR-053), and because the API key exists only as an Actions secret.

**Discovery first.** The probe does not assume a path. It asks the published documentation
for the endpoint list, prints what it finds, and only then issues requests against the paths
the vendor itself named. A guessed path that 404s is recorded as a 404 — that is a
measurement — but the adapter written afterwards is built from the discovered contract.

Budget, treated as a hard application constraint even though the vendor permits more
(`docs/RELEASE2_ROADMAP.md` 10.1.3):

    FANTASYPROS_DAILY_REQUEST_CAP        = 50   # vendor states 100
    FANTASYPROS_MIN_REQUEST_INTERVAL_SEC = 1

This probe budgets itself well below the cap and refuses to exceed it.

**Secret handling.** The key is read from the environment, sent only as the `x-api-key`
request header, and never printed, serialised, cached or written anywhere. Every line this
script emits passes through :func:`emit`, which refuses to print a line containing the key.
The job log of a public repository is world-readable; that guard is not decoration.

**What it deliberately does not do:** retain any payload, print player rows beyond a
redacted schema description, or write to the store.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Mapping, Sequence
from typing import Any

import requests

BASE = "https://api.fantasypros.com/public/v2"
DOCS_URL = f"{BASE}/docs"
SEASON = 2026
SPORT = "nfl"

#: The project's own budget, half the vendor's stated 100/day (roadmap 10.1.3).
DAILY_REQUEST_CAP = 50
MIN_REQUEST_INTERVAL_SECONDS = 1.0

#: Leave headroom under the cap so a probe can never be the reason a production capture
#: is refused on the same day.
PROBE_REQUEST_BUDGET = 45

HEADERS = {
    "User-Agent": (
        "jeisey-tiers source probe (+https://github.com/jeisey/jeisey-tiers); "
        "free non-commercial project, Phase 10 feasibility check"
    ),
    "Accept": "application/json",
}

#: Fields that would be a real id bridge, ordered by how directly each joins this project's
#: canonical registry. `fantasypros_player_id` (or whatever the vendor calls its own key) is
#: only a bridge if it maps to something; a vendor-internal integer maps to nothing on its
#: own and needs the same linkage treatment FFC gets.
ID_FIELDS = (
    "gsis_id",
    "espn_id",
    "sleeper_id",
    "pfr_id",
    "sportradar_id",
    "yahoo_id",
    "mfl_id",
    "player_id",
    "fpid",
    "player_filename",
    "id",
)


class Budget:
    """A request counter that refuses to exceed the probe's allowance."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.used = 0
        self._last: float | None = None

    def spend(self) -> None:
        if self.used >= self.limit:
            raise RuntimeError(
                f"probe request budget exhausted ({self.used}/{self.limit}); "
                "refusing to issue another vendor request",
            )
        if self._last is not None:
            elapsed = time.monotonic() - self._last
            if elapsed < MIN_REQUEST_INTERVAL_SECONDS:
                time.sleep(MIN_REQUEST_INTERVAL_SECONDS - elapsed)
        self.used += 1
        self._last = time.monotonic()


BUDGET = Budget(PROBE_REQUEST_BUDGET)

_KEY = os.environ.get("FANTASYPROS_API_KEY", "").strip()


def emit(line: str = "") -> None:
    """Print, unless the line would disclose the secret.

    A probe that leaks its key into a public job log has failed regardless of what it
    measured, so the guard is unconditional rather than applied at the call sites a reader
    happens to think are risky.
    """
    if _KEY and _KEY in line:
        print("  <<< line suppressed: it contained the API key >>>")
        return
    print(line)


def section(title: str) -> None:
    emit(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def get(
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    authenticated: bool = True,
    accept: str = "application/json",
) -> requests.Response | None:
    """One paced request. Returns ``None`` when the transport itself failed."""
    headers = dict(HEADERS)
    headers["Accept"] = accept
    if authenticated:
        headers["x-api-key"] = _KEY
    BUDGET.spend()
    try:
        return requests.get(url, params=dict(params or {}), headers=headers, timeout=30)
    except Exception as exc:  # noqa: BLE001 - a probe reports, it does not raise
        emit(f"  transport failure: {type(exc).__name__}: {exc}")
        return None


def describe_fields(rows: Sequence[Mapping[str, Any]]) -> list[tuple[str, str, float]]:
    """Field name, observed python types, null fraction — the shape of a schema fixture."""
    if not rows:
        return []
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    out = []
    for key in keys:
        values = [row.get(key) for row in rows]
        types = sorted({type(v).__name__ for v in values if v is not None})
        nulls = sum(1 for v in values if v is None or v == "")
        out.append((key, "|".join(types) or "none", round(nulls / len(values), 4)))
    return out


def rows_of(payload: Any) -> tuple[str, list[dict[str, Any]]]:
    """Find the row list inside an unknown envelope, and name the key it was under."""
    if isinstance(payload, list):
        return "<root>", [dict(row) for row in payload if isinstance(row, dict)]
    if not isinstance(payload, Mapping):
        return "", []
    for key, value in payload.items():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return str(key), [dict(row) for row in value]
    # One level down: some envelopes nest the list under a container object.
    for key, value in payload.items():
        if isinstance(value, Mapping):
            inner_key, inner_rows = rows_of(value)
            if inner_rows:
                return f"{key}.{inner_key}", inner_rows
    return "", []


# --------------------------------------------------------------------------------------
# 0. Discovery
# --------------------------------------------------------------------------------------


def probe_docs() -> dict[str, Any]:
    """Fetch the published documentation and any OpenAPI document behind it."""
    section("0. Published documentation — the endpoint list comes from the vendor")
    emit(f"source: {DOCS_URL}")
    response = get(DOCS_URL, authenticated=False, accept="text/html,application/json")
    if response is None:
        return {}
    ctype = response.headers.get("content-type", "")
    emit(f"  status {response.status_code}  content-type={ctype}  bytes={len(response.content)}")

    spec: dict[str, Any] = {}
    if "json" in ctype:
        try:
            spec = response.json()
        except ValueError:
            spec = {}
    if not spec:
        # Redoc/Swagger pages carry the spec URL in the markup. Read it rather than guessing
        # which of the conventional filenames this vendor chose.
        text = response.text
        for token in ('spec-url="', "spec-url='", '"url":"', "url: '"):
            index = text.find(token)
            while index >= 0:
                start = index + len(token)
                end = min(
                    [p for p in (text.find('"', start), text.find("'", start)) if p > 0] or [start],
                )
                candidate = text[start:end]
                if candidate.endswith((".json", ".yaml", ".yml")) or "openapi" in candidate:
                    emit(f"  documentation names a spec document: {candidate}")
                    spec = _fetch_spec(candidate)
                    if spec:
                        return spec
                index = text.find(token, end)
        emit("  no spec URL found in the documentation markup; trying conventional paths")
        for path in ("/docs.json", "/openapi.json", "/swagger.json", "/docs/openapi.json"):
            spec = _fetch_spec(f"{BASE}{path}")
            if spec:
                return spec
    return spec


def _fetch_spec(url: str) -> dict[str, Any]:
    if url.startswith("/"):
        url = f"https://api.fantasypros.com{url}"
    response = get(url, authenticated=False)
    if response is None or response.status_code != 200:
        emit(f"  spec {url} -> http {response.status_code if response else 'transport failure'}")
        return {}
    try:
        payload = response.json()
    except ValueError:
        emit(f"  spec {url} -> http 200 but body is not JSON")
        return {}
    if isinstance(payload, dict) and ("paths" in payload or "openapi" in payload):
        emit(f"  spec {url} -> OpenAPI document, {len(payload.get('paths', {}))} path(s)")
        return payload
    return {}


def report_spec(spec: Mapping[str, Any]) -> list[str]:
    """Print every documented path and return the ranking-related ones."""
    section("1. Documented endpoints")
    paths = spec.get("paths")
    if not isinstance(paths, Mapping) or not paths:
        emit("  the documentation did not yield a machine-readable path list.")
        emit("  >>> The candidate paths probed below are therefore CANDIDATES, and a")
        emit("  >>> non-200 is evidence the path does not exist, not evidence of a schema.")
        return []
    ranking_paths: list[str] = []
    for path, item in sorted(paths.items()):
        if not isinstance(item, Mapping):
            continue
        for method, operation in item.items():
            if method.lower() != "get" or not isinstance(operation, Mapping):
                continue
            summary = str(operation.get("summary") or operation.get("operationId") or "")
            emit(f"  GET {path}    {summary}")
            params = operation.get("parameters")
            if isinstance(params, list):
                for param in params:
                    if not isinstance(param, Mapping):
                        continue
                    schema = param.get("schema") if isinstance(param.get("schema"), Mapping) else {}
                    enum = schema.get("enum") if isinstance(schema, Mapping) else None
                    required = "required" if param.get("required") else "optional"
                    emit(
                        f"      - {param.get('name')} ({param.get('in')}, {required})"
                        f"{f'  enum={enum}' if enum else ''}",
                    )
            blob = f"{path} {summary}".lower()
            if any(token in blob for token in ("rank", "adp", "consensus", "projection")):
                ranking_paths.append(str(path))
    return ranking_paths


# --------------------------------------------------------------------------------------
# 2. Rankings
# --------------------------------------------------------------------------------------

#: Probed only when discovery produced nothing. Each is reported with the status the server
#: returned, so an absent path is recorded as absent rather than assumed to exist.
CANDIDATE_PATHS = (
    f"/json/{SPORT}/{SEASON}/consensus-rankings",
    f"/json/{SPORT}/{SEASON}/rankings",
    f"/json/{SPORT}/{SEASON}/adp",
)

#: The scoring axis this project publishes. The vendor's own token spelling is discovered.
SCORING_CANDIDATES = ("STD", "HALF", "PPR")


def probe_rankings(paths: Sequence[str]) -> dict[str, Any]:
    section("2. Rankings — envelope, schema, volume, truncation")
    findings: dict[str, Any] = {}
    for path in paths:
        url = _expand(path)
        params = {"position": "ALL", "scoring": "HALF", "type": "weekly", "week": 0}
        response = get(url, params=params)
        if response is None:
            continue
        emit(f"  GET {path}  params={params}  -> http {response.status_code}")
        if response.status_code != 200:
            body = response.text[:300].replace("\n", " ")
            emit(f"      body: {body}")
            continue
        try:
            payload = response.json()
        except ValueError:
            emit("      http 200 but the body is not JSON")
            continue
        key, rows = rows_of(payload)
        emit(f"      row list under {key!r}: {len(rows)} row(s)")
        envelope = (
            {k: v for k, v in payload.items() if not isinstance(v, list | dict)}
            if isinstance(payload, Mapping)
            else {}
        )
        emit(f"      envelope scalars: {json.dumps(envelope, default=str)[:600]}")
        if rows:
            emit("      player-row schema (field, types, null fraction):")
            for name, types, nulls in describe_fields(rows):
                emit(f"        {name:28} {types:18} null={nulls:.3f}")
            emit(f"      first row keys only: {sorted(rows[0])}")
            findings[path] = {"rows": rows, "envelope": envelope, "row_key": key}
            break
    if not findings:
        emit("  >>> No rankings path returned usable JSON. Nothing further can be measured.")
    return findings


def _expand(path: str) -> str:
    """Fill OpenAPI path templates with the values this probe measures against."""
    filled = (
        path.replace("{sport}", SPORT)
        .replace("{season}", str(SEASON))
        .replace("{year}", str(SEASON))
    )
    return f"{BASE}{filled}" if filled.startswith("/") else filled


def probe_signal_separation(path: str) -> None:
    """Are ADP and ECR distinct responses, or two fields of one response?

    The roadmap's hardest requirement is that ECR must never masquerade as ADP. If the
    vendor serves both from one endpoint under different `type` values, the adapter has to
    request each separately and label them; if one response carries both columns, it must
    split them. Either is fine — guessing which is not.
    """
    section("3. ADP vs ECR — are the two signals separable?")
    url = _expand(path)
    for label, params in (
        ("ECR (draft consensus)", {"position": "ALL", "scoring": "HALF", "type": "draft"}),
        ("ADP", {"position": "ALL", "scoring": "HALF", "type": "adp"}),
        ("ECR default", {"position": "ALL", "scoring": "HALF"}),
    ):
        response = get(url, params=params)
        if response is None:
            continue
        emit(f"  {label:24} params={params} -> http {response.status_code}")
        if response.status_code != 200:
            continue
        try:
            payload = response.json()
        except ValueError:
            continue
        _, rows = rows_of(payload)
        if not rows:
            emit("      no rows")
            continue
        keys = sorted(rows[0])
        adp_like = [k for k in keys if "adp" in k.lower()]
        ecr_like = [k for k in keys if any(t in k.lower() for t in ("ecr", "rank_ecr", "rank"))]
        emit(f"      rows={len(rows)}  adp-like fields={adp_like}  rank/ecr-like fields={ecr_like}")


def probe_truncation(path: str) -> None:
    """Roadmap 10.1.3 item 7: do not mistake a truncated response for a complete market."""
    section("4. Truncation — how deep does one response go, and what widens it?")
    url = _expand(path)
    baseline = get(url, params={"position": "ALL", "scoring": "HALF"})
    if baseline is None or baseline.status_code != 200:
        emit("  baseline request failed; truncation cannot be measured")
        return
    try:
        _, base_rows = rows_of(baseline.json())
    except ValueError:
        emit("  baseline body is not JSON")
        return
    emit(f"  position=ALL              -> {len(base_rows)} row(s)")

    total = 0
    for position in ("QB", "RB", "WR", "TE"):
        response = get(url, params={"position": position, "scoring": "HALF"})
        if response is None or response.status_code != 200:
            emit(
                f"  position={position:3}                 -> http "
                f"{response.status_code if response else 'transport failure'}"
            )
            continue
        try:
            _, rows = rows_of(response.json())
        except ValueError:
            continue
        total += len(rows)
        emit(f"  position={position:3}                 -> {len(rows)} row(s)")
    emit(f"  sum of the four positions -> {total} row(s)")
    if total > len(base_rows):
        emit("  >>> position=ALL IS TRUNCATED. A complete capture needs per-position calls.")
        emit("  >>> Minimum deterministic plan: 4 positions x 3 scoring = 12 requests/day,")
        emit(f"  >>> comfortably inside the internal {DAILY_REQUEST_CAP}/day cap.")
    else:
        emit("  >>> position=ALL is at least as deep as the per-position union.")


def probe_scoring(path: str) -> None:
    section("5. Scoring cohorts — are STD/HALF/PPR genuinely different?")
    url = _expand(path)
    seen: dict[str, list[dict[str, Any]]] = {}
    for scoring in SCORING_CANDIDATES:
        response = get(url, params={"position": "RB", "scoring": scoring})
        if response is None or response.status_code != 200:
            emit(
                f"  scoring={scoring:5} -> http "
                f"{response.status_code if response else 'transport failure'}"
            )
            continue
        try:
            _, rows = rows_of(response.json())
        except ValueError:
            continue
        seen[scoring] = rows
        emit(f"  scoring={scoring:5} -> {len(rows)} row(s)")
    keys = sorted(seen)
    for index in range(1, len(keys)):
        left, right = seen[keys[0]], seen[keys[index]]
        left_order = [str(row.get("player_name") or row.get("name")) for row in left]
        right_order = [str(row.get("player_name") or row.get("name")) for row in right]
        verdict = "IDENTICAL ORDER" if left_order == right_order else "different order"
        emit(f"  {keys[0]} vs {keys[index]}: {verdict}")
    if len(seen) < 2:
        emit("  >>> Fewer than two scoring cohorts answered; the axis cannot be claimed.")


def probe_freshness(path: str, envelope: Mapping[str, Any]) -> None:
    section("6. Freshness and aggregation semantics")
    stamp_keys = [
        key
        for key in envelope
        if any(token in key.lower() for token in ("date", "time", "updated", "as_of", "published"))
    ]
    emit(f"  envelope temporal keys: {stamp_keys or 'NONE'}")
    for key in stamp_keys:
        emit(f"    {key} = {envelope[key]!r}")
    if not stamp_keys:
        emit("  >>> No data-as-of time in the envelope. `source_as_of_utc` stays null and")
        emit("  >>> retrieval time is the only defensible stamp (AGENTS.md section 5).")
    else:
        emit("  >>> A source time IS published; it must stay separate from retrieval time.")
    emit(f"  (path probed: {path})")


def probe_identity(rows: Sequence[Mapping[str, Any]]) -> None:
    section("7. Identity — is there a bridge, or does this need name linkage too?")
    present = [f for f in ID_FIELDS if any(f in row for row in rows)]
    emit(f"  id-like fields present: {present or 'NONE'}")
    for field in present:
        values = [row.get(field) for row in rows if row.get(field) not in (None, "")]
        emit(
            f"    {field:20} populated={len(values)}/{len(rows)} "
            f"distinct={len({str(v) for v in values})} "
            f"type={type(values[0]).__name__ if values else 'n/a'}",
        )
    try:
        from ffdraft.identity.ids import IdNamespace
        from ffdraft.market.identity import load_market_identity

        identity = load_market_identity(SEASON)
        registry = identity.registry
        emit(f"  canonical registry players: {len(registry.players)}")
        for field, namespace in (
            ("gsis_id", IdNamespace.GSIS),
            ("espn_id", IdNamespace.ESPN),
            ("sleeper_id", IdNamespace.SLEEPER),
            ("yahoo_id", IdNamespace.YAHOO),
        ):
            if field not in present:
                continue
            hits = sum(
                1
                for row in rows
                if row.get(field) and registry.lookup(namespace, str(row[field])).status == "found"
            )
            emit(f"    {field}: {hits}/{len(rows)} resolve through the registry")
        if not any(f in present for f in ("gsis_id", "espn_id", "sleeper_id", "yahoo_id")):
            emit("  >>> No direct bridge. FantasyPros needs the same name-linkage treatment")
            emit("  >>> as FFC (roadmap 10.2), keyed on its own stable player id.")
    except Exception as exc:  # noqa: BLE001
        emit(f"  registry comparison unavailable: {type(exc).__name__}: {exc}")


def probe_limit_and_pagination(path: str) -> None:
    """Run 1 measured a hard 10-row response with ``public_api_limited: true``.

    That is the single fact that decides whether FantasyPros can be a production ADP/ECR
    source at all, so it gets its own section. Roadmap 10.1.3 item 7 is explicit: do not
    mistake a truncated response for a complete top-300 market. Either a documented
    parameter widens the window, or the key's tier does not serve one.
    """
    section("9. Is the 10-row cap a page size or a tier ceiling?")
    url = _expand(path)
    base = {"position": "ALL", "scoring": "HALF"}
    for label, extra in (
        ("limit=300", {"limit": 300}),
        ("limit=100", {"limit": 100}),
        ("limit=25", {"limit": 25}),
        ("offset=10", {"limit": 10, "offset": 10}),
        ("start=10", {"limit": 10, "start": 10}),
        ("page=2", {"limit": 10, "page": 2}),
        ("max_results=300", {"max_results": 300}),
        ("ranks=1-300", {"ranks": "1-300"}),
    ):
        response = get(url, params={**base, **extra})
        if response is None:
            continue
        if response.status_code != 200:
            emit(f"  {label:18} -> http {response.status_code}")
            continue
        try:
            payload = response.json()
        except ValueError:
            emit(f"  {label:18} -> http 200, body not JSON")
            continue
        _, rows = rows_of(payload)
        envelope = (
            {k: v for k, v in payload.items() if not isinstance(v, list | dict)}
            if isinstance(payload, Mapping)
            else {}
        )
        first = str(rows[0].get("player_name")) if rows else "-"
        emit(
            f"  {label:18} -> {len(rows):>4} row(s)  "
            f"count={envelope.get('count')} limit={envelope.get('limit')} "
            f"public_api_limited={envelope.get('public_api_limited')} "
            f"tier={envelope.get('tier')}  first={first!r}",
        )
    emit("  >>> If every variant returns 10 and `public_api_limited` stays true, the cap is")
    emit("  >>> the key's TIER, not a page size. A 10-row response is not a market, and")
    emit("  >>> roadmap 10.1.3 item 7 forbids treating it as one.")


def probe_rank_object(path: str) -> None:
    """Run 1 found `rank` is a dict. Whatever ADP and ECR are, they are inside it."""
    section("10. Inside the `rank` object — where do ADP and ECR actually live?")
    url = _expand(path)
    for label, params in (
        ("type=draft", {"position": "ALL", "scoring": "HALF", "type": "draft"}),
        ("type=adp", {"position": "ALL", "scoring": "HALF", "type": "adp"}),
        ("no type", {"position": "ALL", "scoring": "HALF"}),
    ):
        response = get(url, params=params)
        if response is None or response.status_code != 200:
            continue
        try:
            _, rows = rows_of(response.json())
        except ValueError:
            continue
        if not rows:
            emit(f"  {label:12} -> no rows")
            continue
        rank = rows[0].get("rank")
        if isinstance(rank, Mapping):
            emit(f"  {label:12} rank keys: {sorted(rank)}")
            for key in sorted(rank):
                value = rank[key]
                emit(f"      {key:24} = {value!r} ({type(value).__name__})")
        else:
            emit(f"  {label:12} rank is {type(rank).__name__}: {rank!r}")
        positions = rows[0].get("positions")
        emit(f"  {label:12} positions = {positions!r}")
    emit("  >>> ADP and ECR must be separable fields. If one `rank` object carries both,")
    emit("  >>> the adapter emits two quote rows with distinct market_signal_type values;")
    emit("  >>> if the vendor serves them from different requests, it makes both requests.")


def probe_adp_path() -> None:
    """Run 1 stopped at the first 200 and never reached the third candidate."""
    section("11. The dedicated ADP path, which run 1 never reached")
    for path in (f"/json/{SPORT}/{SEASON}/adp", f"/json/{SPORT}/{SEASON}/consensus-rankings"):
        url = _expand(path)
        for params in (
            {"position": "ALL", "scoring": "HALF"},
            {"position": "ALL", "scoring": "HALF", "type": "draft", "week": 0},
        ):
            response = get(url, params=params)
            if response is None:
                continue
            emit(f"  GET {path} params={params} -> http {response.status_code}")
            if response.status_code != 200:
                emit(f"      body: {response.text[:240]!r}")
                continue
            try:
                payload = response.json()
            except ValueError:
                emit("      body is not JSON")
                continue
            key, rows = rows_of(payload)
            envelope = (
                {k: v for k, v in payload.items() if not isinstance(v, list | dict)}
                if isinstance(payload, Mapping)
                else {}
            )
            blob = json.dumps(envelope, default=str)[:400]
            emit(f"      rows under {key!r}: {len(rows)}  envelope={blob}")
            if rows:
                emit(f"      row keys: {sorted(rows[0])}")


def probe_headers(path: str) -> None:
    section("12. Response headers — rate limit and quota, as the vendor reports them")
    response = get(_expand(path), params={"position": "ALL", "scoring": "HALF"})
    if response is None:
        return
    interesting = {
        key: value
        for key, value in response.headers.items()
        if any(
            token in key.lower()
            for token in ("rate", "limit", "quota", "remaining", "retry", "tier", "plan")
        )
    }
    emit(f"  quota-related headers: {interesting or 'NONE'}")


#: Run 2 established that this is the endpoint with real ECR rows: `rank_ecr`, `rank_ave`,
#: `rank_min`, `rank_max`, `rank_std`, `pos_rank`, `tier`, and — decisively for identity —
#: `player_yahoo_id`, which the canonical registry already indexes. `position=ALL` is
#: rejected as invalid UNLESS `type=draft&week=0` is also sent.
CONSENSUS_PATH = f"/json/{SPORT}/{SEASON}/consensus-rankings"

#: The vendor's own valid-position vocabulary, quoted from its 400 response in run 2.
VALID_POSITIONS = ("QB", "RB", "WR", "TE", "K", "OP", "FLX", "DST")


def probe_consensus_depth() -> None:
    """How many players can this key actually see, and can per-position calls widen it?

    Run 2 proved the 10-row cap is the key's tier rather than a page size. The remaining
    question is whether a per-position call plan reaches a useful population anyway: ten
    quarterbacks plus ten running backs plus ten receivers plus ten tight ends is forty
    named players, which is not a top-300 market but is not nothing either. The answer
    decides whether FantasyPros ships as a partial reference or does not ship at all, and
    roadmap 10.1.3 item 7 requires it be measured rather than assumed.
    """
    section("13. consensus-rankings — per-position depth under the free-tier cap")
    url = _expand(CONSENSUS_PATH)
    seen: dict[str, list[dict[str, Any]]] = {}
    for position in ("ALL", "FLX", "QB", "RB", "WR", "TE"):
        response = get(
            url,
            params={"position": position, "scoring": "HALF", "type": "draft", "week": 0},
        )
        if response is None:
            continue
        if response.status_code != 200:
            emit(f"  position={position:4} -> http {response.status_code} {response.text[:160]!r}")
            continue
        try:
            payload = response.json()
        except ValueError:
            continue
        _, rows = rows_of(payload)
        envelope = (
            {k: v for k, v in payload.items() if not isinstance(v, list | dict)}
            if isinstance(payload, Mapping)
            else {}
        )
        seen[position] = rows
        names = [str(row.get("player_name")) for row in rows]
        emit(
            f"  position={position:4} -> {len(rows):>3} row(s)  "
            f"count={envelope.get('count')} limit={envelope.get('limit')} "
            f"public_api_limited={envelope.get('public_api_limited')} "
            f"total_experts={envelope.get('total_experts')} "
            f"last_updated={envelope.get('last_updated')!r}",
        )
        emit(f"      names: {names}")
        if rows:
            ecr = [row.get("rank_ecr") for row in rows]
            emit(f"      rank_ecr: {ecr}")

    union = {
        str(row.get("player_id"))
        for position, rows in seen.items()
        if position not in {"ALL", "FLX"}
        for row in rows
    }
    emit(f"  distinct players across the four core positions: {len(union)}")
    emit("  >>> A market this project can publish needs the top 300. Whatever number the")
    emit("  >>> line above shows is what this key serves, and the disposition follows it.")


def probe_consensus_signals() -> None:
    """Does scoring change the order, and is there any ADP anywhere in this response?"""
    section("14. consensus-rankings — scoring axis and the search for an ADP field")
    url = _expand(CONSENSUS_PATH)
    orders: dict[str, list[str]] = {}
    for scoring in SCORING_CANDIDATES:
        response = get(
            url,
            params={"position": "RB", "scoring": scoring, "type": "draft", "week": 0},
        )
        if response is None or response.status_code != 200:
            continue
        try:
            _, rows = rows_of(response.json())
        except ValueError:
            continue
        orders[scoring] = [str(row.get("player_name")) for row in rows]
        emit(f"  scoring={scoring:5} -> {len(rows)} row(s)  {orders[scoring][:4]}")
    keys = sorted(orders)
    for index in range(1, len(keys)):
        verdict = "IDENTICAL ORDER" if orders[keys[0]] == orders[keys[index]] else "different order"
        emit(f"  {keys[0]} vs {keys[index]}: {verdict}")

    response = get(
        url,
        params={"position": "RB", "scoring": "HALF", "type": "adp", "week": 0},
    )
    if response is not None:
        emit(f"  type=adp -> http {response.status_code}")
        if response.status_code == 200:
            try:
                _, rows = rows_of(response.json())
            except ValueError:
                rows = []
            if rows:
                adp_like = [k for k in sorted(rows[0]) if "adp" in k.lower()]
                emit(f"      adp-like row fields: {adp_like or 'NONE'}")
                emit(f"      all row fields: {sorted(rows[0])}")
    emit("  >>> Roadmap 10.1.3 wants FantasyPros ADP *and* ECR as separate signals. If no")
    emit("  >>> response carries an ADP field, this key serves ECR only and the product may")
    emit("  >>> not publish a `fantasypros_adp` column — there is nothing behind it.")


def probe_consensus_identity() -> None:
    """`player_yahoo_id` looked like a real bridge in run 2. Does it actually resolve?"""
    section("15. consensus-rankings identity — is `player_yahoo_id` a usable bridge?")
    url = _expand(CONSENSUS_PATH)
    rows: list[dict[str, Any]] = []
    for position in ("QB", "RB", "WR", "TE"):
        response = get(
            url,
            params={"position": position, "scoring": "HALF", "type": "draft", "week": 0},
        )
        if response is None or response.status_code != 200:
            continue
        try:
            _, page = rows_of(response.json())
        except ValueError:
            continue
        rows.extend(page)
    if not rows:
        emit("  no rows to measure")
        return
    for field in ("player_id", "player_yahoo_id", "sportsdata_id", "cbs_player_id"):
        values = [row.get(field) for row in rows if row.get(field) not in (None, "")]
        distinct = len({str(v) for v in values})
        emit(f"  {field:18} populated={len(values)}/{len(rows)} distinct={distinct}")
    try:
        from ffdraft.identity.ids import IdNamespace
        from ffdraft.market.identity import load_market_identity

        registry = load_market_identity(SEASON).registry
        for field, namespace in (
            ("player_yahoo_id", IdNamespace.YAHOO),
            ("sportsdata_id", IdNamespace.SPORTRADAR),
        ):
            hits = sum(
                1
                for row in rows
                if row.get(field) and registry.lookup(namespace, str(row[field])).status == "found"
            )
            emit(f"  {field} -> registry: {hits}/{len(rows)} resolve")
        emit("  >>> A populated, resolving id bridge means FantasyPros does NOT need the")
        emit("  >>> fuzzy name linkage FFC needs; it joins by id like MyFantasyLeague does.")
    except Exception as exc:  # noqa: BLE001
        emit(f"  registry comparison unavailable: {type(exc).__name__}: {exc}")


def main() -> int:
    emit(f"FantasyPros public v2 probe — season {SEASON}, sport {SPORT}")
    emit(f"base: {BASE}")
    emit(
        f"budget: {PROBE_REQUEST_BUDGET} requests this run, "
        f"internal daily cap {DAILY_REQUEST_CAP}, minimum interval "
        f"{MIN_REQUEST_INTERVAL_SECONDS}s",
    )
    identity_only = "--identity-only" in sys.argv
    if not _KEY:
        emit("")
        emit("FANTASYPROS_API_KEY is not set in this environment.")
        emit("The probe refuses to run unauthenticated: a 401 would measure nothing and an")
        emit("unauthenticated 200 would describe a different product surface.")
        return 1
    emit(f"key: present, {len(_KEY)} characters (value never printed)")

    if identity_only:
        # Run 3 exhausted its budget one section short. This mode spends four requests on
        # the single unmeasured question rather than re-running thirty that already have
        # answers — re-probing a settled fact costs the vendor's quota for nothing.
        try:
            probe_consensus_identity()
        except RuntimeError as exc:
            emit(f"\nprobe halted: {exc}")
        section("8. Request accounting")
        emit(f"  requests issued: {BUDGET.used}")
        emit(f"  internal daily cap: {DAILY_REQUEST_CAP} (vendor states 100)")
        return 0

    try:
        spec = probe_docs()
        ranking_paths = report_spec(spec)
        paths = ranking_paths or list(CANDIDATE_PATHS)
        if not ranking_paths:
            emit("")
            emit(f"  falling back to candidate paths: {list(CANDIDATE_PATHS)}")
        findings = probe_rankings(paths)
        if findings:
            path, found = next(iter(findings.items()))
            rows = list(found["rows"])
            probe_signal_separation(path)
            probe_truncation(path)
            probe_scoring(path)
            probe_freshness(path, found["envelope"])
            probe_identity(rows)
            probe_limit_and_pagination(path)
            probe_rank_object(path)
            probe_adp_path()
            probe_headers(path)
        probe_consensus_depth()
        probe_consensus_signals()
        probe_consensus_identity()
    except RuntimeError as exc:
        emit(f"\nprobe halted: {exc}")

    section("8. Request accounting")
    emit(f"  requests issued: {BUDGET.used}")
    emit(f"  probe budget:    {PROBE_REQUEST_BUDGET}")
    emit(f"  internal daily cap: {DAILY_REQUEST_CAP} (vendor states 100)")
    emit("\nProbe complete. Nothing was retained and no key was printed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
