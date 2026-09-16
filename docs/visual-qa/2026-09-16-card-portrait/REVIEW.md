# Visual QA — the player card's portrait, 2026-09-16 (ADR-087)

64 screens from the fixture build. Screens `01`–`57` are the existing set, re-captured
unchanged; `58`–`61` are new and are what this pass is for.

## Read this before reading the pictures

**The face is not a face.** The fixture's ESPN ids are synthetic (`4000001`…) and resolve to
nothing at the real host, and this sandbox has no egress to `a.espncdn.com` in any case. Every
portrait below is a **drawn silhouette** served by `web/tests/e2e/portrait-stub.mjs` — opaque
where the figure is, so it does to the layers under it exactly what a real cut-out will do.

What these screens therefore prove is the **treatment**: the frame, the position-tinted wash,
the scanlines, the corner ticks, the bottom fade, the crop, and the geometry at each of the
three card variants. What they do not prove is that a given player's picture is the right
picture — that is what `artifact.headshot_url_disagrees_with_id` and
`cross_artifact.headshot_player_not_in_tiers` are for, and they run on every build.

## The four new screens

| screen | variant | what to look at |
|---|---|---|
| `58-card-portrait-desktop` | 1c, 1440px | the hero. The figure's lower edge should **dissolve** into the rail, not end on a line. Both corner ticks visible — top-left and bottom-right |
| `59-card-portrait-tablet-band` | 1a, 900px | the rail is a row, so the portrait is a 4.5rem square left of the name. It must not become a picture with a card beside it |
| `60-card-portrait-mobile-sheet` | 1b, 390px | 3.25rem. Fair rank, the verdict and the status line are still above the tab bar with no tap — that is the constraint the size was picked against |
| `61-card-portrait-monogram` | 1c, 1440px | the fallback. Deebo Gray is the fixture's unbridged player. Same frame, same wash, same ticks; the face is `DG` in a quiet tint and **nothing about the card's geometry moved** |

## Two defects this review found and fixed

Both were invisible to every test and visible in the first capture.

1. **The bottom-right corner tick was buried.** The fade was a `::after` on `.portrait`, which
   is the last child in paint order, so it painted over the veil's own tick. The fade moved
   into `.portrait-veil`'s background as a second gradient layer; the ticks are that element's
   pseudo-elements and now paint above it. One element, no extra node.

2. **The monogram showed through the picture.** It was hidden on *having a URL* and then not
   hidden at all — so with a transparent cut-out over it, the letters would have shown around
   the player's shoulders on every card. The component now has three states rather than two
   and the stylesheet keys off `loaded`: the monogram stays while the request is in flight,
   which is the whole reason it exists, and goes the moment a picture has painted.

The first capture is what found both. Neither would have failed a test, and the second would
have shipped as "why does this player have letters on his chest".

## What was checked and is not a picture

- `npm run e2e` — 129 passed, including five new tests that count portrait requests before and
  after a card is opened. A host allowance alone would be satisfied by a board that fetched
  three hundred pictures on first paint.
- A **negative control** on the boundary guard: a foreign host was requested from a page under
  the guard and the guard failed the run. The allowance is one host, not "any image".
- `npm run verify:board` — zero disagreements. `verify-real-build.mjs` **blocks** the portrait
  host outright, because a gate standing between a build and the deployed site may not depend
  on a third party's uptime.
