/**
 * The browser's data model: indexes built once, view models derived from them.
 *
 * Three rules hold this file together, and each is a repository decision rather than a
 * frontend preference:
 *
 * 1. **Nothing is recomputed.** The browser filters, joins and formats. A fair rank, a VORP,
 *    an arbitrage score and a tier ordinal all arrive from the artifacts and leave unchanged
 *    (`docs/ARCHITECTURE.md` section 3.2). No chart may derive a value the table cannot show.
 * 2. **Status is annotation.** `player_status.json` describes *today*; the projection beside
 *    it never saw a single one of its fields (ADR-043). Joining them here does not make one
 *    an input to the other, and the UI must not say it does.
 * 3. **Artifacts are read-only.** Records are never mutated; a derived view is an explicit
 *    new object.
 */

import type {
  ArbitrageRecord,
  BuildMetadata,
  PlayerProjectionRecord,
  PlayerStatusRecord,
  Position,
  ScoringPreset,
  TierRecord,
} from "./contracts";
import type { AppState, PositionFilter } from "./state";
import { SCORING_TO_PRESET, leaguePresetId } from "./state";

/** `redraft-12|PPR` — the grain both boards are published at. */
function blockKey(leaguePreset: string, scoring: ScoringPreset): string {
  return `${leaguePreset}|${scoring}`;
}

function pushInto<K, V>(map: Map<K, V[]>, key: K, value: V): void {
  const existing = map.get(key);
  if (existing === undefined) {
    map.set(key, [value]);
  } else {
    existing.push(value);
  }
}

export interface ArtifactBundle {
  readonly metadata: BuildMetadata;
  readonly tiers: readonly TierRecord[];
  readonly arbitrage: readonly ArbitrageRecord[] | null;
  readonly playerStatus: readonly PlayerStatusRecord[] | null;
  readonly projections: readonly PlayerProjectionRecord[] | null;
}

/**
 * Precomputed lookups.
 *
 * Built once per load rather than per render: the production board is 2,700 tier rows and
 * 2,124 arbitrage rows across nine preset blocks, and a control change must not rescan them.
 */
export class ArtifactIndex {
  readonly metadata: BuildMetadata;
  private readonly tiersByBlock: ReadonlyMap<string, readonly TierRecord[]>;
  private readonly tierByBlockPlayer: ReadonlyMap<string, TierRecord>;
  private readonly arbitrageByBlock: ReadonlyMap<string, readonly ArbitrageRecord[]>;
  private readonly arbitrageByBlockPlayer: ReadonlyMap<string, ArbitrageRecord>;
  private readonly projectionByScoringPlayer: ReadonlyMap<string, PlayerProjectionRecord>;
  private readonly statusByPlayer: ReadonlyMap<string, PlayerStatusRecord>;
  readonly hasArbitrage: boolean;
  readonly hasPlayerStatus: boolean;
  readonly hasProjections: boolean;

  constructor(bundle: ArtifactBundle) {
    this.metadata = bundle.metadata;
    this.hasArbitrage = bundle.arbitrage !== null;
    this.hasPlayerStatus = bundle.playerStatus !== null;
    this.hasProjections = bundle.projections !== null;

    const tiersByBlock = new Map<string, TierRecord[]>();
    const tierByBlockPlayer = new Map<string, TierRecord>();
    for (const record of bundle.tiers) {
      const key = blockKey(record.league_preset_id, record.scoring_preset);
      pushInto(tiersByBlock, key, record);
      tierByBlockPlayer.set(`${key}|${record.player_id}`, record);
    }
    // Fair rank is unique within a block and is the published ordering; sorting here means no
    // consumer has to remember to.
    for (const rows of tiersByBlock.values()) rows.sort((a, b) => a.fair_rank - b.fair_rank);
    this.tiersByBlock = tiersByBlock;
    this.tierByBlockPlayer = tierByBlockPlayer;

    const arbitrageByBlock = new Map<string, ArbitrageRecord[]>();
    const arbitrageByBlockPlayer = new Map<string, ArbitrageRecord>();
    for (const record of bundle.arbitrage ?? []) {
      const key = blockKey(record.league_preset_id, record.scoring_preset);
      pushInto(arbitrageByBlock, key, record);
      arbitrageByBlockPlayer.set(`${key}|${record.player_id}`, record);
    }
    for (const rows of arbitrageByBlock.values()) {
      rows.sort((a, b) => b.arbitrage_score - a.arbitrage_score || a.fair_rank - b.fair_rank);
    }
    this.arbitrageByBlock = arbitrageByBlock;
    this.arbitrageByBlockPlayer = arbitrageByBlockPlayer;

    const projectionByScoringPlayer = new Map<string, PlayerProjectionRecord>();
    for (const record of bundle.projections ?? []) {
      projectionByScoringPlayer.set(`${record.scoring_preset}|${record.player_id}`, record);
    }
    this.projectionByScoringPlayer = projectionByScoringPlayer;

    const statusByPlayer = new Map<string, PlayerStatusRecord>();
    for (const record of bundle.playerStatus ?? []) statusByPlayer.set(record.player_id, record);
    this.statusByPlayer = statusByPlayer;
  }

