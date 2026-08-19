"""Source adapters — one per external source.

Import market adapters from :mod:`ffdraft.sources.market` explicitly rather than from here.
Keeping them off this namespace makes an accidental market import into an intrinsic module
visible in review, which is the code-level half of the boundary in `docs/ARCHITECTURE.md`
section 3.1.
"""

from __future__ import annotations

from ffdraft.sources.base import (
    BaseSourceAdapter,
    RawRecords,
    SourceAdapter,
    SourceConfig,
    SourceFetchError,
    as_rows,
)
from ffdraft.sources.nflverse import (
    NFLVERSE_SOURCE_ID,
    NflverseDepthChartAdapter,
    NflversePlayerIdsAdapter,
    NflverseRosterAdapter,
)
from ffdraft.sources.sleeper import (
    SLEEPER_SOURCE_ID,
    SleeperPlayerAdapter,
    SleeperState,
    parse_sleeper_state,
)

__all__ = [
    "NFLVERSE_SOURCE_ID",
    "SLEEPER_SOURCE_ID",
    "BaseSourceAdapter",
    "NflverseDepthChartAdapter",
    "NflversePlayerIdsAdapter",
    "NflverseRosterAdapter",
    "RawRecords",
    "SleeperPlayerAdapter",
    "SleeperState",
    "SourceAdapter",
    "SourceConfig",
    "SourceFetchError",
    "as_rows",
    "parse_sleeper_state",
]
