# Drive breadth v2 — development study (ADR-104)

Generated 2026-10-06 by `ffdraft.signals.breadth_study` (method `drive_breadth_v2`) from the
same nflverse inputs as `../drive-breadth-2026-10-06/`, **2020–2024** only. 2025 (the spent
sealed season) and 2026 (the season shown) were not read.

| File | What it holds |
|---|---|
| `coverage.json` | reach, display coverage, saturation and the windowed gap's spread, per season and position |
| `evaluation.json` | ADR-103's predeclared drought comparison, unchanged, re-run under v2 |
| `confounding.json` | partial games, score margin, opponent vs player variance, drives per game |
| `redundancy.json` | ADR-104's added check: a game's drive share against that game's opportunity share and volume |

**Regression check.** Only the QB variant changed (designed runs instead of every rush). Every
RB, WR and TE figure in `coverage.json`, `evaluation.json` and `confounding.json` is identical to
the v1 study's; every difference is under `QB`.

Reproduce (network, cached loaders):

```python
from ffdraft.sources.nflverse_http import nflverse_loaders
from ffdraft.signals.breadth_study import (
    DEVELOPMENT_SEASONS, load_study_inputs, coverage_report, evaluation_report,
    confounding_report, drive_share_redundancy_report,
)
inputs = [load_study_inputs(season, nflverse_loaders()) for season in DEVELOPMENT_SEASONS]
coverage_report(inputs); drive_share_redundancy_report(inputs)
evaluation_report(inputs); confounding_report(inputs)
```

**Result.** The QB designed-run comparison with random fails publication rule 1 (19.4% of 2024
windows clear the display minimums, against 25%), shows no incremental value, and is more a
property of the opponent than the quarterback; quarterbacks therefore get the drive-share rail
alone. A game's drive share repeats the share rails (Spearman 0.95–0.99 with opportunity share
and volume at every position); the information they do not carry is the distance between a bar
and its random notch (|ρ| ≤ 0.18). See ADR-104.
