"""The quality-check record.

`docs/ARCHITECTURE.md` section 12 fixes the shape: every check emits a structured record
rather than raising or logging, so a build can collect the full picture, serialize it into
``build_metadata.json`` and then decide once whether to block. This module holds only the
record; the checks themselves and the gate live in :mod:`ffdraft.quality`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from ffdraft.contracts.enums import CheckStatus, Severity

__all__ = ["QualityCheck", "critical_failures", "failures", "passed"]


@dataclass(frozen=True, slots=True)
class QualityCheck:
    """One structured observation about data or artifact quality."""

    check_id: str
    severity: Severity
    status: CheckStatus
    stage: str
    message: str
    observed: str = ""
    expected: str = ""

    @classmethod
    def ok(cls, check_id: str, *, stage: str, message: str, observed: str = "") -> QualityCheck:
        return cls(
            check_id=check_id,
            severity=Severity.INFO,
            status=CheckStatus.PASS,
            stage=stage,
            message=message,
            observed=observed,
        )

    @classmethod
    def fail(
        cls,
        check_id: str,
        *,
        stage: str,
        message: str,
        observed: str = "",
        expected: str = "",
        severity: Severity = Severity.CRITICAL,
    ) -> QualityCheck:
        return cls(
            check_id=check_id,
            severity=severity,
            status=CheckStatus.FAIL,
            stage=stage,
            message=message,
            observed=observed,
            expected=expected,
        )

    @property
    def blocking(self) -> bool:
        """Critical failures block serialization and deploy; warnings are recorded."""
        return self.status is CheckStatus.FAIL and self.severity is Severity.CRITICAL

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "severity": str(self.severity),
            "status": str(self.status),
            "stage": self.stage,
            "observed": self.observed,
            "expected": self.expected,
            "message": self.message,
        }


def failures(checks: Iterable[QualityCheck]) -> tuple[QualityCheck, ...]:
    return tuple(check for check in checks if check.status is CheckStatus.FAIL)


def critical_failures(checks: Iterable[QualityCheck]) -> tuple[QualityCheck, ...]:
    return tuple(check for check in checks if check.blocking)


def passed(checks: Sequence[QualityCheck]) -> bool:
    """True when no critical failure is present. Warnings do not block."""
    return not critical_failures(checks)
