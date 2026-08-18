import { useEffect, useRef, useState, useCallback } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Search, Trophy, Lock, Gamepad2, ExternalLink } from "lucide-react";
import { api } from "../api";
import type { AchievementSearchResult } from "../types";
import { fmtDate } from "../lib/format";
import { RARITY_TIER_CLASS, rarityTier } from "../lib/rarity";
import { guideSearchUrl } from "../lib/guideLink";
import { PlatformBadge } from "../components/PlatformBadge";

const RARITIES = ["", "Legendary", "Epic", "Rare", "Uncommon", "Common"];

const SORTS = [
  { key: "rarity", label: "Rarity (rarest first)" },
  { key: "unlocked_at", label: "Unlock date" },
  { key: "points", label: "Points" },
  { key: "name", label: "Name" },
];

const PAGE_SIZE = 30;

export function AchievementsPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const q = searchParams.get("q") || "";
  const rarity = searchParams.get("rarity") || "";
  const platform = searchParams.get("platform") || "";
  const unlocked = searchParams.get("unlocked") || "";
  const sort = searchParams.get("sort") || "rarity";
  const qDebounced = useDebounce(q, 300);

  function updateParam(key: string, value: string) {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (value) next.set(key, value);
        else next.delete(key);
        return next;
      },
      { replace: true },
    );
  }

  const [results, setResults] = useState<AchievementSearchResult[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [initialLoading, setInitialLoading] = useState(true);

  const load = useCallback(
    async (pageToLoad: number, replace: boolean) => {
      setLoading(true);
      try {
        const res = await api.searchAchievements({
          q: qDebounced || undefined,
          rarity: rarity || undefined,
          platform: platform || undefined,
          unlocked: unlocked || undefined,
          sort,
          page: pageToLoad,
          page_size: PAGE_SIZE,
        });
        setTotal(res.total);
        setPage(res.page);
        setResults((prev) => {
          const base = replace ? [] : prev;
          const seen = new Set(base.map((a) => `${a.platform_game_id}-${a.platform_ach_id}`));
          const merged = [...base];
          for (const a of res.achievements) {
            const key = `${a.platform_game_id}-${a.platform_ach_id}`;
            if (seen.has(key)) continue;
            seen.add(key);
            merged.push(a);
          }
          return merged;
        });
      } finally {
        setLoading(false);
        setInitialLoading(false);
      }
    },
    [qDebounced, rarity, platform, unlocked, sort],
  );

  useEffect(() => {
    load(1, true);
  }, [load]);

  const hasMore = results.length < total;

  const sentinelRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el || !hasMore) return;
    const obs = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && !loading) load(page + 1, false);
      },
      { rootMargin: "600px" },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [hasMore, loading, page, load]);

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-line bg-ink-850 px-3 py-2 sm:min-w-[220px] sm:flex-none">
          <Search size={15} className="flex-shrink-0 text-faint" />
          <input
            value={q}
            onChange={(e) => updateParam("q", e.target.value)}
            placeholder="Search achievements…"
            className="w-full min-w-0 bg-transparent text-sm text-slate-100 outline-none placeholder:text-faint"
          />
        </div>

        <select
          value={rarity}
          onChange={(e) => updateParam("rarity", e.target.value)}
          className="rounded-lg border border-line bg-ink-850 px-3 py-2 text-sm text-slate-200 outline-none"
        >
          <option value="">All rarities</option>
          {RARITIES.filter(Boolean).map((r) => (
            <option key={r} value={r}>{r}</option>
          ))}
        </select>

        <select
          value={unlocked}
          onChange={(e) => updateParam("unlocked", e.target.value)}
          className="rounded-lg border border-line bg-ink-850 px-3 py-2 text-sm text-slate-200 outline-none"
        >
          <option value="">All achievements</option>
          <option value="true">Unlocked</option>
          <option value="false">Locked</option>
        </select>

        <select
          value={sort}
          onChange={(e) => updateParam("sort", e.target.value)}
          className="rounded-lg border border-line bg-ink-850 px-3 py-2 text-sm text-slate-200 outline-none"
        >
          {SORTS.map((s) => (
            <option key={s.key} value={s.key}>{s.label}</option>
          ))}
        </select>
      </div>

      <div className="mb-3 text-xs uppercase tracking-wide text-faint">
        {total.toLocaleString()} {total === 1 ? "achievement" : "achievements"}
      </div>

      {initialLoading ? (
        <div className="flex flex-col gap-1.5">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="h-16 animate-pulse rounded-lg bg-ink-850" />
          ))}
        </div>
      ) : results.length === 0 ? (
        <div className="py-16 text-center">
          <Trophy size={32} className="mx-auto mb-3 text-faint" />
          <div className="text-muted">No achievements match your filters.</div>
        </div>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {results.map((a) => {
            const isUnlocked = !!a.unlocked;
            const art = a.sgdb_cover_url || a.game_icon_url;
            return (
              <li key={`${a.platform_game_id}-${a.platform_ach_id}`}>
                <div
                  role="button"
                  tabIndex={0}
                  onClick={() => navigate(`/games/${a.platform_game_id}`)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") navigate(`/games/${a.platform_game_id}`);
                  }}
                  className={`flex w-full cursor-pointer items-center gap-3 rounded-lg border border-line bg-ink-850 p-2.5 text-left transition hover:border-ink-600 hover:bg-ink-800 ${isUnlocked ? "" : "opacity-70"}`}
                >
                  <div className="relative h-11 w-11 flex-shrink-0 overflow-hidden rounded-md bg-ink-900">
                    {a.icon_url ? (
                      <img
                        src={a.icon_url}
                        alt=""
                        className={`h-full w-full object-cover ${isUnlocked ? "" : "grayscale"}`}
                        loading="lazy"
                      />
                    ) : (
                      <div className="flex h-full w-full items-center justify-center text-faint">
                        <Trophy size={16} />
                      </div>
                    )}
                    {!isUnlocked && (
                      <div className="absolute inset-0 flex items-center justify-center bg-black/40">
                        <Lock size={13} className="text-slate-300" />
                      </div>
                    )}
                  </div>

                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-slate-100">{a.name || a.platform_ach_id}</div>
                    {a.description && <div className="truncate text-xs text-muted">{a.description}</div>}
                    <div className="mt-1 flex items-center gap-1.5 text-xs text-faint">
                      <div className="h-4 w-4 flex-shrink-0 overflow-hidden rounded bg-ink-900">
                        {art ? (
                          <img src={art} alt="" className="h-full w-full object-cover" loading="lazy" />
                        ) : (
                          <Gamepad2 size={10} className="m-auto" />
                        )}
                      </div>
                      <span className="truncate">{a.game_name}</span>
                      <PlatformBadge platform={a.platform} />
                    </div>
                  </div>

                  <div className="flex-shrink-0 text-right">
                    {a.rarity_pct != null && (
                      <div className={`text-xs font-semibold ${RARITY_TIER_CLASS[rarityTier(a.rarity_pct)]}`}>
                        {a.rarity_pct}%
                      </div>
                    )}
                    {isUnlocked && fmtDate(a.unlocked_at) && (
                      <div className="text-[11px] text-faint">{fmtDate(a.unlocked_at)}</div>
                    )}
                  </div>

                  {!isUnlocked && (
                    <a
                      href={guideSearchUrl(a.platform, a.game_name, a.name)}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      title="Find a guide for this achievement"
                      className="flex-shrink-0 rounded-md p-1.5 text-faint transition hover:bg-ink-700 hover:text-accent"
                    >
                      <ExternalLink size={14} />
                    </a>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {hasMore && <div ref={sentinelRef} className="h-1" />}
      {loading && !initialLoading && results.length > 0 && (
        <div className="mt-6 text-center text-sm text-muted">Loading…</div>
      )}
    </div>
  );
}

function useDebounce<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  const ref = useRef<number>();
  useEffect(() => {
    window.clearTimeout(ref.current);
    ref.current = window.setTimeout(() => setDebounced(value), ms);
    return () => window.clearTimeout(ref.current);
  }, [value, ms]);
  return debounced;
}
