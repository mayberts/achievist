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
  CartesianGrid,
} from "recharts";
import { platformLabel } from "../lib/platforms";

interface Stats {
  general: Record<string, number | string | null>;
  rarity: { tier: string; cnt: number }[];
  completion_dist: { bracket: string; cnt: number }[];
  platforms: { platform: string; earned: number }[];
  progression: { month: string; total: number }[];
}

function Tile({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-card border border-line bg-ink-850 p-4">
      <div className="text-2xl font-bold tabular-nums text-slate-100">{value}</div>
      <div className="mt-1 text-xs uppercase tracking-wide text-faint">{label}</div>
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
  const progression = stats.progression.map((p) => ({ ...p, label: p.month.slice(0, 7) }));
  const platforms = stats.platforms.map((p) => ({ name: platformLabel(p.platform), earned: p.earned }));

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Tile label="Unlocked" value={Number(g.unlocked ?? 0).toLocaleString()} />
        <Tile label="Locked" value={Number(g.locked ?? 0).toLocaleString()} />
        <Tile label="Games" value={Number(g.games_total ?? 0).toLocaleString()} />
        <Tile label="Mastered" value={Number(g.mastered ?? 0).toLocaleString()} />
        <Tile label="Avg completion" value={`${g.avg_completion ?? 0}%`} />
        <Tile label="Best streak" value={`${g.best_streak_days ?? 0}d`} />
      </div>

      <div className="rounded-card border border-line bg-ink-850 p-4">
        <div className="mb-4 text-sm font-semibold text-slate-200">Achievements over time</div>
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
            <Tooltip contentStyle={{ background: "#121826", border: "1px solid #232c42", borderRadius: 8 }} />
            <Area type="monotone" dataKey="total" stroke="#5b8cff" fill="url(#grad)" strokeWidth={2} />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <div className="rounded-card border border-line bg-ink-850 p-4">
        <div className="mb-4 text-sm font-semibold text-slate-200">Achievements by platform</div>
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={platforms}>
            <CartesianGrid strokeDasharray="3 3" stroke="#232c42" />
            <XAxis dataKey="name" stroke="#4d5a75" fontSize={11} />
            <YAxis stroke="#4d5a75" fontSize={11} />
            <Tooltip
              cursor={{ fill: "#161d2e" }}
              contentStyle={{ background: "#121826", border: "1px solid #232c42", borderRadius: 8 }}
            />
            <Bar dataKey="earned" fill="#5b8cff" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
