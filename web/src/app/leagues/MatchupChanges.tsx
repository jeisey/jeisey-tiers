/**
 * Win My Matchup's lineup changes (ADR-110 §5, §6): the evaluated lineups ranked by the chance
 * to win this matchup, and YOLO's potential pickups ranked by ceiling gain — each with the same
 * simulation's difference beside it, and the noise that difference has to clear.
 *
 * Nothing here changes a roster: *Preview* draws a lineup over the baseline's picture, and only
 * *Apply* (or, for a pickup, a confirmed *Add to my roster*) commits one edit, with *Undo*.
 */

import { PositionTag } from "../../components/primitives";
import { formatEastern, formatInteger } from "../../data/format";
import { meaningfulDelta, noisePoints, percentLabel, type SimResult, type VariantResult } from "../../data/matchup";
import type { Proposal } from "../../data/matchupSetup";
import { slotLongName } from "../../data/roster";
import type { Mark } from "../../data/wmmContract";
import {
  YOLO_BAR_QUANTILE,
  YOLO_POOL_MINIMUM,
  YOLO_RULE_VERSION,
  YOLO_UNAVAILABLE_TEXT,
  type YoloCandidate,
  type YoloSelection,
} from "../../data/yolo";
import type { SavedLeague } from "../../data/leagueContract";
import { deltaPoints } from "./MatchupResults";
import { points } from "./shared";

/** How many evaluated lineups the list shows. */
export const SHOWN_CHANGES = 5;

export interface EvaluatedChange {
  readonly proposal: Proposal;
  readonly result: VariantResult;
}

/** The variant result for a proposal id in a changes run. */
export function variantFor(result: SimResult, id: string): VariantResult | null {
  return result.variants.find((variant) => variant.id === id) ?? null;
}

