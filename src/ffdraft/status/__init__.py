"""Current player status: capture, retention and the public annotation artifact.

Status data describes *today*. It annotates a published board and it never enters a model
(ADR-043), and the richer historical injury features it makes tempting are deferred to the
2027 refresh with a spent-holdout reason (ADR-044).
"""

from __future__ import annotations

from ffdraft.status.build import (
    STATUS_SOURCE_IDS,
    PlayerStatusResult,
    build_player_status_records,
)
from ffdraft.status.capture import (
    StatusCapture,
    capture_status,
    read_status_capture,
    write_status_capture,
)

__all__ = [
    "STATUS_SOURCE_IDS",
    "PlayerStatusResult",
    "StatusCapture",
    "build_player_status_records",
    "capture_status",
    "read_status_capture",
    "write_status_capture",
]
