import { useEffect, useState } from "react";
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
import { Trophy, Lock, Gamepad2, Crown, CheckCircle2, Percent, Flame, CalendarDays } from "lucide-react";
import { platformLabel } from "../lib/platforms";
import { fmtDate } from "../lib/format";

interface Stats {
  general: Record<string, number | string | null>;
  rarity: { tier: string; cnt: number }[];
  completion_dist: { bracket: string; cnt: number }[];
  platforms: { platform: string; earned: number }[];
  progression: { month: string; total: number }[];
}

const RARITY_COLORS: Record<string, string> = {
  Legendary: "#fbbf24",
  Epic: "#e879f9",
  Rare: "#38bdf8",
  Uncommon: "#34d399",
  Common: "#94a3b8",
};

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

  useEffect(() => {
    fetch("/api/statistics").then((r) => r.json()).then(setStats).catch(() => setStats(null));
  }, []);

  if (!stats) return <div className="py-16 text-center text-muted">Loading statistics…</div>;

  const g = stats.general;
  const num = (k: string) => Number(g[k] ?? 0);
  const progression = stats.progression.map((p) => ({ ...p, label: p.month.slice(0, 7) }));
  const platforms = stats.platforms
    .map((p) => ({ name: platformLabel(p.platform), earned: p.earned }))
    .sort((a, b) => b.earned - a.earned);
  const rarity = stats.rarity.map((r) => ({ ...r, color: RARITY_COLORS[r.tier] ?? "#94a3b8" }));
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

      {/* records */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
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
          label="Longest streak"
          value={`${num("best_streak_days")} days`}
          sub={
            g.best_streak_start && g.best_streak_end
              ? `${fmtDate(g.best_streak_start as string)} – ${fmtDate(g.best_streak_end as string)}`
              : undefined
          }
        />
      </div>

      {/* progression */}
      <div className="rounded-card border border-line bg-ink-850 p-4">
        <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-slate-200">
          <CalendarDays size={15} className="text-faint" /> Achievements over time
        </div>
        <ResponsiveContainer width="100%" height={260}>
          <AreaChart data={progression}>
            <defs>
              <linearGradient id="grad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#5b8cff" stopOpacity={0.5} />
                <stop offset="100%" stopColor="#5b8cff" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#232c42" />
            <XAxis dataKey="label" stroke="#4d5a75" fontSize={11} />
            <YAxis stroke="#4d5a75" fontSize={11} />
            <Tooltip contentStyle={CHART_TOOLTIP} />
            <Area type="monotone" dataKey="total" stroke="#5b8cff" fill="url(#grad)" strokeWidth={2} />
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
