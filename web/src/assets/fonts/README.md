# Vendored fonts

The Claude Design source (`Player Card HUD.dc.html`, Phase 9A) sets every UI string in **Exo 2**
and every numeric readout in **JetBrains Mono**. Both are part of the design's identity rather
than decoration: the mono figures are what give the board and the card their column rhythm, and
`ui-monospace` resolves to a different face on every platform.

The design links them from Google Fonts. This repository cannot:

- `docs/ARCHITECTURE.md` section 3.2 forbids a runtime call to a third party for core page
  rendering, and
- `web/tests/e2e/board.spec.ts` fails any request that leaves localhost.

So they are vendored. Both families are licensed under the **SIL Open Font License 1.1**, which
permits redistribution and web embedding; the licences are beside the files.

| file | family | subset | axes |
|---|---|---|---|
| `exo2-latin.woff2` | Exo 2 | latin | `wght 400..700` |
| `exo2-latin-ext.woff2` | Exo 2 | latin-ext | `wght 400..700` |
| `jetbrains-mono-latin.woff2` | JetBrains Mono | latin | `wght 400..700` |
| `jetbrains-mono-latin-ext.woff2` | JetBrains Mono | latin-ext | `wght 400..700` |

115 KB in total for both families at every weight the design uses. `latin-ext` is included
because player names carry diacritics often enough that a fallback swap mid-name would be
visible.

These are the Google Fonts variable-font subsets, retrieved from `fonts.gstatic.com` on
2026-08-31 (Exo 2 v26, JetBrains Mono v24). They are referenced from `web/src/styles/base.css`
with relative `url()`s so Vite fingerprints them and rewrites the paths under any `base`,
including the `/jeisey-tiers/` project-Pages path.

**Licences:** `Exo2-OFL.txt`, `JetBrainsMono-OFL.txt`. Neither may be sold on its own; both may
be bundled and served as they are here. See also `docs/SECURITY_LICENSE.md`.
