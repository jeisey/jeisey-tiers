"""Semantic and data-domain checks.

Phase 1 detects **structural** drift: a column an adapter reads disappears, a dtype changes,
a primary key duplicates. That catches the loud failures. It cannot catch the quiet one -
a column that keeps its name and its type while its *meaning* changes. A snap percentage
that starts arriving as 0-100 instead of 0-1, a position vocabulary that gains a code, a
counting stat that goes negative because a sign convention flipped: every one of those
passes a structural check and silently poisons a model.

These checks close that gap as far as it can be closed. They cannot make semantic drift
impossible - nothing can - but they make a silent meaning change substantially harder,
because a value that violates its documented domain now produces a record instead of a
number.

Everything here returns :class:`~ffdraft.contracts.quality.QualityCheck` records, as
`docs/ARCHITECTURE.md` section 12 requires, so a build collects the whole picture before
deciding once whether to stop. None of them raises.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import cast

import polars as pl

from ffdraft.contracts import QualityCheck
from ffdraft.contracts.enums import Severity

__all__ = [
    "check_age_experience_draft_consistency",
    "check_bounded_share",
    "check_categorical_domain",
    "check_missingness",
    "check_non_negative",
    "check_numeric_bounds",
    "check_ratio_denominator",
    "check_row_count_stability",
    "check_season_week_consistency",
    "describe_distribution",
]

_SAMPLE = 8


def _offenders(frame: pl.DataFrame, predicate: pl.Expr, *, label: str) -> tuple[int, str]:
    """Count rows failing ``predicate`` and render a short sample for the record."""
    failing = frame.filter(predicate)
    if failing.is_empty():
        return 0, ""
    columns = [
        name
        for name in ("season", "player_id", "gsis_id", "week", label)
        if name in failing.columns
    ]
    sample = failing.select(columns).head(_SAMPLE)
    rendered = "; ".join(
        ", ".join(f"{name}={row[name]!r}" for name in columns)
        for row in sample.iter_rows(named=True)
    )
    return failing.height, rendered


def check_categorical_domain(
    frame: pl.DataFrame,
    *,
    column: str,
    allowed: Iterable[str],
    stage: str,
    allow_null: bool = False,
    severity: Severity = Severity.CRITICAL,
) -> list[QualityCheck]:
    """Every value of ``column`` must come from a known vocabulary.

    This is the check that catches a source quietly adding, renaming or re-meaning a code -
    a new position abbreviation, a team relocation code, a status value nobody expected.
    """
    if column not in frame.columns:
        return [
            QualityCheck.fail(
                "semantic.column_absent",
                stage=stage,
                message=f"{column} is not present, so its domain cannot be checked",
                observed="absent",
                expected="present",
                severity=severity,
            ),
        ]
    vocabulary = sorted(set(allowed))
    predicate = ~pl.col(column).is_in(vocabulary)
    if allow_null:
        predicate = predicate & pl.col(column).is_not_null()
    else:
        predicate = predicate | pl.col(column).is_null()
    count, sample = _offenders(frame, predicate, label=column)
    if count:
        unexpected = sorted(
            {str(value) for value in frame.filter(predicate).get_column(column).unique().to_list()},
        )[:_SAMPLE]
        return [
            QualityCheck.fail(
                "semantic.categorical_domain",
                stage=stage,
                message=f"{column} contains values outside its declared vocabulary",
                observed=f"{count} row(s); values {unexpected}; e.g. {sample}",
                expected=f"one of {vocabulary}",
                severity=severity,
            ),
        ]
    return [
        QualityCheck.ok(
            "semantic.categorical_domain",
            stage=stage,
            message=f"{column} stays inside its declared vocabulary",
            observed=f"{frame.height} row(s), {len(vocabulary)} allowed value(s)",
        ),
    ]


def check_numeric_bounds(
    frame: pl.DataFrame,
    *,
    column: str,
    minimum: float | None = None,
    maximum: float | None = None,
    stage: str,
    severity: Severity = Severity.CRITICAL,
) -> list[QualityCheck]:
    """A numeric column must stay inside a plausible range. Nulls are ignored."""
    if column not in frame.columns:
        return []
    predicate = pl.col(column).is_not_null()
    if minimum is not None:
        predicate = predicate & (pl.col(column) < minimum)
    if maximum is not None:
        upper = pl.col(column).is_not_null() & (pl.col(column) > maximum)
        predicate = (predicate | upper) if minimum is not None else upper
    count, sample = _offenders(frame, predicate, label=column)
    if count:
        return [
            QualityCheck.fail(
                "semantic.numeric_out_of_range",
                stage=stage,
                message=f"{column} leaves its plausible range",
                observed=f"{count} row(s); e.g. {sample}",
                expected=f"[{minimum}, {maximum}]",
                severity=severity,
            ),
        ]
    return [
        QualityCheck.ok(
            "semantic.numeric_in_range",
            stage=stage,
            message=f"{column} stays within [{minimum}, {maximum}]",
            observed=f"{frame.height} row(s)",
        ),
    ]


def check_non_negative(
    frame: pl.DataFrame,
    *,
    columns: Sequence[str],
    stage: str,
    severity: Severity = Severity.CRITICAL,
) -> list[QualityCheck]:
    """Counting statistics cannot be negative. A negative count is a sign-convention change."""
    present = [name for name in columns if name in frame.columns]
    offenders: list[str] = []
    for name in present:
        count = int(frame.filter(pl.col(name).is_not_null() & (pl.col(name) < 0)).height)
        if count:
            offenders.append(f"{name} x{count}")
    if offenders:
        return [
            QualityCheck.fail(
                "semantic.negative_count",
                stage=stage,
                message="a counting statistic is negative",
                observed="; ".join(offenders),
                expected=">= 0",
                severity=severity,
            ),
        ]
    return [
        QualityCheck.ok(
            "semantic.non_negative_counts",
            stage=stage,
            message="every audited counting statistic is non-negative",
            observed=f"{len(present)} column(s) x {frame.height} row(s)",
        ),
    ]


def check_bounded_share(
    frame: pl.DataFrame,
    *,
    columns: Sequence[str],
    stage: str,
    severity: Severity = Severity.CRITICAL,
) -> list[QualityCheck]:
    """Shares and rates live in ``[0, 1]``.

    This is the check that would catch a percentage arriving as 0-100: the column keeps its
    name, its dtype and its plausibility, and only the unit changed.
    """
    present = [name for name in columns if name in frame.columns]
    offenders: list[str] = []
    for name in present:
        bad = frame.filter(
            pl.col(name).is_not_null() & ((pl.col(name) < 0.0) | (pl.col(name) > 1.0)),
        )
        if not bad.is_empty():
            worst = cast(float, bad.get_column(name).abs().max() or 0.0)
            offenders.append(f"{name} x{bad.height} (max |value| {worst:.4f})")
    if offenders:
        return [
            QualityCheck.fail(
                "semantic.share_out_of_unit_interval",
                stage=stage,
                message="a share or rate falls outside [0, 1]; check the source's unit",
                observed="; ".join(offenders),
                expected="[0, 1]",
                severity=severity,
            ),
        ]
    return [
        QualityCheck.ok(
            "semantic.shares_bounded",
            stage=stage,
            message="every audited share stays in [0, 1]",
            observed=f"{len(present)} column(s) x {frame.height} row(s)",
        ),
    ]


def check_ratio_denominator(
    frame: pl.DataFrame,
    *,
    ratio: str,
    denominator: str,
    minimum: float,
    stage: str,
    severity: Severity = Severity.CRITICAL,
) -> list[QualityCheck]:
    """A derived ratio must be null whenever its denominator is below the declared minimum.

    The failure this prevents is a plausible-looking 14.0 yards per carry computed from a
    single carry, which a tree model will happily split on.
    """
    if ratio not in frame.columns or denominator not in frame.columns:
        return []
    predicate = pl.col(ratio).is_not_null() & (
        pl.col(denominator).is_null() | (pl.col(denominator) < minimum)
    )
    count, sample = _offenders(frame, predicate, label=ratio)
    if count:
        return [
            QualityCheck.fail(
                "semantic.ratio_below_minimum_denominator",
                stage=stage,
                message=f"{ratio} is populated where {denominator} is below its minimum",
                observed=f"{count} row(s); e.g. {sample}",
                expected=f"{ratio} null unless {denominator} >= {minimum}",
                severity=severity,
            ),
        ]
    return [
        QualityCheck.ok(
            "semantic.ratio_denominator_respected",
            stage=stage,
            message=f"{ratio} is only populated above the {denominator} minimum",
            observed=f"{denominator} >= {minimum}",
        ),
    ]


def check_season_week_consistency(
    frame: pl.DataFrame,
    *,
    stage: str,
    max_week_by_season: Mapping[int, int],
    severity: Severity = Severity.CRITICAL,
) -> list[QualityCheck]:
    """Weeks must be positive and no larger than the season actually had."""
    if "season" not in frame.columns or "week" not in frame.columns:
        return []
    offenders: list[str] = []
    for season, maximum in sorted(max_week_by_season.items()):
        bad = frame.filter(
            (pl.col("season") == season)
            & (pl.col("week").is_not_null())
            & ((pl.col("week") < 1) | (pl.col("week") > maximum)),
        )
        if not bad.is_empty():
            offenders.append(f"{season}: {bad.height} row(s) outside 1..{maximum}")
    unknown = sorted(
        set(frame.get_column("season").unique().to_list()) - set(max_week_by_season),
    )
    if unknown:
        offenders.append(f"seasons with no declared week count: {unknown}")
    if offenders:
        return [
            QualityCheck.fail(
                "semantic.season_week_inconsistent",
                stage=stage,
                message="a week number is impossible for its season",
                observed="; ".join(offenders),
                expected="1 <= week <= season week count",
                severity=severity,
            ),
        ]
    return [
        QualityCheck.ok(
            "semantic.season_week_consistent",
            stage=stage,
            message="every week number is possible for its season",
            observed=f"{frame.height} row(s)",
        ),
    ]


def check_age_experience_draft_consistency(
    frame: pl.DataFrame,
    *,
    stage: str,
    severity: Severity = Severity.CRITICAL,
) -> list[QualityCheck]:
    """Age, experience and draft capital must tell a possible story together.

    Three impossibilities are checked, each of which would indicate a join or a lag error
    rather than an unusual player:

    * a player drafted after the season he is being modelled for;
    * more completed NFL seasons than years since his draft;
    * a rookie flag on a row that also claims prior experience.
    """
    offenders: list[str] = []
    if {"draft_year", "season"} <= set(frame.columns):
        count = int(
            frame.filter(
                pl.col("draft_year").is_not_null() & (pl.col("draft_year") > pl.col("season")),
            ).height,
        )
        if count:
            offenders.append(f"draft_year after target season: {count} row(s)")
    if {"experience_years", "seasons_since_draft"} <= set(frame.columns):
        count = int(
            frame.filter(
                pl.col("seasons_since_draft").is_not_null()
                & (pl.col("experience_years") > pl.col("seasons_since_draft")),
            ).height,
        )
        if count:
            offenders.append(f"experience exceeds seasons since draft: {count} row(s)")
    if {"rookie_flag", "experience_years"} <= set(frame.columns):
        count = int(
            frame.filter(pl.col("rookie_flag") & (pl.col("experience_years") > 0)).height,
        )
        if count:
            offenders.append(f"rookie_flag with prior experience: {count} row(s)")
    if {"age_at_anchor"} <= set(frame.columns):
        count = int(
            frame.filter(
                pl.col("age_at_anchor").is_not_null()
                & ((pl.col("age_at_anchor") < 18.0) | (pl.col("age_at_anchor") > 50.0)),
            ).height,
        )
        if count:
            offenders.append(f"implausible age at anchor: {count} row(s)")
    if offenders:
        return [
            QualityCheck.fail(
                "semantic.career_fields_inconsistent",
                stage=stage,
                message="age, experience and draft capital contradict each other",
                observed="; ".join(offenders),
                expected="internally consistent career fields",
                severity=severity,
            ),
        ]
    return [
        QualityCheck.ok(
            "semantic.career_fields_consistent",
            stage=stage,
            message="age, experience and draft capital are mutually consistent",
            observed=f"{frame.height} row(s)",
        ),
    ]


def check_missingness(
    frame: pl.DataFrame,
    *,
    column: str,
    max_null_rate: float,
    stage: str,
    severity: Severity = Severity.WARNING,
) -> list[QualityCheck]:
    """Catch a column that has quietly gone mostly or entirely null.

    A source that stops publishing a field usually keeps the column, so structural checks
    pass while the feature becomes uniformly missing. The threshold is per-feature because
    "expected missingness" is genuinely different for a combine measurement and a
    previous-season game count.
    """
    if column not in frame.columns or frame.is_empty():
        return []
    nulls = int(frame.get_column(column).null_count())
    rate = nulls / frame.height
    if rate > max_null_rate:
        return [
            QualityCheck.fail(
                "semantic.missingness_above_budget",
                stage=stage,
                message=f"{column} is missing more often than its documented budget allows",
                observed=f"{rate:.1%} null ({nulls}/{frame.height})",
                expected=f"<= {max_null_rate:.1%}",
                severity=severity,
            ),
        ]
    return [
        QualityCheck.ok(
            "semantic.missingness_within_budget",
            stage=stage,
            message=f"{column} missingness is within budget",
            observed=f"{rate:.1%} null",
        ),
    ]


def check_row_count_stability(
    counts: Mapping[int, int],
    *,
    stage: str,
    tolerance: float = 0.35,
    severity: Severity = Severity.WARNING,
) -> list[QualityCheck]:
    """Flag a season whose row count departs sharply from the median.

    A source that starts returning a fraction of its usual rows is a real and common
    failure, and it produces a dataset that still validates. Comparing each season to the
    median rather than to a constant keeps the check meaningful as the dataset grows.
    """
    if len(counts) < 3:
        return []
    ordered = sorted(counts.values())
    median = ordered[len(ordered) // 2]
    if median == 0:
        return []
    outliers = [
        f"{season}={count} ({(count - median) / median:+.0%})"
        for season, count in sorted(counts.items())
        if abs(count - median) / median > tolerance
    ]
    if outliers:
        return [
            QualityCheck.fail(
                "semantic.row_count_anomaly",
                stage=stage,
                message="a season's row count departs sharply from the median season",
                observed="; ".join(outliers),
                expected=f"within {tolerance:.0%} of median {median}",
                severity=severity,
            ),
        ]
    return [
        QualityCheck.ok(
            "semantic.row_counts_stable",
            stage=stage,
            message="every season's row count is close to the median season",
            observed=f"median {median} across {len(counts)} season(s)",
        ),
    ]


def describe_distribution(
    frame: pl.DataFrame,
    *,
    column: str,
    by: Sequence[str],
    stage: str,
) -> list[QualityCheck]:
    """Emit an informational per-group summary of a numeric column.

    These records carry no pass/fail judgement. They exist because a distribution that
    shifts between eras is exactly the thing a single aggregate number hides, and
    `docs/DATA_CONTRACTS.md` section 12 asks for the slices to be visible rather than
    averaged away.
    """
    if column not in frame.columns or frame.is_empty():
        return []
    grouped = (
        frame.group_by(list(by))
        .agg(
            pl.len().alias("rows"),
            pl.col(column).null_count().alias("nulls"),
            pl.col(column).median().alias("median"),
            pl.col(column).quantile(0.9).alias("p90"),
        )
        .sort(list(by))
    )
    rendered = "; ".join(
        f"{'/'.join(str(row[key]) for key in by)}: n={row['rows']}, "
        f"null={row['nulls']}, median={_fmt(row['median'])}, p90={_fmt(row['p90'])}"
        for row in grouped.iter_rows(named=True)
    )
    return [
        QualityCheck.ok(
            "semantic.distribution_summary",
            stage=stage,
            message=f"{column} distribution by {'/'.join(by)}",
            observed=rendered,
        ),
    ]


def _fmt(value: object) -> str:
    if value is None:
        return "-"
    return f"{float(value):.3f}"  # type: ignore[arg-type]
