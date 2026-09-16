/**
 * The portrait host, served locally, for the Node verifiers (ADR-087).
 *
 * The specs get this from `boundary.ts`; the `.mjs` verifiers are plain scripts with no test
 * runner, so they get it here. Two callers with two different needs:
 *
 * - **A gate** (`verify-real-build`, `verify-presets`, `verify-csv`, `measure-performance`)
 *   must be hermetic. `blockPortraits` refuses the request, the card falls back to its
 *   monogram, and whether a provider's CDN is up has no bearing on whether a deploy proceeds.
 *   This matters most in `daily-refresh.yml`, where `verify:board` stands between a build and
 *   the live site: a gate that could go red because somebody else's image server was slow
 *   would be a gate that stops the board for a reason that is not about the board.
 *
 * - **A screenshot run** (`capture-screens`) is evidence for a human, and a review of the
 *   card's layered treatment against a monogram would be a review of the fallback.
 *   `stubPortraits` serves a plain silhouette instead, so the frame, the wash, the scanlines,
 *   the bottom fade and the crop are all real and only the face is a stand-in. The fixture's
 *   ESPN ids are synthetic (`4000001`...) and resolve to nothing at the real host anyway, so
 *   there is no version of this that shows a genuine player.
 *
 * `verify-live` is the exception and takes neither: it is an observation of the deployed site
 * from outside, gates nothing, and the real portrait loading is part of what it is looking at.
 */

const HOST = "a.espncdn.com";

/** The pattern every portrait address matches. Mirrors `ffdraft.headshots.HEADSHOT_HOST`. */
export const PORTRAIT_GLOB = `https://${HOST}/**`;

/**
 * A neutral bust, drawn rather than borrowed.
 *
 * Deliberately not a real person and deliberately not a traced likeness: a screenshot in
 * `docs/visual-qa/` is committed to a public repository, and a stand-in that has to be
 * rights-cleared is a stand-in that costs more than it saves. The geometry is two shapes on
 * a transparent ground, which is also the shape the real provider serves — opaque where the
 * figure is, so a screenshot shows what a real cut-out does to the layers under it.
 */
const SILHOUETTE = Buffer.from(
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 350 420">
     <g fill="#8ea7bd">
       <circle cx="175" cy="132" r="78"/>
       <path d="M175 228c-79 0-143 55-143 123v69h286v-69c0-68-64-123-143-123z"/>
     </g>
   </svg>`,
  "utf8",
);

/** Refuse every portrait request. For anything whose result is a pass/fail verdict. */
export async function blockPortraits(page) {
  await page.route(PORTRAIT_GLOB, (route) => route.abort());
}

/** Serve a silhouette instead. For anything whose result is a picture a person will look at. */
export async function stubPortraits(page) {
  await page.route(PORTRAIT_GLOB, (route) =>
    route.fulfill({ status: 200, contentType: "image/svg+xml", body: SILHOUETTE }),
  );
}
