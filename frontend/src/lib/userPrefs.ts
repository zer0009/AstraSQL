export type Density = "comfortable" | "compact";

export interface UserPrefs {
  conversationTurns: number;
  density: Density;
  sidebarOpen: boolean;
}

const PREFS_KEY = "astrasql.prefs";
const LEGACY_DENSITY_KEY = "astrasql.ui.density";

export const DEFAULT_PREFS: UserPrefs = {
  conversationTurns: 3,
  density: "comfortable",
  sidebarOpen: true,
};

function clampTurns(value: unknown): number {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return DEFAULT_PREFS.conversationTurns;
  return Math.min(10, Math.max(1, Math.round(n)));
}

function normalizeDensity(value: unknown): Density {
  return value === "compact" ? "compact" : "comfortable";
}

function readLegacyDensity(): Density | null {
  try {
    const raw = localStorage.getItem(LEGACY_DENSITY_KEY);
    if (raw === "compact" || raw === "comfortable") return raw;
  } catch {
    // ignore
  }
  return null;
}

export const userPrefs = {
  load(): UserPrefs {
    try {
      const raw = localStorage.getItem(PREFS_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as Partial<UserPrefs>;
        return {
          conversationTurns: clampTurns(
            parsed.conversationTurns ?? DEFAULT_PREFS.conversationTurns,
          ),
          density: normalizeDensity(parsed.density ?? DEFAULT_PREFS.density),
          sidebarOpen:
            typeof parsed.sidebarOpen === "boolean"
              ? parsed.sidebarOpen
              : DEFAULT_PREFS.sidebarOpen,
        };
      }
    } catch {
      // fall through to defaults / legacy
    }

    const legacyDensity = readLegacyDensity();
    return {
      ...DEFAULT_PREFS,
      density: legacyDensity ?? DEFAULT_PREFS.density,
    };
  },

  save(patch: Partial<UserPrefs>): UserPrefs {
    const next: UserPrefs = {
      ...this.load(),
      ...patch,
    };
    next.conversationTurns = clampTurns(next.conversationTurns);
    next.density = normalizeDensity(next.density);
    next.sidebarOpen =
      typeof next.sidebarOpen === "boolean"
        ? next.sidebarOpen
        : DEFAULT_PREFS.sidebarOpen;

    try {
      localStorage.setItem(PREFS_KEY, JSON.stringify(next));
      // Keep legacy key in sync for older code paths during transition.
      localStorage.setItem(LEGACY_DENSITY_KEY, next.density);
    } catch {
      // ignore quota / private mode errors
    }
    return next;
  },
};

export function sessionStorageKey(connectionId: string): string {
  return `astrasql.currentSessionId.${connectionId}`;
}

export function readCurrentSessionId(connectionId: string): string | null {
  try {
    return localStorage.getItem(sessionStorageKey(connectionId));
  } catch {
    return null;
  }
}

export function writeCurrentSessionId(
  connectionId: string,
  sessionId: string | null,
): void {
  try {
    const key = sessionStorageKey(connectionId);
    if (sessionId) localStorage.setItem(key, sessionId);
    else localStorage.removeItem(key);
  } catch {
    // ignore
  }
}
