# Jeisey Tiers

**Live site: <https://jeisey.github.io/jeisey-tiers/>**

Jeisey Tiers is a free, static fantasy-football site for redraft leagues. Before the season it is
a draft sheet: a value model that never sees a market price, tiers discovered from that value, and
a separate comparison of that value with draft-market ADP. Once the regular season starts it
switches to in-season tools: rest-of-season tiers, a weekly Start/Sit comparison, trade targets,
a waiver-activity board and a weekly pick at each position.

Every number on the page comes from versioned JSON/CSV artifacts built by GitHub Actions and
served by GitHub Pages. There is no backend, no account and no runtime call to a data vendor.

## What the site does

The site has two modes. **Auto** (the default) follows the NFL schedule: Draft mode before the
season's first regular-season kickoff, In-season mode from that kickoff. The mode switch in the
controls lets you open either mode at any time; the draft board stays reachable all season.

### Draft mode

| Tab | What it shows |
|---|---|
| **Tiers** | The intrinsic Tier board and table: fair rank, positional rank, simulated value over replacement (VORP) with its P10–P90 range, and contiguous tiers labelled `S`, `A`, `B`, … The board shows the draft-relevant top by default and opens the rest on request. |
| **Arbitrage** | The Draft Rail and table: each player's fair rank against his ADP, drawn as the signed gap in picks. A market selector switches between the published ADP sources (Fantasy Football Calculator "FFC Recent" and MyFantasyLeague "MFL Cumulative") and, when both are present, a cross-market spread view. |
| **Data** | Build time, model versions, source status, methodology, limitations and attribution. |

### In-season mode

| Tab | What it shows |
|---|---|
| **ROS tiers** | Rest-of-season value and tiers from a separate rest-of-season model, from an explicit cutoff week. It is a different quantity from the preseason fair rank and the two are never averaged. |
| **Start/Sit** | Compare two to four players for one lineup slot. Ranks them by the chance each gives you to win the week at your matchup margin, prints the calibrated head-to-head probability and the margin at which the answer flips, and shows each player's next-game range, game context (implied team total, kickoff-hour forecast) and injury designation with how often that designation has meant a missed game. |
| **Trade** | Offer one to three players, choose what you want back (rest-of-season value, highest ceiling or highest floor) and how many players (1–3), and browse incoming packages whose expected rest-of-season value falls within a band around what you offer. Packages can be swapped, extended and kept. |
| **Opportunity** (`Opp` on narrow screens) | Rest-of-season value beside what managers are doing on the waiver wire: Sleeper add/drop counts, net adds, add momentum and role direction. Five separate orderings and single-signal filters; no blended score. |
| **POTW** | Pick of the Week: one waiver target per position. Add volume decides who is eligible; rest-of-season value decides who is picked. Each card prints the threshold the player cleared. |
| **Data** | As above, plus the in-season methods. |

**Player cards** open from any board row or chart mark. They carry the player's model numbers,
range, market history, current status and, in season, his next game and his availability
reading. Headshots are loaded from ESPN only when a card or Pick of the Week is opened.

## Leagues and scoring

Defined in [`config/league-defaults.yaml`](config/league-defaults.yaml):

- Scoring: Standard, Half-PPR and PPR (4-point passing TDs, −2 interceptions and fumbles lost).
- League size: 10, 12 or 14 teams — nine scoring × size presets. The default view is PPR, 12 teams.
- Roster: 1 QB, 2 RB, 2 WR, 1 TE, 2 FLEX (RB/WR/TE), 5 bench. Preseason replacement level comes
  from starter and FLEX allocation, never from ADP; in season it is the best unrostered player
  (ADR-071).
- Positions: QB, RB, WR and TE. No kickers, team defenses, superflex, IDP, dynasty or custom scoring.

## Using it

- **Pick your league** with the scoring and team-count controls, and narrow with the position
  filter and player search. The boards and tools switch to that preset.
- **Share a view** by copying the address bar. Tab, scoring, league size, filters, search, open
  tiers, the Start/Sit comparison and the Trade exploration are all stored in the URL query
  string (for example `?scoring=half&teams=10&position=rb`), so a link reopens the same view.
- **Export CSV** from the Tiers, Arbitrage, ROS tiers and Opportunity tabs. *Download full CSV*
  fetches the whole published board; *Export filtered CSV* saves exactly the rows on screen, in
  screen order. Filenames carry the board, preset and build date.
- **Read the availability marks** in season. `OUT · season`, `IR`, `OUT`, `D`, `Q` and `?` beside
  a name are the availability policy's reading of the roster and injury feeds (ADR-101). A
  player out for the season, on a reserve list, or out or doubtful this week is never a
  Start/Sit pick, Pick of the Week or a suggested trade target, but stays listed with the reason;
  his model numbers are unchanged. Season-ending is recorded from reviewed public reporting,
  never inferred from an IR designation. `?` means the evidence is missing, stale or
  contradictory — not that he is healthy.
