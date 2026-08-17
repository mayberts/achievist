import { Trophy, Clock, Calendar, Hourglass } from "lucide-react";
import type { Game } from "../types";
import { fmtPlaytime, fmtDate, fmtHours } from "../lib/format";
import { PlatformBadge } from "./PlatformBadge";

// Only sgdb_cover_url is genuine landscape art (SGDB's 460x215/920x430 grids,
// close to this card's aspect ratio). igdb_cover_url is IGDB's t_cover_big_2x
// (portrait box art) and icon_url is a small square Steam icon — center-cropping
// either of those to fill a wide card just slices through the artwork/logo.
function landscapeArt(g: Game): string | null {
  return g.sgdb_cover_url || null;
}

function fallbackArt(g: Game): string | null {
  return g.igdb_cover_url || g.icon_url || null;
}

export function GameCard({
  game,
  onClick,
  showRemaining,
}: {
  game: Game;
  onClick?: () => void;
  // Surfaces the estimated hours left to 100%. Only shown when that's what
  // the list is ordered by, so the ordering is legible instead of looking
  // arbitrary — it's noise on every other sort.
  showRemaining?: boolean;
}) {
  const wide = landscapeArt(game);
  const fallback = !wide ? fallbackArt(game) : null;
  const pct = Math.round(game.completion_pct ?? 0);
  const playtime = fmtPlaytime(game.playtime_minutes);
  const played = fmtDate(game.last_played_at);
  const remaining = showRemaining ? fmtHours(game.hltb_remaining) : null;
  const tag =
    pct >= 100 ? { label: "Mastered", cls: "bg-accent/20 text-accent" } :
    pct >= 80 ? { label: "Finished", cls: "bg-good/15 text-good" } :
    null;

  return (
    <button
      onClick={onClick}
      className="group relative flex h-32 w-full overflow-hidden rounded-card border border-line bg-ink-850 text-left transition hover:border-ink-600"
    >
      {wide ? (
        <>
          {/* full-bleed cover art, sharp — a left-side gradient (in the app's
              own ink colors) carries the text instead of blurring the art */}
          <img
            src={wide}
            alt=""
            className="pointer-events-none absolute inset-0 h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.03]"
            loading="lazy"
          />
          <div className="absolute inset-0 bg-gradient-to-r from-ink-850 from-10% via-ink-850/85 via-45% to-transparent to-[90%]" />
          <div className="absolute inset-0 bg-gradient-to-t from-ink-850/40 to-transparent" />
        </>
      ) : fallback ? (
        <>
          {/* no landscape art available — this source is portrait/square, so
              blur it into a soft ambient backdrop instead of hard-cropping it */}
          <div
            className="pointer-events-none absolute inset-0 scale-110 bg-cover bg-center opacity-[0.16] blur-md transition-opacity duration-300 group-hover:opacity-[0.24]"
            style={{ backgroundImage: `url(${fallback})` }}
          />
          <div className="absolute inset-0 bg-gradient-to-r from-ink-850 via-ink-850/70 to-ink-850/95" />
        </>
      ) : (
        <div className="absolute inset-0 flex items-center justify-center text-faint">
          <Trophy size={22} />
        </div>
      )}

      {/* on the fallback path, show the actual art crisply in a properly-fit
          box instead of only as an unrecognizable blur */}
      {fallback && (
        <div className="relative z-10 flex flex-shrink-0 items-center pl-4">
          <img
            src={fallback}
            alt=""
            className="h-24 w-16 rounded-md object-cover ring-1 ring-black/40"
            loading="lazy"
          />
        </div>
      )}

      {/* content */}
      <div className="relative z-10 flex min-w-0 flex-1 flex-col justify-center gap-1.5 px-4 py-3">
        <div className="flex items-start justify-between gap-2">
          <h3 className="truncate text-[15px] font-semibold text-slate-100 drop-shadow-sm">{game.name}</h3>
          {tag && (
            <span className={`flex-shrink-0 rounded-md px-2 py-0.5 text-[10px] font-semibold ${tag.cls}`}>
              {tag.label}
            </span>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-muted">
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
          {remaining && (
            <span className="inline-flex items-center gap-1 font-medium text-slate-300">
              <Hourglass size={12} className="text-faint" />
              ~{remaining} to 100%
            </span>
          )}
        </div>

        {/* progress */}
        <div className="flex items-center gap-2">
          <div className="h-1.5 max-w-56 flex-1 overflow-hidden rounded-full bg-ink-900/80">
            <div
              className={`h-full rounded-full ${pct >= 100 ? "bg-accent" : "bg-accent-soft"}`}
              style={{ width: `${pct}%` }}
            />
          </div>
          <span className="w-9 text-right text-[11px] font-medium tabular-nums text-muted">{pct}%</span>
        </div>

        <div>
          <PlatformBadge platform={game.platform} />
        </div>
      </div>
    </button>
  );
}
