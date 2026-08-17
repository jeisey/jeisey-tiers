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

### nflverse

Research finding as of 2026-08-12: nflreadpy code is MIT; majority of nflverse data is broadly CC-BY 4.0, with FTN-origin data noted as CC-BY-SA 4.0. Each used dataset must be checked and attributed according to its own docs.

### ffopportunity

Expected-points model/data are CC-BY-SA 4.0. Preserve attribution/share-alike obligations applicable to derivative data artifacts as advised by the project license. Package R code being GPL does not mean Python simply importing precomputed licensed data becomes GPL; nevertheless license handling should be documented carefully.

### Sleeper

Use official documented API. Trending endpoint documentation requests attribution. Attribute Sleeper if trending data is exposed.

### FantasyCalc

Current terms found during research state data is FantasyCalc property, non-commercial website use is permitted under policy, commercial use requires express permission. Re-check exact terms in Phase 0 and before monetization. If unsure, disable production use.

### FantasyPros-derived rankings

Treat as benchmark-only by default. nflverse access convenience does not override FantasyPros ownership/terms. Do not redistribute raw ECR unless explicitly permitted.

### MFL

MFL publicly promotes its developer API for third-party add-ons, but exact 2026 API terms and data reuse decision must be recorded during Phase 0.

### SportsDataIO

Commercial; use only under purchased agreement/license.

## 9. Attribution UI

Methodology/Data section should contain concise source acknowledgements and links. Repository `README` or `NOTICE` should contain full attribution/license notes if required.

Generated CSV may include a short `source_methodology`/metadata reference or companion metadata rather than repeating long license text in every row.

## 10. Non-commercial boundary

Because an optional source may permit only non-commercial reuse, treat any of these as a trigger for a source-rights review before deployment:

- ads
- affiliate links/revenue
- paid premium features
- paid newsletter access bundling
- commercial API resale
- sponsorship tied to product access
- selling the underlying data/derived rankings

The code may remain open/public, but source rights are separate.

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
