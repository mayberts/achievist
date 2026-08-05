import type {
  Account,
  Achievement,
  AchievementSearchResponse,
  Activity,
  AuthStatus,
  BackupsResponse,
  GameDetail,
  GamesResponse,
  LeaderboardResponse,
  PlatformSchema,
  Profile,
  SharedGamesResponse,
  RecentUnlocksResponse,
  SgdbSearchResponse,
  Summary,
  SyncProgress,
  User,
} from "./types";

// Session cookie expiring mid-use (or never having been set) surfaces as a
// 401 from any endpoint. Rather than have every page handle that specially,
// AuthGate registers a handler here once that bounces back to the login
// screen — /api/auth/* calls themselves are exempt, since a wrong password
// legitimately 401s and shouldn't trigger a "session expired" bounce.
let unauthorizedHandler: (() => void) | null = null;
export function onUnauthorized(handler: () => void) {
  unauthorizedHandler = handler;
}
function reportIfUnauthorized(url: string, status: number) {
  if (status === 401 && !url.startsWith("/api/auth/")) unauthorizedHandler?.();
}

// AppBackground fetches the profile once on mount, same as SummaryBar — but
// it has no props/callback wired to ProfileEditModal's save, so without this
// it'd stay stale until the next full page load. Broadcasting here instead
// of threading a callback through App/SummaryBar/ProfileEditModal keeps the
// background layer decoupled from where profile edits happen to live.
const profileUpdatedHandlers = new Set<(p: Profile) => void>();
export function onProfileUpdated(handler: (p: Profile) => void): () => void {
  profileUpdatedHandlers.add(handler);
  return () => {
    profileUpdatedHandlers.delete(handler);
  };
}
function notifyProfileUpdated(p: Profile) {
  profileUpdatedHandlers.forEach((h) => h(p));
}

async function get<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) {
    reportIfUnauthorized(url, r.status);
    throw new Error(`${r.status} ${await r.text()}`);
  }
  return r.json() as Promise<T>;
}

async function send<T>(url: string, method: string, body?: unknown): Promise<T> {
  const r = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    reportIfUnauthorized(url, r.status);
    let detail = await r.text();
    try {
      detail = JSON.parse(detail).detail ?? detail;
    } catch {
      /* keep raw text */
    }
    throw new Error(detail || `${r.status}`);
  }
  if (r.status === 204) return undefined as T;
  return r.json().catch(() => undefined) as Promise<T>;
}

export interface GamesQuery {
  sort?: string;
  platform?: string;
  search?: string;
  completion?: string;
  page?: number;
  page_size?: number;
}

export interface AchievementSearchQuery {
  q?: string;
  rarity?: string;
  platform?: string;
  unlocked?: string;
  sort?: string;
  page?: number;
  page_size?: number;
}

export const api = {
  authStatus: () => get<AuthStatus>("/api/auth/status"),
  authSetup: (username: string, password: string) =>
    send<User>("/api/auth/setup", "POST", { username, password }),
  login: (username: string, password: string) =>
    send<User>("/api/auth/login", "POST", { username, password }),
  logout: () => send<{ status: string }>("/api/auth/logout", "POST"),

  users: () => get<User[]>("/api/users"),
  createUser: (body: { username: string; password: string; display_name?: string; is_admin?: boolean }) =>
    send<User>("/api/users", "POST", body),
  deleteUser: (id: number) => send<void>(`/api/users/${id}`, "DELETE"),

  summary: () => get<Summary>("/api/summary"),

  profile: () => get<Profile>("/api/profile"),
  updateProfile: (p: Profile) =>
    send<Profile>("/api/profile", "PUT", p).then((saved) => {
      notifyProfileUpdated(saved);
      return saved;
    }),

  leaderboard: () => get<LeaderboardResponse>("/api/leaderboard"),
  sharedGames: () => get<SharedGamesResponse>("/api/leaderboard/games"),

  games: (q: GamesQuery) => {
    const params = new URLSearchParams();
    Object.entries(q).forEach(([k, v]) => {
      if (v !== undefined && v !== "" && v !== null) params.set(k, String(v));
    });
    return get<GamesResponse>(`/api/games?${params.toString()}`);
  },

  gameDetail: (id: number) => get<GameDetail>(`/api/games/${id}`),
  gameAchievements: (id: number) => get<Achievement[]>(`/api/games/${id}/achievements`),

  platforms: () => get<PlatformSchema[]>("/api/platforms"),
  accounts: () => get<Account[]>("/api/accounts"),
  connectAccount: (body: { platform: string; external_id?: string; credentials: Record<string, string> }) =>
    send<{ id: number; status: string }>("/api/accounts", "POST", body),
  disconnectAccount: (id: number) => send<void>(`/api/accounts/${id}`, "DELETE"),
  syncAccount: (id: number) => send<{ status: string }>(`/api/accounts/${id}/sync`, "POST"),

  activity: () => get<Activity>("/api/activity"),

  syncAll: () => send<{ status: string }>("/api/sync", "POST"),
  syncProgress: () => get<SyncProgress>("/api/sync/progress"),

  // Xbox backend sign-in (used to look up public profiles by gamertag)
  xboxServiceStatus: () => get<{ signed_in: boolean }>("/api/xbox-service-status"),

  // PlayStation backend service credential (used to look up public trophies by Online ID)
  psnServiceStatus: () => get<{ signed_in: boolean }>("/api/psn-service-status"),
  psnServiceTicket: (npsso: string) =>
    send<{ status: string }>("/api/psn-service-ticket", "POST", { npsso }),

  // Backups
  backups: () => get<BackupsResponse>("/api/backups"),
  createBackup: () => send<{ filename: string }>("/api/backups", "POST"),
  deleteBackup: (filename: string) =>
    send<void>(`/api/backups/${encodeURIComponent(filename)}`, "DELETE"),

  // Change Cover (manual SteamGridDB override)
  sgdbSearch: (q: string) => get<SgdbSearchResponse>(`/api/sgdb-search?q=${encodeURIComponent(q)}`),
  sgdbSet: (platformGameId: number, url: string) =>
    send<{ status: string }>(
      `/api/sgdb-set?platform_game_id=${platformGameId}&url=${encodeURIComponent(url)}`,
      "POST",
    ),
  sgdbRefresh: (force: boolean) =>
    send<{ status: string }>(`/api/sgdb-refresh?force=${force}`, "POST"),
  hltbRefresh: () => send<{ status: string }>("/api/hltb-refresh", "POST"),

  // Achievement-unlock notification feed
  recentUnlocks: (since: string) =>
    get<RecentUnlocksResponse>(`/api/unlocks/recent?since=${encodeURIComponent(since)}`),

  searchAchievements: (q: AchievementSearchQuery) => {
    const params = new URLSearchParams();
    Object.entries(q).forEach(([k, v]) => {
      if (v !== undefined && v !== "" && v !== null) params.set(k, String(v));
    });
    return get<AchievementSearchResponse>(`/api/achievements/search?${params.toString()}`);
  },
};
