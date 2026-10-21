/**
 * Export, placed beside the table it exports (`docs/UX_SPEC.md` section 8).
 *
 * `Download full CSV` is a plain link to the artifact the build wrote, so it resolves under
 * both the root and the project Pages base path and costs the browser nothing. `Export
 * filtered CSV` serializes exactly the rows on screen, in the order they are on screen.
 */

import { downloadCsv, exportFilename, type ExportBoard } from "../data/csv";
import { artifactUrl } from "../data/load";
import type { ScoringValue, TeamCount } from "../data/state";

export function ExportControls({
  board,
  scoring,
  teams,
  buildDate,
  filteredCount,
  buildFilteredCsv,
  throughWeek,
  fullLabel = "Download full CSV",
  fullTitle,
  filteredLabel = "Export filtered CSV",
}: {
  readonly board: ExportBoard;
  readonly scoring: ScoringValue;
  readonly teams: TeamCount;
  readonly buildDate: string;
  readonly filteredCount: number;
  readonly buildFilteredCsv: () => string;
  /** Present on an in-season export, so two cutoffs never share a filename. */
  readonly throughWeek?: number;
  /**
   * ADR-113: what the prebuilt file is and is not. The full CSV is the build's, written once
   * for every row and block; it never reflects a lens the reader picked on the page.
   */
  readonly fullLabel?: string;
  readonly fullTitle?: string;
  /** The filtered button's words, e.g. naming the selected window it exports. */
  readonly filteredLabel?: string;
}): React.JSX.Element {
  const fullHref = artifactUrl(`${board}.csv`);
  return (
    <>
      <a className="button" href={fullHref} download title={fullTitle}>
        {fullLabel}
      </a>
      <button
        type="button"
        className="button"
        disabled={filteredCount === 0}
        onClick={() => {
          downloadCsv(
            exportFilename(board, scoring, teams, buildDate, throughWeek),
            buildFilteredCsv(),
          );
        }}
      >
        {`${filteredLabel} (${String(filteredCount)})`}
      </button>
    </>
  );
}
