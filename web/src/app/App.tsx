/**
 * Phase-1 application shell.
 *
 * Deliberately not the product. Its job is to prove the artifact contract end to end in the
 * browser: load `build_metadata.json`, refuse an unsupported schema version, and report
 * freshness and source status from the metadata rather than anything hardcoded. The Tier
 * Board, Draft Rail, tables and exports are Phase 6 (`docs/UX_SPEC.md`).
 */

import { useEffect, useState } from "react";

import {
  ArtifactVersionError,
  buildAgeHours,
  degradedSources,
  loadBuildMetadata,
} from "../data/load";
import type { BuildMetadata } from "../data/contracts";

type LoadState =
  | { readonly status: "loading" }
  | { readonly status: "ready"; readonly metadata: BuildMetadata }
  | { readonly status: "error"; readonly message: string; readonly incompatible: boolean };

export function App(): React.JSX.Element {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    loadBuildMetadata()
      .then((metadata) => {
        if (!cancelled) setState({ status: "ready", metadata });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setState({
          status: "error",
          message: error instanceof Error ? error.message : String(error),
          incompatible: error instanceof ArtifactVersionError,
        });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main>
      <h1>Fantasy Draft Intelligence</h1>
      <p className="subtitle">
        Intrinsic value tiers and draft-market arbitrage, built from public football data.
      </p>
      <BuildStatus state={state} />
    </main>
  );
}

function BuildStatus({ state }: { readonly state: LoadState }): React.JSX.Element {
  if (state.status === "loading") {
    return <p role="status">Loading build metadata…</p>;
  }

  if (state.status === "error") {
    return (
      <div className="notice" data-severity="warning" role="alert">
        <strong>{state.incompatible ? "Incompatible data" : "No build data"}</strong>
        <p>{state.message}</p>
        <p>
          Generate fixture artifacts with{" "}
          <code>uv run ffdraft build-fixture-artifacts</code>, then reload.
        </p>
      </div>
    );
  }

  const { metadata } = state;
  const ageHours = buildAgeHours(metadata);
  const degraded = degradedSources(metadata);

  return (
    <section aria-labelledby="build-status">
      <h2 id="build-status">Current build</h2>
      <dl className="facts">
        <dt>Build</dt>
        <dd>{metadata.build_id}</dd>
        <dt>Generated</dt>
        <dd>
          {metadata.generated_at_utc} ({Math.round(ageHours)}h ago)
        </dd>
        <dt>Season</dt>
        <dd>{metadata.season}</dd>
        <dt>Intrinsic model</dt>
        <dd>{metadata.intrinsic_model_version}</dd>
        <dt>Arbitrage mode</dt>
        <dd>{metadata.arbitrage_mode}</dd>
        <dt>Presets</dt>
        <dd>{metadata.supported_presets.join(", ")}</dd>
        <dt>Quality gate</dt>
        <dd>
          {metadata.quality_gate.status} ({metadata.quality_gate.critical_failures} critical,{" "}
          {metadata.quality_gate.warnings} warning)
        </dd>
      </dl>

      {metadata.arbitrage_mode === "baseline" && (
        <div className="notice">
          Arbitrage is a <strong>deterministic baseline</strong>, not a learned model. Public
          historical ADP is not point-in-time, so no surplus model has been trained.
        </div>
      )}

      {degraded.length > 0 && (
        <div className="notice" data-severity="warning">
          <strong>Degraded sources:</strong> {degraded.join(", ")}
        </div>
      )}

      {metadata.warnings.length > 0 && (
        <>
          <h2>Build warnings</h2>
          <ul className="plain">
            {metadata.warnings.map((warning, index) => (
              // Warnings are free text from the build; the quality gate makes each line
              // distinct by including its stage, and position guarantees uniqueness even if
              // a future check emits two identical lines.
              <li key={`${String(index)}-${warning}`}>{warning}</li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
