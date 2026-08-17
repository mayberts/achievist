import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  BarChart,
  Bar,
  Cell,
  CartesianGrid,
} from "recharts";
import {
  Trophy, Lock, Gamepad2, Crown, CheckCircle2, Percent, Flame, CalendarDays, Sparkles, Target, Zap,
} from "lucide-react";
import { api } from "../api";
import { platformLabel } from "../lib/platforms";
import { fmtDate } from "../lib/format";
import { RARITY_TIER_HEX, RARITY_TIER_CLASS, rarityTier } from "../lib/rarity";

interface ChaseItem {
  platform_game_id: number;
  platform_ach_id: string;
  name: string | null;
  icon_url: string | null;
  rarity_pct: number;
  game_name: string;
  platform: string;
}

// How many of the most-recently-played games to pull locked achievements
// from — keeps the list actionable (games you're actually in the middle of)
// rather than the rarest achievement in your entire library, which could be
// sitting in something you last touched years ago.
const CHASE_RECENT_GAMES = 5;

interface QuickWinItem {
  platform_game_id: number;
  name: string;
  platform: string;
  icon_url: string | null;
  earned_achievements: number;
  total_achievements: number;
  completion_pct: number;
  remaining: number;
}

interface ProgressionPoint {
  month: string;
  cnt: number;
  total: number;
}

interface OnThisDayEntry {
  years_ago: number;
  unlocked_at: string;
  achievement_name: string;
  icon_url: string | null;
  game_name: string;
  platform: string;
}

interface Stats {
  general: Record<string, number | string | null>;
  rarity: { tier: string; cnt: number }[];
  completion_dist: { bracket: string; cnt: number }[];
  platforms: { platform: string; earned: number }[];
  progression: ProgressionPoint[];
  points_progression: ProgressionPoint[];
  progression_years: number[];
  on_this_day: OnThisDayEntry[];
}

const MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** All-time: cumulative running total, labeled YYYY-MM. A single year: per-month count, zero-filled Jan–Dec. */
function chartData(points: ProgressionPoint[], year: number | "all") {
  if (year === "all") {
    return points.map((p) => ({ label: p.month.slice(0, 7), value: p.total }));
  }
  const byMonth = new Map(points.filter((p) => p.month.startsWith(`${year}-`)).map((p) => [p.month.slice(5, 7), p.cnt]));
  return MONTH_LABELS.map((label, i) => ({
    label,
    value: byMonth.get(String(i + 1).padStart(2, "0")) ?? 0,
  }));
}

const CHART_TOOLTIP = { background: "#121826", border: "1px solid #232c42", borderRadius: 8 } as const;

const PLATFORM_BAR_COLORS = ["#5b8cff", "#3ecf8e", "#f0b429", "#e879f9", "#38bdf8", "#fb7185", "#a78bfa"];

function Tile({ icon, label, value }: { icon: React.ReactNode; label: string; value: string | number }) {
  return (
    <div className="rounded-card border border-line bg-ink-850 p-4">
      <div className="flex items-center gap-2 text-faint">{icon}</div>
      <div className="mt-2 text-2xl font-bold tabular-nums text-slate-100">{value}</div>
      <div className="mt-0.5 text-xs uppercase tracking-wide text-faint">{label}</div>
    </div>
  );
}

function Record({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-card border border-line bg-ink-850 p-4">
      <div className="text-xs uppercase tracking-wide text-faint">{label}</div>
      <div className="mt-1 text-lg font-semibold text-slate-100">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-muted">{sub}</div>}
    </div>
  );
}

