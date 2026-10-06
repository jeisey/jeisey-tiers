# Drive breadth above expectation — development study (ADR-103)

Generated 2026-10-06 by `ffdraft.signals.breadth_study` from nflverse play-by-play, weekly
player stats, snap counts, season rosters and schedules for **2020–2024**. 2025 (the spent
sealed season) and 2026 (the season shown) were not read.

| File | Phase | What it holds |
|---|---|---|
| `coverage.json` | 1, before ADR-103 was frozen | reach, display coverage, saturation and the windowed gap's spread, per season and position; no outcome |
| `evaluation.json` | 2, after | the predeclared drought comparison: per-season log loss, Brier and AUC, pooled Δ log loss with a 95% player-season cluster bootstrap |
| `confounding.json` | 2 | partial games, score margin, opponent vs player variance, drives per game |
| `examples.json` | 2 | the 2024 same-volume, same-share pair with the widest breadth difference, per position |

Reproduce (network, cached loaders):

```python
from ffdraft.sources.nflverse_http import nflverse_loaders
from ffdraft.signals.breadth_study import (
    DEVELOPMENT_SEASONS, load_study_inputs, coverage_report, evaluation_report, confounding_report,
)
inputs = [load_study_inputs(season, nflverse_loaders()) for season in DEVELOPMENT_SEASONS]
coverage_report(inputs); evaluation_report(inputs); confounding_report(inputs)
```

**Result:** distinct from share and volume at every position; no measurable incremental value
for anticipating a next-appearance opportunity drought at any position. Published as
descriptive context only. See ADR-103.
