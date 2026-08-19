"""Repository path resolution.

Configuration, schemas and fixtures live in the repository, not in the installed package,
so every consumer needs one agreed way to find the repository root. Resolution order:

1. ``FFDRAFT_REPO_ROOT`` if set - lets CI and tests point at a checkout explicitly;
2. the nearest ancestor of this file that looks like the repository.

"Looks like the repository" means it carries both ``pyproject.toml`` and ``config/``. That
is deliberately stricter than ``pyproject.toml`` alone, so an editable install inside some
other project cannot silently resolve to that project's root.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "config_dir",
    "repo_root",
    "schemas_dir",
]

_MARKERS = ("pyproject.toml", "config")


class RepoRootNotFound(RuntimeError):
    """Raised when the repository root cannot be located."""


def _looks_like_repo(candidate: Path) -> bool:
    return all((candidate / marker).exists() for marker in _MARKERS)


def repo_root(*, env: os._Environ[str] | dict[str, str] | None = None) -> Path:
    """Return the repository root directory."""
    environ = os.environ if env is None else env
    override = environ.get("FFDRAFT_REPO_ROOT")
    if override:
        candidate = Path(override).expanduser().resolve()
        if not _looks_like_repo(candidate):
            raise RepoRootNotFound(
                f"FFDRAFT_REPO_ROOT={override!r} does not contain {_MARKERS}",
            )
        return candidate

    here = Path(__file__).resolve()
    for parent in here.parents:
        if _looks_like_repo(parent):
            return parent
    raise RepoRootNotFound(
        f"no ancestor of {here} contains all of {_MARKERS}; set FFDRAFT_REPO_ROOT",
    )


def config_dir(*, root: Path | None = None) -> Path:
    """Return the ``config/`` directory."""
    return (root or repo_root()) / "config"


def schemas_dir(*, root: Path | None = None) -> Path:
    """Return the ``schemas/`` directory holding the public artifact contracts."""
    return (root or repo_root()) / "schemas"
