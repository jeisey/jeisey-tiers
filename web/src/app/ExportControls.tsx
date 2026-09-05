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
}: {
  readonly board: ExportBoard;
  readonly scoring: ScoringValue;
  readonly teams: TeamCount;
  readonly buildDate: string;
  readonly filteredCount: number;
  readonly buildFilteredCsv: () => string;
  /** Present on an in-season export, so two cutoffs never share a filename. */
  readonly throughWeek?: number;
}): React.JSX.Element {
  const fullHref = artifactUrl(`${board}.csv`);
  return (
    <>
      <a className="button" href={fullHref} download>
        Download full CSV
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
        {`Export filtered CSV (${String(filteredCount)})`}
      </button>
    </>
  );
}
