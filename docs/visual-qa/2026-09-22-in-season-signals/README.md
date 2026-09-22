# 2026-09-22 — the in-season signal layer (ADR-091)

Evidence for the role, production and next-game blocks on the player card and the evidence row
on Pick of the Week. Two kinds of capture, kept apart by name.

**`48`–`80` come from the fixture builds** (`npm run e2e:screens`, served by
`web/tests/e2e/static-server.mjs`). Each screen shows a *state* the signal layer has to draw
differently, and two runs of the same code reproduce them byte for byte.

**`real-01`–`real-06` come from a real `build-ros` on live 2026 week-2 data**
(`--as-of 2026-09-22T16:00:00Z`) with the draft bundle from the fixtures beside it. They are a
dated record, like `docs/source-probes/`, not a baseline to diff. The private behaviour store
was not reachable from the capturing session, so the real build has no add counts, no Pick of
the Week cards and no momentum; `verify:board` passed on it with zero disagreements.

| screen | state | what to look at |
|---|---|---|
| `48`, `49` | the in-season card, desktop and mobile | the section order: role → production → cohort → next game → roster moves → momentum |
| `50` | the draft card opened in November | the draft card is unchanged; the signal layer lives only on the in-season card |
| `58`, `62`, `63` | Pick of the Week at 1440, 390 and 320 px | the evidence row replaces the two-share tile row; no horizontal overflow |
| `67` | QB (PHI, on bye in week 9) | rails are pass and rush attempts, never snap or target share; EPA per dropback and points from TDs tiles; QB cohort rows |
| `68` | RB, role rising | ▲ changes on snap and carry share with the window printed; points rail beside them |
| `69` | WR, role declining | ▼ changes shown, not hidden; air-yards share rail |
| `70` | TE, no snap row in the latest game, line unposted | `·` mark, change withheld (never reached back for); "no line posted yet", no split bar |
| `71` | a player absent for weeks | `×` marks, never floor-height bars |
| `72` | a player with no usage record | "No week-by-week role is published for him on this build." |
| `73` | the build published no signal artifacts | both blocks say which artifact is missing; every other value unchanged |
| `74` | next game and momentum | spread from the team's side, implied split of the total, the sportsbook statement, retrieval time; add momentum on the card |
| `75` | one appearance (surfaced player) | `week 8 only`, no change printed; no projection or pace, and the card says why; tiles agree with the rails |
| `76`, `77` | role tab at 390 and 320 px | rails reflow; no overflow |
| `78`, `79` | Pick of the Week evidence, desktop and mobile | Role · observed / Production / Next game · context as three labelled blocks |
| `80` | Pick of the Week with no signal artifacts | the picks are the same players; each evidence block says the build published no role series / no schedule context |
| `real-01`, `real-06` | Emanuel Wilson, RB, desktop and mobile | snap 6% → 41%, carry 9% → 53% in week 2 against week 1 |
| `real-02` | Aaron Jones Sr., RB | snap 46% → 81%, carry 35% → 82% |
| `real-03` | Josh Allen, QB | attempts rails; EPA per dropback +0.46 |
| `real-04` | Jaxon Smith-Njigba, WR | target and air-yards share |
| `real-05` | Trey McBride, TE | the next game with a posted week-3 line |
