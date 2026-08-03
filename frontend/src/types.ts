export interface PlatformSummary {
  platform: string;
  games: number;
  earned: number;
  possible: number;
  pct: number;
  total_playtime_minutes: number | null;
  last_sync: string | null;
  most_played: boolean;
}

export interface Summary {
  total_games: number;
  total_earned: number;
  total_possible: number;
  overall_pct: number;
  perfect_games: number;
  by_platform: PlatformSummary[];
}

export interface Game {
  platform_game_id: number;
  platform: string;
  platform_app_id: string;
  name: string;
  icon_url: string | null;
  store_id: string | null;
  sgdb_cover_url: string | null;
  igdb_cover_url: string | null;
  playtime_minutes: number | null;
  earned_achievements: number;
  total_achievements: number;
  completion_pct: number;
  last_played_at: string | null;
}

export interface GameDetail extends Game {
  hltb_main: number | null;
  hltb_extra: number | null;
  hltb_complete: number | null;
  rarity_summary: { tier: string; cnt: number }[];
  total_points: number;
}

export interface SgdbSearchResult {
  id: number;
  name: string;
  heroes: string[];
  grids: string[];
}

export interface SgdbSearchResponse {
  games?: SgdbSearchResult[];
  error?: string;
}

export interface Achievement {
  platform_ach_id: string;
  name: string | null;
  description: string | null;
  icon_url: string | null;
  points: number | null;
  rarity_pct: number | null;
  unlocked: boolean | null;
  unlocked_at: string | null;
}

export interface GamesResponse {
  total: number;
  page: number;
  page_size: number;
  games: Game[];
}

export interface ConnectField {
  name: string;
  label: string;
  type: "text" | "password" | "select";
  required?: boolean;
  secret?: boolean;
  help?: string;
  options?: string[];
}

export interface PlatformSchema {
  key: string;
  label: string;
  auth_type: "form" | "oauth";
  fields: ConnectField[];
}

export interface Account {
  id: number;
  platform: string;
  external_id: string;
  display_name: string | null;
  enabled: boolean;
  status: string | null;
  last_error: string | null;
  last_synced_at: string | null;
  credentials: Record<string, string>;
}

export interface ActivityFeedItem {
  platform_game_id: number;
  name: string;
  platform: string;
  cover_url: string | null;
  day: string;
  count: number;
  icons: string[];
}

export interface Activity {
  heatmap: { day: string; count: number }[];
  current_streak: number;
  longest_streak: number;
  total_playtime_minutes: number;
  feed: ActivityFeedItem[];
}

export interface BackupInfo {
  filename: string;
  size_bytes: number;
  created_at: string;
}

export interface BackupsResponse {
  backups: BackupInfo[];
  keep_count: number;
  interval_hours: number;
}

export interface SyncProgress {
  running: boolean;
  started_at: string | null;
  platforms: Record<
    string,
    { status: string; games_seen: number; achievements_synced: number; error: string | null }
  >;
}
