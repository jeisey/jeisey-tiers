# Security, Supply Chain, Licensing, and Attribution

## 1. Threat model

This is a public static data site, so security risk is modest but not zero. Main concerns:

- secrets accidentally committed/logged;
- overprivileged GitHub Actions token;
- compromised third-party dependency/action;
- malicious/unexpected upstream data content;
- unsafe deserialization of downloaded model/data objects;
- XSS via player/source text rendered unsafely;
- licensing/terms violations from data redistribution;
- workflow injection from untrusted branch/PR context.

## 2. Secrets

V1 should not require vendor secrets if free source plan succeeds.

**Recorded 2026-08-18 (ADR-017).** The one secret set that exists is the MyFantasyLeague developer-client configuration — `MFL_API_CLIENT_NAME`, `MFL_API_USERNAME`, `MFL_API_PASSWORD`, `MFL_API_USER_AGENT` — held as GitHub repository secrets. It is a *client-identity* secret, not an access credential: the public ADP export needs no authentication, so the adapter transmits only the User-Agent and never attaches a username, password, `APIKEY` or `Authorization` header. Configuration objects record which environment variable a value came from and whether it is present, never the value; their `repr` is redacted; and no secret may enter a log line, a cache key, a URL query, a committed fixture or a serialized artifact. Absence degrades the request identity, it does not block the source. Network-free tests must not read these variables at all.

**Recorded 2026-08-22 (ADR-049).** A second secret now exists: **`MARKET_DATA_REPO_TOKEN`**, a fine-grained personal access token whose scope is `jeisey/jeisey-tiers-market-data` alone, with Contents: Read and write and nothing else. It exists because the application repository became public and a workflow's ordinary `GITHUB_TOKEN` cannot write another repository's contents.

Unlike the MFL client identity, this *is* an access credential, so it is bounded three ways and each is enforced rather than remembered:

- **It never reaches a shell.** It is passed to `actions/checkout` through its `token:` input, which stores it as a git extraheader in the checkout. The pre-Phase-7 workflow built `https://x-access-token:${GH_TOKEN}@github.com/...` in a shell block; that construction is gone, and `tests/unit/test_workflows.py` asserts the secret appears only as a `token:` input to `.github/actions/market-data-store`.
- **It does not survive into replaceable work.** Jobs that only read the store check out with `persist-credentials: false`, so no credential is present in the workspace when the frontend builds or the Pages artifact is packaged.
- **Untrusted code cannot ask for it.** `ci.yml` — the workflow a pull request from a fork runs — never references it and never checks out the store. A test asserts that too.

Its blast radius if leaked is one private repository of retained vendor payloads, not the application repository, not Pages, and not the model. It carries an expiry; renewal is in `docs/OPERATIONS.md` section 5.3, and expiry fails the daily refresh loudly at its first job rather than degrading anything.

If a future paid/API-key source is added:

- GitHub Actions secret only;
- never write key to public artifact, logs, cache key, URL query if avoidable, or test fixture;
- adapter reads from environment;
- missing key disables optional paid adapter or fails clearly if configured critical.

## 3. GitHub Actions permissions

Default `permissions: read-all` or more restrictive, then elevate per job only where required.

PR workflows from forks must not receive production secrets/write tokens.

Pages job receives only official required Pages/OIDC permissions.

Data-branch writer receives `contents: write` narrowly.

**Phase-7 implementation.** Every workflow declares `contents: read` at the top level. Exactly one job in the repository elevates: `daily-refresh.yml`'s `deploy`, to `pages: write` + `id-token: write` under the `github-pages` environment. The full per-job table is in `docs/OPERATIONS.md` section 6 and is asserted by `tests/unit/test_workflows.py`.

The data-writer clause above became *unnecessary* rather than merely satisfied. Since the store moved to its own repository (ADR-049), the capture jobs write through a repository-scoped token and need **no** write scope on this repository at all. Splitting data from code made this repository's own permissions strictly narrower than they were when it was private.

Do not use `pull_request_target` with untrusted code execution.

## 4. Third-party Actions

