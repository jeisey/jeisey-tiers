# Deliberately broken identity fixtures

Used only by the fail-closed tests. `roster_espn_collision.json` gives two distinct
canonical players the same `espn_id`, which poisons that index: the registry must
report a collision and every lookup through `4000004` must return `ambiguous`
rather than a player (ADR-005 / ADR-019).
