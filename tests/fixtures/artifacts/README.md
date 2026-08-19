# Golden fixture artifacts

Committed output of `ffdraft build-fixture-artifacts --git-sha 0000000`, regenerated with
that exact command whenever the contracts change deliberately.

They are here for two reasons:

1. `docs/TEST_STRATEGY.md` section 4 wants golden outputs for artifact field order and CSV
   headers - the things a refactor breaks silently.
2. The frontend loads them in its own tests, so the TypeScript artifact types and the
   Python serializers are checked against the *same* bytes. A field renamed on one side
   fails on the other.

These are fixture artifacts, not production data: `intrinsic_model_version` is
`fixture-stub-0` and every number originates in `tests/fixtures/pipeline/`. Generated
production artifacts stay out of Git (AGENTS.md section 15) and are written to
`web/public/data/`, which is `.gitignore`d.
