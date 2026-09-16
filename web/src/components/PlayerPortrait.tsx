/**
 * The player card's portrait (ADR-087).
 *
 * The one place in this product where the browser touches a third party. Everything else —
 * every number, every font, every icon — is served from the same origin as the page, and
 * `docs/ARCHITECTURE.md` section 3.2 is what keeps it that way. So the rules here are narrow
 * on purpose:
 *
 * - **It is rendered only inside the open card.** The `<img>` element does not exist until a
 *   reader opens a player, so the request is made by an act, not by arriving at the site. A
 *   portrait on a three-hundred-row board would be three hundred requests for decoration.
 * - **The address comes from the published artifact**, never assembled here. The build
 *   validates the host; this component does not get to pick one.
 * - **`no-referrer`**, so the provider is told an IP and a path and not which page or which
 *   board the reader was on.
 * - **It carries no information.** `alt=""` and the veil is `aria-hidden`: the player's name,
 *   position, team, tier and status are all text within a few pixels of the frame, so a
 *   screen reader that announced "photo of X" would be repeating the heading it just read.
 *
 * **The monogram is always in the DOM, behind the image.** That is what makes a slow network,
 * a blocked request, a player the crosswalk cannot bridge and a provider 404 all look the
 * same and all reserve the same space: there is no empty frame, no broken-image glyph, and no
 * layout shift when the picture arrives. It is also why nothing here transitions — the
 * stylesheet has no opacity animation and this does not add one.
 *
 * It is hidden once the picture has **painted**, which is why `onLoad` exists and why the
 * state has three values rather than two. The provider serves a cut-out on a transparent
 * ground, so letters left behind a loaded portrait would show through around the shoulders;
 * hiding them any earlier would leave an empty frame for as long as the request takes.
 */

import { useState } from "react";

import type { Position } from "../data/contracts";

/**
 * Up to two initials, from the name the card is already showing.
 *
 * Deliberately naive: it splits on whitespace and takes first letters. A suffix or a hyphen
 * yields a slightly odd pair of letters and nothing worse, which is the right failure for a
 * decorative placeholder. It is never used to identify anybody.
 */
export function initialsOf(name: string): string {
  const parts = name
    .split(/\s+/u)
    .map((part) => part.trim())
    .filter((part) => part.length > 0);
  const letters = [parts.at(0), parts.length > 1 ? parts.at(-1) : undefined]
    .filter((part): part is string => part !== undefined)
    // `Array.from` rather than a spread or `.split("")`: it yields code points, so a name
    // beginning with a non-BMP character produces one whole character instead of half of one.
    .map((part) => Array.from(part)[0] ?? "")
    .join("");
  return letters.toUpperCase() || "—";
}

export function PlayerPortrait({
  name,
  position,
  imageUrl,
}: {
  readonly name: string;
  readonly position: Position | null;
  /** The published address, or null when this build has no portrait for the player. */
  readonly imageUrl: string | null;
}): React.JSX.Element {
  const [status, setStatus] = useState<"pending" | "loaded" | "failed">("pending");
  // A new player in an already-open dialog must not inherit the previous one's outcome.
  // Adjusted during render rather than in an effect, the same pattern the dialog's tab index
  // uses: React re-renders immediately instead of painting one player's error state under
  // another player's name.
  const [lastUrl, setLastUrl] = useState(imageUrl);
  if (lastUrl !== imageUrl) {
    setLastUrl(imageUrl);
    setStatus("pending");
  }

  const showImage = imageUrl !== null && status !== "failed";
  return (
    <div
      className="portrait chamfer"
      data-pos={position ?? undefined}
      // Three states, not two. `loaded` is the one the stylesheet acts on: it is what hides
      // the monogram, and hiding it any earlier would leave an empty frame for as long as the
      // request takes.
      data-state={showImage ? status : "monogram"}
    >
      <span className="portrait-monogram" aria-hidden="true">
        {initialsOf(name)}
      </span>
      {showImage && (
        <img
          className="portrait-image"
          // Keyed so a second player's portrait is a new element rather than the first one's
          // with a new `src`; without it the old picture stays painted until the new one
          // decodes, which puts one player's face under another player's name.
          key={imageUrl}
          src={imageUrl}
          alt=""
          loading="lazy"
          decoding="async"
          referrerPolicy="no-referrer"
          draggable={false}
          onLoad={() => {
            setStatus("loaded");
          }}
          onError={() => {
            setStatus("failed");
          }}
        />
      )}
      <span className="portrait-veil" aria-hidden="true" />
    </div>
  );
}
