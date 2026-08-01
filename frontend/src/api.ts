import type {
  Account,
  Achievement,
  GameDetail,
  GamesResponse,
  PlatformSchema,
  Summary,
  SyncProgress,
} from "./types";

async function get<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json() as Promise<T>;
}

async function send<T>(url: string, method: string, body?: unknown): Promise<T> {
  const r = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
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

export const api = {
  summary: () => get<Summary>("/api/summary"),

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

  syncAll: () => send<{ status: string }>("/api/sync", "POST"),
  syncProgress: () => get<SyncProgress>("/api/sync/progress"),

  // Xbox backend sign-in (used to look up public profiles by gamertag)
  xboxServiceStatus: () => get<{ signed_in: boolean }>("/api/xbox-service-status"),

  // Ubisoft backend service credential (used to look up public profiles by username)
  ubisoftServiceStatus: () => get<{ signed_in: boolean }>("/api/ubisoft-service-status"),
  ubisoftServiceTicket: (ticket: string) =>
    send<{ status: string }>("/api/ubisoft-service-ticket", "POST", { ticket }),
};
