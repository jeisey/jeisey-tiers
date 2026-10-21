# Visual QA — card controls, bye filter, methodology on Data (ADR-114, ADR-115), 2026-10-21

Before: main at ee863cc. After: `claude/magical-maxwell-0s0xat`. Both from the in-season fixture
build (`npm run e2e:build`), Chromium 141.0.7390.37, `deviceScaleFactor: 1`. Emulation, not a
physical device.

* `card-controls.mjs` → `{before,after}/card-*.png` and `report.json`: the card's close and
  Expand controls at 320, 390, 412×839 (Pixel 7), 390×560, 768, 1024 and 1440 px, for three cards
  (the reported Puka Nightingale, Kyle Pitts Sr. with an Out badge, and the longest name), both
  header states, all six tabs and scrolled. **Before: 92 overlapping measurements** (6.41 × 25.77
  px compact, 6.41 × 15.77 px expanded). **After: 0 of 160; smallest gap 8 px**; no page or card
  overflow; Escape closes and focus returns to the opening button everywhere.
* `views.mjs` → `{before,after}/<view>-<width>.png` and `views-report.json`: ROS (board, table,
  `nobye=1`), Start/Sit `nobye=1`, Opportunity (board, table), POTW and Data's *Reading the
  boards* at 320, 390, 412, 768, 1024 and 1440 px. 0 page overflow either side. The only console
  errors are the fixture's synthetic portrait URLs on the external host (404), identical before
  and after. Caption length at 1440 px: ROS 1,084 → 125 characters; Opportunity 2,036 → 467.