  /** Preset blocks the build actually published, so a control can offer only what exists. */
  availableBlocks(): readonly { leaguePreset: string; scoring: ScoringPreset }[] {
    return [...this.tiersByBlock.keys()].map((key) => {
      const [leaguePreset, scoring] = key.split("|");
      return { leaguePreset: leaguePreset ?? "", scoring: (scoring ?? "PPR") as ScoringPreset };
    });
  }

  tiersFor(leaguePreset: string, scoring: ScoringPreset): readonly TierRecord[] {
    return this.tiersByBlock.get(blockKey(leaguePreset, scoring)) ?? [];
  }

  arbitrageFor(leaguePreset: string, scoring: ScoringPreset): readonly ArbitrageRecord[] {
    return this.arbitrageByBlock.get(blockKey(leaguePreset, scoring)) ?? [];
  }

  tierFor(leaguePreset: string, scoring: ScoringPreset, playerId: string): TierRecord | null {
    return this.tierByBlockPlayer.get(`${blockKey(leaguePreset, scoring)}|${playerId}`) ?? null;
  }

  arbitrageRecordFor(
    leaguePreset: string,
    scoring: ScoringPreset,
    playerId: string,
  ): ArbitrageRecord | null {
    return this.arbitrageByBlockPlayer.get(`${blockKey(leaguePreset, scoring)}|${playerId}`) ?? null;
  }

  projectionFor(scoring: ScoringPreset, playerId: string): PlayerProjectionRecord | null {
    return this.projectionByScoringPlayer.get(`${scoring}|${playerId}`) ?? null;
  }

  statusFor(playerId: string): PlayerStatusRecord | null {
    return this.statusByPlayer.get(playerId) ?? null;
  }
}

/** A tier row with its annotation joined. `status` is null whenever nothing is published. */
export interface TierRow {
  readonly record: TierRecord;
  readonly status: PlayerStatusRecord | null;
  /** Present only when the player also carries a market price. Missing is normal, not an error. */
  readonly arbitrage: ArbitrageRecord | null;
}

export interface ArbitrageRow {
  readonly record: ArbitrageRecord;
  readonly status: PlayerStatusRecord | null;
  readonly tier: TierRecord | null;
  /** 1-based position in the published arbitrage-score ordering for this block. */
  readonly arbitrageRank: number;
}

const POSITION_OF: Readonly<Record<Exclude<PositionFilter, "all">, Position>> = {
  qb: "QB",
  rb: "RB",
  wr: "WR",
  te: "TE",
};

export function matchesPosition(position: Position, filter: PositionFilter): boolean {
  return filter === "all" || position === POSITION_OF[filter];
}

/**
 * Case- and punctuation-insensitive substring match on the display name, position and team.
 *
 * Deliberately forgiving: a drafter typing "stbrown" should find Amon-Ra St. Brown, and
 * typing "SF" should narrow to a roster.
 */
export function matchesSearch(
  row: { display_name: string; team: string | null; position: Position },
  search: string,
): boolean {
  const needle = normalizeSearch(search);
  if (needle === "") return true;
  return (
    normalizeSearch(row.display_name).includes(needle) ||
    normalizeSearch(row.team ?? "").includes(needle) ||
    normalizeSearch(row.position) === needle
  );
}

export function normalizeSearch(value: string): string {
  return value
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]/g, "");
}

export function selectTierRows(index: ArtifactIndex, state: AppState): readonly TierRow[] {
  const leaguePreset = leaguePresetId(state.teams);
  const scoring = SCORING_TO_PRESET[state.scoring];
  const rows: TierRow[] = [];
  for (const record of index.tiersFor(leaguePreset, scoring)) {
    if (!matchesPosition(record.position, state.position)) continue;
    if (!matchesSearch(record, state.search)) continue;
    rows.push({
      record,
      status: index.statusFor(record.player_id),
      arbitrage: index.arbitrageRecordFor(leaguePreset, scoring, record.player_id),
    });
  }
  return rows;
}

export function selectArbitrageRows(index: ArtifactIndex, state: AppState): readonly ArbitrageRow[] {
  const leaguePreset = leaguePresetId(state.teams);
  const scoring = SCORING_TO_PRESET[state.scoring];
  const ordered = index.arbitrageFor(leaguePreset, scoring);
  const rows: ArbitrageRow[] = [];
  ordered.forEach((record, position) => {
    if (!matchesPosition(record.position, state.position)) return;
    if (!matchesSearch(record, state.search)) return;
    rows.push({
      record,
      status: index.statusFor(record.player_id),
      tier: index.tierFor(leaguePreset, scoring, record.player_id),
      arbitrageRank: position + 1,
    });
  });
  return rows;
}

