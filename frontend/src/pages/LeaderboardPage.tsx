import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Crown, Medal, Trophy, Gamepad2, CheckCircle2, Swords, Activity } from "lucide-react";
import { api } from "../api";
import type {
  FamilyActivityResponse, FamilyUnlockEvent, LeaderboardEntry, LeaderboardResponse, SharedGame, SharedGamesResponse,
} from "../types";
import { fmtNum, fmtRelative } from "../lib/format";
import { platformLabel } from "../lib/platforms";

const FAMILY_ACTIVITY_POLL_MS = 45_000;

type LeaderboardSort = "achievist_points" | "achievements_unlocked" | "games_completed" | "games_played";
type LeaderboardWindow = "all" | "week" | "month";
type SharedGamesSort = "gap" | "name" | "recent";

const SORT_LABEL: Record<LeaderboardSort, string> = {
  achievist_points: "Achievist Points",
  achievements_unlocked: "Achievements unlocked",
  games_completed: "Games completed",
  games_played: "Games played",
};

const WINDOW_LABEL: Record<LeaderboardWindow, string> = {
  all: "All time",
  week: "This week",
  month: "This month",
};

const SHARED_SORT_LABEL: Record<SharedGamesSort, string> = {
  gap: "Closest race",
  name: "Alphabetical",
  recent: "Recently played",
};

function ActivityRow({ event }: { event: FamilyUnlockEvent }) {
  return (
    <div className="flex items-center gap-3 rounded-lg bg-ink-800 px-3 py-2">
      {event.icon_url ? (
        <img src={event.icon_url} alt="" className="h-8 w-8 shrink-0 rounded" />
      ) : (
        <div className="h-8 w-8 shrink-0 rounded bg-ink-700" />
      )}
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium text-slate-100">
          {event.achievement_name || "Achievement unlocked"}
        </div>
        <div className="truncate text-xs text-muted">
          {event.is_you ? "You" : event.display_name || event.username} · {event.game_name}
        </div>
      </div>
      <div className="shrink-0 text-xs text-faint">{fmtRelative(event.unlocked_at)}</div>
    </div>
  );
}

const RANK_STYLE = [
  "border-amber-400/40 bg-amber-400/10 text-amber-300",
  "border-slate-300/30 bg-slate-300/10 text-slate-200",
  "border-orange-400/30 bg-orange-400/10 text-orange-300",
];

function RankBadge({ rank }: { rank: number }) {
  if (rank < 3) {
    return (
      <div
        className={`flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full border text-sm font-bold ${RANK_STYLE[rank]}`}
      >
        <Crown size={16} />
      </div>
    );
  }
  return (
    <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full border border-line bg-ink-800 text-sm font-bold text-muted">
      {rank + 1}
    </div>
  );
}

