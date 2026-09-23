# 2026-09-23 — the Opportunity Board reads the signal layer (ADR-092)

Evidence for the board's Role / Add momentum / Next game readings, its three filters and its two
new orderings. Two kinds of capture, kept apart by name.

**`81`–`92` come from the fixture builds** (`npm run e2e:screens`, served by
`web/tests/e2e/static-server.mjs`). Each shows a *state* the board has to draw differently, and
two runs of the same code reproduce them.

**`real-01`–`real-07` come from a real `build-ros` on live 2026 week-2 data**
(`--as-of 2026-09-22T23:50:00Z`, the same anchor as production's run 61) **with the retained
Sleeper window** — the fourteen behaviour snapshots inside the seven days, read as data from the
private store — and the fixture draft bundle beside it. They are a dated record, not a baseline
to diff. `verify:board` passed on that build with zero disagreements across all 507 PPR/12 rows.

## The question each screen answers

The success test is whether the board says which candidates deserve a deeper look, and why,
before a card is opened.

| screen | state | what to look at |
|---|---|---|
| `81` | fixture board, desktop | the chart's fourth readout is **Role** (`SNAP 81% ▲ +34 pts`, `PASS ATT 48 ▲ +20`), not a generic snap share; the three chips above it |
| `82` | fixture table, desktop | every state in one table: QB attempts (Jalen Marsh), a flat lead whose other rails rose (Rashee Kirk, `▬ no change`), no snap value (Trey McBride, `no latest value`), one appearance (`wk 8 only`), a window that **ended** four days early (Zay Meadows, muted, `· to Aug 17`), one observation, never in the feed, a bye before the next game (`bye W9 · no line yet`), an unposted line, no game published (WAS) |
| `83` | Role rising + Momentum rising | two rows; the status line prints what passed **and** how many rows had no reading to decide on |
| `84` | Role order, all positions | rising → flat → falling → no reading; inside a category by ROS rank, and the note says why (a QB's attempts are not share points) |
| `85` | Role order, WRs only | inside a category, the larger published change first |
| `86` | Momentum order | current slopes by slope, then the ended one, then no slope — "not in feed" is never a zero between a riser and a faller |
| `87` | a link naming Role rising on a build with no role series | the chip is struck through, a notice names the missing artifact, and the board is **not** emptied |
| `88` | behaviour feed down | Adds/Drops/Net `—`, momentum `—` (series not published), "Momentum rising" disabled; role and next game unaffected |
| `89` | 1024px | Team and Drops step aside, signal cells wrap to a second line, no sideways scroll |
| `90`, `91` | 420px board and table | the chart row carries a Role line; the table pins the name and leads with Role |
| `92` | 320px controls | five orderings and three chips wrap instead of clipping |
| `real-01` | live board, desktop | the role readout on real week-2 data, all positions |
| `real-02` | live table | the column set on 507 rows with six- and seven-digit Sleeper counts |
| `real-03` | live Role rising + Momentum rising | 33 of 507; the status line: 175 role risers, 150 with no published change; 56 current momentum risers, 370 with no current slope |
| `real-04` | live RBs by role | Aaron Jones Sr. and Emanuel Wilson both `▲ +35 pts` snap — one at ROS VORP 55.2 with 0 adds and falling momentum, one at −6.6 with 2.58M adds |
| `real-05` | live momentum order | Emanuel Wilson first (+265,334/day); surfaced QBs Mariota and Winston near the top with one game each |
| `real-06` | live 420px, filtered | the phone table: name pinned, role first |
| `real-07` | live QBs by role | Mahomes ▲ +20 attempts, Stroud ▲ +17, Geno Smith ▲ +17 — sizes compared because one position is on screen |

## "Which three players should I open first?"

On the live board, `Role rising` + `Momentum rising` answers it in one click, and the ordering
decides what "first" means — each ordering is one quantity, never a blend:

- **by ROS value**: Davante Adams (snap ▲ +11), Patrick Mahomes (▲ +20 attempts), Travis Kelce
  (snap ▲ +14) — rising role, rising interest, strong model value. Their add counts (≈19–33k)
  are small next to the wire's biggest names, which is the add count's own caution about
  availability (ADR-088).
- **by adds**: Emanuel Wilson (2.58M), Adonai Mitchell (1.72M), Darren Waller (611k) — where the
  wire is moving, with the role reading beside it and ROS value on the same row.

## Not defects, recorded

- A player outside Sleeper's top 100 shows `0` adds (the board artifact publishes 0 when the feed
  is up) beside `not in feed` momentum (the series publishes no point). Pre-existing board
  contract; see ADR-092 "Deliberately not done".
- Two live records carry `display_name: "None"` (RB, NO and MIA). Pre-existing, pipeline-side.