Prefer official GitHub actions for checkout, setup, Pages artifact/upload/deploy.

For community actions:

- assess maintenance/reputation/license;
- pin to trusted version/commit where feasible;
- minimize count.

## 5. Dependencies

- commit lockfiles;
- use `uv sync --frozen` / `npm ci` in CI;
- avoid `curl | bash` in workflows where a package-manager/setup action exists;
- run dependency vulnerability tooling if low-friction;
- review licenses before adding dependencies with copyleft implications to distributed application code.

## 6. Upstream data safety

Treat all text from APIs as untrusted data.

- parse JSON/CSV/XML with standard libraries;
- no `eval`;
- no executing downloaded scripts;
- no untrusted Python pickle/joblib from remote sources;
- sanitize/escape strings through React normal rendering; avoid `dangerouslySetInnerHTML` for source/player content;
- bound absurd string lengths/record counts where appropriate.

## 7. Model artifact safety

Prefer LightGBM native text model or another explicit safe format. If joblib/pickle is used for self-generated production artifacts, only load artifacts from the checked-out trusted repository/model registry, never a remote user-controlled URL.

Manifest hash must match expected artifact where practical.

## 8. Data licensing/attribution

> **Phase-0 verification (2026-08-17):** every statement in this section was re-checked live; the quoted evidence and the resulting policy per source are in `docs/DATA_SOURCES.md` section 13, with decisions in ADR-010 through ADR-015. The subsections below note what changed.

### nflverse

Research finding as of 2026-08-12: nflreadpy code is MIT; majority of nflverse data is broadly CC-BY 4.0, with FTN-origin data noted as CC-BY-SA 4.0. Each used dataset must be checked and attributed according to its own docs.

**Confirmed.** `LICENSE.md` is MIT ("Copyright (c) 2025 nflreadpy contributors"); the client README states "The majority of all nflverse data available (ie all but the FTN data as of July 2025) is broadly licensed as CC-BY 4.0, and the FTN data is CC-BY-SA 4.0". nflreadr adds that "NFL data accessed by this package belong to their respective owners, and are governed by their terms of use". `load_ftn_charting` is therefore the one nflverse loader that drags in share-alike obligations, and it should stay unused unless a feature justifies them.

### ffopportunity

Expected-points model/data are CC-BY-SA 4.0. Preserve attribution/share-alike obligations applicable to derivative data artifacts as advised by the project license. Package R code being GPL does not mean Python simply importing precomputed licensed data becomes GPL; nevertheless license handling should be documented carefully.

### Sleeper

Use official documented API. Trending endpoint documentation requests attribution. Attribute Sleeper if trending data is exposed.

**Materially updated.** Sleeper's docs state the API is "free to use for non-commercial purposes" and that "For commercial use of the Sleeper API, please reach out to us directly to discuss licensing". Sleeper therefore sits inside the section 10 non-commercial boundary alongside FantasyCalc — the original spec treated it as an unrestricted public API. Because ADR-011 promotes Sleeper to the current-status path, **monetisation now requires re-clearing Sleeper, not only FantasyCalc.** Documented rate guidance is to stay under 1000 calls per minute; attribution is requested for trending data.

### FantasyCalc

Current terms found during research state data is FantasyCalc property, non-commercial website use is permitted under policy, commercial use requires express permission. Re-check exact terms in Phase 0 and before monetization. If unsure, disable production use.

**Resolved: disabled.** The terms page is client-rendered and its text is not in the served markup, and no documented reuse mechanism exists, so "if unsure, disable" applies. See ADR-013.

### FantasyPros-derived rankings

Treat as benchmark-only by default. nflverse access convenience does not override FantasyPros ownership/terms. Do not redistribute raw ECR unless explicitly permitted.

**Resolved: `benchmark_only` (owner terms review, 2026-08-18).** Phase 0 switched the benchmark off because terms were unread; the owner has now read them and approved internal benchmark use for this non-commercial project (ADR-014 as amended). The default in the paragraph above therefore stands rather than being overridden: benchmark-only, no redistribution of raw ECR, and no place in intrinsic features or DraftValue inputs. The probe still enforces this mechanically — rows from benchmark-only sources are suppressed from the report and fixtures — because permission to compare is not permission to republish. The source is `non_commercial_only`, so it is inside the section 10 boundary.

