# Start/Sit — 2026-09-30 (ADR-096)

Captured from the **fixture** in-season build (`web/dist-in-season`, served at
`/scenario/in-season/`) after `npm run e2e` rebuilt it, so the images are reproducible. The
fixture week is built so every case the tab must get right is present (see
`web/tests/fixtures/artifacts.ts`, "the weekly layer"): a steady back and a boom-bust receiver
with a flip point between them, CIN teammates with a measured correlation, a Questionable, a
Doubtful and an Out player, two teams on bye, and a game with no posted line.

Every capture reported **0px of horizontal overflow**. The capture script also logs console
errors, and there were none.

| File | Screen |
|---|---|
| `01-desktop-pair-even-1440` | Cook vs Nightingale at an even matchup: Nightingale is the pick although Cook has the higher median, and the page says both halves |
| `02-desktop-pair-up20-flip-1440` | The same pair at Up 20: the pick flips to Cook, and the flip sentence points back to Nightingale's ceiling below +6.5 |
| `03-desktop-four-down10-1440` | Four players at Down 10: four shield-meter cards in one row, verdict, ridges, the head-to-head matrix, the "why" account |
| `04-laptop-four-1024` | Four players at 1024px: the deck is two cards a row |
| `05-tablet-four-820` | Tablet portrait |
| `06-phone-pair-390` | A pair on a phone: the empty slots step aside and the whole verdict is on the first screen; five tabs on one row |
| `07-phone-four-390` | Four players on a phone: the P25–P75 cell is wider, and a range that still does not fit wraps after its en dash; none is clipped |
| `08-reflow-four-320` | WCAG reflow width: one card a row; the tab row scrolls sideways, as it does only below 360px |
| `09-desktop-pending-and-out-1440` | A game with no posted line (Ertz) and a player ruled Out (Kirk) beside Cook: both listed, both explained, neither in the verdict |
| `10-desktop-week-board-1440` | Full page: the week board ordered by startable probability, with byes and the pending game last |

The live 2026 week-4 board was reviewed the same way from a real `build-ros` run (Rice vs
Nacua, and St. Brown, Chase, Rice and Nacua at Down 10) and is not committed, because it
changes with every build. Two phone defects were found there and fixed before these captures:
a clipped P25–P75 range in a half-width card at 390px, and a tab label wrapping onto two lines
once a fifth tab existed.
