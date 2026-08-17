#!/usr/bin/env python
"""Phase-0 source, legal, and feasibility probe.

This script is the executable evidence generator required by `docs/IMPLEMENTATION_PLAN.md`
Phase 0. It answers, empirically:

* does the documented access path exist and work today;
* what schema/record counts/freshness does it actually return;
* how far back does usable history go (per dataset / per market year);
* what do the current licence/terms/robots documents say (captured as short excerpts).

Design rules:

* Nothing here is allowed to *assume* an endpoint or schema. Every claim in the report is
  derived from a response that was actually received, or the check is recorded as failed.
* A failure caused by the local sandbox's egress policy is reported as ``blocked_egress``
  and must never be read as "the source is down" (see `docs/DECISIONS.md` ADR-009).
* Benchmark-only sources (FantasyPros-derived rankings) are probed for shape only; their
  rows are never written into the report or fixtures.
* FantasyCalc data is not ingested at all here: only its published terms page is read,
  because Phase 0 has to decide whether *any* access mechanism is permitted first.

Usage::

    uv run python scripts/source_probe.py --out docs/source-probes/$(date -u +%F)
    uv run python scripts/source_probe.py --only sleeper,mfl --no-fixtures
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

PROBE_SCHEMA_VERSION = "1.0"

USER_AGENT = (
    "jeisey-tiers-source-probe/0.1 "
    "(+https://github.com/jeisey/jeisey-tiers; non-commercial fantasy research) "
    "python-requests"
)

# Status vocabulary. Keep it small and unambiguous; the summary and the derived decisions
# both key off these exact strings.
OK = "ok"
EMPTY = "empty"
HTTP_ERROR = "http_error"
BLOCKED_EGRESS = "blocked_egress"
NETWORK_ERROR = "network_error"
PARSE_ERROR = "parse_error"
LOADER_ERROR = "loader_error"
SKIPPED = "skipped"

MAX_SAMPLE_ROWS = 2
MAX_EXCERPT_CHARS = 300
MAX_EXCERPTS = 5


# --------------------------------------------------------------------------------------
# Finding container
# --------------------------------------------------------------------------------------


@dataclass
class Finding:
    """One probe observation. Serialised verbatim into the report."""

    check_id: str
    source_id: str
    kind: str  # http | loader | package | rights
    target: str
    status: str
    question: str = ""
    http_status: int | None = None
    elapsed_ms: int | None = None
    content_type: str | None = None
    bytes_received: int | None = None
    record_count: int | None = None
    columns: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    freshness: dict[str, Any] = field(default_factory=dict)
    sample_rows: list[dict[str, Any]] = field(default_factory=list)
    excerpts: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    redistributable: bool = True
    # Full row set, kept in memory for follow-up analysis (e.g. the identity bridge) and
    # deliberately never serialised: the report carries schema and counts, not payloads.
    rows: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "check_id": self.check_id,
            "source_id": self.source_id,
            "kind": self.kind,
            "target": self.target,
            "status": self.status,
        }
        if self.question:
            out["question"] = self.question
        for key in (
            "http_status",
            "elapsed_ms",
            "content_type",
            "bytes_received",
            "record_count",
        ):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        for key in ("columns", "coverage", "freshness", "sample_rows", "excerpts", "notes"):
            value = getattr(self, key)
            if value:
                out[key] = value
        if not self.redistributable:
            out["redistributable"] = False
        return out


# --------------------------------------------------------------------------------------
# Pure helpers (unit-tested offline)
# --------------------------------------------------------------------------------------


def classify_request_exception(exc: BaseException) -> tuple[str, str]:
    """Map a requests exception onto a probe status.

    A sandboxed egress proxy answers ``403`` to ``CONNECT``, which surfaces as a proxy
    error rather than a source error. Phase 0 must not confuse the two.
    """
    text = f"{type(exc).__name__}: {exc}"
    lowered = text.lower()
    proxy_markers = (
        "tunnel connection failed",
        "proxyerror",
        "cannot connect to proxy",
        "403 forbidden",
    )
    if "proxy" in lowered and any(marker in lowered for marker in proxy_markers):
        return BLOCKED_EGRESS, text
    if "tunnel connection failed" in lowered:
        return BLOCKED_EGRESS, text
    return NETWORK_ERROR, text


def dtype_summary(frame: Any) -> list[dict[str, Any]]:
    """Column name/dtype/null-fraction summary for a polars DataFrame."""
    rows = frame.height
    summary: list[dict[str, Any]] = []
    for name, dtype in zip(frame.columns, frame.dtypes, strict=True):
        entry: dict[str, Any] = {"name": name, "dtype": str(dtype)}
        if rows:
            entry["null_fraction"] = round(frame[name].null_count() / rows, 4)
        summary.append(entry)
    return summary


def jsonable(value: Any) -> Any:
    """Best-effort conversion of loader values into JSON-safe primitives."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]
    return str(value)


def frame_sample(frame: Any, limit: int = MAX_SAMPLE_ROWS) -> list[dict[str, Any]]:
    """Deterministic head-sample of a polars DataFrame as JSON-safe dicts."""
    if frame.height == 0:
        return []
    return [
        {key: jsonable(val) for key, val in row.items()} for row in frame.head(limit).to_dicts()
    ]


def numeric_coverage(frame: Any, column: str) -> dict[str, Any]:
    """min/max/distinct summary for one column, if it exists."""
    if column not in frame.columns or frame.height == 0:
        return {}
    series = frame[column].drop_nulls()
    if series.len() == 0:
        return {}
    return {
        f"{column}_min": jsonable(series.min()),
        f"{column}_max": jsonable(series.max()),
        f"{column}_distinct": int(series.n_unique()),
    }


def strip_markup(text: str) -> str:
    """Crude HTML/whitespace flattener used only for terms/licence excerpting."""
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = text.replace("&amp;", "&").replace("&nbsp;", " ").replace("&#39;", "'")
    text = text.replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\s+", " ", text).strip()


