import { useEffect, useState } from "react";
import { X, Trophy, Clock, Calendar, ExternalLink, Lock } from "lucide-react";
import { api } from "../api";
import type { Achievement, GameDetail } from "../types";
import { fmtPlaytime, fmtDate, fmtNum } from "../lib/format";
import { PlatformBadge } from "./PlatformBadge";
import { PLATFORM_META } from "../lib/platforms";

function banner(g: GameDetail): string | null {
  return g.sgdb_cover_url || g.igdb_cover_url || g.icon_url || null;
}

function hltb(h: number | null): string | null {
  if (!h || h <= 0) return null;
  return `${h}h`;
}

const RARITY_COLOR: Record<string, string> = {
  Legendary: "text-amber-400",
  Epic: "text-fuchsia-400",
  Rare: "text-sky-400",
  Uncommon: "text-emerald-400",
  Common: "text-slate-400",
};

export function GameDetailModal({ gameId, onClose }: { gameId: number; onClose: () => void }) {
  const [game, setGame] = useState<GameDetail | null>(null);
  const [achs, setAchs] = useState<Achievement[] | null>(null);

  useEffect(() => {
    setGame(null);
    setAchs(null);
    api.gameDetail(gameId).then(setGame).catch(() => setGame(null));
    api.gameAchievements(gameId).then(setAchs).catch(() => setAchs([]));
  }, [gameId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const art = game ? banner(game) : null;
  const pct = Math.round(game?.completion_pct ?? 0);
  const storeUrl =
    game && PLATFORM_META[game.platform]?.storeUrl
      ? PLATFORM_META[game.platform].storeUrl!(game)
      : null;

  const hltbParts = game
    ? [
        ["Main", hltb(game.hltb_main)],
        ["Main + Extra", hltb(game.hltb_extra)],
        ["Completionist", hltb(game.hltb_complete)],
      ].filter(([, v]) => v)
    : [];

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4" onClick={onClose}>
      <div
        className="my-8 w-full max-w-2xl overflow-hidden rounded-card border border-line bg-ink-850 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* header banner */}
        <div className="relative">
          {art && (
            <div
              className="absolute inset-0 bg-cover bg-center opacity-25"
              style={{ backgroundImage: `url(${art})` }}
            />
          )}
          <div className="absolute inset-0 bg-gradient-to-t from-ink-850 to-ink-850/40" />
          <button
            onClick={onClose}
            className="absolute right-3 top-3 z-10 rounded-lg bg-black/40 p-1.5 text-slate-200 hover:bg-black/60"
          >
            <X size={18} />
          </button>
          <div className="relative flex gap-4 p-5">
            {art && (
              <img src={art} alt="" className="h-24 w-40 flex-shrink-0 rounded-md object-cover ring-1 ring-black/40" />
            )}
            <div className="min-w-0 flex-1">
              <h2 className="text-xl font-bold text-slate-100">{game?.name ?? "…"}</h2>
              <div className="mt-2 flex flex-wrap items-center gap-3 text-sm text-muted">
                <span className="inline-flex items-center gap-1">
                  <Trophy size={14} className="text-faint" />
                  {game?.earned_achievements ?? 0} / {game?.total_achievements ?? 0}
                </span>
                {game && fmtPlaytime(game.playtime_minutes) && (
                  <span className="inline-flex items-center gap-1">
                    <Clock size={14} className="text-faint" />
                    {fmtPlaytime(game.playtime_minutes)}
                  </span>
                )}
                {game && fmtDate(game.last_played_at) && (
                  <span className="inline-flex items-center gap-1">
                    <Calendar size={14} className="text-faint" />
                    {fmtDate(game.last_played_at)}
                  </span>
                )}
              </div>
              <div className="mt-3 flex items-center gap-2">
                {game && <PlatformBadge platform={game.platform} />}
                {game && game.total_points > 0 && (
                  <span className="text-xs text-muted">{fmtNum(game.total_points)} pts</span>
                )}
                {storeUrl && (
                  <a
                    href={storeUrl}
                    target="_blank"
                    rel="noopener"
                    className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
                  >
                    Store <ExternalLink size={11} />
                  </a>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* progress + hltb */}
        <div className="border-b border-line px-5 pb-4">
          <div className="flex items-center gap-3">
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-ink-700">
              <div
                className={`h-full rounded-full ${pct >= 100 ? "bg-accent" : "bg-accent-soft"}`}
                style={{ width: `${pct}%` }}
              />
            </div>
            <span className="text-sm font-semibold tabular-nums text-slate-200">{pct}%</span>
          </div>
          {hltbParts.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-4 text-xs text-muted">
              {hltbParts.map(([label, v]) => (
                <span key={label}>
                  <span className="text-faint">{label}:</span> {v}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* achievements */}
        <div className="max-h-[50vh] overflow-y-auto p-3">
          {achs === null ? (
            <div className="py-10 text-center text-muted">Loading achievements…</div>
          ) : achs.length === 0 ? (
            <div className="py-10 text-center text-muted">No achievement details stored.</div>
          ) : (
            <ul className="space-y-1">
              {achs.map((a) => {
                const unlocked = !!a.unlocked;
                return (
                  <li
                    key={a.platform_ach_id}
                    className={`flex items-center gap-3 rounded-lg p-2 ${unlocked ? "bg-ink-800/60" : "opacity-60"}`}
                  >
                    <div className="relative h-11 w-11 flex-shrink-0 overflow-hidden rounded-md bg-ink-900">
                      {a.icon_url ? (
                        <img
                          src={a.icon_url}
                          alt=""
                          className={`h-full w-full object-cover ${unlocked ? "" : "grayscale"}`}
                          loading="lazy"
                        />
                      ) : (
                        <div className="flex h-full w-full items-center justify-center text-faint">
                          <Trophy size={16} />
                        </div>
                      )}
                      {!unlocked && (
                        <div className="absolute inset-0 flex items-center justify-center bg-black/40">
                          <Lock size={13} className="text-slate-300" />
                        </div>
                      )}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium text-slate-100">{a.name || a.platform_ach_id}</div>
                      {a.description && <div className="truncate text-xs text-muted">{a.description}</div>}
                    </div>
                    <div className="flex-shrink-0 text-right">
                      {a.rarity_pct != null && (
                        <div className={`text-xs font-semibold ${RARITY_COLOR[rarityTier(a.rarity_pct)]}`}>
                          {a.rarity_pct}%
                        </div>
                      )}
                      {unlocked && fmtDate(a.unlocked_at) && (
                        <div className="text-[11px] text-faint">{fmtDate(a.unlocked_at)}</div>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

function rarityTier(pct: number): string {
  if (pct <= 1) return "Legendary";
  if (pct <= 5) return "Epic";
  if (pct <= 20) return "Rare";
  if (pct <= 50) return "Uncommon";
  return "Common";
}
