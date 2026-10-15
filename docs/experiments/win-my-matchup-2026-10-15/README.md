# Win My Matchup — measurements behind ADR-110's frozen choices

Two measurements were taken on the live 2026-10-15 build
(`2026w05-intrinsic-ros-v1-20261015T113222Z`, target week 6, PPR) before anything depended on
them. Neither is a calibration of matchup probabilities: the build saves no out-of-fold weekly
predictions, so team-level calibration is not measurable here (ADR-110 §10).

## The draw count — `convergence.json`

`web/tests/matchup-convergence.test.ts` is offline and skipped unless pointed at a build. The
setup:

* 60 random two-lineup matchups (1 QB, 2 RB, 2 WR, 1 TE and 1 FLEX a side), with real games,
  teams and latent same-game correlations;
* one single-player swap per matchup;
* 20 seeds at each of 8,192, 16,384 and 32,768 draws;
* a 1,048,576-draw reference.

Each count is checked against ADR-110's three rules:
1. the worst-case 95% half-width, with the seed SD close to the binomial SE;
2. the swap's paired SE;
3. rounded headlines within ±1 point of the reference.

8,192 passes all three and was frozen. The report was regenerated after the engine's
performance work. Every statistic is identical, and only the run times fell: 23 / 46 / 93 ms.

```bash
MATCHUP_CONVERGENCE=<build>/weekly_projections.json \
MATCHUP_METADATA=<build>/ros_build_metadata.json \
MATCHUP_REPORT=docs/experiments/win-my-matchup-2026-10-15/convergence.json \
  npx vitest run tests/matchup-convergence.test.ts      # about 5 minutes
```

## YOLO's net-add bar — `yolo_coverage.py`

Before `yolo_ceiling_v1` was frozen, this measured how many players each candidate bar lets
through, and how many of them also have a rising role:

```bash
uv run python docs/experiments/win-my-matchup-2026-10-15/yolo_coverage.py <build data dir>
```

On the live build, `redraft-12`/PPR (every block was identical that day):

| | QB | RB | WR | TE |
|---|---:|---:|---:|---:|
| positive-net-add pool | 10 | 20 | 18 | 5 |
| median bar (the rule) | 49,065 | 57,568 | 55,110 | 42,482 |
| at or above it | 5 | 10 | 9 | 3 |
| … with a rising role (and a week-6 distribution) | 2 | 7 | 5 | 3 |
| 75th-percentile bar (rejected): rising and at or above | 1 | 4 | 2 | 2 |

The median bar was kept, because the 75th percentile left too few players for a waiver list.
The TE pool sat exactly at the minimum of 5, so a quieter day leaves TE without candidates. That
is the intended, stated outcome.

The script's role test mirrors the Opportunity Board's for this measurement only. The page uses
`passesFilter(candidate, "role")` itself, and the page's numbers come from the page's code
(`web/src/data/yolo.ts`, tested in `web/tests/wmm-setup.test.ts`).
