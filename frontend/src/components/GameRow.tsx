import { Trophy, Clock, Hourglass } from "lucide-react";
import type { Game } from "../types";
import { fmtPlaytime, fmtDate, fmtHours } from "../lib/format";
import { PlatformBadge } from "./PlatformBadge";

function banner(g: Game): string | null {
  return g.sgdb_cover_url || g.igdb_cover_url || g.icon_url || null;
}

export function GameRow({
  game,
  onClick,
  showRemaining,
}: {
  game: Game;
  onClick?: () => void;
  // See GameCard: only shown when the list is ordered by time-to-100%.
  showRemaining?: boolean;
}) {
  const art = banner(game);
  const pct = Math.round(game.completion_pct ?? 0);
  const playtime = fmtPlaytime(game.playtime_minutes);
  const played = fmtDate(game.last_played_at);
  const remaining = showRemaining ? fmtHours(game.hltb_remaining) : null;

  return (
    <button
      onClick={onClick}
      className="group flex w-full items-center gap-3 rounded-lg border border-line bg-ink-850 px-3 py-2 text-left transition hover:border-ink-600 hover:bg-ink-800"
    >
      <div className="h-9 w-16 flex-shrink-0 overflow-hidden rounded bg-ink-900">
        {art ? (
          <img src={art} alt="" className="h-full w-full object-cover" loading="lazy" />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-faint">
            <Trophy size={13} />
          </div>
        )}
      </div>

      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-semibold text-slate-100">{game.name}</div>
        <div className="mt-0.5 flex items-center gap-3 text-[11px] text-muted">
          <span className="inline-flex items-center gap-1">
            <Trophy size={11} className="text-faint" />
            {game.earned_achievements}/{game.total_achievements}
          </span>
          {playtime && (
            <span className="inline-flex items-center gap-1">
              <Clock size={11} className="text-faint" />
              {playtime}
            </span>
          )}
          {played && <span className="hidden sm:inline text-faint">{played}</span>}
          {remaining && (
            <span className="inline-flex items-center gap-1 font-medium text-slate-300">
              <Hourglass size={11} className="text-faint" />
              ~{remaining} to 100%
            </span>
          )}
        </div>
      </div>

      <div className="hidden w-40 items-center gap-2 md:flex">
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-ink-700">
          <div
            className={`h-full rounded-full ${pct >= 100 ? "bg-accent" : "bg-accent-soft"}`}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      <span className="w-9 flex-shrink-0 text-right text-xs font-medium tabular-nums text-muted">{pct}%</span>

      <div className="hidden flex-shrink-0 sm:block">
        <PlatformBadge platform={game.platform} />
      </div>
    </button>
  );
}
