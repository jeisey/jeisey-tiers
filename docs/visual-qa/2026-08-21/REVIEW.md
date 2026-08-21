# Visual QA review — 2026-08-21 (Phase 6)

Captured from the fixture build at `21cf583..`, reviewed by eye. Defects found during the pass
were fixed and the set recaptured; what follows records both.

## Defects found and fixed

| Screen | Defect | Fix |
|---|---|---|
| Tier board (all) | The axis was scaled to P10-P90 while the chart drew P25-P75, so every median sat inside the middle third of the plot and a third of the width was blank. | Scale the axis to the interval actually drawn, and drop the outer whisker from the chart (it is in player detail and in every mark's accessible label). |
| Tier board (all) | Player labels crossed neighbouring intervals and became unreadable. | A surface-coloured halo behind label text via `paint-order: stroke`. |
| Tier board (mobile) | "James Cook III" shortened to "III". | A generational suffix is not a surname; `shortName` drops `Jr/Sr/II/III/IV/V` before taking the last word. |
| Tier board (long boards) | The scale existed only at the foot of a 1,800px chart. | Tick labels repeated at the head. |
| Draft rail | The gap label column was narrower than its longest label, so "150.1 picks later" ran under the rail. | Widened the reserved column and shortened the phrase to `+150.1 picks later`. |
| Arbitrage view | Three stacked notice panels above the chart pushed the board off a phone screen entirely. | One notice that states the condition outright, with the evidence in a `<details>` disclosure. |
| Arbitrage table (mobile) | The page scrolled horizontally by ~700px with no visible cause. | `.table-scroll` was not a containing block, so the absolutely positioned screen-reader-only spans inside table cells escaped the scroller and dragged the document's scroll width out to the table's width. `position: relative` on the scroller. |
| Controls (tablet) | The search field filled the full row width. | Capped at 24rem. |
| Data view | Every reference section rendered as a narrow ribbon down the left of a 1440px page. | The three reference sections flow into a responsive two-column grid, each column keeping its own readable measure. |
| Tablet, RB filter | The screen showed one row, because the fixture board held one running back. A one-row screen catches no layout defect. | The fixture board grew from ten players to eighteen — five RB, seven WR, three TE, three QB across three tier bands — which also gives the position filter, the tier grouping and the export counts something to be wrong about. |

## Checked and clean

- No clipped text, no colliding labels, no marks outside the plot area at 1440, 900 or 390px.
- No horizontal page overflow on any captured screen (asserted by the capture script).
- Sticky table headers hold on scroll; no header overlaps a row.
- Tier lanes are separated by whitespace and a change of surface. No rule, arrow or "cliff"
  annotation is drawn anywhere between two tiers.
- Injury badges sit beside player names and never over them; the longest observed badge is
  `Q · Hamstring`.
- Focus is visible on chart marks, table header buttons, player buttons, the segmented controls
  and the skip link.
- Under `/jeisey-tiers/` every asset, artifact and CSV link resolves; no `/data/...` request is
  made.
- The degraded-market screen is a single calm line, not a full-page error, and the tier board is
  reachable and unchanged.