/**
 * Tier players the search matches but the arbitrage board has no price for.
 *
 * The intrinsic board is complete and the market board is not: 42 top-150 players carried no
 * MyFantasyLeague price in the launch build. Naming them beats a bare "0 results", which
 * would read as "this player does not exist" (prompt requirement; ADR-045 context).
 */
export function unpricedMatches(index: ArtifactIndex, state: AppState): readonly TierRecord[] {
  if (state.search.trim() === "") return [];
  const leaguePreset = leaguePresetId(state.teams);
  const scoring = SCORING_TO_PRESET[state.scoring];
  return index
    .tiersFor(leaguePreset, scoring)
    .filter(
      (record) =>
        matchesPosition(record.position, state.position) &&
        matchesSearch(record, state.search) &&
        index.arbitrageRecordFor(leaguePreset, scoring, record.player_id) === null,
    );
}

/** Contiguous fair-rank runs sharing a tier ordinal — the lanes the Tier Board draws. */
export interface TierGroup {
  readonly ordinal: number;
  readonly label: string;
  readonly rows: readonly TierRow[];
}

export function groupByTier(rows: readonly TierRow[]): readonly TierGroup[] {
  interface MutableGroup {
    ordinal: number;
    label: string;
    rows: TierRow[];
  }
  const groups: MutableGroup[] = [];
  // Tier ordinals are nondecreasing in fair-rank order and every tier is a contiguous run
  // (`docs/DATA_CONTRACTS.md` section 8), so a single pass over the sorted rows is enough.
  for (const row of [...rows].sort((a, b) => a.record.fair_rank - b.record.fair_rank)) {
    const current = groups[groups.length - 1];
    if (current?.ordinal !== row.record.tier_ordinal) {
      groups.push({
        ordinal: row.record.tier_ordinal,
        label: row.record.tier_label,
        rows: [row],
      });
    } else {
      current.rows.push(row);
    }
  }
  return groups;
}

/**
 * Whether a status record carries anything worth telling a drafter.
 *
 * A null `injury_status` is *absence of a reported designation*, never a claim of health
 * (ADR-043 and the prompt's explicit rule). Nothing in this file ever produces the word
 * "Healthy" from a null.
 */
export function hasMeaningfulStatus(status: PlayerStatusRecord | null): boolean {
  if (status === null) return false;
  return (
    status.injury_status !== null ||
    status.injury_body_part !== null ||
    status.injury_notes !== null ||
    status.practice_participation !== null ||
    isNoteworthyRosterStatus(status.roster_status) ||
    isNoteworthySleeperStatus(status.sleeper_status)
  );
}

/** `ACT` is the ordinary case and says nothing; a reserve or exempt designation does. */
export function isNoteworthyRosterStatus(value: string | null): boolean {
  if (value === null) return false;
  return !["ACT", "A01", "DEV"].includes(value.toUpperCase());
}

export function isNoteworthySleeperStatus(value: string | null): boolean {
  if (value === null) return false;
  return value.toLowerCase() !== "active";
}

const INJURY_ABBREVIATIONS: Readonly<Record<string, string>> = {
  questionable: "Q",
  doubtful: "D",
  out: "OUT",
  ir: "IR",
  pup: "PUP",
  nfi: "NFI",
  sus: "SUS",
  suspended: "SUS",
  "injured reserve": "IR",
  dnr: "DNR",
};

/**
 * The compact badge text, e.g. `Q · Hamstring`.
 *
 * Returns null when there is nothing meaningful. Colour is never the only channel: this text
 * is the badge's content, not a tooltip on top of a coloured dot (UX spec section 12).
 */
export function statusBadge(status: PlayerStatusRecord | null): {
  readonly short: string;
  readonly full: string;
  readonly severity: "caution" | "warn";
} | null {
  if (status === null || !hasMeaningfulStatus(status)) return null;
  const designation =
    status.injury_status ??
    (isNoteworthySleeperStatus(status.sleeper_status) ? status.sleeper_status : null) ??
    (isNoteworthyRosterStatus(status.roster_status) ? status.roster_status : null);
  const abbreviation =
    designation === null
      ? "NOTE"
      : (INJURY_ABBREVIATIONS[designation.toLowerCase()] ?? designation.toUpperCase().slice(0, 4));
  const body = status.injury_body_part;
  const short = body === null ? abbreviation : `${abbreviation} · ${body}`;
  const full = [designation, body].filter((part) => part !== null).join(" · ");
  const severe =
    designation !== null && ["out", "ir", "pup", "nfi", "sus", "suspended"].includes(designation.toLowerCase());
  return {
    short,
    full: full === "" ? "Status note" : full,
    severity: severe ? "warn" : "caution",
  };
}
