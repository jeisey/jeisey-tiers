# `market-data` — the append-only point-in-time capture store

This branch is **data, not code**. It shares no history with `main`, is never merged into
it, and is never rebased away. It exists because ADR-006 requires point-in-time market
history to survive, and ADR-010 makes that history the only route to a future learned
arbitrage model: MyFantasyLeague's historical export is a season-long aggregate recomputed
at request time, so a price we do not capture on the day can never be reconstructed.

The architecture, the layout, the manifest contract and the append-only rules are recorded
in `docs/DECISIONS.md` **ADR-038** on the code branches.

## Layout

```text
market/<source_id>/<season>/<YYYY-MM-DDTHH-MM-SSZ>/
    manifest.json                        # provenance, filters, hashes, resolution counts
    players.raw.json.gz                  # exact MFL player-directory payload bytes
    cohorts/<cohort_id>/adp.raw.json.gz  # exact MFL ADP payload bytes, one per cohort
    market.normalized.json.gz            # normalized, identity-resolved quotes
status/<source_id>/<season>/<YYYY-MM-DDTHH-MM-SSZ>/
    manifest.json
    status.normalized.json.gz            # normalized Sleeper current-status rows
```

## Rules

- **A retained directory is immutable.** A new timestamp appends. An existing path with
  identical content is an idempotent no-op. An existing path with different content fails
  closed and writes nothing.
- **Every file is hashed in its manifest.** `ffdraft validate-market-history` re-hashes them.
- **`source_as_of_utc` is always null for MyFantasyLeague.** Its response `timestamp` is
  generation time, retained as vendor metadata and never promoted to a data-as-of claim.
- **Do not hand-edit anything here.** Take a new capture instead.

## How captures are made

`ffdraft snapshot-market` and `ffdraft capture-status`, run from
`.github/workflows/market-capture.yml` on a GitHub runner (ADR-009). Phase 7 will schedule
the same commands; nothing about this store needs to change when it does.