### MFL

MFL publicly promotes its developer API for third-party add-ons, but exact 2026 API terms and data reuse decision must be recorded during Phase 0.

**Recorded: production allowed, with obligations.** MFL's published "General Rules and Terms of Service" state access "is provided free to anyone to use in almost any way" and forbid harvesting league/user data, circumventing league rules, overloading the service, and collecting user information without permission — none of which describes reading the public ADP aggregate. Obligations we must honour: send the User-Agent from a registered developer client (**registered 2026-08-18**; supplied as the `MFL_API_USER_AGENT` repository secret, ADR-017), back off on HTTP 429, and request the player database at most once per day. `robots.txt` restricts only `/fflnetdynamic*/` league directories.

### SportsDataIO

Commercial; use only under purchased agreement/license.

### Vendored fonts

**Exo 2** and **JetBrains Mono**, both **SIL Open Font License 1.1**, added in Phase 9A under
`web/src/assets/fonts/` with their licence files beside them
(`Exo2-OFL.txt`, `JetBrainsMono-OFL.txt`).

The OFL permits redistribution and web embedding of the font software, including bundled inside
a larger work, provided the licence travels with it and the fonts are not sold on their own.
Both conditions hold here. They are the Google Fonts Latin and Latin-Ext variable subsets, 115 KB
in total, retrieved on 2026-08-31.

They are **vendored rather than linked**, and that is a privacy decision as much as an
architectural one: a `fonts.googleapis.com` stylesheet makes every visitor's browser announce
itself to a third party on first paint. Section 11 says prefer no third-party behavioural
collection, `docs/ARCHITECTURE.md` section 3.2 forbids a third-party call in the critical render
path, and `web/tests/e2e/board.spec.ts` fails any request that leaves localhost. The site makes
no cross-origin request at all.

### Owner artwork

**`web/src/assets/jt_logo.png`** is the project owner's own logo, supplied by them and uploaded
directly to `main` on 2026-09-01. It is not a vendor asset, carries no third-party licence
obligation, and nothing else in the repository depends on redistribution rights to it.

`web/public/favicon.ico`, `web/public/favicon.png` and `web/public/apple-touch-icon.png` are
**generated from that file** by `scripts/make_favicon.py` and are committed. They are original
geometry drawn in a palette sampled from the logo — no part of the artwork is copied into them —
so they inherit its rights position exactly and add no new one. `ci.yml` runs the generator with
`--check`, so a committed icon cannot drift from the code that produced it.

### Software licence

**Deliberately unresolved (Phase 7, 2026-08-22).** The repository carries no `LICENSE` file, and Phase 7 did not add one. Making a repository public is a visibility decision; choosing a software licence is a separate rights decision that belongs to the project owner, and picking one on their behalf because the code became readable would be choosing for them.

Until the owner records a choice, the ordinary default applies: the source is publicly *viewable*, and no reuse rights are granted. Note that this is independent of the **data** licensing above — nflverse's CC-BY, ffopportunity's CC-BY-SA and Sleeper's non-commercial terms bind the data regardless of what licence the code eventually carries.

## 9. Attribution UI

Methodology/Data section should contain concise source acknowledgements and links. Repository `README` or `NOTICE` should contain full attribution/license notes if required.

Generated CSV may include a short `source_methodology`/metadata reference or companion metadata rather than repeating long license text in every row.

## 10. Non-commercial boundary

As of the 2026-08-18 owner decisions, the non-commercial-only sources in the plan are **Sleeper** (verified, and on the current-status path), **FantasyPros-derived ECR** (benchmark-only, ADR-014 as amended) and FantasyCalc (disabled). `config/source-registry.yaml` keeps the authoritative list in `decisions.non_commercial_deployment_required_by`, and a unit test fails if a source is marked non-commercial without being listed there.

