/**
 * The Win My Matchup store as React context (ADR-110): tests hand in their own store; the page
 * uses the shared one. Mirrors `LeagueStoreContext`.
 */

import { createContext } from "react";

import type { WmmStore } from "../../data/wmmStore";

export const WmmStoreContext = createContext<WmmStore | null>(null);
