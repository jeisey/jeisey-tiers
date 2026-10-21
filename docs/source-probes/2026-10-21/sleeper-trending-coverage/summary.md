# Sleeper trending feeds — coverage probe, 2026-10-21 (ADR-114)

Regenerate with `uv run python scripts/probe_sleeper_trending_coverage.py --season 2026 --out <dir>`
(about 60 paced requests, one per second, plus nflverse rosters). `report.json` beside this file
is the machine-readable record and holds aggregates only. `selection-audit.json` is the before /
after audit of the behaviour-based selections on the live build.

| Question | Measured answer |
|---|---|
| Documented parameters | `lookback_hours` (default 24), `limit` (default 25). Nothing else, and no per-player route |
| Does a larger `limit` return more? | **No.** 101, 250, 500, 1000, 5000: exactly 100 distinct ids, the same set as `limit=100`, both feeds |
| Is each feed a top-N list? | Yes: sorted by count descending, and `limit=25` is an exact prefix of `limit=100` on both feeds |
| Undocumented pagination or filters | `offset`, `page`, `skip`, `start`, `cursor`, `after`, `position`, `season`, `week`, `order`, `sort`, `min_count`: HTTP 200, **no population change** (baseline drift 0) |
| Other windows | 1, 6, 12, 24, 48, 168 h: each honoured, each capped at 100 rows |
| Season selector | None; the population is Sleeper's whole platform |
| Floors at the probe (24 h) | add ≈ 38.5k, drop ≈ 58.7k (they move with every request) |
| Universe (2026 spine) | 987 QB/RB/WR/TE with a verified `sleeper_id`; 212 without; 0 ambiguous |
| Universe observed | add 83, drop 77, both 29 (2.9%), neither 856 |
| Retained history | 76 captures; 73.7% of player-snapshot rows one-sided, all zero-filled before ADR-114 |

## Conclusion

Complete daily counts are not obtainable from the documented route. The repair publishes each
side's observability and never a zero for an absence; the coverage remains the top 100 of each
feed. See `docs/DATA_SOURCES.md` §24 and ADR-114.

## Selection audit (live build 2026-10-21, redraft-12 PPR)

Pick of the Week: **unchanged** in all five sets. Win My Matchup's YOLO net-add bar: changed at
every position (one-sided rows now enter with a bound, not a zero-filled net) — QB 71,840 → 121,500
(pool 14 → 11), RB 124,432 → 111,854 (21 → 16), WR 148,088 → 126,949 (22 → 18), TE 117,561 →
61,611 (8 → 7).
