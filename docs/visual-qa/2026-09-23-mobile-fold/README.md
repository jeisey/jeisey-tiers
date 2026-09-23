# 2026-09-23 — the phone's control bands fold (ADR-093)

Evidence for the owner's report that on a phone "half the mobile screen is just navbar". Every
screen here comes from the fixture builds.

**`92`–`99` come from `npm run e2e:screens`**, served by `web/tests/e2e/static-server.mjs`, so two
runs of the same code reproduce them. **`before-*` come from the parent commit `70491d5`**, built
and served the same way from a separate worktree. They are a dated record of the state this
change replaced, and the current code cannot reproduce them.

## Measured, 390×844, Opportunity Board

| | before | after |
|---|---|---|
| sticky block while the board scrolls | 248px | **86px** |
| chart's first row on first paint | y = 743 | **y = 391** |

## The question each screen answers

| screen | state | what to look at |
|---|---|---|
| `before-opportunity-first-screen` | parent commit, first paint | the season-mode band, four controls and the tabs, then the orderings, depth button and chips: the chart's first row is at the bottom edge |
| `before-opportunity-scrolled` | parent commit, scrolled | the sticky block is 248px, which the board scrolls under for as long as it is read |
| `93` | folded, first paint | one **Settings** row and the tabs; the board's **Options** row; the census line (`19 shown`) is still printed; the chart starts halfway up the screen |
| `94` | folded, scrolled | the sticky block is the Settings row and the tabs, 86px |
| `95` | Settings open | season mode, scoring, teams, position and search between the row and the tabs; the chevron points up |
| `96` | Options open | Order by, Show full board, Show only, exactly as before the fold |
| `97` | a shared link: half, search `cook`, in-season override, momentum order, two filters | every one of them is named on a folded row, so no filter can be on without being on screen |
| `98` | 320px, a search and three filters | both rows ellipsise rather than wrap or widen the page |
| `99` | 568×320 (a small phone on its side), Settings open, scrolled | the open panel scrolls inside itself; the tabs stay on screen |
| `92` | 320px, Options open | (re-captured) the five orderings and three chips still wrap rather than clip once shown |

Desktop and tablet are not pictured because they did not change. Full-page screenshots of 8
views at 1440, 1024, 900 and 768px were compared as PNG bytes against the parent commit, and all
32 were identical.
