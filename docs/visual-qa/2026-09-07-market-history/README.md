# 2026-09-07 — the player card's market history, per market

Verification evidence for ADR-081, and a deliberate exception to this directory's usual rule.

Every other set here is captured from the **fixture** build, so two runs of the same code
produce the same images. These are captured from a build over the **real retained store**
(`jeisey/jeisey-tiers-market-data`, branch `market-data`, at `1bd7f20`), because the thing
being evidenced is precisely what a fixture could not show: that a second real market with a
real retained history reaches a real player card. The defect was invisible to every fixture
in the repository for two phases, which is the reason this set exists at all.

They are therefore a dated record, like `docs/source-probes/`, not a baseline to diff.

## The build behind them

The intrinsic half is a deterministic stand-in — the model needs nflverse and this was built
offline — so fair rank here is order-by-ADP and the VORP figures are placeholders. **The
market half is the production code path**, unchanged: `run_arbitrage_build` over the same
append-only bytes the daily refresh reads.

```
retained store   : /home/user/jeisey-tiers-market-data @ 1bd7f20
MFL snapshots    : 32 retained for 2026; 15 inside the trailing 7-day window
FFC snapshots    :  7 retained for 2026, 2026-09-03 18:18Z .. 2026-09-06 11:22Z
arbitrage rows   : 2,232
market_trend_series : 3,957 records — 2,232 MyFantasyLeague, 1,725 FFC
validate-artifacts  : 0 critical, 0 warning
verify:board        : 0 failures, both markets charted
```

## What each image shows

`Jahmyr Gibbs` is the top of the board and the two markets sit close together; `mover/` is
`Jadarian Price`, whose FFC price moved 3.9 picks over the window, so the shapes are legible.

| File | Mode | The point |
|---|---|---|
| `card-fantasyfootballcalculator` | FFC selected | Every readout is FFC's — ADP, gap, cohort, window, snapshot — and the chart is FFC's four retained days |
| `chart-fantasyfootballcalculator` | FFC selected | Sep 3 → Sep 6, four marks, **`trend collecting`**: seven observations over 2.7 days of span, which `phase5_trend_v1` correctly refuses to fit |
| `card-myfantasyleague` | MFL selected | The same card following the other market |
| `chart-myfantasyleague` | MFL selected | Aug 30 → Sep 6, eight marks, `+0.02/day` — a slope the frozen rule *does* qualify |
| `card-cross` | Cross | `Market trend` reads an em dash and "per market, below"; no single scalar is invented |
| `chart-cross` | Cross | Both real series on one dated axis, told apart by stroke pattern and named in the legend, each with its own direction and its own slope-or-reason |
| `mover/*` | all three | The same, on a player whose FFC price actually moved |

The two facts to read off `chart-cross`: the markets moved **by date** rather than by
position, and MyFantasyLeague sits consistently earlier than FFC — the disagreement a
single-source board could not have shown.

## The state this replaces

Before ADR-081 the same card, with FFC selected, showed a current FFC ADP beside

> Not enough retained FFC Recent history to draw a trend yet — 0 snapshots so far.

while seven FFC snapshots sat in the store, and printed MyFantasyLeague's `+0.02/day` under
the heading `Market trend`. In cross mode there was no chart at all: the history index was
asked for a source called `cross`, which no capture produces.

## Regenerating

Needs a checkout of the private retained store beside the repository. The capture harness is
not committed — it is twenty lines of Playwright around `web/tests/e2e/static-server.mjs`, and
committing a script that only runs against a private data checkout would be a gate nobody can
run. The reproducible version of these assertions is
`web/tests/e2e/markethistory.spec.ts`, which runs on every `npm run e2e`.
