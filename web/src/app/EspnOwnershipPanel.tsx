/**
 * The card's ESPN reading (ADR-112): the latest roster and start shares, the 7- and 1-day
 * roster changes in percentage points, and — only once the reader activates it — the
 * retained history as two aligned small multiples.
 *
 * The latest values arrive with the card shard, so the sentence renders at once. The history is
 * a separate, content-addressed bucket file fetched only on activation (the In-season usage tab
 * on a phone, the button elsewhere), so opening a card costs no history bytes and a second
 * player in the same bucket costs none at all.
 */

import { Suspense, lazy, useEffect, useState } from "react";

// The chart's code is fetched with the history, on activation, never with the card or a view.
const EspnOwnershipChart = lazy(() =>
  import("../charts/EspnOwnershipChart").then((module) => ({ default: module.EspnOwnershipChart })),
);
import type { EspnOwnershipMetadata, EspnOwnershipSeriesRecord } from "../data/contracts";
import {
  ABSENT_TEXT,
  CHANGE_STATE_TEXT,
  changeCell,
  changeSentence,
  exactPercent,
  formatEspnPercent,
  startedText,
  type EspnSignal,
} from "../data/espn";
import { EM_DASH, formatEastern } from "../data/format";
import type { OwnershipHistorySource } from "../data/store";

type HistoryState =
  | { readonly status: "idle" }
  | { readonly status: "loading" }
  | { readonly status: "loaded"; readonly series: EspnOwnershipSeriesRecord | null }
  | { readonly status: "failed" };

function useOwnershipHistory(
  source: OwnershipHistorySource | null,
  playerId: string,
  active: boolean,
): HistoryState {
  const [state, setState] = useState<{ readonly playerId: string; readonly value: HistoryState } | null>(null);
  useEffect(() => {
    if (!active || source?.status !== "published") return;
    let cancelled = false;
    source
      .load(playerId)
      .then((series) => {
        if (!cancelled) setState({ playerId, value: { status: "loaded", series } });
      })
      .catch(() => {
        if (!cancelled) setState({ playerId, value: { status: "failed" } });
      });
    return () => {
      cancelled = true;
    };
  }, [active, source, playerId]);
  // No setState before the fetch settles: "loading" is simply "active, and nothing yet".
  if (state !== null && state.playerId === playerId) return state.value;
  return active && source?.status === "published" ? { status: "loading" } : { status: "idle" };
}

function changeReadout(signal: Extract<EspnSignal, { kind: "observed" | "stale" }>, window: "1d" | "7d"): {
  readonly value: string;
  readonly hint: string;
} {
  const change = window === "7d" ? signal.record.rostered_change_7d : signal.record.rostered_change_1d;
  if (change.state === "measured" && change.span_hours !== null) {
    return { value: changeCell(change), hint: `vs ${formatEastern(change.baseline_observed_at_utc)}` };
  }
  return { value: EM_DASH, hint: CHANGE_STATE_TEXT[change.state] ?? "" };
}