def keyword_excerpts(
    text: str,
    keywords: Sequence[str],
    *,
    window: int = MAX_EXCERPT_CHARS,
    limit: int = MAX_EXCERPTS,
) -> list[str]:
    """Short keyword-anchored excerpts.

    Used to capture *evidence* of licence/terms wording without copying whole pages into
    the repository. Excerpts are deduplicated and capped.
    """
    flat = strip_markup(text)
    lowered = flat.lower()
    excerpts: list[str] = []
    for keyword in keywords:
        start = lowered.find(keyword.lower())
        if start < 0:
            continue
        left = max(0, start - window // 3)
        right = min(len(flat), start + window)
        snippet = flat[left:right].strip()
        if left > 0:
            snippet = f"...{snippet}"
        if right < len(flat):
            snippet = f"{snippet}..."
        if snippet not in excerpts:
            excerpts.append(snippet)
        if len(excerpts) >= limit:
            break
    return excerpts


def gsis_coverage(records: Iterable[dict[str, Any]], id_field: str) -> dict[str, Any]:
    """Fraction of records carrying a non-empty crosswalk id."""
    total = 0
    present = 0
    for record in records:
        total += 1
        value = record.get(id_field)
        if value not in (None, "", "0"):
            present += 1
    if not total:
        return {}
    return {
        f"{id_field}_present": present,
        f"{id_field}_total": total,
        f"{id_field}_fraction": round(present / total, 4),
    }


def _envelope_int(finding: Finding | None, key: str) -> int | None:
    """Read an integer out of a recorded MFL response envelope, if present."""
    if finding is None:
        return None
    envelope = finding.coverage.get("response_envelope")
    if not isinstance(envelope, dict):
        return None
    value = envelope.get(key)
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def derive_decisions(findings: Sequence[Finding]) -> dict[str, Any]:
    """Turn raw findings into the explicit Phase-0 decisions TASKS.md demands.

    Deliberately mechanical: the decision follows from observed statuses so a reader can
    re-derive it from the same report.
    """
    by_id = {f.check_id: f for f in findings}

    def status_of(check_id: str) -> str:
        finding = by_id.get(check_id)
        return finding.status if finding else "missing"

    mfl_current = status_of("mfl_adp_current_default")
    mfl_years = {
        f.check_id.rsplit("_", 1)[-1]: f for f in findings if f.check_id.startswith("mfl_adp_year_")
    }
    dense_years = sorted(
        year
        for year, finding in mfl_years.items()
        if finding.status == OK and (finding.record_count or 0) >= 100
    )
    # Rolling arbitrage evaluation needs train seasons *plus* >= 3 chronological holdouts.
    dense_enough = len(dense_years) >= 5

    # Volume alone is not enough. A learned arbitrage target needs the market *cost* as of a
    # draft-time anchor; a season-long aggregate recomputed today embeds in-season drafting
    # that already knows the outcome. Point-in-time capability counts as demonstrated only
    # if a window filter provably changes a historical aggregate.
    baseline = by_id.get(f"mfl_adp_year_{MFL_HISTORY_WINDOW_YEAR}")
    window_findings = [f for f in findings if f.check_id.startswith("mfl_adp_history_window_")]
    baseline_count = (baseline.record_count or 0) if baseline else 0
    baseline_drafts = _envelope_int(baseline, "totalDrafts") if baseline else None
    point_in_time = False
    window_evidence: list[str] = []
    for candidate in window_findings:
        drafts = _envelope_int(candidate, "totalDrafts")
        changed = candidate.status == OK and (
            (candidate.record_count or 0) != baseline_count
            or (drafts is not None and baseline_drafts is not None and drafts != baseline_drafts)
        )
        window_evidence.append(
            f"{candidate.check_id}: status={candidate.status} "
            f"records={candidate.record_count} totalDrafts={drafts} changed={changed}"
        )
        if changed and candidate.check_id.endswith(("days30", "days1", "days14")):
            point_in_time = True
    feasible = dense_enough and point_in_time
    injuries_current = [
        f for f in findings if f.check_id.startswith("nflverse_injuries_") and f.status == OK
    ]
    injury_years = sorted(
        f.check_id.rsplit("_", 1)[-1] for f in injuries_current if (f.record_count or 0) > 0
    )

    identity = by_id.get("identity_market_to_gsis_bridge")
    identity_fraction = (
        identity.coverage.get("resolved_fraction") if identity and identity.status == OK else None
    )

    return {
        "current_market_source_viable": mfl_current == OK,
        "current_market_source_status": mfl_current,
        "mfl_historical_years_with_data": dense_years,
        "mfl_history_dense_enough": dense_enough,
        "market_history_point_in_time_capable": point_in_time,
        "market_history_window_evidence": window_evidence,
        "arbitrage_ml_historical_feasible": feasible,
        "arbitrage_mode_recommended": "ml_candidate" if feasible else "baseline",
        "arbitrage_ml_feasibility_rule": (
            ">=5 historical MFL ADP years each with >=100 priced players AND demonstrated "
            "point-in-time windowing of a historical aggregate; volume alone is insufficient "
            "because a season-long aggregate embeds in-season drafting that already knows the "
            "outcome"
        ),
        "market_identity_resolved_fraction": identity_fraction,
        "market_identity_core_position_resolved_fraction": (
            identity.coverage.get("core_position_resolved_fraction")
            if identity and identity.status == OK
            else None
        ),
        "nflverse_injury_years_with_data": injury_years,
        "blocked_by_local_egress": sorted(
            {f.source_id for f in findings if f.status == BLOCKED_EGRESS}
        ),
        "checks_by_status": {
            status: sorted(f.check_id for f in findings if f.status == status)
            for status in sorted({f.status for f in findings})
        },
    }


# --------------------------------------------------------------------------------------
# HTTP probing
# --------------------------------------------------------------------------------------


class HttpProbe:
    """Thin, polite HTTP client used for every non-nflreadpy check."""

    def __init__(self, *, timeout: float = 30.0, sleep_seconds: float = 1.0) -> None:
        import requests

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "*/*"})
        self.timeout = timeout
        self.sleep_seconds = sleep_seconds
        self._last_call = 0.0

    def _pace(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if self._last_call and elapsed < self.sleep_seconds:
            time.sleep(self.sleep_seconds - elapsed)
        self._last_call = time.monotonic()

    def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> tuple[Any | None, Finding_partial]:
        """Return (response, partial finding fields)."""
        self._pace()
        started = time.monotonic()
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
        except BaseException as exc:  # noqa: BLE001 - classified, never swallowed silently
            status, detail = classify_request_exception(exc)
            return None, Finding_partial(
                status=status,
                elapsed_ms=int((time.monotonic() - started) * 1000),
                notes=[detail],
            )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        notes = []
        for header in ("retry-after", "x-ratelimit-limit", "x-ratelimit-remaining"):
            if header in response.headers:
                notes.append(f"{header}={response.headers[header]}")
        return response, Finding_partial(
            status=OK if response.ok else HTTP_ERROR,
            http_status=response.status_code,
            elapsed_ms=elapsed_ms,
            content_type=response.headers.get("content-type"),
            bytes_received=len(response.content),
            notes=notes,
            effective_url=response.url,
        )


@dataclass
class Finding_partial:  # noqa: N801 - intentionally reads as a partial Finding
    status: str
    http_status: int | None = None
    elapsed_ms: int | None = None
    content_type: str | None = None
    bytes_received: int | None = None
    notes: list[str] = field(default_factory=list)
    effective_url: str | None = None

    def apply(self, finding: Finding) -> Finding:
        finding.status = self.status
        finding.http_status = self.http_status
        finding.elapsed_ms = self.elapsed_ms
        finding.content_type = self.content_type
        finding.bytes_received = self.bytes_received
        finding.notes = [*finding.notes, *self.notes]
        if self.effective_url and self.effective_url != finding.target:
            finding.notes.append(f"effective_url={self.effective_url}")
        return finding


# --------------------------------------------------------------------------------------
# nflverse / nflreadpy probes
# --------------------------------------------------------------------------------------

# (check suffix, callable name, kwargs, question, extra analysis columns)
NflverseSpec = tuple[str, str, dict[str, Any], str]

NFLVERSE_SPECS: list[NflverseSpec] = [
    ("players", "load_players", {}, "Is there a player master with canonical gsis ids?"),
    (
        "ff_playerids",
        "load_ff_playerids",
        {},
        "Does the crosswalk cover gsis/sleeper/mfl/espn ids for identity joins?",
    ),
    ("teams", "load_teams", {}, "Team crosswalk for team-context features."),
    (
        "draft_picks",
        "load_draft_picks",
        {"seasons": True},
        "Draft capital history depth (rookie features).",
    ),
    ("combine", "load_combine", {"seasons": True}, "Athletic measure history depth."),
    (
        "player_stats_season_2012",
        "load_player_stats",
        {"seasons": [2012], "summary_level": "reg"},
        "How deep is season-level stat history for lagged features?",
    ),
    (
        "player_stats_season_2019",
        "load_player_stats",
        {"seasons": [2019], "summary_level": "reg"},
        "Season-level stats for a mid-history training season.",
    ),
    (
        "player_stats_season_2024",
        "load_player_stats",
        {"seasons": [2024], "summary_level": "reg"},
        "Season-level stats for a recent training season.",
    ),
    (
        "player_stats_season_2025",
        "load_player_stats",
        {"seasons": [2025], "summary_level": "reg"},
        "Are 2025 labels complete enough to serve as the final holdout season?",
    ),
    (
        "player_stats_weekly_2025",
        "load_player_stats",
        {"seasons": [2025], "summary_level": "week"},
        "Weekly grain for the documented weeks 1-17 fantasy horizon.",
    ),
    (
        "rosters_2012",
        "load_rosters",
        {"seasons": [2012]},
        "Roster universe depth for early training seasons.",
    ),
    ("rosters_2019", "load_rosters", {"seasons": [2019]}, "Roster universe, mid history."),
    ("rosters_2025", "load_rosters", {"seasons": [2025]}, "Roster universe, recent season."),
    (
        "rosters_2026",
        "load_rosters",
        {"seasons": [2026]},
        "Is the current (draft-target) season roster published yet?",
    ),
    (
        "rosters_weekly_2019",
        "load_rosters_weekly",
        {"seasons": [2019]},
        "Can a point-in-time roster be reconstructed for a historical anchor?",
    ),
    (
        "rosters_weekly_2025",
        "load_rosters_weekly",
        {"seasons": [2025]},
        "Weekly roster snapshots for the most recent completed season.",
    ),
    (
        "depth_charts_2019",
        "load_depth_charts",
        {"seasons": [2019]},
        "Does historical depth-chart data carry a week/date usable as an anchor?",
    ),
    (
        "depth_charts_2024",
        "load_depth_charts",
        {"seasons": [2024]},
        "Depth-chart schema stability in a recent season.",
    ),
    (
        "depth_charts_2025",
        "load_depth_charts",
        {"seasons": [2025]},
        "Depth-chart availability for the last completed season.",
    ),
    (
        "depth_charts_2026",
        "load_depth_charts",
        {"seasons": [2026]},
        "Is a current-season depth chart available for the live product?",
    ),
    (
        "snap_counts_2019",
        "load_snap_counts",
        {"seasons": [2019]},
        "Prior-season snap share feature availability.",
    ),
    (
        "snap_counts_2025",
        "load_snap_counts",
        {"seasons": [2025]},
        "Snap counts for the most recent completed season.",
    ),
    (
        "ff_opportunity_2019",
        "load_ff_opportunity",
        {"seasons": [2019], "stat_type": "weekly"},
        "Expected fantasy points coverage for training seasons.",
    ),
    (
        "ff_opportunity_2024",
        "load_ff_opportunity",
        {"seasons": [2024], "stat_type": "weekly"},
        "Expected points coverage, recent season.",
    ),
    (
        "ff_opportunity_2025",
        "load_ff_opportunity",
        {"seasons": [2025], "stat_type": "weekly"},
        "Is ffopportunity still being produced for the latest season?",
    ),
    (
        "injuries_2019",
        "load_injuries",
        {"seasons": [2019]},
        "Historical injury/status coverage for point-in-time reconstruction.",
    ),
    (
        "injuries_2024",
        "load_injuries",
        {"seasons": [2024]},
        "Injury coverage in the last season the spec believes is covered.",
    ),
    (
        "injuries_2025",
        "load_injuries",
        {"seasons": [2025]},
        "Did the nflverse injury feed really stop after 2024?",
    ),
    (
        "injuries_2026",
        "load_injuries",
        {"seasons": [2026]},
        "Is there any current-season injury report before the season starts?",
    ),
    (
        "ftn_charting_2025",
        "load_ftn_charting",
        {"seasons": [2025]},
        "FTN-derived data carries CC-BY-SA: is it present, and would we need it?",
    ),
    (
        "nextgen_receiving_2025",
        "load_nextgen_stats",
        {"seasons": [2025], "stat_type": "receiving"},
        "Optional advanced feature availability.",
    ),
    (
        "pfr_rec_season_2025",
        "load_pfr_advstats",
        {"seasons": [2025], "stat_type": "rec", "summary_level": "season"},
        "Optional advanced feature availability.",
    ),
    (
        "schedules_2026",
        "load_schedules",
        {"seasons": [2026]},
        "Current-season schedule for anchor/horizon logic.",
    ),
]

# Benchmark-only: shape may be recorded, rows may never be redistributed.
NFLVERSE_BENCHMARK_SPECS: list[NflverseSpec] = [
    (
        "ff_rankings_draft",
        "load_ff_rankings",
        {"type": "draft"},
        "Is a FantasyPros-derived consensus rank reachable for benchmark-only use?",
    ),
]

# Columns worth an explicit coverage summary per loader family.
COVERAGE_COLUMNS = ("season", "week", "game_type", "position", "dt", "date", "report_date")


def probe_nflverse(
    specs: Sequence[NflverseSpec],
    *,
    redistributable: bool = True,
) -> list[Finding]:
    findings: list[Finding] = []
    try:
        import nflreadpy as nfl
    except Exception as exc:  # noqa: BLE001
        return [
            Finding(
                check_id="nflverse_import",
                source_id="nflreadpy",
                kind="package",
                target="import nflreadpy",
                status=LOADER_ERROR,
                notes=[f"{type(exc).__name__}: {exc}"],
            )
        ]

    for suffix, loader_name, kwargs, question in specs:
        check_id = f"nflverse_{suffix}"
        loader = getattr(nfl, loader_name, None)
        target = f"nflreadpy.{loader_name}({json.dumps(kwargs, sort_keys=True)})"
        finding = Finding(
            check_id=check_id,
            source_id="nflreadpy",
            kind="loader",
            target=target,
            status=SKIPPED,
            question=question,
            redistributable=redistributable,
        )
        if loader is None:
            finding.status = LOADER_ERROR
            finding.notes.append(f"nflreadpy has no attribute {loader_name!r}")
            findings.append(finding)
            continue

        started = time.monotonic()
        try:
            frame = loader(**kwargs)
        except BaseException as exc:  # noqa: BLE001
            status, detail = classify_request_exception(exc)
            if status == NETWORK_ERROR:
                status = LOADER_ERROR
            finding.status = status
            finding.elapsed_ms = int((time.monotonic() - started) * 1000)
            finding.notes.append(detail)
            findings.append(finding)
            continue

        finding.elapsed_ms = int((time.monotonic() - started) * 1000)
        finding.record_count = int(frame.height)
        finding.columns = dtype_summary(frame)
        finding.status = OK if frame.height else EMPTY
        for column in COVERAGE_COLUMNS:
            finding.coverage.update(numeric_coverage(frame, column))
        if redistributable:
            finding.sample_rows = frame_sample(frame)
        else:
            finding.notes.append("rows suppressed: benchmark-only source, not redistributable")
        findings.append(finding)
    return findings


def probe_nflverse_meta() -> list[Finding]:
    """Record library version and its own view of the current season/week."""
    findings: list[Finding] = []
    try:
        import nflreadpy as nfl
    except Exception as exc:  # noqa: BLE001
        return [
            Finding(
                check_id="nflverse_meta",
                source_id="nflreadpy",
                kind="package",
                target="import nflreadpy",
                status=LOADER_ERROR,
                notes=[f"{type(exc).__name__}: {exc}"],
            )
        ]

    finding = Finding(
        check_id="nflverse_loader_surface",
        source_id="nflreadpy",
        kind="package",
        target="dir(nflreadpy)",
        status=OK,
        question="Which loader functions does the installed version actually expose?",
    )
    loaders = sorted(name for name in dir(nfl) if name.startswith("load_"))
    finding.notes.append(f"loaders={','.join(loaders)}")
    finding.notes.append(f"download_base_urls={json.dumps(_downloader_base_urls())}")
    findings.append(finding)

    season_finding = Finding(
        check_id="nflverse_current_season",
        source_id="nflreadpy",
        kind="package",
        target="nflreadpy.get_current_season()/get_current_week()",
        status=OK,
        question="What does the library consider the current season/week (anchor sanity)?",
    )
    try:
        season_finding.coverage = {
            "current_season": int(nfl.get_current_season()),
            "current_season_roster": int(nfl.get_current_season(roster=True)),
            "current_week": int(nfl.get_current_week()),
        }
    except BaseException as exc:  # noqa: BLE001
        season_finding.status = LOADER_ERROR
        season_finding.notes.append(f"{type(exc).__name__}: {exc}")
    findings.append(season_finding)
    return findings


def _downloader_base_urls() -> dict[str, str]:
    try:
        from nflreadpy.downloader import NflverseDownloader

        return dict(NflverseDownloader.BASE_URLS)
    except Exception:  # noqa: BLE001
        return {}


# --------------------------------------------------------------------------------------
# MyFantasyLeague probes
# --------------------------------------------------------------------------------------

MFL_BASE = "https://api.myfantasyleague.com"

# Parameter variants are exploratory on purpose: Phase 0 must discover which filters the
# 2026 ADP export really honours instead of trusting a remembered parameter list.
MFL_ADP_VARIANTS: list[tuple[str, dict[str, Any], str]] = [
    ("default", {}, "Does the bare ADP export work without any filters?"),
    (
        "ppr_12team",
        {"IS_PPR": 1, "FCOUNT": 12},
        "Are PPR/league-size cohort filters honoured?",
    ),
    (
        "std_10team",
        {"IS_PPR": 0, "FCOUNT": 10},
        "Are standard-scoring/10-team cohort filters honoured?",
    ),
    # The cohort filters are also probed one at a time: if a combined cohort returns
    # almost nothing we need to know which dimension is thin before designing presets.
    ("ppr_only", {"IS_PPR": 1}, "How much data does the PPR cohort alone carry?"),
    ("std_only", {"IS_PPR": 0}, "How much data does the standard-scoring cohort alone carry?"),
    ("fcount10", {"FCOUNT": 10}, "How much data does the 10-team cohort alone carry?"),
    ("fcount12", {"FCOUNT": 12}, "How much data does the 12-team cohort alone carry?"),
    ("fcount14", {"FCOUNT": 14}, "How much data does the 14-team cohort alone carry?"),
    (
        "no_mock_redraft",
        {"IS_MOCK": 0, "IS_KEEPER": "N"},
        "Can mock drafts and keeper leagues be excluded?",
    ),
    (
        "recent_14days",
        {"DAYS": 14},
        "Is there a date window filter that would make snapshots point-in-time?",
    ),
    (
        "recent_1day",
        {"DAYS": 1},
        "Does a one-day window actually shrink the sample (proof the filter is honoured)?",
    ),
    (
        "cutoff5",
        {"CUTOFF": 5},
        "Does a minimum-draft-appearance cutoff exist?",
    ),
]

MFL_HISTORY_YEARS = [2019, 2020, 2021, 2022, 2023, 2024, 2025]

# The arbitrage-ML question is not "is there historical ADP" but "can historical ADP be
# reduced to what the market believed at a draft-time anchor". These variants test, on one
# historical season, whether any window/date filter changes the aggregate at all.
MFL_HISTORY_WINDOW_YEAR = 2019
MFL_HISTORY_WINDOW_VARIANTS: list[tuple[str, dict[str, Any], str]] = [
    (
        "days30",
        {"DAYS": 30},
        "Does a day window applied to a past season change the aggregate?",
    ),
    (
        "no_mock_redraft",
        {"IS_MOCK": 0, "IS_KEEPER": "N"},
        "Do draft-type filters still work on a past season?",
    ),
]


def _mfl_records(payload: Any) -> list[dict[str, Any]]:
    """Extract ADP player rows from an MFL JSON payload without assuming nesting."""
    if not isinstance(payload, dict):
        return []
    for key in ("adp", "adpResults", "players"):
        node = payload.get(key)
        if isinstance(node, dict):
            for inner in ("player", "adpPlayer", "players"):
                rows = node.get(inner)
                if isinstance(rows, list):
                    return [r for r in rows if isinstance(r, dict)]
                if isinstance(rows, dict):
                    return [rows]
    return []


def _record_field_union(records: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    fields: dict[str, set[str]] = {}
    for record in records:
        for key, value in record.items():
            fields.setdefault(key, set()).add(type(value).__name__)
    return [
        {"name": name, "dtype": "|".join(sorted(types))} for name, types in sorted(fields.items())
    ]


def probe_mfl(http: HttpProbe, *, current_year: int) -> list[Finding]:
    findings: list[Finding] = []

    # 1. MFL's own developer documentation, which is also where its usage expectations live.
    for suffix, params, question, keywords in (
        (
            "all",
            {"JSON": 1},
            "What does MFL tell third-party developers about acceptable use and rates?",
            (
                "General Rules and Terms of Service",
                "forbidden",
                "Client Registration",
                "APIKEY",
                "requests per",
                "limit is",
                "429",
                "throttl",
                "cache",
                "commercial",
            ),
        ),
        (
            "adp",
            {"TYPE": "adp", "JSON": 1},
            "Does MFL self-document the ADP request parameters?",
            ("FCOUNT", "IS_PPR", "IS_KEEPER", "IS_MOCK", "CUTOFF", "DAYS", "PERIOD", "INJURED"),
        ),
    ):
        url = f"{MFL_BASE}/{current_year}/api_info"
        finding = Finding(
            check_id=f"mfl_api_info_{suffix}",
            source_id="myfantasyleague_adp",
            kind="rights" if suffix == "all" else "http",
            target=f"{url}?{_qs(params)}",
            status=SKIPPED,
            question=question,
        )
        response, partial = http.get(url, params=params)
        partial.apply(finding)
        if response is not None and response.ok:
            finding.excerpts = keyword_excerpts(
                response.text, keywords, window=400, limit=len(keywords)
            )
            if not finding.excerpts:
                finding.notes.append("no keyword match in document")
        findings.append(finding)

    # 2. Current-season ADP, across candidate filter variants.
    for suffix, extra, question in MFL_ADP_VARIANTS:
        params: dict[str, Any] = {"TYPE": "adp", "JSON": 1, **extra}
        findings.append(
            _probe_mfl_adp(
                http,
                check_id=f"mfl_adp_current_{suffix}",
                year=current_year,
                params=params,
                question=question,
            )
        )

    # 3. Historical seasons: the arbitrage-ML feasibility question.
    for year in MFL_HISTORY_YEARS:
        findings.append(
            _probe_mfl_adp(
                http,
                check_id=f"mfl_adp_year_{year}",
                year=year,
                params={"TYPE": "adp", "JSON": 1},
                question=f"Is {year} ADP still retrievable, and how many players are priced?",
            )
        )

    # 3b. Can a historical aggregate be windowed back to a draft-time anchor?
    for suffix, extra, question in MFL_HISTORY_WINDOW_VARIANTS:
        findings.append(
            _probe_mfl_adp(
                http,
                check_id=f"mfl_adp_history_window_{suffix}",
                year=MFL_HISTORY_WINDOW_YEAR,
                params={"TYPE": "adp", "JSON": 1, **extra},
                question=question,
            )
        )

    # 4. Player database (crosswalk ids for market-to-intrinsic joins).
    url = f"{MFL_BASE}/{current_year}/export"
    params = {"TYPE": "players", "DETAILS": 1, "JSON": 1}
    finding = Finding(
        check_id="mfl_players_details",
        source_id="myfantasyleague_adp",
        kind="http",
        target=f"{url}?{_qs(params)}",
        status=SKIPPED,
        question="Does the MFL player export expose crosswalk ids (gsis/espn/sportradar)?",
    )
    response, partial = http.get(url, params=params)
    partial.apply(finding)
    if response is not None and response.ok:
        try:
            payload = response.json()
        except ValueError as exc:
            finding.status = PARSE_ERROR
            finding.notes.append(f"json decode failed: {exc}")
        else:
            node = payload.get("players", {}) if isinstance(payload, dict) else {}
            records = node.get("player", []) if isinstance(node, dict) else []
            records = [r for r in records if isinstance(r, dict)]
            finding.record_count = len(records)
            finding.columns = _record_field_union(records[:2000])
            finding.sample_rows = [jsonable(r) for r in records[:MAX_SAMPLE_ROWS]]
            for id_field in ("gsis_id", "espn_id", "sportradar_id", "nfl_id", "id"):
                finding.coverage.update(gsis_coverage(records, id_field))
            if not records:
                finding.status = EMPTY
    findings.append(finding)

    return findings


def _probe_mfl_adp(
    http: HttpProbe,
    *,
    check_id: str,
    year: int,
    params: dict[str, Any],
    question: str,
) -> Finding:
    url = f"{MFL_BASE}/{year}/export"
    finding = Finding(
        check_id=check_id,
        source_id="myfantasyleague_adp",
        kind="http",
        target=f"{url}?{_qs(params)}",
        status=SKIPPED,
        question=question,
    )
    response, partial = http.get(url, params=params)
    partial.apply(finding)
    if response is None or not response.ok:
        return finding
    try:
        payload = response.json()
    except ValueError as exc:
        finding.status = PARSE_ERROR
        finding.notes.append(f"json decode failed: {exc}")
        finding.excerpts = keyword_excerpts(response.text[:2000], ["error", "adp"], limit=2)
        return finding

    if isinstance(payload, dict) and "error" in payload:
        finding.status = HTTP_ERROR
        finding.notes.append(f"api error payload: {jsonable(payload['error'])}")
        return finding

    records = _mfl_records(payload)
    finding.record_count = len(records)
    finding.columns = _record_field_union(records)
    finding.sample_rows = [jsonable(r) for r in records[:MAX_SAMPLE_ROWS]]
    finding.rows = records
    finding.status = OK if records else EMPTY
    envelope = {
        key: jsonable(value)
        for key, value in (payload.items() if isinstance(payload, dict) else [])
        if not isinstance(value, dict | list)
    }
    if isinstance(payload, dict):
        node = payload.get("adp")
        if isinstance(node, dict):
            envelope.update(
                {
                    key: jsonable(value)
                    for key, value in node.items()
                    if not isinstance(value, dict | list)
                }
            )
    if envelope:
        finding.coverage["response_envelope"] = envelope
    numeric = [
        float(r["averagePick"])
        for r in records
        if str(r.get("averagePick", "")).replace(".", "", 1).isdigit()
    ]
    if numeric:
        finding.coverage["averagePick_min"] = min(numeric)
        finding.coverage["averagePick_max"] = max(numeric)
    return finding


def _qs(params: dict[str, Any]) -> str:
    return "&".join(f"{key}={value}" for key, value in params.items())


# --------------------------------------------------------------------------------------
# Sleeper probes
# --------------------------------------------------------------------------------------

SLEEPER_BASE = "https://api.sleeper.app/v1"


def probe_sleeper(http: HttpProbe) -> list[Finding]:
    findings: list[Finding] = []

    state_finding = Finding(
        check_id="sleeper_state_nfl",
        source_id="sleeper",
        kind="http",
        target=f"{SLEEPER_BASE}/state/nfl",
        status=SKIPPED,
        question="What season/week/season_type does Sleeper report (anchor sanity)?",
    )
    response, partial = http.get(f"{SLEEPER_BASE}/state/nfl")
    partial.apply(state_finding)
    if response is not None and response.ok:
        try:
            payload = response.json()
        except ValueError as exc:
            state_finding.status = PARSE_ERROR
            state_finding.notes.append(str(exc))
        else:
            state_finding.coverage = jsonable(payload) if isinstance(payload, dict) else {}
    findings.append(state_finding)

    players_finding = Finding(
        check_id="sleeper_players_nfl",
        source_id="sleeper",
        kind="http",
        target=f"{SLEEPER_BASE}/players/nfl",
        status=SKIPPED,
        question=(
            "Does the player map still expose status/injury fields and a gsis crosswalk, "
            "and how large is the payload?"
        ),
    )
    response, partial = http.get(f"{SLEEPER_BASE}/players/nfl")
    partial.apply(players_finding)
    if response is not None and response.ok:
        try:
            payload = response.json()
        except ValueError as exc:
            players_finding.status = PARSE_ERROR
            players_finding.notes.append(str(exc))
        else:
            records = list(payload.values()) if isinstance(payload, dict) else []
            records = [r for r in records if isinstance(r, dict)]
            players_finding.record_count = len(records)
            players_finding.columns = _record_field_union(records[:3000])
            players_finding.status = OK if records else EMPTY
            for id_field in ("gsis_id", "espn_id", "sportradar_id", "player_id", "injury_status"):
                players_finding.coverage.update(gsis_coverage(records, id_field))
            skill = [
                r
                for r in records
                if r.get("position") in {"QB", "RB", "WR", "TE"}
                and (r.get("status") == "Active" or r.get("active") is True)
            ]
            players_finding.coverage["active_skill_position_records"] = len(skill)
            players_finding.coverage.update(
                {f"active_skill_{k}": v for k, v in gsis_coverage(skill, "gsis_id").items()}
            )
            players_finding.sample_rows = [
                jsonable(r) for r in skill[:MAX_SAMPLE_ROWS] or records[:MAX_SAMPLE_ROWS]
            ]
    findings.append(players_finding)

    trending_finding = Finding(
        check_id="sleeper_trending_add",
        source_id="sleeper",
        kind="http",
        target=f"{SLEEPER_BASE}/players/nfl/trending/add?lookback_hours=24&limit=25",
        status=SKIPPED,
        question="Is the optional trending endpoint available (attribution required if used)?",
    )
    response, partial = http.get(
        f"{SLEEPER_BASE}/players/nfl/trending/add",
        params={"lookback_hours": 24, "limit": 25},
    )
    partial.apply(trending_finding)
    if response is not None and response.ok:
        try:
            payload = response.json()
        except ValueError as exc:
            trending_finding.status = PARSE_ERROR
            trending_finding.notes.append(str(exc))
        else:
            records = (
                [r for r in payload if isinstance(r, dict)] if isinstance(payload, list) else []
            )
            trending_finding.record_count = len(records)
            trending_finding.columns = _record_field_union(records)
            trending_finding.sample_rows = [jsonable(r) for r in records[:MAX_SAMPLE_ROWS]]
            trending_finding.status = OK if records else EMPTY
    findings.append(trending_finding)

    return findings


# --------------------------------------------------------------------------------------
# Identity bridge probe: can market rows reach a canonical id without name matching?
# --------------------------------------------------------------------------------------

TOP_N_FOR_IDENTITY = 100
CORE_POSITIONS = frozenset({"QB", "RB", "WR", "TE"})


def probe_identity_bridge(http: HttpProbe, *, current_year: int) -> list[Finding]:
    """Measure whether priced market players can reach `gsis_id` by id alone.

    ADR-005 forbids name-only production joins, so the whole arbitrage join hinges on an
    id path existing from an MFL ADP row to a canonical player. Two independent bridges
    are possible, and both are measured because agreement between them is what lets
    Phase 1 fail closed instead of guessing:

    1. ``mfl_id`` -> ``load_ff_playerids()`` -> ``gsis_id``
    2. ``MFL players export espn_id`` -> ``load_rosters(current)`` -> ``gsis_id``
    """
    findings: list[Finding] = []
    finding = Finding(
        check_id="identity_market_to_gsis_bridge",
        source_id="identity",
        kind="loader",
        target="mfl adp -> {ff_playerids.mfl_id, rosters.espn_id} -> gsis_id",
        status=SKIPPED,
        question=(
            "Can priced market players be resolved to a canonical id without name matching, "
            "and do the two independent id bridges agree?"
        ),
    )

    adp = _probe_mfl_adp(
        http,
        check_id="identity_source_adp",
        year=current_year,
        params={"TYPE": "adp", "JSON": 1},
        question="market rows used for the identity measurement",
    )
    if adp.status != OK:
        finding.status = adp.status
        finding.notes.append(f"market rows unavailable: {adp.status}")
        return [finding]

    players = _mfl_player_index(http, current_year=current_year)

    try:
        import nflreadpy as nfl

        crosswalk = nfl.load_ff_playerids()
        rosters = nfl.load_rosters(seasons=[current_year])
    except BaseException as exc:  # noqa: BLE001
        status, detail = classify_request_exception(exc)
        finding.status = LOADER_ERROR if status == NETWORK_ERROR else status
        finding.notes.append(detail)
        return [finding]

    mfl_to_gsis = _id_map(crosswalk, "mfl_id", "gsis_id")
    espn_to_gsis = _id_map(rosters, "espn_id", "gsis_id")

    rows = adp.rows
    resolved_via_mfl = 0
    resolved_via_espn = 0
    resolved_either = 0
    agreed = 0
    disagreed = 0
    unresolved: list[str] = []
    top_resolved = 0
    top_total = 0
    # PRD section 21 states the identity threshold for modelled positions only, so the
    # core-position rate is tracked separately from the all-rows rate (MFL prices team
    # defences and kickers, which this product does not model in V1).
    core_total = 0
    core_resolved = 0
    unresolved_positions: dict[str, int] = {}

    for row in rows:
        mfl_id = str(row.get("id", "")).strip()
        rank = int(float(row.get("rank", 0) or 0))
        gsis_a = mfl_to_gsis.get(mfl_id.lstrip("0")) or mfl_to_gsis.get(mfl_id)
        espn_id = players.get(mfl_id, {}).get("espn_id")
        position = str(players.get(mfl_id, {}).get("position", "") or "unknown")
        gsis_b = espn_to_gsis.get(str(espn_id).strip()) if espn_id else None
        is_resolved = bool(gsis_a or gsis_b)
        if gsis_a:
            resolved_via_mfl += 1
        if gsis_b:
            resolved_via_espn += 1
        if is_resolved:
            resolved_either += 1
        else:
            unresolved_positions[position] = unresolved_positions.get(position, 0) + 1
            if len(unresolved) < 10:
                unresolved.append(f"mfl_id={mfl_id} rank={rank} position={position}")
        if gsis_a and gsis_b:
            if gsis_a == gsis_b:
                agreed += 1
            else:
                disagreed += 1
        if rank and rank <= TOP_N_FOR_IDENTITY:
            top_total += 1
            if is_resolved:
                top_resolved += 1
        if position in CORE_POSITIONS:
            core_total += 1
            if is_resolved:
                core_resolved += 1

    total = len(rows)
    finding.status = OK if total else EMPTY
    finding.record_count = total
    finding.coverage = {
        "priced_players": total,
        "resolved_via_mfl_id_bridge": resolved_via_mfl,
        "resolved_via_espn_id_bridge": resolved_via_espn,
        "resolved_by_either_bridge": resolved_either,
        "resolved_fraction": round(resolved_either / total, 4) if total else 0.0,
        "core_position_priced": core_total,
        "core_position_resolved": core_resolved,
        "core_position_resolved_fraction": (
            round(core_resolved / core_total, 4) if core_total else None
        ),
        "both_bridges_agree": agreed,
        "both_bridges_disagree": disagreed,
        f"top{TOP_N_FOR_IDENTITY}_priced": top_total,
        f"top{TOP_N_FOR_IDENTITY}_resolved": top_resolved,
        "unresolved_by_position": dict(sorted(unresolved_positions.items())),
        "crosswalk_rows": int(crosswalk.height),
        "roster_rows": int(rosters.height),
        "mfl_player_index_rows": len(players),
    }
    if unresolved:
        finding.notes.append("unresolved sample: " + "; ".join(unresolved))
    findings.append(finding)
    return findings


def _mfl_player_index(http: HttpProbe, *, current_year: int) -> dict[str, dict[str, Any]]:
    """MFL player id -> record, used to reach the ESPN id the export publishes."""
    response, _partial = http.get(
        f"{MFL_BASE}/{current_year}/export",
        params={"TYPE": "players", "DETAILS": 1, "JSON": 1},
    )
    if response is None or not response.ok:
        return {}
    try:
        payload = response.json()
    except ValueError:
        return {}
    node = payload.get("players", {}) if isinstance(payload, dict) else {}
    records = node.get("player", []) if isinstance(node, dict) else []
    return {
        str(record["id"]).strip(): record
        for record in records
        if isinstance(record, dict) and record.get("id")
    }


def _id_map(frame: Any, left: str, right: str) -> dict[str, str]:
    """Build a left-id -> right-id map, dropping blanks and ambiguous duplicates.

    Ambiguity fails closed: an id that maps to two different canonical ids is dropped
    rather than resolved arbitrarily (ADR-005).
    """
    if left not in frame.columns or right not in frame.columns:
        return {}
    mapping: dict[str, str] = {}
    ambiguous: set[str] = set()
    for left_value, right_value in zip(frame[left].to_list(), frame[right].to_list(), strict=True):
        if left_value is None or right_value is None:
            continue
        key = str(left_value).strip()
        value = str(right_value).strip()
        if not key or not value or key in ambiguous:
            continue
        existing = mapping.get(key)
        if existing and existing != value:
            del mapping[key]
            ambiguous.add(key)
            continue
        mapping[key] = value
    return mapping


# --------------------------------------------------------------------------------------
# Rights / terms / robots probes
# --------------------------------------------------------------------------------------

LICENSE_KEYWORDS = (
    "CC BY",
    "CC-BY",
    "Creative Commons",
    "ShareAlike",
    "MIT",
    "GPL",
    "licen",
    "attribut",
)
TERMS_KEYWORDS = (
    "commercial",
    "non-commercial",
    "noncommercial",
    "redistribut",
    "scrape",
    "rate limit",
    "attribut",
    "permission",
    "copyright",
)

# (check_id, source_id, url, keywords, question)
RIGHTS_TARGETS: list[tuple[str, str, str, Sequence[str], str]] = [
    (
        "rights_nflreadpy_license",
        "nflreadpy",
        "https://raw.githubusercontent.com/nflverse/nflreadpy/main/LICENSE.md",
        LICENSE_KEYWORDS,
        "What licence covers the nflreadpy client code?",
    ),
    (
        "rights_nflreadpy_readme_data_license",
        "nflreadpy",
        "https://raw.githubusercontent.com/nflverse/nflreadpy/main/README.md",
        ("CC-BY", "CC BY", "FTN", "ShareAlike", "licen"),
        "What does the client say about the licence of the *data* it downloads?",
    ),
    (
        "rights_nflreadr_terms_of_use",
        "nflreadpy",
        "https://raw.githubusercontent.com/nflverse/nflreadr/main/README.md",
        ("Terms of Use", "licen", "belong to their respective owners"),
        "What terms does the nflverse reader project attach to the underlying NFL data?",
    ),
    (
        "rights_nflverse_data_readme",
        "nflreadpy",
        "https://raw.githubusercontent.com/nflverse/nflverse-data/master/README.md",
        (*LICENSE_KEYWORDS, "releases", "automation"),
        "What does the nflverse-data repository say about data licensing/attribution?",
    ),
    (
        "rights_nflverse_update_schedule",
        "nflreadpy",
        "https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html",
        ("roster", "depth", "injur", "nextgen", "pfr", "UTC"),
        "What refresh cadence should the daily workflow assume?",
    ),
    (
        "rights_ffopportunity_description",
        "ffopportunity",
        "https://raw.githubusercontent.com/ffverse/ffopportunity/main/DESCRIPTION",
        LICENSE_KEYWORDS,
        "What licence does ffopportunity declare?",
    ),
    (
        "rights_ffopportunity_readme",
        "ffopportunity",
        "https://raw.githubusercontent.com/ffverse/ffopportunity/main/README.md",
        LICENSE_KEYWORDS,
        "What attribution does ffopportunity request for its expected-points data?",
    ),
    (
        "rights_dynastyprocess_readme",
        "fantasypros_ecr_via_dynastyprocess",
        "https://raw.githubusercontent.com/dynastyprocess/data/master/README.md",
        (*LICENSE_KEYWORDS, "FantasyPros"),
        "What does the FantasyPros-derived ranking mirror say about ownership/reuse?",
    ),
    (
        "rights_sleeper_docs",
        "sleeper",
        "https://docs.sleeper.com/",
        (*TERMS_KEYWORDS, "1000 API calls", "cache"),
        "What rate/attribution/caching guidance does Sleeper publish?",
    ),
    (
        "rights_sleeper_robots",
        "sleeper",
        "https://api.sleeper.app/robots.txt",
        ("Disallow", "User-agent"),
        "Does the API host publish crawl restrictions?",
    ),
    (
        "rights_mfl_developer_page",
        "myfantasyleague_adp",
        "https://myfantasyleague.wordpress.com/2008/08/06/developer-api/",
        TERMS_KEYWORDS,
        "What does MFL say about third-party use of its developer API?",
    ),
    (
        "rights_mfl_robots",
        "myfantasyleague_adp",
        "https://api.myfantasyleague.com/robots.txt",
        ("Disallow", "User-agent"),
        "Does the MFL API host publish crawl restrictions?",
    ),
    (
        "rights_mfl_terms",
        "myfantasyleague_adp",
        "https://www.myfantasyleague.com/terms.html",
        TERMS_KEYWORDS,
        "Are there published MFL terms constraining derived-data publication?",
    ),
    (
        "rights_fantasycalc_terms",
        "fantasycalc",
        "https://fantasycalc.com/terms-of-usage",
        TERMS_KEYWORDS,
        "Do FantasyCalc's current terms permit non-commercial reuse, and by what mechanism?",
    ),
    (
        "rights_fantasycalc_robots",
        "fantasycalc",
        "https://fantasycalc.com/robots.txt",
        ("Disallow", "User-agent"),
        "Does FantasyCalc restrict automated access?",
    ),
    (
        "rights_fantasypros_terms",
        "fantasypros_ecr_via_dynastyprocess",
        "https://www.fantasypros.com/terms-of-use/",
        TERMS_KEYWORDS,
        "Do FantasyPros terms permit even internal benchmark use of derived ranks?",
    ),
]


def probe_rights(http: HttpProbe) -> list[Finding]:
    findings: list[Finding] = []
    for check_id, source_id, url, keywords, question in RIGHTS_TARGETS:
        finding = Finding(
            check_id=check_id,
            source_id=source_id,
            kind="rights",
            target=url,
            status=SKIPPED,
            question=question,
        )
        response, partial = http.get(url)
        partial.apply(finding)
        if response is not None and response.ok:
            finding.excerpts = keyword_excerpts(response.text, keywords)
            if not finding.excerpts:
                finding.notes.append("no keyword match in document")
        findings.append(finding)
    return findings


# --------------------------------------------------------------------------------------
# Report writing
# --------------------------------------------------------------------------------------


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _package_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in ("nflreadpy", "polars", "requests"):
        try:
            versions[name] = version(name)
        except PackageNotFoundError:
            versions[name] = "not-installed"
    return versions


def build_report(
    findings: Sequence[Finding], *, started_at: str, finished_at: str
) -> dict[str, Any]:
    ordered = sorted(findings, key=lambda f: (f.source_id, f.check_id))
    return {
        "probe_schema_version": PROBE_SCHEMA_VERSION,
        "run": {
            "started_at_utc": started_at,
            "finished_at_utc": finished_at,
            "git_sha": _git_sha(),
            "user_agent": USER_AGENT,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "environment": (
                "github-actions" if os.environ.get("GITHUB_ACTIONS") == "true" else "local"
            ),
            "package_versions": _package_versions(),
        },
        "decisions": derive_decisions(ordered),
        "findings": [f.to_dict() for f in ordered],
    }


def render_summary(report: dict[str, Any]) -> str:
    run = report["run"]
    decisions = report["decisions"]
    lines = [
        "# Source probe summary",
        "",
        f"- run environment: `{run['environment']}`",
        f"- started (UTC): `{run['started_at_utc']}`",
        f"- finished (UTC): `{run['finished_at_utc']}`",
        f"- git sha: `{run['git_sha']}`",
        f"- python: `{run['python']}`",
        "- package versions: "
        + ", ".join(f"`{k}=={v}`" for k, v in sorted(run["package_versions"].items())),
        "",
        "## Derived decisions",
        "",
        f"- current market source viable: **{decisions['current_market_source_viable']}** "
        f"(`{decisions['current_market_source_status']}`)",
        "- MFL historical years returning >=100 priced players: "
        + (", ".join(decisions["mfl_historical_years_with_data"]) or "none"),
        f"- history dense enough: **{decisions['mfl_history_dense_enough']}**; "
        f"point-in-time capable: **{decisions['market_history_point_in_time_capable']}**",
        "- `arbitrage_ml_historical_feasible`: "
        f"**{decisions['arbitrage_ml_historical_feasible']}** "
        f"-> arbitrage mode **{decisions['arbitrage_mode_recommended']}**",
        f"  - rule: {decisions['arbitrage_ml_feasibility_rule']}",
        *(f"  - {line}" for line in decisions["market_history_window_evidence"]),
        "- market rows resolved to a canonical id without name matching: "
        f"**{decisions['market_identity_resolved_fraction']}** all priced, "
        f"**{decisions['market_identity_core_position_resolved_fraction']}** QB/RB/WR/TE",
        "- nflverse injury years with rows: "
        + (", ".join(decisions["nflverse_injury_years_with_data"]) or "none"),
        "- sources blocked by local egress policy: "
        + (", ".join(decisions["blocked_by_local_egress"]) or "none"),
        "",
        "## Findings",
        "",
        "| check | source | status | records | notes |",
        "| --- | --- | --- | --- | --- |",
    ]
    for finding in report["findings"]:
        note = "; ".join(finding.get("notes", []))[:160].replace("|", "/")
        lines.append(
            f"| `{finding['check_id']}` | {finding['source_id']} | {finding['status']} | "
            f"{finding.get('record_count', '')} | {note} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_fixtures(findings: Sequence[Finding], fixtures_dir: Path) -> list[Path]:
    """Write tiny schema fixtures for adapter tests (Phase 1 consumes these)."""
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    wanted = {
        "nflverse_players",
        "nflverse_ff_playerids",
        "nflverse_player_stats_season_2024",
        "nflverse_depth_charts_2024",  # pre-2025 weekly format
        "nflverse_depth_charts_2025",  # 2025+ timestamped-snapshot format
        "nflverse_rosters_2026",
        "nflverse_injuries_2025",
        "nflverse_ff_opportunity_2024",
        "mfl_adp_current_default",
        "mfl_players_details",
        "sleeper_players_nfl",
        "sleeper_state_nfl",
    }
    for finding in findings:
        if finding.check_id not in wanted or finding.status != OK:
            continue
        payload = {
            "check_id": finding.check_id,
            "source_id": finding.source_id,
            "target": finding.target,
            "captured_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "record_count": finding.record_count,
            "columns": finding.columns,
            "coverage": finding.coverage,
            "sample_rows": finding.sample_rows if finding.redistributable else [],
        }
        path = fixtures_dir / f"{finding.check_id}.schema.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(path)
    return written


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase-0 source/legal/feasibility probe (see module docstring).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output directory (default docs/source-probes/<UTC date>)",
    )
    parser.add_argument(
        "--only",
        default="nflverse,mfl,sleeper,identity,rights",
        help="comma-separated groups to run: nflverse,mfl,sleeper,identity,rights",
    )
    parser.add_argument(
        "--current-year",
        type=int,
        default=datetime.now(UTC).year,
        help="market season to treat as current",
    )
    parser.add_argument("--sleep", type=float, default=1.0, help="seconds between HTTP requests")
    parser.add_argument("--timeout", type=float, default=60.0, help="HTTP timeout seconds")
    parser.add_argument("--no-fixtures", action="store_true", help="do not write schema fixtures")
    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=REPO_ROOT / "tests" / "fixtures" / "source_schemas",
    )
    args = parser.parse_args(argv)

    groups = {g.strip() for g in args.only.split(",") if g.strip()}
    started_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    out_dir = args.out or (
        REPO_ROOT / "docs" / "source-probes" / datetime.now(UTC).strftime("%Y-%m-%d")
    )

    os.environ.setdefault("NFLREADPY_USER_AGENT", USER_AGENT)
    os.environ.setdefault("NFLREADPY_CACHE", "filesystem")

    findings: list[Finding] = []
    if "nflverse" in groups:
        print("[probe] nflverse/nflreadpy ...", flush=True)
        findings += probe_nflverse_meta()
        findings += probe_nflverse(NFLVERSE_SPECS)
        findings += probe_nflverse(NFLVERSE_BENCHMARK_SPECS, redistributable=False)
    http = HttpProbe(timeout=args.timeout, sleep_seconds=args.sleep)
    if "mfl" in groups:
        print("[probe] myfantasyleague ...", flush=True)
        findings += probe_mfl(http, current_year=args.current_year)
    if "sleeper" in groups:
        print("[probe] sleeper ...", flush=True)
        findings += probe_sleeper(http)
    if "identity" in groups:
        print("[probe] identity bridge (market -> gsis) ...", flush=True)
        findings += probe_identity_bridge(http, current_year=args.current_year)
    if "rights" in groups:
        print("[probe] rights/terms/robots ...", flush=True)
        findings += probe_rights(http)

    finished_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    report = build_report(findings, started_at=started_at, finished_at=finished_at)

    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    summary_path = out_dir / "summary.md"
    summary_path.write_text(render_summary(report), encoding="utf-8")
    print(f"[probe] wrote {report_path}")
    print(f"[probe] wrote {summary_path}")

    if not args.no_fixtures:
        written = write_fixtures(findings, args.fixtures_dir)
        for path in written:
            print(f"[probe] wrote fixture {path}")

    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.status] = counts.get(finding.status, 0) + 1
    print("[probe] status counts: " + json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
