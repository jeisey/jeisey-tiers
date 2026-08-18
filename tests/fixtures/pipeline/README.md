# Fixture pipeline inputs

Small, entirely **synthetic** source payloads that drive the network-free Phase-1 pipeline
(`ffdraft build-fixture-artifacts`). Every player, id and price here is invented. Nothing is
an excerpt of a vendor dataset, so no source's redistribution terms are engaged.

The set is deliberately shaped around `docs/DATA_CONTRACTS.md` section 14. Each listed case
has a specific carrier, so a test can assert the behaviour rather than hope for it:

| Case | Carrier |
|---|---|
| normal veteran | `00-0000001` Marcus Vandelay (QB, 12 seasons) |
| rookie / prospect | `00-0000011` Bram Kowalczyk (TE, `years_exp` 0, `rookie_season` 2026) |
| player changing teams | `00-0000006` Tobias Ferreira (roster GB, crosswalk still says SEA) |
| same / similar names | `00-0000004` Chris Johnson and `00-0000005` Chris Johnson Jr. |
| missing optional id | `00-0000008` Nnamdi Brightwater has no `sleeper_id`; `00-0000009` Emeka Vasquez has no `espn_id` |
| ambiguous external mapping | MFL `6000015`: the ESPN bridge says Hollis Amadi, the crosswalk says Xavier Nkemdiche |
| stale source metadata | `stale_batch.json` carries a deliberately old `retrieved_at_utc` |
| market player missing from intrinsic output | MFL `6000099`, priced but on no roster |
| intrinsic player missing market ADP | `00-0000013` Ade Fontenot has no MFL quote |
| extreme / late ADP | `00-0000012` Yusuf Lindqvist at pick 218.4 |
| legitimate single-player top tier | `00-0000002` Dez Okonkwo, far clear of the field |

Three further hygiene cases are carried because Phase 0 measured them upstream:

- **whitespace-bearing id** — Sleeper reports `" 00-0000001"` with a leading space, exactly
  as observed in the real Sleeper map. It must trim, resolve and record a flag.
- **failed cross-check** — Sleeper record `5000014` reports another player's `gsis_id`.
  The record must fail closed rather than accept either reading.
- **non-player entities** — MFL `0151` (`TMWR`) and `0152` (`Def`) are team units and must
  never enter QB/RB/WR/TE identity.

`collisions/` holds a separate, deliberately broken registry input used only by the
fail-closed tests; keeping it out of the main set means the healthy pipeline stays healthy.
