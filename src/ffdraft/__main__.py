"""Allow ``python -m ffdraft`` in addition to the ``ffdraft`` console script."""

from __future__ import annotations

from ffdraft.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