export function EspnOwnershipPanel({
  signal,
  meta,
  history,
  playerId,
  sheet,
}: {
  readonly signal: EspnSignal | null;
  readonly meta: EspnOwnershipMetadata | null;
  readonly history: OwnershipHistorySource | null;
  readonly playerId: string;
  /** On a phone the tab is the activation, so the history loads as soon as this renders. */
  readonly sheet: boolean;
}): React.JSX.Element | null {
  const [open, setOpen] = useState(false);
  const active = sheet || open;
  const loaded = useOwnershipHistory(history, playerId, active);
  if (signal === null) return null;

  if (signal.kind === "unavailable") {
    return (
      <div className="espn-block" data-espn="unavailable">
        <span className="readout-label">Rostered on ESPN</span>
        <p className="section-note">
          {meta === null
            ? "This build carries no ESPN roster percentages."
            : `No ESPN roster percentages were published with this build (${meta.reason ?? "no capture"}).`}
        </p>
      </div>
    );
  }
  if (signal.kind === "no_record" || signal.kind === "absent") {
    const text = signal.kind === "absent" ? ABSENT_TEXT[signal.state] : null;
    return (
      <div className="espn-block" data-espn={signal.kind === "absent" ? signal.state : "no_record"}>
        <span className="readout-label">Rostered on ESPN</span>
        <p className="section-note">{text?.sentence ?? "No ESPN reading is published for him on this build."}</p>
      </div>
    );
  }

  const { record, rostered } = signal;
  const started = startedText(record);
  const week = changeReadout(signal, "7d");
  const day = changeReadout(signal, "1d");
  const sentence =
    changeSentence(rostered, record.rostered_change_7d) ??
    `Rostered on ESPN: ${exactPercent(rostered)} — no 7-day change (${CHANGE_STATE_TEXT[record.rostered_change_7d.state] ?? "none"}).`;
  const panelId = `espn-history-${playerId.replace(/[^a-zA-Z0-9-]/g, "-")}`;

  return (
    <div className="espn-block" data-espn={signal.kind} data-testid="espn-block">
      <span className="readout-label">Rostered on ESPN</span>
      <p className="espn-sentence" data-current={signal.kind === "observed" ? "true" : "false"}>
        {sentence}
        {signal.kind === "stale" && (
          <strong>{` Stale: read ${formatEastern(record.observed_at_utc)}, so not current.`}</strong>
        )}
      </p>
      <div className="readout-grid espn-readouts">
        <div className="readout">
          <span className="readout-label">ESPN rostered</span>
          <span className="readout-value">{formatEspnPercent(rostered)}</span>
          <span className="readout-hint">{exactPercent(rostered)} of leagues</span>
        </div>
        <div className="readout">
          <span className="readout-label">ESPN started</span>
          <span className="readout-value">{started.short}</span>
          <span className="readout-hint">
            {record.start_state === "observed" && record.espn_current_period !== null
              ? `read in ESPN period ${String(record.espn_current_period)}`
              : record.start_state === "observed"
                ? "period not reported"
                : "unknown, not 0%"}
          </span>
        </div>
        <div className="readout">
          <span className="readout-label">7-day change</span>
          <span className="readout-value">{week.value}</span>
          <span className="readout-hint">{week.hint}</span>
        </div>
        <div className="readout">
          <span className="readout-label">1-day change</span>
          <span className="readout-value">{day.value}</span>
          <span className="readout-hint">{day.hint}</span>
        </div>
      </div>
      <p className="cohort-note">
        {`Read ${formatEastern(record.observed_at_utc)}. `}
        {meta?.population_statement ?? ""} Changes are in percentage points, not percent growth.{" "}
        {meta?.start_context_statement ?? ""}
      </p>

      {history === null ? (
        <p className="section-note">No ESPN history was published with this build.</p>
      ) : history.status === "incompatible" ? (
        <p className="section-note">
          This build&apos;s ESPN history uses a contract version this page cannot read; reload to get the current page.
        </p>
      ) : (
        <>
          {!sheet && (
            <button
              type="button"
              className="button"
              aria-expanded={open}
              aria-controls={open ? panelId : undefined}
              onClick={() => {
                setOpen((current) => !current);
              }}
            >
              {open ? "Hide ESPN trend" : "Show ESPN trend"}
            </button>
          )}
          {active && (
            <div id={panelId} className="espn-history">
              {loaded.status === "loaded" ? (
                loaded.series === null ? (
                  <p className="section-note">No retained ESPN read carried him inside the 28-day window.</p>
                ) : (
                  <>
                    {loaded.series.observations === 1 && (
                      <p className="section-note">
                        One retained read so far, so there is no trend to draw yet — only this point.
                      </p>
                    )}
                    <Suspense fallback={<p className="section-note">Loading the ESPN chart…</p>}>
                      <EspnOwnershipChart points={loaded.series.points} />
                    </Suspense>
                  </>
                )
              ) : loaded.status === "failed" ? (
                <p className="section-note">The ESPN history could not be loaded. The readings above are unaffected.</p>
              ) : (
                <p className="section-note">Loading the ESPN history…</p>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
