# Historical source fixtures

Synthetic nflverse-shaped rows for the Phase-2 pipeline. They are read through the real
adapters (`ffdraft.features.sources.load_fixture_sources`), so the integration tests
exercise normalization, contracts, eligibility, features, scoring, VORP and the quality
gate on the same code path production takes — with no network.

Nothing here is vendor data. Every player, team, statistic and identifier is invented.

## Seasons

Source seasons 2022–2025; target seasons **2024 and 2025**. That pair is deliberate: 2024
sits in the lagged-only era and 2025 in the timestamped-snapshot era, so one build crosses
the ADR-018 boundary. The 2024 opener is a Thursday and the 2025 opener a Wednesday, which
exercises both anchor-weekday cases.

Teams are `BUF` and `MIA` — real nflverse abbreviations, because the team-code domain check
rejects anything outside the league vocabulary.

## Cast

| Player | GSIS | Case it carries |
|---|---|---|
| Vera Steadman | `00-0090001` | Veteran WR with full prior history; also listed as a punt returner, so the depth-rank selection must ignore a rank-1 slot at a position the project does not model |
| Marcus Lagg | `00-0090002` | Veteran RB rostered by two clubs in 2023 (a legitimate duplicate `(season, gsis_id)` pair) and observed on a different team in the 2025 snapshot, giving a true `team_change_flag` |
| Quill Passer | `00-0090003` | Veteran QB; the only source of passing volume, so the QB-only efficiency features have a denominator |
| Tate Endzone | `00-0090004` | Low-volume TE whose targets never reach the minimum denominator, so the efficiency ratios stay null |
| Rookie Draftee | `00-0090005` | 2025 first-round RB: draft class plus a pre-anchor depth listing, with combine measurements |
| Undrafted Newcomer | `00-0090006` | 2025 UDFA WR visible **only** on the pre-anchor depth snapshot — the player a lagged-only universe structurally cannot contain |
| Ghost Roster | `00-0090007` | On the previous season's roster and records nothing in either target season: an eligible row whose honest label is zero |
| Lineman Guard | `00-0090008` | Offensive lineman, excluded as `non_core_position` with his real position in the ledger |
| Twin Alpha / Twin Beta | `00-0090009` | One GSIS id under two different names on the 2023 roster — the upstream identity collision that must fail closed (ADR-019) |
| Missing Bio | `00-0090010` | No birth date in any source, so `age_at_anchor` is null and `age_at_anchor_known` is false |
| Prior Draftee | `00-0090011` | 2024 fourth-round WR: a pre-2025 rookie, so `depth_unavailable` with no fabricated rank |
| Snap Only | `00-0090012` | Has snap counts but no ffopportunity rows and no 2024+ stat lines, so the expected-points join has a measurable, legitimate gap |

## Deliberate contents

* **Every weekly row carries every column the adapter reads**, including the ones that are
  zero for all fixture players. Omitting a key would look to the schema check exactly like
  the column disappearing upstream.
* **Week 2 of each season carries a lost fumble and a two-point conversion**, so those
  scoring paths are exercised rather than assumed.
* **The last two weeks of each season straddle the fantasy horizon**, and one postseason row
  exists per season, so the horizon exclusion is provable rather than asserted.
* **`load_draft_picks` rows carry career outcomes** (games, approximate value, Pro Bowls).
  The contract must refuse to normalize them.
* **`load_players` rows carry current-state columns** (`status`, `latest_team`,
  `last_season`, `years_of_experience`). The biographical contract must refuse those too.
* **The 2025 depth chart has two timestamps**, one before the anchor and one after, so the
  point-in-time filter has something to discard.
* **The 2024 depth chart is week-1 weekly-era data**, present precisely to prove ADR-018
  ignores it.

## Regenerating

Edit the JSON by hand. There is no committed generator: the fixtures are the reviewable
artefact, and a change to them should be a deliberate, readable diff rather than the output
of a script nobody reads. If a change is large enough to want scripting, write the script,
run it, and delete it — the same way this set was first produced.
