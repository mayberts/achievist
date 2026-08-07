import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Trophy, Clock, Calendar, ExternalLink, Lock, ImageUp, Search, RefreshCw } from "lucide-react";
import { api } from "../api";
import type { Achievement, GameDetail } from "../types";
import { fmtPlaytime, fmtDate, fmtNum } from "../lib/format";
import { PlatformBadge } from "../components/PlatformBadge";
import { PLATFORM_META } from "../lib/platforms";
import { RARITY_TIER_CLASS, RARITY_TIER_HEX, rarityTier } from "../lib/rarity";
import { guideSearchUrl } from "../lib/guideLink";
import { ChangeCoverModal } from "../components/ChangeCoverModal";

function banner(g: GameDetail): string | null {
  return g.sgdb_cover_url || g.igdb_cover_url || g.icon_url || null;
}

function hltb(h: number | null): string | null {
  if (!h || h <= 0) return null;
  return `${h}h`;
}

type StatusFilter = "all" | "unlocked" | "locked";
type SortKey = "default" | "name" | "rarity" | "points" | "unlocked_at";

const SORTS: { key: SortKey; label: string }[] = [
  { key: "default", label: "Default" },
  { key: "rarity", label: "Rarity (rarest first)" },
  { key: "points", label: "Points (highest first)" },
  { key: "name", label: "Name (A-Z)" },
  { key: "unlocked_at", label: "Unlock date (most recent)" },
];