function Row({ entry, rank, highlight }: { entry: LeaderboardEntry; rank: number; highlight: LeaderboardSort }) {
  const headline: Record<LeaderboardSort, string> = {
    achievist_points: fmtNum(entry.achievist_points),
    achievements_unlocked: fmtNum(entry.achievements_unlocked),
    games_completed: fmtNum(entry.games_completed),
    games_played: fmtNum(entry.games_played),
  };
  return (
    <div className="flex items-center gap-3 rounded-card border border-line bg-ink-850 p-3.5 sm:p-4">
      <RankBadge rank={rank} />
      <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center overflow-hidden rounded-full bg-ink-700 text-muted">
        {entry.avatar_url ? (
          <img src={entry.avatar_url} alt="" className="h-full w-full object-cover" />
        ) : (
          <Medal size={18} />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate font-semibold text-slate-100">
          {entry.display_name || entry.username}
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
          <span className="inline-flex items-center gap-1">
            <Trophy size={12} /> {fmtNum(entry.achievements_unlocked)} unlocked
          </span>
          <span className="inline-flex items-center gap-1">
            <Gamepad2 size={12} /> {fmtNum(entry.games_played)} games
          </span>
          <span className="inline-flex items-center gap-1">
            <CheckCircle2 size={12} /> {fmtNum(entry.games_completed)} completed
          </span>
        </div>
      </div>
      <div className="flex-shrink-0 text-right">
        <div className="text-xl font-bold tabular-nums text-slate-100">{headline[highlight]}</div>
        <div className="text-[10px] uppercase tracking-wide text-faint">
          {highlight === "achievist_points" ? "Achievist Pts" : SORT_LABEL[highlight]}
        </div>
      </div>
    </div>
  );
}

function SharedGameRow({ game, onCompare }: { game: SharedGame; onCompare: () => void }) {
  const leader = game.players[0];
  return (
    <button
      onClick={onCompare}
      className="w-full rounded-card border border-line bg-ink-850 p-3.5 text-left transition hover:border-ink-600 sm:p-4"
    >
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center overflow-hidden rounded-lg bg-ink-700 text-muted">
          {game.sgdb_cover_url || game.icon_url ? (
            <img src={game.sgdb_cover_url || game.icon_url || ""} alt="" className="h-full w-full object-cover" />
          ) : (
            <Gamepad2 size={16} />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate font-semibold text-slate-100">{game.name}</div>
          <div className="text-xs text-faint">{platformLabel(game.platform)}</div>
        </div>
      </div>

      <div className="mt-3 space-y-2">
        {game.players.map((p) => {
          const isLeader = p.user_id === leader.user_id && p.completion_pct > 0;
          return (
            <div key={p.user_id} className="flex items-center gap-2.5">
              <div className="w-24 flex-shrink-0 truncate text-xs text-muted sm:w-28">
                {p.display_name || p.username}
                {isLeader && game.players.length > 1 && (
                  <Crown size={11} className="ml-1 inline text-amber-400" />
                )}
              </div>
              <div className="h-2 flex-1 overflow-hidden rounded-full bg-ink-800">
                <div
                  className={`h-full rounded-full ${isLeader ? "bg-amber-400" : "bg-accent"}`}
                  style={{ width: `${Math.min(100, Math.round(p.completion_pct))}%` }}
                />
              </div>
              <div className="w-16 flex-shrink-0 text-right text-xs tabular-nums text-muted">
                {p.earned}/{p.total}
              </div>
            </div>
          );
        })}
      </div>
    </button>
  );
}

export function LeaderboardPage() {
  const navigate = useNavigate();
  const [data, setData] = useState<LeaderboardResponse | null>(null);
  const [gamesData, setGamesData] = useState<SharedGamesResponse | null>(null);
  const [activityEvents, setActivityEvents] = useState<FamilyUnlockEvent[]>([]);
  const [activityLoaded, setActivityLoaded] = useState(false);

  const [lbPlatform, setLbPlatform] = useState("");
  const [lbWindow, setLbWindow] = useState<LeaderboardWindow>("all");
  const [lbSort, setLbSort] = useState<LeaderboardSort>("achievist_points");

  const [sgPlatform, setSgPlatform] = useState("");
  const [sgSort, setSgSort] = useState<SharedGamesSort>("gap");

  useEffect(() => {
    setData(null);
    api.leaderboard({ platform: lbPlatform || undefined, window: lbWindow === "all" ? undefined : lbWindow })
      .then(setData)
      .catch(() => setData(null));
  }, [lbPlatform, lbWindow]);

  useEffect(() => {
    api.sharedGames().then(setGamesData).catch(() => setGamesData(null));
  }, []);

  useEffect(() => {
    let cancelled = false;
    let cursor = "";
    const poll = async () => {
      try {
        const res: FamilyActivityResponse = await api.familyActivity(cursor);
        if (cancelled) return;
        if (res.events.length > 0) {
          cursor = res.events[res.events.length - 1].unlocked_at;
          setActivityEvents((prev) => [...res.events].reverse().concat(prev).slice(0, 50));
        }
        setActivityLoaded(true);
      } catch {
        /* ignore */
      }
    };
    poll();
    const id = window.setInterval(poll, FAMILY_ACTIVITY_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  const availablePlatforms = useMemo(
    () => Array.from(new Set((gamesData?.games ?? []).map((g) => g.platform))).sort(),
    [gamesData],
  );

  const sortedEntries = useMemo(() => {
    if (!data) return [];
    return [...data.entries].sort((a, b) => b[lbSort] - a[lbSort]);
  }, [data, lbSort]);

  const filteredSharedGames = useMemo(() => {
    if (!gamesData) return [];
    let games = gamesData.games;
    if (sgPlatform) games = games.filter((g) => g.platform === sgPlatform);
    const withGap = (g: SharedGame) => {
      const sorted = [...g.players].sort((a, b) => b.completion_pct - a.completion_pct);
      return sorted.length >= 2 ? sorted[0].completion_pct - sorted[1].completion_pct : 0;
    };
    const sorted = [...games];
    if (sgSort === "gap") sorted.sort((a, b) => withGap(a) - withGap(b));
    else if (sgSort === "name") sorted.sort((a, b) => a.name.localeCompare(b.name));
    else if (sgSort === "recent") {
      sorted.sort((a, b) => {
        const at = a.last_activity ? new Date(a.last_activity).getTime() : 0;
        const bt = b.last_activity ? new Date(b.last_activity).getTime() : 0;
        return bt - at;
      });
    }
    return sorted;
  }, [gamesData, sgPlatform, sgSort]);

  const selectClass = "rounded-lg border border-line bg-ink-800 px-2 py-1 text-xs text-slate-200";

  return (
    <div>
      {activityLoaded && (
        <div className="mb-8 rounded-card border border-line bg-ink-850 p-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-200">
            <Activity size={15} className="text-faint" /> Family Activity
          </div>
          {activityEvents.length === 0 ? (
            <div className="py-6 text-center text-sm text-muted">
              No recent activity yet — achievements will show up here as they're unlocked.
            </div>
          ) : (
            <div className="max-h-80 space-y-2 overflow-y-auto">
              {activityEvents.map((e, i) => (
                <ActivityRow key={`${e.unlocked_at}-${e.username}-${i}`} event={e} />
              ))}
            </div>
          )}
        </div>
      )}

      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="text-lg font-semibold text-slate-100">Leaderboard</div>
        <div className="flex flex-wrap items-center gap-2">
          <select value={lbSort} onChange={(e) => setLbSort(e.target.value as LeaderboardSort)} className={selectClass}>
            {(Object.keys(SORT_LABEL) as LeaderboardSort[]).map((k) => (
              <option key={k} value={k}>Sort: {SORT_LABEL[k]}</option>
            ))}
          </select>
          <select value={lbWindow} onChange={(e) => setLbWindow(e.target.value as LeaderboardWindow)} className={selectClass}>
            {(Object.keys(WINDOW_LABEL) as LeaderboardWindow[]).map((k) => (
              <option key={k} value={k}>{WINDOW_LABEL[k]}</option>
            ))}
          </select>
          <select value={lbPlatform} onChange={(e) => setLbPlatform(e.target.value)} className={selectClass}>
            <option value="">All platforms</option>
            {availablePlatforms.map((p) => (
              <option key={p} value={p}>{platformLabel(p)}</option>
            ))}
          </select>
        </div>
      </div>
      <p className="mb-5 text-sm text-muted">
        Achievist Points weight each unlock by how rare it is (Legendary unlocks are worth far more
        than common ones), so it stays fair across platforms and games. Only family members who've
        opted in to sharing are shown here — you always see your own row.
        {lbWindow !== "all" && " Games played/completed always reflect all-time, even with a time window selected."}
      </p>

      {!data ? (
        <div className="py-8 text-center text-muted">Loading…</div>
      ) : !data.you_share ? (
        <div className="mb-5 rounded-card border border-accent/30 bg-accent/10 px-4 py-3 text-sm text-slate-200">
          You're not sharing your stats yet — turn on <strong>Compare achievements with family</strong>{" "}
          from your profile (click your avatar above) so you show up for everyone else too.
        </div>
      ) : null}

      {data && (
        sortedEntries.length === 0 ? (
          <div className="rounded-card border border-line bg-ink-850 p-6 text-center text-sm text-muted">
            No data yet — connect and sync a platform to get on the board.
          </div>
        ) : (
          <div className="space-y-2.5">
            {sortedEntries.map((e, i) => (
              <Row key={e.user_id} entry={e} rank={i} highlight={lbSort} />
            ))}
          </div>
        )
      )}

      <div className="mb-2 mt-8 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-lg font-semibold text-slate-100">
          <Swords size={18} className="text-accent" />
          Games in Common
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select value={sgSort} onChange={(e) => setSgSort(e.target.value as SharedGamesSort)} className={selectClass}>
            {(Object.keys(SHARED_SORT_LABEL) as SharedGamesSort[]).map((k) => (
              <option key={k} value={k}>Sort: {SHARED_SORT_LABEL[k]}</option>
            ))}
          </select>
          <select value={sgPlatform} onChange={(e) => setSgPlatform(e.target.value)} className={selectClass}>
            <option value="">All platforms</option>
            {availablePlatforms.map((p) => (
              <option key={p} value={p}>{platformLabel(p)}</option>
            ))}
          </select>
        </div>
      </div>
      <p className="mb-5 text-sm text-muted">
        Games two or more of you own, with who's furthest ahead on each.
      </p>

      {!gamesData ? (
        <div className="py-8 text-center text-muted">Loading…</div>
      ) : filteredSharedGames.length === 0 ? (
        <div className="rounded-card border border-line bg-ink-850 p-6 text-center text-sm text-muted">
          No shared games yet — once two of you own the same game, it'll show up here.
        </div>
      ) : (
        <div className="grid gap-2.5 sm:grid-cols-2">
          {filteredSharedGames.map((g) => (
            <SharedGameRow
              key={g.platform_game_id}
              game={g}
              onCompare={() => navigate(`/leaderboard/games/${g.platform_game_id}`)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
