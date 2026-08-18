"""The quality gate.

`docs/ARCHITECTURE.md` section 12: critical failures block serialization and deploy;
warnings are recorded in ``build_metadata.json`` and the workflow summary. The gate does
not decide *what* is critical - each check does that - it only collects and enforces.

The important property is that a build collects every finding before it stops. Raising on
the first problem would make a broken refresh take as many runs to diagnose as it has bugs.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from ffdraft.contracts import CheckStatus, QualityCheck, Severity

__all__ = ["QualityGate", "QualityGateError"]


class QualityGateError(RuntimeError):
    """Raised when a build tries to publish through a failed gate."""

    def __init__(self, failures: Sequence[QualityCheck]) -> None:
        self.failures = tuple(failures)
        detail = "; ".join(
            f"{check.check_id} [{check.stage}] {check.message} (observed: {check.observed})"
            for check in failures
        )
        super().__init__(f"{len(failures)} critical quality failure(s): {detail}")


@dataclass
class QualityGate:
    """Accumulates checks and answers one question: may this build publish?"""

    checks: list[QualityCheck] = field(default_factory=list)

    def add(self, *checks: QualityCheck) -> QualityGate:
        self.checks.extend(checks)
        return self

    def extend(self, checks: Iterable[QualityCheck]) -> QualityGate:
        self.checks.extend(checks)
        return self

    @property
    def critical_failures(self) -> tuple[QualityCheck, ...]:
        return tuple(check for check in self.checks if check.blocking)

    @property
    def warnings(self) -> tuple[QualityCheck, ...]:
        return tuple(
            check
            for check in self.checks
            if check.status is CheckStatus.FAIL and check.severity is Severity.WARNING
        )

    @property
    def passed(self) -> bool:
        return not self.critical_failures

    def raise_if_blocked(self) -> None:
        """Stop the build if anything critical failed."""
        if not self.passed:
            raise QualityGateError(self.critical_failures)

    def summary(self) -> dict[str, Any]:
        """The ``quality_gate`` object in ``build_metadata.schema.json``."""
        return {
            "status": "pass" if self.passed else "fail",
            "critical_failures": len(self.critical_failures),
            "warnings": len(self.warnings),
        }

    def warning_messages(self) -> list[str]:
        """Warning text for ``build_metadata.warnings``."""
        return [f"{check.check_id}: {check.message}" for check in self.warnings]

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary(),
            "checks": [check.to_dict() for check in self.checks],
        }