export function StatisticsPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [year, setYear] = useState<number | "all">("all");
  const [chaseList, setChaseList] = useState<ChaseItem[] | null>(null);
  const [quickWins, setQuickWins] = useState<QuickWinItem[] | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    fetch("/api/statistics").then((r) => r.json()).then(setStats).catch(() => setStats(null));

    api
      .games({ sort: "completion", completion: "in_progress", page_size: 200 })
      .then((r) => {
        const wins = r.games
          .map((g) => ({
            platform_game_id: g.platform_game_id,
            name: g.name,
            platform: g.platform,
            icon_url: g.icon_url,
            earned_achievements: g.earned_achievements,
            total_achievements: g.total_achievements,
            completion_pct: g.completion_pct,
            remaining: g.total_achievements - g.earned_achievements,
          }))
          .sort((a, b) => a.remaining - b.remaining)
          .slice(0, 8);
        setQuickWins(wins);
      })
      .catch(() => setQuickWins([]));

    api
      .games({ sort: "recent", page_size: CHASE_RECENT_GAMES })
      .then(async (r) => {
        const recent = r.games.filter((g) => g.last_played_at && g.earned_achievements < g.total_achievements);
        const perGame = await Promise.all(
          recent.map(async (g) => {
            const achievements = await api.gameAchievements(g.platform_game_id).catch(() => []);
            // A game with a huge locked achievement list (e.g. an
            // achievement-farm title with thousands of near-0%-rarity
            // entries) would otherwise fill every slot on rarity alone —
            // cap each game's contribution so the list actually spans your
            // recently played games instead of just the spammiest one.
            return achievements
              .filter((a) => !a.unlocked && a.rarity_pct != null)
              .sort((a, b) => (a.rarity_pct as number) - (b.rarity_pct as number))
              .slice(0, 2)
              .map((a) => ({
                platform_game_id: g.platform_game_id,
                platform_ach_id: a.platform_ach_id,
                name: a.name,
                icon_url: a.icon_url,
                rarity_pct: a.rarity_pct as number,
                game_name: g.name,
                platform: g.platform,
              }));
          }),
        );
        setChaseList(perGame.flat().sort((a, b) => a.rarity_pct - b.rarity_pct).slice(0, 8));
      })
      .catch(() => setChaseList([]));
  }, []);

  const achievementsChart = useMemo(() => (stats ? chartData(stats.progression, year) : []), [stats, year]);
  const pointsChart = useMemo(() => (stats ? chartData(stats.points_progression, year) : []), [stats, year]);

  if (!stats) return <div className="py-16 text-center text-muted">Loading statistics…</div>;

  const g = stats.general;
  const num = (k: string) => Number(g[k] ?? 0);
  const platforms = stats.platforms
    .map((p) => ({ name: platformLabel(p.platform), earned: p.earned }))
    .sort((a, b) => b.earned - a.earned);
  const rarity = stats.rarity.map((r) => ({ ...r, color: RARITY_TIER_HEX[r.tier] ?? "#94a3b8" }));
  const totalRarity = rarity.reduce((a, r) => a + r.cnt, 0);

  return (
    <div className="space-y-6">
      {/* headline tiles */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8">
        <Tile icon={<Trophy size={15} />} label="Unlocked" value={num("unlocked").toLocaleString()} />
        <Tile icon={<Lock size={15} />} label="Locked" value={num("locked").toLocaleString()} />
        <Tile icon={<Gamepad2 size={15} />} label="Games" value={num("games_total").toLocaleString()} />
        <Tile icon={<Crown size={15} />} label="Mastered" value={num("mastered").toLocaleString()} />
        <Tile icon={<CheckCircle2 size={15} />} label="Finished 80%+" value={num("finished").toLocaleString()} />
        <Tile icon={<Percent size={15} />} label="Avg completion" value={`${g.avg_completion ?? 0}%`} />
        <Tile icon={<Percent size={15} />} label="Overall" value={`${g.absolute_completion ?? 0}%`} />
        <Tile icon={<Flame size={15} />} label="Best streak" value={`${num("best_streak_days")}d`} />
      </div>

      {/* quick wins */}
      {quickWins && quickWins.length > 0 && (
        <div className="rounded-card border border-line bg-ink-850 p-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-200">
            <Zap size={15} className="text-faint" /> Quick wins
            <span className="font-normal text-faint">— closest to done</span>
          </div>
          <div className="space-y-2">
            {quickWins.map((g) => (
              <button
                key={g.platform_game_id}
                onClick={() => navigate(`/games/${g.platform_game_id}`)}
                className="flex w-full items-center gap-3 rounded-lg bg-ink-800 px-3 py-2 text-left transition hover:bg-ink-700"
              >
                {g.icon_url ? (
                  <img src={g.icon_url} alt="" className="h-8 w-8 shrink-0 rounded" />
                ) : (
                  <div className="h-8 w-8 shrink-0 rounded bg-ink-700" />
                )}
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-slate-100">{g.name}</div>
                  <div className="mt-1 flex items-center gap-2">
                    <div className="h-1.5 max-w-40 flex-1 overflow-hidden rounded-full bg-ink-900/80">
                      <div className="h-full rounded-full bg-accent-soft" style={{ width: `${g.completion_pct}%` }} />
                    </div>
                    <span className="shrink-0 text-[11px] text-muted">{platformLabel(g.platform)}</span>
                  </div>
                </div>
                <div className="shrink-0 text-right text-xs font-semibold text-slate-200">
                  {g.remaining} left
                  <div className="font-normal text-faint">{Math.round(g.completion_pct)}%</div>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* chase list */}
      {chaseList && chaseList.length > 0 && (
        <div className="rounded-card border border-line bg-ink-850 p-4">
          <div className="mb-3 flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
              <Target size={15} className="text-faint" /> Chase list
              <span className="font-normal text-faint">— rarest locked, in what you're playing now</span>
            </div>
            <button
              onClick={() => navigate("/?tab=achievements&unlocked=false&sort=rarity")}
              className="shrink-0 text-xs text-muted transition hover:text-slate-200"
            >
              See rarest locked in your whole library →
            </button>
          </div>
          <div className="space-y-2">
            {chaseList.map((a) => (
              <button
                key={`${a.platform_game_id}-${a.platform_ach_id}`}
                onClick={() => navigate(`/games/${a.platform_game_id}`)}
                className="flex w-full items-center gap-3 rounded-lg bg-ink-800 px-3 py-2 text-left transition hover:bg-ink-700"
              >
                {a.icon_url ? (
                  <img src={a.icon_url} alt="" className="h-8 w-8 shrink-0 rounded grayscale" />
                ) : (
                  <div className="h-8 w-8 shrink-0 rounded bg-ink-700" />
                )}
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-slate-100">{a.name}</div>
                  <div className="truncate text-xs text-muted">
                    {a.game_name} · {platformLabel(a.platform)}
                  </div>
                </div>
                {a.rarity_pct != null && (
                  <div className={`shrink-0 text-xs font-semibold ${RARITY_TIER_CLASS[rarityTier(a.rarity_pct)]}`}>
                    {a.rarity_pct}%
                  </div>
                )}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* records */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Record
          label="Best day"
          value={`${num("daily_max").toLocaleString()} achievements`}
          sub={fmtDate(g.best_day as string) ?? undefined}
        />
        <Record
          label="Best month"
          value={`${num("best_month_cnt").toLocaleString()} achievements`}
          sub={g.best_month ? String(g.best_month).slice(0, 7) : undefined}
        />
        <Record
          label="Backlog"
          value={`${num("active_games").toLocaleString()} active`}
          sub={`${num("untouched_games").toLocaleString()} untouched`}
        />
        <Record
          label="Longest streak"
          value={`${num("best_streak_days")} days`}
          sub={
            g.best_streak_start && g.best_streak_end
              ? `${fmtDate(g.best_streak_start as string)} – ${fmtDate(g.best_streak_end as string)}`
              : undefined
          }
        />
      </div>

      {/* on this day */}
      {stats.on_this_day.length > 0 && (
        <div className="rounded-card border border-line bg-ink-850 p-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-200">
            <Sparkles size={15} className="text-faint" /> On this day
          </div>
          <div className="space-y-2">
            {stats.on_this_day.map((e, i) => (
              <div key={i} className="flex items-center gap-3 rounded-lg bg-ink-800 px-3 py-2">
                {e.icon_url ? (
                  <img src={e.icon_url} alt="" className="h-8 w-8 shrink-0 rounded" />
                ) : (
                  <div className="h-8 w-8 shrink-0 rounded bg-ink-700" />
                )}
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-slate-100">{e.achievement_name}</div>
                  <div className="truncate text-xs text-muted">
                    {e.game_name} · {platformLabel(e.platform)}
                  </div>
                </div>
                <div className="shrink-0 text-xs text-faint">
                  {e.years_ago} {e.years_ago === 1 ? "year" : "years"} ago
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* progression */}
      <div className="rounded-card border border-line bg-ink-850 p-4">
        <div className="mb-4 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
            <CalendarDays size={15} className="text-faint" /> Achievements over time
          </div>
          <select
            value={year}
            onChange={(e) => setYear(e.target.value === "all" ? "all" : Number(e.target.value))}
            className="rounded-lg border border-line bg-ink-800 px-2 py-1 text-xs text-slate-200"
          >
            <option value="all">All time</option>
            {stats.progression_years.map((y) => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
        </div>
        <ResponsiveContainer width="100%" height={260}>
          <AreaChart data={achievementsChart}>
            <defs>
              <linearGradient id="grad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#5b8cff" stopOpacity={0.5} />
                <stop offset="100%" stopColor="#5b8cff" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#232c42" />
            <XAxis dataKey="label" stroke="#4d5a75" fontSize={11} />
            <YAxis stroke="#4d5a75" fontSize={11} allowDecimals={false} />
            <Tooltip contentStyle={CHART_TOOLTIP} />
            <Area type="monotone" dataKey="value" stroke="#5b8cff" fill="url(#grad)" strokeWidth={2} />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* points progression */}
      <div className="rounded-card border border-line bg-ink-850 p-4">
        <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-slate-200">
          <Trophy size={15} className="text-faint" /> Points {year === "all" ? "over time" : `earned in ${year}`}
        </div>
        <ResponsiveContainer width="100%" height={220}>
          <AreaChart data={pointsChart}>
            <defs>
              <linearGradient id="gradPts" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#f0b429" stopOpacity={0.5} />
                <stop offset="100%" stopColor="#f0b429" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#232c42" />
            <XAxis dataKey="label" stroke="#4d5a75" fontSize={11} />
            <YAxis stroke="#4d5a75" fontSize={11} allowDecimals={false} />
            <Tooltip contentStyle={CHART_TOOLTIP} />
            <Area type="monotone" dataKey="value" stroke="#f0b429" fill="url(#gradPts)" strokeWidth={2} />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* rarity + completion distribution */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <div className="rounded-card border border-line bg-ink-850 p-4">
          <div className="mb-4 text-sm font-semibold text-slate-200">Unlocked by rarity</div>
          {totalRarity === 0 ? (
            <div className="py-8 text-center text-sm text-muted">No rarity data yet.</div>
          ) : (
            <div className="space-y-3">
              {rarity.map((r) => (
                <div key={r.tier}>
                  <div className="mb-1 flex items-center justify-between text-xs">
                    <span style={{ color: r.color }} className="font-medium">{r.tier}</span>
                    <span className="tabular-nums text-muted">
                      {r.cnt.toLocaleString()} ({Math.round((r.cnt / totalRarity) * 100)}%)
                    </span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-ink-700">
                    <div
                      className="h-full rounded-full"
                      style={{ width: `${(r.cnt / totalRarity) * 100}%`, background: r.color }}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="rounded-card border border-line bg-ink-850 p-4">
          <div className="mb-4 text-sm font-semibold text-slate-200">Games by completion</div>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={stats.completion_dist}>
              <CartesianGrid strokeDasharray="3 3" stroke="#232c42" />
              <XAxis dataKey="bracket" stroke="#4d5a75" fontSize={11} />
              <YAxis stroke="#4d5a75" fontSize={11} allowDecimals={false} />
              <Tooltip cursor={{ fill: "#161d2e" }} contentStyle={CHART_TOOLTIP} />
              <Bar dataKey="cnt" fill="#5b8cff" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* platform comparison */}
      <div className="rounded-card border border-line bg-ink-850 p-4">
        <div className="mb-4 text-sm font-semibold text-slate-200">Achievements by platform</div>
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={platforms}>
            <CartesianGrid strokeDasharray="3 3" stroke="#232c42" />
            <XAxis dataKey="name" stroke="#4d5a75" fontSize={11} />
            <YAxis stroke="#4d5a75" fontSize={11} />
            <Tooltip cursor={{ fill: "#161d2e" }} contentStyle={CHART_TOOLTIP} />
            <Bar dataKey="earned" radius={[4, 4, 0, 0]}>
              {platforms.map((_, i) => (
                <Cell key={i} fill={PLATFORM_BAR_COLORS[i % PLATFORM_BAR_COLORS.length]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