- **Go home** with the logo: it opens the default view for the current point of the season.
- **Check freshness** in the header: the *Updated* timestamp is the build time, and the status
  chip names the most serious problem, if any (a degraded source, a stale build), and opens the
  Data view.

### When it refreshes

All times America/New_York (`.github/workflows/daily-refresh.yml`, `docs/OPERATIONS.md`):

| When | What |
|---|---|
| Daily, 07:17 | Full refresh: sources, draft board, draft-market comparison and, in season, the rest-of-season and weekly layers. |
| Tuesday, 12:40 | Post-week refresh, after Monday night's games are published. |
| Thursday and Friday 17:47, Sunday 10:23 | Game-day refresh: forecasts and injury reports are re-captured and the weekly layer is re-run from the committed models. |

Models are not retrained by the refresh. If any quality gate fails, nothing is deployed and the
previous site keeps serving, so the page can be stale but should not be partially built.

## Method, briefly

- **Intrinsic value.** The preseason model (`intrinsic-cb-hurdle-v1`) estimates a distribution of
  season fantasy points from football data only — nflverse statistics, roles, draft capital and
  ffopportunity expected points. ADP, expert or consensus ranks, market values and sportsbook
  lines are forbidden inputs, and a test fails on any import path from a market module into it.
- **Value over replacement.** A seeded Monte Carlo simulation fills every team's starters and
  FLEX in each draw and measures each player against that draw's replacement level.
- **Tiers.** Contiguous groups found by segmentation of the simulated value distributions; the
  tier count is discovered per build, not fixed per position.
- **Draft-market comparison.** `a0_rank_gap_v1` compares fair rank with ADP as a within-preset
  percentile. It is a transparent baseline, not a learned model. ADP is read from snapshots
  captured point-in-time into a private store; once the draft anchor passes, the draft board
  keeps the last price captured before it.
- **Rest of season.** `intrinsic-ros-v1` predicts the remaining season from completed weeks only.
- **Start/Sit.** `weekly-startsit-v1` predicts next-game points as seven quantiles. Unlike the
  draft and rest-of-season models it may read the week's sportsbook lines; nothing upstream
  reads its output.
- **Trade.** Packages are arithmetic over published rest-of-season fields; floors and ceilings for
  two- or three-player packages are approximations, printed with `~`.

Model cards: [`models/cards/`](models/cards/). Feature definitions:
[`docs/FEATURE_DICTIONARY.md`](docs/FEATURE_DICTIONARY.md) and
[`docs/ROS_FEATURE_DICTIONARY.md`](docs/ROS_FEATURE_DICTIONARY.md). Full methodology:
[`docs/MODELING.md`](docs/MODELING.md) and [`docs/DECISIONS.md`](docs/DECISIONS.md).

## Limitations

These are measured shortfalls or deliberate scope limits. The Data view lists them on the site.

- **Tier boundaries are unstable.** Preseason and rest-of-season tiers both failed their declared
  boundary-stability bar, so the board draws a tier as a band. Treat players either side of an
  edge as close.
- **The simulation draw count is a predeclared fallback**, not a converged count. A build is
  exactly reproducible for its seed; another seed moves expected VORP slightly and tier cuts more.
- **The draft-market comparison is not machine learning.** No learned surplus or probability of
  surplus is published, because point-in-time historical ADP does not exist to train one.
- **ADP cohorts are approximate.** MyFantasyLeague has no half-PPR filter, so Standard and
  Half-PPR are priced largely by PPR drafters; FantasyPros is retrieved but not published.
- **Start/Sit projects points given that the player appears.** A Questionable player's
  projection is not discounted for the chance he sits; the measured appearance rate for his
  designation is printed beside it instead.
- **Injury and practice reports are context.** The preseason and rest-of-season models do not
  read them, and the published status does not change their numbers. An absent designation means
  no report, not a clearance. How status affects which players the decision tools offer is
  governed by the availability policy (ADR-101, [`docs/UX_SPEC.md`](docs/UX_SPEC.md)).
- **`weekly-startsit-v2` is in shadow.** A candidate that also reads team health is recorded each
  week for a prospective test; it does not drive anything on the site. Weather and opposing-defense
  health are shown as context only, because they added nothing measurable over the lines.
- **No rostered percentage.** No permitted source publishes one; the waiver tools use add counts
  and say so.
- **Trade packages ignore who owns the players** and whether anyone would accept; asset value is
  not lineup value.

## Data sources and attribution

