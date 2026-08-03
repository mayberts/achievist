import { useEffect, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Trophy, Clock, Calendar, ExternalLink, Lock, ImageUp } from "lucide-react";
import { api } from "../api";
import type { Achievement, GameDetail } from "../types";
import { fmtPlaytime, fmtDate, fmtNum } from "../lib/format";
import { PlatformBadge } from "../components/PlatformBadge";
import { PLATFORM_META } from "../lib/platforms";
import { RARITY_TIER_CLASS, rarityTier } from "../lib/rarity";
import { ChangeCoverModal } from "../components/ChangeCoverModal";

function banner(g: GameDetail): string | null {
  return g.sgdb_cover_url || g.igdb_cover_url || g.icon_url || null;
}

function hltb(h: number | null): string | null {
  if (!h || h <= 0) return null;
  return `${h}h`;
}

export function GameDetailPage() {
  const { id } = useParams();
  const gameId = Number(id);
  const navigate = useNavigate();
  const location = useLocation();
  const [game, setGame] = useState<GameDetail | null>(null);
  const [achs, setAchs] = useState<Achievement[] | null>(null);
  const [changingCover, setChangingCover] = useState(false);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    setGame(null);
    setAchs(null);
    setNotFound(false);
    api.gameDetail(gameId).then(setGame).catch(() => setNotFound(true));
    api.gameAchievements(gameId).then(setAchs).catch(() => setAchs([]));
  }, [gameId]);

  function goBack() {
    // Prefer real browser back (preserves scroll position / filters on the
    // page that linked here); fall back to the library if we were opened
    // directly (e.g. a bookmark or shared link — react-router gives the
    // initial entry a "default" key, meaning there's no in-app history).
    if (location.key !== "default") navigate(-1);
    else navigate("/");
  }

  if (notFound) {
    return (
      <div className="py-16 text-center">
        <div className="text-muted">Game not found.</div>
        <button
          onClick={goBack}
          className="mt-3 inline-flex items-center gap-1.5 text-sm text-accent hover:underline"
        >
          <ArrowLeft size={14} /> Back
        </button>
      </div>
    );
  }

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
    <div>
      <button
        onClick={goBack}
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted transition hover:text-slate-200"
      >
        <ArrowLeft size={15} /> Back
      </button>

      <div className="overflow-hidden rounded-card border border-line bg-ink-850 shadow-2xl">
        {/* header banner */}
        <div className="relative">
          {art && (
            <div
              className="absolute inset-0 bg-cover bg-center opacity-25"
              style={{ backgroundImage: `url(${art})` }}
            />
          )}
          <div className="absolute inset-0 bg-gradient-to-t from-ink-850 to-ink-850/40" />
          <div className="relative flex flex-col gap-4 p-4 sm:flex-row sm:p-5">
            {art && (
              <img
                src={art}
                alt=""
                className="h-32 w-full flex-shrink-0 rounded-md object-cover ring-1 ring-black/40 sm:h-24 sm:w-40"
              />
            )}
            <div className="min-w-0 flex-1">
              <h2 className="text-lg font-bold text-slate-100 sm:text-xl">{game?.name ?? "…"}</h2>
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
                {game && (
                  <button
                    onClick={() => setChangingCover(true)}
                    className="ml-auto inline-flex items-center gap-1 rounded-lg border border-line bg-ink-800/80 px-2 py-1 text-xs text-slate-200 transition hover:bg-ink-700"
                  >
                    <ImageUp size={12} /> Change Cover
                  </button>
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
        <div className="p-3">
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
                        <div className={`text-xs font-semibold ${RARITY_TIER_CLASS[rarityTier(a.rarity_pct)]}`}>
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

      {changingCover && game && (
        <ChangeCoverModal
          gameId={game.platform_game_id}
          initialQuery={game.name}
          onClose={() => setChangingCover(false)}
          onChanged={(url) => setGame((prev) => (prev ? { ...prev, sgdb_cover_url: url || null } : prev))}
        />
      )}
    </div>
  );
}
