"""Render the production refresh summary that `docs/OPERATIONS.md` section 10 asks for.

This is a script rather than eighty lines of shell inside a workflow for three reasons: the
numbers come from JSON that already exists, a mistake here should be a red test rather than a
malformed summary, and the same renderer serves the daily refresh, the forced-failure proof
and a local dry run.

It reads only generated artifacts and the retained store's own manifests. It never reads a
secret, an environment variable holding one, or the token the store checkout was made with;
the workflow passes the handful of run-scoped facts it knows through ``--fact``.

    uv run python scripts/workflow_summary.py \
        --artifacts web/public/data --store market-data \
        --fact pages_url=https://example.github.io/repo/
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

# Facts the workflow supplies, in the order they should be printed, with their labels. A
# fact that is absent is omitted rather than rendered as "unknown", because a summary that
# invents an empty row is harder to read than one that is short.
RUN_FACTS: tuple[tuple[str, str], ...] = (
    ("trigger", "Trigger"),
    ("forced_failure", "Forced-failure proof"),
    ("run_url", "Workflow run"),
    ("code_sha", "Code SHA"),
    ("capture_result", "Source capture"),
    ("store_repository", "Retained store"),
    ("store_commit_before", "Store commit (before)"),
    ("store_commit", "Store commit (after)"),
    ("store_appended", "Store appended"),
    ("deploy_result", "Pages deployment"),
    ("pages_url", "Pages URL"),
)


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _records(envelope: Any) -> list[Mapping[str, Any]]:
    if isinstance(envelope, Mapping):
        records = envelope.get("records")
        if isinstance(records, list):
            return [row for row in records if isinstance(row, Mapping)]
    return []


def _table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    if not rows:
        return []
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join(["---"] * len(header)) + "|"]
    lines.extend("| " + " | ".join(cell for cell in row) + " |" for row in rows)
    lines.append("")
    return lines


def _run_section(facts: Mapping[str, str]) -> list[str]:
    rows = [(label, f"`{facts[key]}`") for key, label in RUN_FACTS if facts.get(key)]
    return _table(("", ""), rows)


def _build_section(metadata: Mapping[str, Any]) -> list[str]:
    """Build identity: what code, what model, what methodology produced these bytes."""
    rows = [
        ("Build id", str(metadata.get("build_id", "—"))),
        ("Generated at", str(metadata.get("generated_at_utc", "—"))),
        ("Season", str(metadata.get("season", "—"))),
        ("Intrinsic model", str(metadata.get("intrinsic_model_version", "—"))),
        ("Methodology", str(metadata.get("methodology_version", "—"))),
        (
            "Arbitrage",
            f"{metadata.get('arbitrage_mode', '—')} "
            f"({metadata.get('arbitrage_method_version', '—')})",
        ),
        ("Presets", ", ".join(str(p) for p in metadata.get("supported_presets", [])) or "—"),
    ]
    return ["### Build", ""] + _table(("", ""), [(k, f"`{v}`") for k, v in rows])


def _source_section(metadata: Mapping[str, Any]) -> list[str]:
    sources = metadata.get("sources")
    if not isinstance(sources, list):
        return []
    rows = []
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        warnings = source.get("warnings") or []
        rows.append(
            (
                str(source.get("source_id", "—")),
                str(source.get("status", "—")).upper(),
                str(source.get("retrieved_at_utc") or "—"),
                str(source.get("source_as_of_utc") or "—"),
                str(source.get("record_count", "—")),
                str(len(warnings)) if isinstance(warnings, list) else "—",
            ),
        )
    header = ("source", "status", "retrieved (UTC)", "source as-of", "records", "warnings")
    return ["### Sources", ""] + _table(header, rows)


def _market_section(metadata: Mapping[str, Any], arbitrage: Any) -> list[str]:
    market = metadata.get("market")
    lines: list[str] = ["### Market", ""]
    if isinstance(market, Mapping):
        lines.extend(
            _table(
                ("", ""),
                [
                    ("Source", f"`{market.get('source_id', '—')}`"),
                    ("Snapshot", f"`{market.get('snapshot_key', '—')}`"),
                    ("Snapshot at", f"`{market.get('snapshot_at_utc', '—')}`"),
                    ("Cohort rule", f"`{market.get('cohort_rule_version', '—')}`"),
                    (
                        "Trend",
                        "`available`" if market.get("trend_available") else "`null (ADR-042)`",
                    ),
                ],
            ),
        )
        assignments = market.get("assignments")
        if isinstance(assignments, list) and assignments:
            rows = []
            for item in assignments:
                if not isinstance(item, Mapping):
                    continue
                failed = item.get("failed_clauses") or []
                rows.append(
                    (
                        f"{item.get('scoring_preset', '—')}/{item.get('league_size', '—')}",
                        str(item.get("cohort_id", "—")),
                        "exact" if item.get("exact") else "approximate",
                        "yes" if item.get("sufficient") else "**no**",
                        ", ".join(str(clause) for clause in failed) if failed else "—",
                    ),
                )
            header = ("preset", "cohort", "match", "sufficient", "failed clauses")
            lines.extend(["**Cohort selected per preset**", ""])
            lines.extend(_table(header, rows))

    records = _records(arbitrage)
    if records:
        confidence = Counter(str(row.get("confidence", "—")) for row in records)
        samples = sorted(
            int(row["market_sample_size"])
            for row in records
            if isinstance(row.get("market_sample_size"), int | float)
        )
        median = f"{samples[len(samples) // 2]}" if samples else "—"
        cohorts = sorted({str(row.get("market_cohort_id", "—")) for row in records})
        lines.extend(
            _table(
                ("", ""),
                [
                    ("Priced rows", f"`{len(records)}`"),
                    (
                        "Confidence",
                        ", ".join(f"`{k}` {v}" for k, v in sorted(confidence.items())),
                    ),
                    ("Median per-player sample", f"`{median}` drafts"),
                    ("Cohorts used", ", ".join(f"`{c}`" for c in cohorts)),
                ],
            ),
        )
    return lines


def _identity_section(store: Path | None, metadata: Mapping[str, Any]) -> list[str]:
    """Identity coverage is a per-cohort fact in the manifest the capture wrote.

    It is deliberately reported over the population the manifest counts rather than
    recomputed here: ADR-039's clarification is that a coverage number only means something
    beside the population it was measured on.
    """
    market = metadata.get("market")
    if store is None or not isinstance(market, Mapping):
        return []
    source_id = str(market.get("source_id", ""))
    season = metadata.get("season")
    key = str(market.get("snapshot_key", ""))
    if not (source_id and season and key):
        return []
    manifest = _read_json(store / "market" / source_id / str(season) / key / "manifest.json")
    if not isinstance(manifest, Mapping):
        return []
    cohorts = manifest.get("cohorts")
    if not isinstance(cohorts, list):
        return []
    rows = []
    for cohort in sorted(
        (c for c in cohorts if isinstance(c, Mapping)),
        key=lambda c: str(c.get("cohort_id", "")),
    ):
        resolvable = cohort.get("resolvable_players")
        resolved = cohort.get("resolved_players")
        coverage = (
            f"{resolved / resolvable:.3f}"
            if isinstance(resolvable, int | float)
            and isinstance(resolved, int | float)
            and resolvable
            else "—"
        )
        rows.append(
            (
                f"`{cohort.get('cohort_id', '—')}`",
                str(cohort.get("total_drafts", "—")),
                str(cohort.get("row_count", "—")),
                f"{resolved}/{resolvable}",
                coverage,
                str(cohort.get("ambiguous_players", "—")),
            ),
        )
    header = ("cohort", "drafts", "rows", "resolved", "coverage", "ambiguous")
    lines = ["### Retained capture — identity and volume", ""]
    lines.extend(_table(header, rows))
    lines.append(
        "Coverage is over each cohort's *resolvable* priced players; MFL also prices "
        "kickers, team defences and IDP (ADR-039 clarification).",
    )
    lines.append("")
    return lines


def _artifact_section(artifacts: Path, metadata: Mapping[str, Any]) -> list[str]:
    rows = []
    for name in ("tiers", "projections", "arbitrage", "player_status"):
        envelope = _read_json(artifacts / f"{name}.json")
        count = len(_records(envelope)) if envelope is not None else None
        rows.append((f"`{name}.json`", str(count) if count is not None else "**absent**"))
    status = metadata.get("player_status")
    if isinstance(status, Mapping):
        rows.append(
            (
                "player status matched",
                f"{status.get('sleeper_matched', '—')} of {status.get('players', '—')} via Sleeper",
            ),
        )
    return ["### Artifacts", ""] + _table(("artifact", "records"), rows)


def _quality_section(metadata: Mapping[str, Any]) -> list[str]:
    gate = metadata.get("quality_gate")
    lines: list[str] = ["### Quality gate", ""]
    if isinstance(gate, Mapping):
        verdict = str(gate.get("status", "—")).upper()
        lines.append(
            f"**{verdict}** — {gate.get('critical_failures', '—')} critical, "
            f"{gate.get('warnings', '—')} warnings.",
        )
        lines.append("")
    warnings = metadata.get("warnings")
    if isinstance(warnings, list) and warnings:
        lines.append("<details><summary>Warnings recorded in this build</summary>")
        lines.append("")
        lines.extend(f"- {warning}" for warning in warnings)
        lines.extend(["", "</details>", ""])
    return lines


def render(
    artifacts: Path,
    store: Path | None,
    facts: Mapping[str, str],
    title: str,
) -> str:
    lines = [f"## {title}", ""]
    lines.extend(_run_section(facts))

    metadata = _read_json(artifacts / "build_metadata.json")
    if not isinstance(metadata, Mapping):
        lines.extend(
            [
                f"No `build_metadata.json` under `{artifacts}`.",
                "",
                "That is the expected shape of this summary when a gate before the artifact "
                "build failed: **nothing was generated, so nothing could be deployed** and "
                "the previously deployed site is still live.",
                "",
            ],
        )
        return "\n".join(lines) + "\n"

    lines.extend(_build_section(metadata))
    lines.extend(_source_section(metadata))
    lines.extend(_market_section(metadata, _read_json(artifacts / "arbitrage.json")))
    lines.extend(_identity_section(store, metadata))
    lines.extend(_artifact_section(artifacts, metadata))
    lines.extend(_quality_section(metadata))
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, default=Path("web/public/data"))
    parser.add_argument("--store", type=Path, default=None)
    parser.add_argument("--title", default="Daily refresh")
    parser.add_argument("--out", type=Path, default=None, help="write here as well as stdout")
    parser.add_argument(
        "--fact",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="a run-scoped fact the workflow knows and the artifacts do not",
    )
    args = parser.parse_args(argv)

    facts: dict[str, str] = {}
    for item in args.fact:
        key, _, value = str(item).partition("=")
        if key and value:
            facts[key.strip()] = value.strip()

    store = args.store if args.store and args.store.exists() else None
    text = render(args.artifacts, store, facts, args.title)
    print(text, end="")
    if args.out is not None:
        with args.out.open("a", encoding="utf-8") as handle:
            handle.write(text)
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through tests/unit
    raise SystemExit(main())