| Source | Used for | Terms |
|---|---|---|
| [nflverse](https://github.com/nflverse/nflverse-data) via [nflreadpy](https://github.com/nflverse/nflreadpy) | Statistics, play-by-play, rosters, depth charts, snap counts, schedules (including spread and total lines), injury reports, draft and combine data | Data broadly CC-BY 4.0 and owned by its respective owners; nflreadpy is MIT |
| [ffopportunity](https://ffopportunity.ffverse.com/) | Expected fantasy points, as a model input only | CC-BY-SA 4.0 |
| [MyFantasyLeague](https://api.myfantasyleague.com/) | Draft ADP | Read under MyFantasyLeague's developer rules with a registered client |
| [Fantasy Football Calculator](https://fantasyfootballcalculator.com/adp) | Draft ADP | Used with attribution, as its API terms ask |
| [Sleeper](https://docs.sleeper.com/) | Player status, injury designations, add/drop trending | Free for non-commercial use |
| [National Weather Service](https://www.weather.gov/documentation/services-web-api) | Kickoff-hour forecasts at U.S. venues | U.S. Government open data |
| [Open-Meteo](https://open-meteo.com/) | Kickoff-hour forecasts at venues outside the U.S. | Weather data by Open-Meteo.com, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| [ESPN](https://www.espn.com/) | Player headshots on cards, loaded by the browser from ESPN's CDN | No ESPN ranking, projection or ADP is used |
| [FantasyPros](https://www.fantasypros.com/) | Retrieved server-side; no FantasyPros number is published | Attribution given wherever retrieved |

Source policy, verification evidence and fallbacks: [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md)
and [`config/source-registry.yaml`](config/source-registry.yaml). The site is free and
non-commercial, with no ads, affiliate links or paid tier.

## Licensing

- **Code:** the repository has no `LICENSE` file; choosing a software licence is the owner's
  decision and has not been made.
- **Data:** the source terms above bind the data regardless of the code's licence.
- **Fonts:** Exo 2 and JetBrains Mono are vendored under the SIL Open Font License 1.1; the
  licence texts are in [`web/src/assets/fonts/`](web/src/assets/fonts/).
- **Logo:** `web/src/assets/jt_logo.png` is the owner's artwork; the favicons are generated from it
  by `scripts/make_favicon.py`.

## Development

Python is managed with `uv` and the frontend with `npm`; both lockfiles are committed. Tests and
the fixture pipeline run without network access.

```bash
# Python
uv sync --frozen
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest                          # network-free
uv run pytest -m live                  # opt-in live source checks

# Fixture pipeline: fixtures -> adapters -> identity -> contracts -> artifacts
uv run ffdraft build-fixture-artifacts --out web/public/data
uv run python -m ffdraft.cli validate-artifacts web/public/data
uv run ffdraft --help                  # every pipeline, evaluation and capture command

# Frontend
npm ci
npm run lint && npm run typecheck
npm run test -- --run                  # Vitest
npm run build                          # VITE_BASE_PATH=/jeisey-tiers/ for the Pages path
npm run e2e                            # Playwright: Chromium, mobile, accessibility (needs uv)
npm run e2e:browsers                   # Chromium, Firefox and WebKit smoke
npm run verify:board                   # rendered board against artifact bytes
```

Production builds (`build-current`, `build-arbitrage`, `build-ros`, `package-site-data`) read a
separate private repository of retained market and status captures and run in
`daily-refresh.yml`; see [`docs/OPERATIONS.md`](docs/OPERATIONS.md) for every workflow and
command. Generated artifacts (`web/public/data/`, `data/historical/`) are gitignored and
reproducible from code plus source releases.

| Path | Contents |
|---|---|
| `src/ffdraft/` | Python pipeline: sources, identity, features, models, simulation, tiers, market, arbitrage, in-season (`ros/`, `weekly/`, `opportunity/`, `behavior/`, `season/`), artifacts, CLI |
| `web/` | React/TypeScript frontend (D3 charts, TanStack tables) and its tests |
| `schemas/` | Public artifact contracts (JSON Schema) |
| `config/` | League presets, source registry, identity aliases, venues |
| `models/` | Versioned production and shadow model artifacts and their cards |
| `docs/` | Architecture, data contracts, sources, modelling, operations, UX, decisions (ADRs) |
| `docs/experiments/` | The committed evidence behind each model decision |
| `tests/` | Python tests: unit, contract, integration, data quality, leakage, model |

## For contributors and coding agents

Read [`AGENTS.md`](AGENTS.md) first; it is the repository's operating contract (with
[`CLAUDE.md`](CLAUDE.md) as the Claude Code bridge). Current work and state are in
[`TASKS.md`](TASKS.md) and [`SESSION_STATE.md`](SESSION_STATE.md); product scope is in
[`PRD.md`](PRD.md); design decisions are in [`docs/DECISIONS.md`](docs/DECISIONS.md).

Development history, including the phase-by-phase build and releases, is in
[`docs/HISTORY.md`](docs/HISTORY.md).
