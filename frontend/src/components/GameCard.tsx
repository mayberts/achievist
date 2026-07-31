import { Trophy, Clock, Calendar } from "lucide-react";
import type { Game } from "../types";
import { fmtPlaytime, fmtDate } from "../lib/format";
import { PlatformBadge } from "./PlatformBadge";

function banner(g: Game): string | null {
  return g.sgdb_cover_url || g.igdb_cover_url || g.icon_url || null;
}

export function GameCard({ game, onClick }: { game: Game; onClick?: () => void }) {
  const art = banner(game);
  const pct = Math.round(game.completion_pct ?? 0);
  const playtime = fmtPlaytime(game.playtime_minutes);
  const played = fmtDate(game.last_played_at);
  const tag =
    pct >= 100 ? { label: "Mastered", cls: "bg-accent/20 text-accent" } :
    pct >= 80 ? { label: "Finished", cls: "bg-good/15 text-good" } :
    null;

  return (
    <button
      onClick={onClick}
      className="group relative flex w-full overflow-hidden rounded-card border border-line bg-ink-850 text-left transition hover:border-ink-600 hover:bg-ink-800"
    >
      {/* faded banner backdrop */}
      {art && (
        <div
          className="pointer-events-none absolute inset-0 bg-cover bg-center opacity-[0.12] transition-opacity group-hover:opacity-20"
          style={{ backgroundImage: `url(${art})` }}
        />
      )}
      <div className="absolute inset-0 bg-gradient-to-r from-ink-850 via-ink-850/85 to-transparent" />

      {/* thumbnail */}
      <div className="relative z-10 flex-shrink-0 p-3">
        <div className="h-16 w-28 overflow-hidden rounded-md bg-ink-900 ring-1 ring-black/40">
          {art ? (
            <img src={art} alt="" className="h-full w-full object-cover" loading="lazy" />
          ) : (
            <div className="flex h-full w-full items-center justify-center text-faint">
              <Trophy size={18} />
            </div>
          )}
        </div>
      </div>

      {/* content */}
      <div className="relative z-10 min-w-0 flex-1 py-3 pr-3">
        <div className="flex items-start justify-between gap-2">
          <h3 className="truncate text-[15px] font-semibold text-slate-100">{game.name}</h3>
          {tag && (
            <span className={`flex-shrink-0 rounded-md px-2 py-0.5 text-[10px] font-semibold ${tag.cls}`}>
              {tag.label}
            </span>
          )}
        </div>

        <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-muted">
          <span className="inline-flex items-center gap-1">
            <Trophy size={12} className="text-faint" />
            {game.earned_achievements} / {game.total_achievements}
          </span>
          {playtime && (
            <span className="inline-flex items-center gap-1">
              <Clock size={12} className="text-faint" />
              {playtime}
            </span>
          )}
          {played && (
            <span className="inline-flex items-center gap-1">
              <Calendar size={12} className="text-faint" />
              {played}
            </span>
          )}
        </div>

        {/* progress */}
        <div className="mt-2.5 flex items-center gap-2">
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-ink-700">
            <div
              className={`h-full rounded-full ${pct >= 100 ? "bg-accent" : "bg-accent-soft"}`}
              style={{ width: `${pct}%` }}
            />
          </div>
          <span className="w-9 text-right text-[11px] font-medium tabular-nums text-muted">{pct}%</span>
        </div>

        <div className="mt-2.5">
          <PlatformBadge platform={game.platform} />
        </div>
      </div>
    </button>
  );
}
