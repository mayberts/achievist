import { useEffect, useMemo, useState } from "react";
import { Flame, Clock, Trophy } from "lucide-react";
import { api } from "../api";
import type { Activity } from "../types";
import { fmtPlaytime, fmtDate, fmtRelative } from "../lib/format";
import { PlatformBadge } from "../components/PlatformBadge";
import { GameDetailModal } from "../components/GameDetailModal";

function Heatmap({ data }: { data: { day: string; count: number }[] }) {
  const counts = useMemo(() => new Map(data.map((d) => [d.day, d.count])), [data]);

  // Build 53 week-columns ending this week, aligned to Sunday.
  const { weeks, monthLabels } = useMemo(() => {
    const today = new Date();
    const end = new Date(today);
    end.setDate(end.getDate() + (6 - end.getDay())); // Saturday of this week
    const start = new Date(end);
    start.setDate(start.getDate() - 53 * 7 + 1);
    start.setDate(start.getDate() - start.getDay()); // back to Sunday

    const weeks: { date: Date; key: string; count: number }[][] = [];
    const monthLabels: { col: number; label: string }[] = [];
    const cur = new Date(start);
    let lastMonth = -1;
    for (let w = 0; w < 54; w++) {
      const col: { date: Date; key: string; count: number }[] = [];
      for (let d = 0; d < 7; d++) {
        const key = cur.toISOString().slice(0, 10);
        col.push({ date: new Date(cur), key, count: counts.get(key) ?? 0 });
        if (d === 0 && cur.getMonth() !== lastMonth && cur <= today) {
          lastMonth = cur.getMonth();
          monthLabels.push({ col: w, label: cur.toLocaleString("en-GB", { month: "short" }) });
        }
        cur.setDate(cur.getDate() + 1);
      }
      weeks.push(col);
      if (cur > today && weeks.length >= 1) break;
    }
    return { weeks, monthLabels };
  }, [counts]);

  const color = (c: number, future: boolean) => {
    if (future) return "transparent";
    if (c === 0) return "#161d2e";
    if (c <= 2) return "#2f4a8f";
    if (c <= 5) return "#3a5bd0";
    if (c <= 10) return "#5b8cff";
    return "#8fb0ff";
  };

  const today = new Date();
  return (
    <div className="overflow-x-auto">
      <div className="inline-block">
        <div className="mb-1 flex text-[10px] text-faint" style={{ paddingLeft: 2 }}>
          {weeks.map((_, w) => {
            const m = monthLabels.find((x) => x.col === w);
            return (
              <div key={w} style={{ width: 13 }}>
                {m ? m.label : ""}
              </div>
            );
          })}
        </div>
        <div className="flex gap-[3px]">
          {weeks.map((col, w) => (
            <div key={w} className="flex flex-col gap-[3px]">
              {col.map((cell) => {
                const future = cell.date > today;
                return (
                  <div
                    key={cell.key}
                    title={future ? "" : `${cell.count} on ${cell.key}`}
                    style={{ width: 10, height: 10, background: color(cell.count, future), borderRadius: 2 }}
                  />
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function StatCard({ icon, value, label, sub }: { icon: React.ReactNode; value: string; label: string; sub?: string }) {
  return (
    <div className="rounded-card border border-line bg-ink-850 p-4">
      <div className="flex items-center gap-2">
        <span className="text-warn">{icon}</span>
        <span className="text-xl font-bold text-slate-100">{value}</span>
      </div>
      <div className="mt-1 text-sm text-slate-300">{label}</div>
      {sub && <div className="mt-0.5 text-xs text-faint">{sub}</div>}
    </div>
  );
}

export function ActivityPage() {
  const [data, setData] = useState<Activity | null>(null);
  const [selected, setSelected] = useState<number | null>(null);

  useEffect(() => {
    api.activity().then(setData).catch(() => setData(null));
  }, []);

  if (!data) return <div className="py-16 text-center text-muted">Loading activity…</div>;

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard icon={<Flame size={18} />} value={`${data.current_streak}`} label="Current streak (days)" />
        <StatCard icon={<Flame size={18} />} value={`${data.longest_streak}`} label="Longest streak (days)" />
        <StatCard
          icon={<Clock size={18} />}
          value={fmtPlaytime(data.total_playtime_minutes) ?? "0h"}
          label="Total playtime"
        />
      </div>

      <div className="rounded-card border border-line bg-ink-850 p-4">
        <div className="mb-3 text-sm font-semibold text-slate-200">Unlock activity</div>
        <Heatmap data={data.heatmap} />
      </div>

      <div>
        <div className="mb-2 text-sm font-semibold text-slate-200">Recent activity</div>
        {data.feed.length === 0 ? (
          <div className="py-10 text-center text-muted">No achievement activity yet.</div>
        ) : (
          <div className="space-y-2">
            {data.feed.map((f) => (
              <button
                key={`${f.platform_game_id}-${f.day}`}
                onClick={() => setSelected(f.platform_game_id)}
                className="flex w-full items-center gap-3 rounded-card border border-line bg-ink-850 p-3 text-left transition hover:border-ink-600 hover:bg-ink-800"
              >
                <div className="h-12 w-20 flex-shrink-0 overflow-hidden rounded bg-ink-900">
                  {f.cover_url ? (
                    <img src={f.cover_url} alt="" className="h-full w-full object-cover" loading="lazy" />
                  ) : (
                    <div className="flex h-full w-full items-center justify-center text-faint">
                      <Trophy size={16} />
                    </div>
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm font-semibold text-slate-100">{f.name}</span>
                    <PlatformBadge platform={f.platform} />
                  </div>
                  <div className="mt-0.5 text-xs text-muted">
                    Earned <span className="font-semibold text-slate-300">{f.count}</span>{" "}
                    {f.count === 1 ? "achievement" : "achievements"} · {fmtRelative(f.day)}
                    <span className="text-faint"> · {fmtDate(f.day)}</span>
                  </div>
                </div>
                <div className="hidden flex-shrink-0 gap-1 sm:flex">
                  {f.icons.slice(0, 6).map((ic, i) => (
                    <img key={i} src={ic} alt="" className="h-8 w-8 rounded object-cover" loading="lazy" />
                  ))}
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      {selected !== null && <GameDetailModal gameId={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
