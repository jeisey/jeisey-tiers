"""Fantasy Draft Intelligence data and modeling package.

Subpackage boundaries follow `docs/ARCHITECTURE.md` section 5 and must stay recognisable:

* :mod:`ffdraft.config`     - validated YAML configuration and secret-safe client identity
* :mod:`ffdraft.contracts`  - typed internal entities and Polars frame contracts
* :mod:`ffdraft.sources`    - one adapter per external source; no cross-source identity here
* :mod:`ffdraft.identity`   - canonical crosswalk and fail-closed resolver
* :mod:`ffdraft.quality`    - reusable checks, severities and the deploy gate
* :mod:`ffdraft.artifacts`  - public JSON/CSV serialisation against `schemas/`
* :mod:`ffdraft.pipeline`   - wiring, including the network-free fixture mini-pipeline

The load-bearing invariant of the whole project (AGENTS.md section 1): the intrinsic path
never sees market or expert-rank data. Market code lives in :mod:`ffdraft.sources.market`
and, from Phase 5, ``ffdraft.arbitrage`` - never inside the intrinsic feature packages.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

__all__ = ["__version__"]

try:
    __version__ = version("ffdraft")
except PackageNotFoundError:  # pragma: no cover - only when running from a bare checkout
    __version__ = "0+unknown"
