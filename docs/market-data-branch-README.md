# `market-data` — the append-only point-in-time capture store

This repository is **data, not code**. It exists because ADR-006 requires point-in-time
market history to survive, and ADR-010 makes that history the only route to a future learned
arbitrage model: MyFantasyLeague's historical export is a season-long aggregate recomputed
at request time, so a price we do not capture on the day can never be reconstructed.

**It is private, and it must stay private.** It holds retained MyFantasyLeague payloads and
normalized Sleeper status rows. Those are a private research cache, not a redistribution:
Sleeper's terms are non-commercial, and nothing here has been cleared for republication. The
application repository, `jeisey/jeisey-tiers`, is public; this one is the reason that is safe.

Until Phase 7 this was a branch *of* the application repository. It moved here when that
repository was made public, because GitHub visibility is a property of a repository, not of a
branch — there is no private branch inside a public repository. Nothing else changed: the
branch is still called `market-data`, and a checkout is byte-identical to what the old branch
held. The architecture, the layout, the manifest contract and the append-only rules are in
`docs/DECISIONS.md` **ADR-038**, as amended by **ADR-049**, in the application repository.

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

`ffdraft snapshot-market` and `ffdraft capture-status`, run on a GitHub runner (ADR-009)
from the application repository:

- `.github/workflows/daily-refresh.yml` — every morning at 07:17 America/New_York, as the
  first job of the production refresh. It validates the whole store before it pushes.
- `.github/workflows/market-capture.yml` — on demand, for an extra snapshot before a rules
  change or a wide `study` capture.

Both reach this repository through `.github/actions/market-data-store`, which reads the
address from `config/source-registry.yaml` and authenticates with the `MARKET_DATA_REPO_TOKEN`
fine-grained token — scoped to this repository alone.

## Reading it

```bash
git clone https://github.com/jeisey/jeisey-tiers-market-data ../market-data
uv run ffdraft validate-market-history ../market-data --season 2026
uv run ffdraft build-current   --store ../market-data
uv run ffdraft build-arbitrage --store ../market-data
```
