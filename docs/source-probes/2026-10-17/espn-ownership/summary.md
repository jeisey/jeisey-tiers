# ESPN roster and start percentages — source probe, 2026-10-17 (ADR-112)

Regenerate with `uv run python scripts/probe_espn_ownership.py --season 2026 --out <dir>`
(eight paced requests). `report.json` beside this file is the machine-readable record. It
holds aggregates only and no ESPN player rows.

## Answers

| Question | Measured answer |
|---|---|
| Authentication | None. Every request below was unauthenticated, with a descriptive User-Agent and no cookies |
| Global `/seasons/2026/players` route honours `X-Fantasy-Filter`? | **No.** Without a header: 50 rows, and `X-Fantasy-Filter-Player-Count: 2675`. With *any* filter, including a two-id `filterIds` and `limit: 2`: all 11,618 players (2.35 MB decoded `players_wl`; 45 MB `kona_player_info`), and the count header reads 0 |
| League-default route `/segments/0/leaguedefaults/3?view=kona_player_info` honours it? | **Yes.** `limit`, `sortPercOwned`, `filterStatsForSourceIds` and `filterRanksForScoringPeriodIds` all change the response. Invalid values answer HTTP 400 with a typed message. Defaults 1, 3, 5 and 6 are identical; 2 and 4 answer 404 |
| Complete? | 1,052 rows = `X-Fantasy-Filter-Player-Count` 1,052 = the global list's QB/RB/WR/TE/K/DST players carrying an ownership object (same ids, 0 value disagreements) |
| Cost | One request: **463,301 B on the wire**, 2,490,153 B decoded, 0.7 s. ESPN's season object adds 201 B |
| Core rows (QB/RB/WR/TE) | 962. Every one carries `percentStarted` (962/962) |
| Scale | Percent, 0–100, two decimals. `percentOwned` ranges 0.0–99.93 and `percentStarted` 0.0–99.75. 128 core rows are exactly 0.0 |
| `percentStarted > percentOwned` | 0 rows |
| `scoringPeriodId` | 0, 1, 5, 6, 7 and omitted all return byte-identical ownership (`percentOwned`, `percentStarted`, `date`, `percentChange`), so no period is requested |
| Current period | `/seasons/2026` → `currentScoringPeriod.id = 6` |
| Source timestamp | `ownership.date` per player, epoch ms, from 2026-10-10T04:30Z to 2026-10-17T18:30Z. Stamps cluster at :30 past the hour. 31 core rows were stamped more than 24 h before the probe, all at low roster shares |
| Other ownership keys | `percentChange` (window not stated), `leagueType` (0 on every row), `activityLevel` (null), and ADP/auction keys (discarded) |
| Cache | CloudFront, `Vary: x-fantasy-filter`; `cache-control` read 300 s and 5 s on different requests |
| Identity | 885 of 962 core rows resolve through the verified `espn_id` crosswalk (nflverse 2026 + 2025 rosters, 1,254 registry players). **All 268 rows rostered ≥ 1% resolve.** The 77 that do not are all under 1%. 0 ambiguous |

## What is not verified, and so not claimed

* **The denominator of `percentStarted`.** It is plausibly "share of ESPN leagues starting
  him", which is consistent with started ≤ rostered on every row, but ESPN does not state it.
  So no started-among-rostered ratio and no roster-minus-start gap is computed.
* **Which week's lineups `percentStarted` counts.** No period parameter changes it. The
  product prints the period ESPN reported as current at retrieval ("read during ESPN period
  6") and never says "Week 6 start rate".
* **What `ownership.date` means.** The :30 cadence suggests an hourly recompute, and the old
  stamps on low-roster players suggest "last changed". Both are unverified, so the stamp is
  published as "ESPN's update stamp", beside our retrieval time, and freshness is judged on
  retrieval time.
* **`percentChange`'s window.** It is retained privately and published nowhere until our own
  daily captures can confirm its window.

## Rights

Reachable is not licensed. ESPN's pages link the Disney Terms of Use (last updated
2024-05-24). They limit use to personal, noncommercial use (§2.A, §3.G) and prohibit
automated access or extraction "using a robot, spider, script, or other automated means",
data mining and web scraping (§2.B.x). They also grant "no right to reproduce, distribute,
communicate to the public" (§2.A). `lm-api-reads.fantasy.espn.com/robots.txt` answers 403.
`www.espn.com/robots.txt` disallows `anthropic-ai` and several AI crawlers outright; this
probe and the capture identify themselves as `jeisey-tiers`. No sanctioned public API exists.

The project owner reviewed these clauses on 2026-10-17 and chose to enable daily capture and
public display for this non-commercial project, with attribution (ADR-112). That is an owner
decision and not a legal clearance.
