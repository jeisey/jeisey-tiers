"""Polars frame contracts.

`docs/DATA_CONTRACTS.md` section 1: dataframe columns are APIs. A normalized frame that
loses a column, changes a dtype or gains duplicate keys is a schema break, and it must be
caught at the boundary rather than three stages later as a column of nulls.

A :class:`FrameContract` is deliberately small. It declares the columns, their types, which
may be null and what the primary key is, and it can do three things: build an empty frame
that matches, coerce a frame into the declared column order and dtypes, and validate a
frame into :class:`~ffdraft.contracts.quality.QualityCheck` records.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import polars as pl

from ffdraft.contracts.enums import CheckStatus, Severity
from ffdraft.contracts.quality import QualityCheck

__all__ = ["ColumnSpec", "DType", "FrameContract"]


#: Polars accepts both a DataType class (``pl.Int32``) and an instance
#: (``pl.Datetime(time_zone="UTC")``) wherever a dtype is expected; both appear in the
#: contracts below, so the alias admits either.
DType = pl.DataType | type[pl.DataType]


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    """One declared column."""

    name: str
    dtype: DType
    nullable: bool = True
    description: str = ""


@dataclass(frozen=True, slots=True)
class FrameContract:
    """A named, versioned column contract for one normalized dataset."""

    contract_id: str
    version: str
    columns: tuple[ColumnSpec, ...]
    primary_key: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        names = [column.name for column in self.columns]
        if len(names) != len(set(names)):
            raise ValueError(f"{self.contract_id}: duplicate column names in contract")
        missing = set(self.primary_key) - set(names)
        if missing:
            raise ValueError(
                f"{self.contract_id}: primary key references unknown {sorted(missing)}",
            )

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)

    @property
    def schema(self) -> dict[str, DType]:
        return {column.name: column.dtype for column in self.columns}

    def spec(self, name: str) -> ColumnSpec:
        for column in self.columns:
            if column.name == name:
                return column
        raise KeyError(f"{self.contract_id}: no column {name!r}")

    def empty(self) -> pl.DataFrame:
        """An empty frame matching the contract - the canonical "no rows" value."""
        return pl.DataFrame(schema=self.schema)

    def build(self, rows: Iterable[Mapping[str, Any]]) -> pl.DataFrame:
        """Build a contract-shaped frame from row dicts, filling absent columns with null."""
        materialised = list(rows)
        if not materialised:
            return self.empty()
        normalised = [{name: row.get(name) for name in self.column_names} for row in materialised]
        return pl.DataFrame(normalised, schema=self.schema, orient="row")

    def coerce(self, frame: pl.DataFrame) -> pl.DataFrame:
        """Select the declared columns in declared order and cast them to declared types.

        Missing columns become nulls of the right type rather than an exception, so that
        :meth:`validate` reports *all* the problems at once instead of the first one.
        """
        expressions = [
            (
                pl.col(column.name).cast(column.dtype, strict=False)
                if column.name in frame.columns
                else pl.lit(None, dtype=column.dtype)
            ).alias(column.name)
            for column in self.columns
        ]
        return frame.select(expressions)

    def validate(self, frame: pl.DataFrame, *, stage: str | None = None) -> list[QualityCheck]:
        """Return quality records describing how ``frame`` conforms to this contract."""
        where = stage or self.contract_id
        checks: list[QualityCheck] = []
        present = set(frame.columns)

        missing = [name for name in self.column_names if name not in present]
        if missing:
            checks.append(
                QualityCheck.fail(
                    "frame_contract.missing_columns",
                    stage=where,
                    message=f"{self.contract_id} is missing declared columns",
                    observed=", ".join(missing),
                    expected=", ".join(self.column_names),
                ),
            )

        unexpected = [name for name in frame.columns if name not in set(self.column_names)]
        if unexpected:
            checks.append(
                QualityCheck.fail(
                    "frame_contract.unexpected_columns",
                    stage=where,
                    message=f"{self.contract_id} carries undeclared columns",
                    observed=", ".join(unexpected),
                    expected="only declared columns",
                    severity=Severity.WARNING,
                ),
            )

        schema = frame.schema
        for column in self.columns:
            if column.name not in present:
                continue
            actual = schema[column.name]
            if actual != column.dtype:
                checks.append(
                    QualityCheck.fail(
                        "frame_contract.dtype_mismatch",
                        stage=where,
                        message=f"{self.contract_id}.{column.name} has the wrong dtype",
                        observed=str(actual),
                        expected=str(column.dtype),
                    ),
                )
            if not column.nullable:
                nulls = int(frame.get_column(column.name).null_count())
                if nulls:
                    checks.append(
                        QualityCheck.fail(
                            "frame_contract.unexpected_nulls",
                            stage=where,
                            message=f"{self.contract_id}.{column.name} is declared non-null",
                            observed=f"{nulls} null(s)",
                            expected="0 nulls",
                        ),
                    )

        checks.extend(self._primary_key_checks(frame, where, present))
        if not any(check.status is CheckStatus.FAIL for check in checks):
            checks.append(
                QualityCheck.ok(
                    "frame_contract.conforms",
                    stage=where,
                    message=f"{self.contract_id} v{self.version} conforms",
                    observed=f"{frame.height} row(s)",
                ),
            )
        return checks

    def _primary_key_checks(
        self,
        frame: pl.DataFrame,
        where: str,
        present: set[str],
    ) -> Sequence[QualityCheck]:
        if not self.primary_key or not set(self.primary_key).issubset(present):
            return ()
        duplicates = frame.height - frame.select(self.primary_key).n_unique()
        if duplicates <= 0:
            return ()
        return (
            QualityCheck.fail(
                "frame_contract.duplicate_primary_key",
                stage=where,
                message=f"{self.contract_id} has duplicate {'+'.join(self.primary_key)} keys",
                observed=f"{duplicates} duplicate row(s)",
                expected="0 duplicates",
            ),
        )