export function movesText(proposal: Proposal, league: SavedLeague, name: (id: string) => string): string {
  const parts: string[] = [];
  for (const move of proposal.moves) {
    if (move.from.index < 0) parts.push(`add ${name(move.id)} at ${slotLongName(move.to, league.slots)}`);
    else if (move.to.group === "BN") parts.push(`bench ${name(move.id)}`);
    else parts.push(`start ${name(move.id)} at ${slotLongName(move.to, league.slots)}`);
  }
  const text = parts.join(", ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** "61% (+2.4 pts)" or "61% — within simulation noise". */
function deltaLine(variant: VariantResult): string {
  const paired = variant.paired;
  if (paired === null) return percentLabel(variant.win);
  if (!meaningfulDelta(paired)) return `${percentLabel(variant.win)} — within simulation noise (${deltaPoints(paired.win)} ±${noisePoints(paired.se).toFixed(1)})`;
  return `${percentLabel(variant.win)} (${deltaPoints(paired.win)} ±${noisePoints(paired.se).toFixed(1)})`;
}

export function NormalChanges({
  league,
  evaluated,
  base,
  name,
  previewId,
  writable,
  onPreview,
  onApply,
}: {
  readonly league: SavedLeague;
  readonly evaluated: readonly EvaluatedChange[];
  readonly base: VariantResult;
  readonly name: (id: string) => string;
  readonly previewId: string | null;
  readonly writable: boolean;
  readonly onPreview: (proposal: Proposal | null) => void;
  readonly onApply: (proposal: Proposal) => void;
}): React.JSX.Element {
  const ranked = [...evaluated].sort((a, b) => b.result.win - a.result.win || (a.proposal.id < b.proposal.id ? -1 : 1));
  const shown = ranked.slice(0, SHOWN_CHANGES);
  const best = ranked[0];
  const anyBetter = best !== undefined && best.result.paired !== null && best.result.paired.win > 0 && meaningfulDelta(best.result.paired);
  return (
    <div className="wmm-changes">
      {evaluated.length > 0 && (
        <p className="lg-help">
          {`Best of ${String(evaluated.length)} evaluated lineup${evaluated.length === 1 ? "" : "s"} — Auto Start/Sit's median, floor and ceiling proposals and single bench swaps, each on the same simulated games as yours. Ranked by the chance to win this matchup, not by projected points. Not a proof that no better lineup exists.`}
        </p>
      )}
      <p className="wmm-change-base">{`Your lineup: ${percentLabel(base.win)} to win.`}</p>
      {evaluated.length === 0 ? (
        <p className="lg-auto-none">No legal change to evaluate: every bench player is locked, sidelined or cannot fill a starting slot.</p>
      ) : (
        <>
          {!anyBetter && <p className="lg-auto-none">No evaluated change beats your lineup by more than simulation noise.</p>}
          <ol className="wmm-change-list" aria-label="Evaluated lineup changes">
            {shown.map(({ proposal, result }) => {
              const paired = result.paired;
              const previewing = previewId === proposal.id;
              return (
                <li key={proposal.id} className="wmm-change" data-previewing={previewing || undefined}>
                  <div className="wmm-change-head">
                    <span className="wmm-change-label">{proposal.label}</span>
                    <span className="wmm-change-moves">{movesText(proposal, league, name)}</span>
                  </div>
                  <p className="wmm-change-figures">
                    <span>{`Chance to win ${deltaLine(result)}`}</span>
                    {paired !== null && <span>{`Your 90th-percentile total ${points(result.mine.p90)} (${paired.p90 >= 0 ? "+" : "−"}${Math.abs(paired.p90).toFixed(1)})`}</span>}
                  </p>
                  <div className="wmm-change-actions">
                    <button type="button" className="button" aria-pressed={previewing} onClick={() => { onPreview(previewing ? null : proposal); }}>
                      {previewing ? "Hide preview" : "Preview"}
                    </button>
                    <button type="button" className="button chamfer" data-variant="primary" disabled={!writable} onClick={() => { onApply(proposal); }}>
                      Apply
                    </button>
                  </div>
                </li>
              );
            })}
          </ol>
        </>
      )}
    </div>
  );
}

export function YoloPanel({
  league,
  on,
  writable,
  selection,
  loading,
  failure,
  evaluated,
  benchCeiling,
  name,
  previewId,
  onToggle,
  onMark,
  onPreview,
  onAdd,
  onApplyBench,
}: {
  readonly league: SavedLeague;
  readonly on: boolean;
  readonly writable: boolean;
  readonly selection: YoloSelection | null;
  readonly loading: boolean;
  readonly failure: Error | null;
  /** The simulated difference for each candidate, once changes have been evaluated. */
  readonly evaluated: ReadonlyMap<string, VariantResult>;
  /** Evaluated bench options that raise the 90th percentile of the simulated total. */
  readonly benchCeiling: readonly EvaluatedChange[];
  readonly name: (id: string) => string;
  readonly previewId: string | null;
  readonly onToggle: (on: boolean) => void;
  readonly onMark: (id: string, mark: Mark | null) => void;
  readonly onPreview: (candidate: YoloCandidate | null) => void;
  readonly onAdd: (candidate: YoloCandidate) => void;
  readonly onApplyBench: (proposal: Proposal) => void;
}): React.JSX.Element {
  return (
    <section className="wmm-yolo" aria-labelledby="wmm-yolo-heading">
      <div className="wmm-yolo-head">
        <h4 id="wmm-yolo-heading" className="wmm-side-title">YOLO waiver mode</h4>
        <label className="lg-toggle">
          <input type="checkbox" checked={on} disabled={!writable} onChange={(event) => { onToggle(event.target.checked); }} />
          <span>YOLO</span>
        </label>
      </div>
      <p className="lg-help">
        Ceiling first: potential pickups whose role is rising and whose net adds are high, and whose 90th-percentile
        week beats one of your starters&rsquo;. It chases upside — it does not promise a better chance to win, and the
        simulated difference is shown beside each. Off unless you turn it on; remembered for this league.
      </p>
      {on && <YoloBody league={league} selection={selection} loading={loading} failure={failure} evaluated={evaluated} benchCeiling={benchCeiling} name={name} previewId={previewId} writable={writable} onMark={onMark} onPreview={onPreview} onAdd={onAdd} onApplyBench={onApplyBench} />}
    </section>
  );
}

function YoloBody({
  league,
  selection,
  loading,
  failure,
  evaluated,
  benchCeiling,
  name,
  previewId,
  writable,
  onMark,
  onPreview,
  onAdd,
  onApplyBench,
}: {
  readonly league: SavedLeague;
  readonly selection: YoloSelection | null;
  readonly loading: boolean;
  readonly failure: Error | null;
  readonly evaluated: ReadonlyMap<string, VariantResult>;
  readonly benchCeiling: readonly EvaluatedChange[];
  readonly name: (id: string) => string;
  readonly previewId: string | null;
  readonly writable: boolean;
  readonly onMark: (id: string, mark: Mark | null) => void;
  readonly onPreview: (candidate: YoloCandidate | null) => void;
  readonly onAdd: (candidate: YoloCandidate) => void;
  readonly onApplyBench: (proposal: Proposal) => void;
}): React.JSX.Element {
  if (failure !== null) {
    return <p className="notice" data-severity="error" role="alert">{`YOLO's role and add evidence could not be loaded. Reload to try again. (${failure.message})`}</p>;
  }
  if (selection === null || loading) return <p className="lg-help" role="status">Loading role and add evidence…</p>;
  if (selection.kind === "unavailable") {
    return (
      <p className="notice" data-severity="warning" role="status">
        {YOLO_UNAVAILABLE_TEXT[selection.reason]}
        {selection.snapshotAt !== null && ` Snapshot ${formatEastern(selection.snapshotAt)}.`}
      </p>
    );
  }
  return (
    <>
      <p className="lg-help">
        {`Net adds = Sleeper adds minus drops over ${selection.lookbackHours === null ? "the requested window" : `${String(selection.lookbackHours)} hours`}, snapshot ${formatEastern(selection.snapshotAt)}. "High" means at least the ${YOLO_BAR_QUANTILE === 0.5 ? "median" : `${String(YOLO_BAR_QUANTILE * 100)}th percentile`} of the position's players with positive net adds on this board; a position with fewer than ${String(YOLO_POOL_MINIMUM)} such players has no bar. Rising role is the Opportunity Board's rule. ${YOLO_RULE_VERSION}.`}
      </p>
      <ul className="wmm-funnel" aria-label="How many players passed each gate, by position">
        {selection.funnels.map((funnel) => (
          <li key={funnel.position}>
            <PositionTag position={funnel.position} />
            {funnel.bar.threshold === null ? (
              <span>{`${String(funnel.bar.pool)} with positive net adds — too few to set a bar; none qualify`}</span>
            ) : (
              <span>
                {`bar ${formatInteger(funnel.bar.threshold)} net adds (median of ${String(funnel.bar.pool)}) · ${String(funnel.highAdds)} at or above · ${String(funnel.rising)} rising · ${String(funnel.playable)} playable · ${String(funnel.unowned)} not known owned · ${String(funnel.ceiling)} beat a starter's ceiling`}
              </span>
            )}
          </li>
        ))}
      </ul>
      <h5 className="wmm-subhead">Potential pickups — availability unverified</h5>
      <p className="lg-help">Ownership in the rest of your league is unknown: none of these is claimed to be a free agent. Mark each one you checked.</p>
      {selection.candidates.length === 0 ? (
        <p className="lg-auto-none">No potential pickup passes every gate this week. That is a genuine gap, not an error.</p>
      ) : (
        <ol className="wmm-yolo-list" aria-label="Potential pickups">
          {selection.candidates.map((candidate) => (
            <YoloCard
              key={candidate.id}
              league={league}
              candidate={candidate}
              result={evaluated.get(candidate.id) ?? null}
              name={name}
              previewing={previewId === `yolo-${candidate.id}`}
              writable={writable}
              onMark={onMark}
              onPreview={onPreview}
              onAdd={onAdd}
            />
          ))}
        </ol>
      )}
      {selection.beyondCap > 0 && <p className="lg-help">{`${String(selection.beyondCap)} more qualified beyond the list's limit (3 per position, 8 in all).`}</p>}
      {selection.markedUnavailable.length > 0 && (
        <p className="lg-help">
          {`Marked unavailable: `}
          {selection.markedUnavailable.map((id, index) => (
            <span key={id}>
              {index > 0 && ", "}
              {name(id)}{" "}
              <button type="button" className="button-link" disabled={!writable} onClick={() => { onMark(id, null); }}>
                Unmark
              </button>
            </span>
          ))}
        </p>
      )}
      <h5 className="wmm-subhead">From your bench</h5>
      {benchCeiling.length === 0 ? (
        <p className="lg-help">No evaluated bench option raises your 90th-percentile total, or changes have not been evaluated yet.</p>
      ) : (
        <ul className="wmm-change-list" aria-label="Bench ceiling upgrades">
          {benchCeiling.map(({ proposal, result }) => (
            <li key={proposal.id} className="wmm-change">
              <div className="wmm-change-head">
                <span className="wmm-change-label">{`Bench option · 90th percentile ${(result.paired?.p90 ?? 0) >= 0 ? "+" : "−"}${Math.abs(result.paired?.p90 ?? 0).toFixed(1)}`}</span>
                <span className="wmm-change-moves">{movesText(proposal, league, name)}</span>
              </div>
              <p className="wmm-change-figures">
                <span>{`Chance to win ${deltaLine(result)}`}</span>
              </p>
              <div className="wmm-change-actions">
                <button type="button" className="button chamfer" data-variant="primary" disabled={!writable} onClick={() => { onApplyBench(proposal); }}>
                  Apply
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function YoloCard({
  league,
  candidate,
  result,
  name,
  previewing,
  writable,
  onMark,
  onPreview,
  onAdd,
}: {
  readonly league: SavedLeague;
  readonly candidate: YoloCandidate;
  readonly result: VariantResult | null;
  readonly name: (id: string) => string;
  readonly previewing: boolean;
  readonly writable: boolean;
  readonly onMark: (id: string, mark: Mark | null) => void;
  readonly onPreview: (candidate: YoloCandidate | null) => void;
  readonly onAdd: (candidate: YoloCandidate) => void;
}): React.JSX.Element {
  const slot = slotLongName(candidate.slot.slot, league.slots);
  const incumbent = candidate.slot.id === null ? "an empty slot" : name(candidate.slot.id);
  const paired = result?.paired ?? null;
  const tradeoff = paired !== null && paired.win < 0 && meaningfulDelta(paired);
  return (
    <li className="wmm-yolo-card" data-previewing={previewing || undefined}>
      <div className="wmm-change-head">
        <PositionTag position={candidate.position} />
        <span className="wmm-change-label">{candidate.name}</span>
        <span className="lg-team">{candidate.team ?? ""}</span>
        <span className="wmm-gain">{`+${candidate.ceilingGain.toFixed(1)} ceiling`}</span>
      </div>
      <p className="wmm-change-moves">{`For ${slot}, replacing ${incumbent}${candidate.week.conditional ? " · if active" : ""}`}</p>
      <dl className="wmm-evidence">
        <div>
          <dt>Ceiling (P90)</dt>
          <dd>{`${points(candidate.incumbentQ90)} → ${points(candidate.q90)}`}</dd>
        </div>
        <div>
          <dt>Median (P50)</dt>
          <dd>{`${points(candidate.incumbentQ50)} → ${points(candidate.q50)}`}</dd>
        </div>
        <div>
          <dt>Net adds</dt>
          <dd>{`${formatInteger(candidate.netAdds)} (bar ${formatInteger(candidate.bar.threshold)})`}</dd>
        </div>
        <div>
          <dt>Role</dt>
          <dd>{`${candidate.role.metric} ${candidate.role.change ?? ""} · ${candidate.role.detail}`}</dd>
        </div>
        <div>
          <dt>Chance to win</dt>
          <dd>{result === null ? "Evaluate changes to see it" : deltaLine(result)}</dd>
        </div>
      </dl>
      {tradeoff && (
        <p className="wmm-tradeoff">
          Higher ceiling, lower chance to win: this pickup raises your upside but loses more of the matchups your
          current lineup wins.
        </p>
      )}
      <p className="wmm-mark-line">
        {candidate.mark === "available" ? "You marked him available in your league." : "Availability unverified."}
      </p>
      <div className="wmm-change-actions">
        {candidate.mark !== "available" && (
          <button type="button" className="button" disabled={!writable} onClick={() => { onMark(candidate.id, "available"); }}>
            Mark available
          </button>
        )}
        <button type="button" className="button" disabled={!writable} onClick={() => { onMark(candidate.id, "unavailable"); }}>
          Mark unavailable
        </button>
        {result !== null && (
          <button type="button" className="button" aria-pressed={previewing} onClick={() => { onPreview(previewing ? null : candidate); }}>
            {previewing ? "Hide preview" : "Preview"}
          </button>
        )}
        <button type="button" className="button chamfer" data-variant="primary" disabled={!writable} onClick={() => { onAdd(candidate); }}>
          Add to my roster…
        </button>
      </div>
    </li>
  );
}