Because an optional source may permit only non-commercial reuse, treat any of these as a trigger for a source-rights review before deployment:

- ads
- affiliate links/revenue
- paid premium features
- paid newsletter access bundling
- commercial API resale
- sponsorship tied to product access
- selling the underlying data/derived rankings

The code may remain open/public, but source rights are separate.

**Phase-5 change of exposure (2026-08-20).** Sleeper's obligation used to bind only what the pipeline *read*. It now binds what the site *publishes*: `player_status.json` and `player_status.csv` carry Sleeper's `status`, `injury_status`, `injury_body_part`, `injury_notes`, `practice_participation` and depth-chart fields into a public artifact (ADR-043). Two consequences:

- Sleeper attribution is no longer optional politeness on a methodology panel. The artifact records its contributing `source_ids` per row and `build_metadata.player_status.source_ids` records them per build, so a Phase-6 UI has what it needs to attribute; section 9 requires it to.
- The retained status captures are a **private research cache**, not redistribution: only normalized rows are kept, and they are excluded from any release archive or Pages publish.

**Phase-7 resolution of that exclusion (2026-08-22, ADR-049).** The sentence above used to end "if ADR-016 is revisited in Phase 7, that exclusion is part of the decision, not an implementation detail." It was revisited, and the exclusion could not be honoured by workflow care: **GitHub visibility is a property of a repository, not of a branch**, so a `market-data` branch inside a public `jeisey/jeisey-tiers` would have been published by any `git clone`, no matter what the Pages artifact contained.

The store therefore moved to a separate private repository, `jeisey/jeisey-tiers-market-data`, **before** visibility changed, and the old branch was deleted **before** that. The retained MFL payloads and normalized Sleeper rows have never been publicly readable, and the objects were never reachable from `main` — the store branch shared no history with it, which was verified rather than assumed.

Two consequences for this section's boundary:

- Sleeper's non-commercial terms now bind a **published** artifact. `player_status.json` and `player_status.csv` carry Sleeper fields to every visitor of a public site, so the free, ad-free, non-commercial character of the deployment is a licence condition rather than a preference, and the attribution required by section 9 is live on the Data / Methodology view rather than planned.
- The *retained* payloads remain unpublished, which is what keeps the research cache a cache. `daily-refresh.yml` asserts the Pages artifact's contents before uploading it, so the boundary is a check rather than a promise.

**Public-release audit, 2026-08-22, before visibility changed.** Every path ever added on `main` (517), scanned for `.env` files, key material, raw retained payloads, generated artifacts and modelling datasets: **none**. Every commit reachable from `main` (56), content-scanned for credential-shaped literals — GitHub/Slack/AWS token prefixes, PEM private-key headers, `Authorization:` headers, credentials embedded in URLs: **one match, and it is not a secret** — the old `market-capture.yml` contained the shell text `https://x-access-token:${GH_TOKEN}@github.com/...`, a variable reference expanded at runtime, and the Phase-7 rewrite removes that construction entirely. No local filesystem path identifying a person. `web/public/data/` and `data/historical/` are gitignored and were never committed. The full record is `docs/PHASE7_DEPLOYMENT.md`.

MyFantasyLeague's published rules permit the ADP read and are unchanged; the Phase-5 obligations the adapter honours (registered User-Agent, one player-database request per day, bounded 429 backoff, no credentials on the public path) are recorded in ADR-017 and `config/source-registry.yaml`.

## 11. Privacy

No user accounts/analytics are needed for V1. Prefer no third-party behavioral analytics. If basic analytics are later desired, require a privacy decision and avoid collecting draft/user data by default.

## 12. Incident response

If a source license/terms issue is discovered:

1. disable affected adapter/public fields;
2. deploy a source-clean build if core product remains viable;
3. remove prohibited stored raw data from current branch/artifacts as required (Git history remediation may be necessary; seek appropriate guidance);
4. document decision.

If a secret is exposed:

1. revoke/rotate immediately;
2. remove from workflow/config;
3. audit logs/history;
4. only then clean Git history as needed.
