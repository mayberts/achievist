import { Trophy, Gamepad2, Crown, Clock, Target, User } from "lucide-react";
import type { Summary } from "../types";
import { fmtNum, fmtPlaytime } from "../lib/format";
import { platformLabel } from "../lib/platforms";

function Stat({ icon, value, title }: { icon: React.ReactNode; value: string; title: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-slate-200" title={title}>
      <span className="text-faint">{icon}</span>
      <span className="font-semibold tabular-nums">{value}</span>
    </span>
  );
}

export function SummaryBar({ summary }: { summary: Summary }) {
  const totalPlaytime = summary.by_platform.reduce(
    (acc, p) => acc + (p.total_playtime_minutes ?? 0),
    0,
  );
  const platforms = [...summary.by_platform].sort((a, b) => b.earned - a.earned);

  return (
    <div className="flex items-center gap-4 rounded-card border border-line bg-ink-850 p-4">
      <div className="flex h-16 w-16 flex-shrink-0 items-center justify-center rounded-full bg-ink-700 text-muted">
        <User size={30} />
      </div>
      <div className="min-w-0">
        <div className="text-lg font-bold text-slate-100">Pantheon</div>
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm">
          <Stat icon={<Trophy size={15} />} value={fmtNum(summary.total_earned)} title="Achievements earned" />
          <span className="h-4 w-px bg-line" />
          <Stat icon={<Target size={15} />} value={`${summary.overall_pct}%`} title="Overall completion" />
          <span className="h-4 w-px bg-line" />
          <Stat icon={<Gamepad2 size={15} />} value={fmtNum(summary.total_games)} title="Games" />
          <span className="h-4 w-px bg-line" />
          <Stat icon={<Crown size={15} />} value={fmtNum(summary.perfect_games)} title="Perfect games" />
          <span className="h-4 w-px bg-line" />
          <Stat icon={<Clock size={15} />} value={fmtPlaytime(totalPlaytime) ?? "0h"} title="Total playtime" />
        </div>
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {platforms.map((p) => (
            <span
              key={p.platform}
              className="rounded-md border border-line bg-ink-800 px-2 py-0.5 text-[11px] text-muted"
              title={`${platformLabel(p.platform)} — ${fmtNum(p.earned)} earned`}
            >
              {platformLabel(p.platform)} <span className="text-faint tabular-nums">{fmtNum(p.earned)}</span>
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
