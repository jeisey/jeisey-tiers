/**
 * The players a saved roster can name, resolved by canonical id against the current build
 * (ADR-106).
 *
 * A saved league stores ids and nothing else; every visit resolves them here against the
 * artifacts the workspace already loads — the week's projections, the league's rest-of-season
 * block and the season actuals — never by name. A player none of them carries is **unresolved**:
 * he keeps his slot, his name is read from the build's player dictionary when it has one, and
 * nothing is computed for him.
 *
 * The same index serves the slot picker's search, which matches names for the reader's
 * convenience only: what is saved is the id the reader picked.
 */

import type { Position, RosTierRecord, ScoringPreset, WeeklyProjectionRecord } from "./contracts";
import type { InSeasonBundle } from "./ros";

export interface UniversePlayer {
  readonly id: string;
  readonly name: string;
  readonly position: Position;
  readonly team: string | null;
  readonly weekly: WeeklyProjectionRecord | null;
  readonly ros: RosTierRecord | null;
  /** Lower-cased, accent-free, punctuation-free name, for search only. */
  readonly key: string;
}

const SKILL: ReadonlySet<Position> = new Set(["QB", "RB", "WR", "TE"]);

export function searchKey(text: string): string {
  return text
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9 ]+/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

export class PlayerUniverse {
  private readonly byId: ReadonlyMap<string, UniversePlayer>;
  private readonly ordered: readonly UniversePlayer[];

  constructor(
    bundle: InSeasonBundle,
    scoring: ScoringPreset,
    leaguePreset: string,
    nameOf: (playerId: string) => string | null,
  ) {
    const byId = new Map<string, UniversePlayer>();
    const add = (
      id: string,
      position: Position,
      name: string | null,
      team: string | null,
      weekly: WeeklyProjectionRecord | null,
      ros: RosTierRecord | null,
    ): void => {
      if (!SKILL.has(position) || byId.has(id)) return;
      const label = name ?? nameOf(id) ?? id;
      byId.set(id, { id, name: label, position, team, weekly, ros, key: searchKey(label) });
    };
    // Precedence: this week's record, then the rest-of-season row, then the actuals row.
    const rosById = new Map(bundle.rosFor(leaguePreset, scoring).map((record) => [record.player_id, record]));
    for (const record of bundle.weeklyFor(scoring)) {
      add(record.player_id, record.position, record.display_name, record.team, record, rosById.get(record.player_id) ?? null);
    }
    for (const record of rosById.values()) {
      add(record.player_id, record.position, record.display_name, record.team, null, record);
    }
    for (const row of bundle.actualsRowsFor(scoring)) {
      add(row.player_id, row.position, null, null, null, null);
    }
    this.byId = byId;
    this.ordered = [...byId.values()].sort(
      (a, b) =>
        (a.ros?.ros_fair_rank ?? Number.POSITIVE_INFINITY) - (b.ros?.ros_fair_rank ?? Number.POSITIVE_INFINITY) ||
        (b.weekly?.quantiles?.q50 ?? -1) - (a.weekly?.quantiles?.q50 ?? -1) ||
        a.name.localeCompare(b.name) ||
        (a.id < b.id ? -1 : 1),
    );
  }

  get(playerId: string): UniversePlayer | null {
    return this.byId.get(playerId) ?? null;
  }

  get size(): number {
    return this.byId.size;
  }

  /**
   * Up to `limit` players whose name, team or position matches every word of `query`, best
   * known first (ROS rank, then this week's median). Names that start with a query word come
   * before names that only contain it.
   */
  search(query: string, accepts: (player: UniversePlayer) => boolean, limit = 8): UniversePlayer[] {
    const words = searchKey(query).split(" ").filter((word) => word !== "");
    if (words.length === 0) return [];
    const starts: UniversePlayer[] = [];
    const contains: UniversePlayer[] = [];
    for (const player of this.ordered) {
      if (!accepts(player)) continue;
      const hay = `${player.key} ${(player.team ?? "").toLowerCase()} ${player.position.toLowerCase()}`;
      if (!words.every((word) => hay.includes(word))) continue;
      const parts = player.key.split(" ");
      if (words.some((word) => parts.some((part) => part.startsWith(word)))) starts.push(player);
      else contains.push(player);
      if (starts.length >= limit) break;
    }
    return [...starts, ...contains].slice(0, limit);
  }
}

const cache = new WeakMap<InSeasonBundle, Map<string, PlayerUniverse>>();

/** One universe per bundle and block, kept as long as the bundle is. */
export function universeFor(
  bundle: InSeasonBundle,
  scoring: ScoringPreset,
  leaguePreset: string,
  nameOf: (playerId: string) => string | null,
): PlayerUniverse {
  let byBlock = cache.get(bundle);
  if (byBlock === undefined) {
    byBlock = new Map();
    cache.set(bundle, byBlock);
  }
  const key = `${leaguePreset}|${scoring}`;
  const known = byBlock.get(key);
  if (known !== undefined) return known;
  const universe = new PlayerUniverse(bundle, scoring, leaguePreset, nameOf);
  byBlock.set(key, universe);
  return universe;
}