export function GameDetailPage() {
  const { id } = useParams();
  const gameId = Number(id);
  const navigate = useNavigate();
  const location = useLocation();
  const [game, setGame] = useState<GameDetail | null>(null);
  const [achs, setAchs] = useState<Achievement[] | null>(null);
  const [changingCover, setChangingCover] = useState(false);
  const [notFound, setNotFound] = useState(false);

  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [sort, setSort] = useState<SortKey>("default");
  const [refreshingGuides, setRefreshingGuides] = useState(false);

  useEffect(() => {
    setGame(null);
    setAchs(null);
    setNotFound(false);
    setSearch("");
    setStatus("all");
    setSort("default");
    api.gameDetail(gameId).then(setGame).catch(() => setNotFound(true));
    api.gameAchievements(gameId).then(setAchs).catch(() => setAchs([]));
  }, [gameId]);

  async function refreshGuideLinks() {
    setRefreshingGuides(true);
    try {
      await api.refreshGuideLinks(gameId);
      const [g, a] = await Promise.all([api.gameDetail(gameId), api.gameAchievements(gameId)]);
      setGame(g);
      setAchs(a);
    } catch {
      /* best-effort — leave whatever links were already there */
    } finally {
      setRefreshingGuides(false);
    }
  }

  function goBack() {
    // Prefer real browser back (preserves scroll position / filters on the
    // page that linked here); fall back to the library if we were opened
    // directly (e.g. a bookmark or shared link — react-router gives the
    // initial entry a "default" key, meaning there's no in-app history).
    if (location.key !== "default") navigate(-1);
    else navigate("/");
  }

  const visibleAchs = useMemo(() => {
    if (!achs) return null;
    const q = search.trim().toLowerCase();
    let list = achs.filter((a) => {
      if (status === "unlocked" && !a.unlocked) return false;
      if (status === "locked" && a.unlocked) return false;
      if (q && !`${a.name ?? ""} ${a.description ?? ""}`.toLowerCase().includes(q)) return false;
      return true;
    });
    list = [...list];
    switch (sort) {
      case "name":
        list.sort((a, b) => (a.name ?? a.platform_ach_id).localeCompare(b.name ?? b.platform_ach_id));
        break;
      case "rarity":
        list.sort((a, b) => (a.rarity_pct ?? 101) - (b.rarity_pct ?? 101));
        break;
      case "points":
        list.sort((a, b) => (b.points ?? 0) - (a.points ?? 0));
        break;
      case "unlocked_at":
        list.sort((a, b) => (b.unlocked_at ?? "").localeCompare(a.unlocked_at ?? ""));
        break;
    }
    return list;
  }, [achs, search, status, sort]);

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
      {/* full-page backdrop, pinned behind the header/nav too (they have no
          opaque background of their own) via a negative z-index rather than
          relying on DOM order */}
      {art && (
        <>
          <div
            className="fixed inset-0 -z-10 bg-cover bg-center opacity-70"
            style={{ backgroundImage: `url(${art})` }}
          />
          <div className="fixed inset-0 -z-10 bg-gradient-to-t from-ink-950 via-ink-950/70 to-ink-950/30" />
        </>
      )}

      <button
        onClick={goBack}
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted transition hover:text-slate-200"
      >
        <ArrowLeft size={15} /> Back
      </button>

      <div className="overflow-hidden rounded-card border border-line/50 bg-ink-850/45 shadow-2xl backdrop-blur-md">
        {/* header banner */}
        <div className="relative">
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

        {/* progress */}
        <div className="border-b border-line/50 px-5 pb-4">
          <div className="flex items-center gap-3">
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-ink-700">
              <div
                className={`h-full rounded-full ${pct >= 100 ? "bg-accent" : "bg-accent-soft"}`}
                style={{ width: `${pct}%` }}
              />
            </div>
            <span className="text-sm font-semibold tabular-nums text-slate-200">{pct}%</span>
          </div>
        </div>

        {/* main content: achievements + sidebar */}
        <div className="grid grid-cols-1 gap-4 p-3 lg:grid-cols-[1fr_260px]">
          <div className="min-w-0">
            {/* toolbar */}
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <div className="flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-line/50 bg-ink-900/50 px-3 py-2 backdrop-blur-sm">
                <Search size={14} className="flex-shrink-0 text-faint" />
                <input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search achievements…"
                  className="w-full min-w-0 bg-transparent text-sm text-slate-100 outline-none placeholder:text-faint"
                />
              </div>
              <select
                value={status}
                onChange={(e) => setStatus(e.target.value as StatusFilter)}
                className="rounded-lg border border-line/50 bg-ink-900/50 px-3 py-2 text-sm text-slate-200 outline-none backdrop-blur-sm"
              >
                <option value="all">All achievements</option>
                <option value="unlocked">Unlocked</option>
                <option value="locked">Locked</option>
              </select>
              <select
                value={sort}
                onChange={(e) => setSort(e.target.value as SortKey)}
                className="rounded-lg border border-line/50 bg-ink-900/50 px-3 py-2 text-sm text-slate-200 outline-none backdrop-blur-sm"
              >
                {SORTS.map((s) => (
                  <option key={s.key} value={s.key}>{s.label}</option>
                ))}
              </select>
              {game && (game.platform === "steam" || game.platform === "xbox") && (
                <button
                  onClick={refreshGuideLinks}
                  disabled={refreshingGuides}
                  title="Re-check achievement guide links"
                  className="inline-flex items-center gap-1.5 rounded-lg border border-line/50 bg-ink-900/50 px-3 py-2 text-sm text-muted backdrop-blur-sm transition hover:text-slate-200 disabled:opacity-50"
                >
                  <RefreshCw size={14} className={refreshingGuides ? "animate-spin" : ""} />
                  Guide links
                </button>
              )}
            </div>

            {achs === null ? (
              <div className="py-10 text-center text-muted">Loading achievements…</div>
            ) : achs.length === 0 ? (
              <div className="py-10 text-center text-muted">No achievement details stored.</div>
            ) : visibleAchs && visibleAchs.length === 0 ? (
              <div className="py-10 text-center text-muted">No achievements match your filters.</div>
            ) : (
              <ul className="space-y-1">
                {visibleAchs!.map((a) => {
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
                      {!unlocked && game && (
                        <a
                          href={a.guide_url || game.guide_url || guideSearchUrl(game.platform, game.name, a.name)}
                          target="_blank"
                          rel="noopener noreferrer"
                          title="Find a guide for this achievement"
                          className="flex-shrink-0 rounded-md p-1.5 text-faint transition hover:bg-ink-700 hover:text-accent"
                        >
                          <ExternalLink size={14} />
                        </a>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          {/* sidebar */}
          <div className="space-y-3 lg:border-l lg:border-line/50 lg:pl-4">
            <div className="grid grid-cols-3 gap-2 lg:grid-cols-1">
              {game && fmtPlaytime(game.playtime_minutes) && (
                <StatBox label="Playtime" value={fmtPlaytime(game.playtime_minutes)!} />
              )}
              <StatBox label="Completion" value={`${pct}%`} />
              {hltbParts.length > 0 && <StatBox label="Time to beat" value={hltbParts[0][1]!} />}
            </div>

            {hltbParts.length > 1 && (
              <div className="rounded-lg border border-line/50 bg-ink-900/50 p-3 backdrop-blur-sm">
                <div className="mb-1.5 text-xs font-semibold text-slate-200">Time to beat</div>
                <div className="space-y-1 text-xs text-muted">
                  {hltbParts.map(([label, v]) => (
                    <div key={label} className="flex justify-between">
                      <span>{label}</span>
                      <span className="text-slate-300">{v}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {game && game.rarity_summary.length > 0 && (
              <div className="rounded-lg border border-line/50 bg-ink-900/50 p-3 backdrop-blur-sm">
                <div className="mb-1.5 text-xs font-semibold text-slate-200">Rarity breakdown</div>
                <div className="space-y-1.5">
                  {game.rarity_summary.map((r) => (
                    <div key={r.tier} className="flex items-center justify-between text-xs">
                      <span className="flex items-center gap-1.5">
                        <span
                          className="h-2 w-2 rounded-full"
                          style={{ backgroundColor: RARITY_TIER_HEX[r.tier] }}
                        />
                        <span className={RARITY_TIER_CLASS[r.tier]}>{r.tier}</span>
                      </span>
                      <span className="font-medium text-slate-300">{r.cnt}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
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

function StatBox({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-line/50 bg-ink-900/50 px-3 py-2 text-center backdrop-blur-sm lg:text-left">
      <div className="text-[10px] uppercase tracking-wide text-faint">{label}</div>
      <div className="mt-0.5 text-sm font-semibold text-slate-200">{value}</div>
    </div>
  );
}
