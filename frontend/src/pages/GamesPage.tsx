import { useEffect, useRef, useState, useCallback } from "react";
import { Search, List, LayoutGrid, Gamepad2 } from "lucide-react";
import { api } from "../api";
import type { Game, Summary } from "../types";
import { GameCard } from "../components/GameCard";
import { GameRow } from "../components/GameRow";
import { GameCardSkeleton, GameRowSkeleton } from "../components/Skeleton";
import { GameDetailModal } from "../components/GameDetailModal";
import { platformLabel } from "../lib/platforms";

type ViewMode = "grid" | "list";

const SORTS = [
  { key: "recent", label: "Recent" },
  { key: "completion", label: "Completion" },
  { key: "playtime", label: "Playtime" },
  { key: "name", label: "Name" },
];

const COMPLETIONS = [
  { key: "", label: "All" },
  { key: "in_progress", label: "In progress" },
  { key: "completed", label: "Completed" },
  { key: "not_started", label: "Not started" },
];

const PAGE_SIZE = 24;

export function GamesPage({ summary }: { summary: Summary | null }) {
  const [games, setGames] = useState<Game[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [initialLoading, setInitialLoading] = useState(true);
  const [hasAnyAccount, setHasAnyAccount] = useState<boolean | null>(null);

  const [selected, setSelected] = useState<number | null>(null);
  const [view, setView] = useState<ViewMode>(
    () => (localStorage.getItem("pantheon.view") as ViewMode) || "grid",
  );
  const [sort, setSort] = useState("recent");

  function changeView(v: ViewMode) {
    setView(v);
    localStorage.setItem("pantheon.view", v);
  }
  const [platform, setPlatform] = useState("");
  const [completion, setCompletion] = useState("");
  const [search, setSearch] = useState("");
  const searchDebounced = useDebounce(search, 300);

  // Build the platform filter from connected accounts (so a newly added account
  // appears immediately), unioned with any platforms that already have games.
  const [accountPlatforms, setAccountPlatforms] = useState<string[]>([]);
  useEffect(() => {
    api.accounts()
      .then((a) => {
        setAccountPlatforms(a.map((x) => x.platform));
        setHasAnyAccount(a.length > 0);
      })
      .catch(() => setHasAnyAccount(false));
  }, []);

  const platforms = Array.from(
    new Set([...(summary?.by_platform.map((p) => p.platform) ?? []), ...accountPlatforms]),
  );

  const load = useCallback(
    async (pageToLoad: number, replace: boolean) => {
      setLoading(true);
      try {
        const res = await api.games({
          sort,
          platform: platform || undefined,
          completion: completion || undefined,
          search: searchDebounced || undefined,
          page: pageToLoad,
          page_size: PAGE_SIZE,
        });
        setTotal(res.total);
        setPage(res.page);
        setGames((prev) => {
          const base = replace ? [] : prev;
          const seen = new Set(base.map((g) => g.platform_game_id));
          const merged = [...base];
          for (const g of res.games) {
            if (seen.has(g.platform_game_id)) continue;
            seen.add(g.platform_game_id);
            merged.push(g);
          }
          return merged;
        });
      } finally {
        setLoading(false);
        setInitialLoading(false);
      }
    },
    [sort, platform, completion, searchDebounced],
  );

  // reload from page 1 whenever filters change
  useEffect(() => {
    load(1, true);
  }, [load]);

  const hasMore = games.length < total;

  // Infinite scroll: auto-load the next page when the sentinel scrolls into view.
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
      {/* toolbar */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex max-w-full overflow-x-auto rounded-lg border border-line bg-ink-850 p-1">
          {SORTS.map((s) => (
            <button
              key={s.key}
              onClick={() => setSort(s.key)}
              className={`flex-shrink-0 whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium transition ${
                sort === s.key ? "bg-ink-700 text-slate-100" : "text-muted hover:text-slate-200"
              }`}
            >
              {s.label}
            </button>
          ))}
        </div>

        <select
          value={completion}
          onChange={(e) => setCompletion(e.target.value)}
          className="rounded-lg border border-line bg-ink-850 px-3 py-2 text-sm text-slate-200 outline-none"
        >
          {COMPLETIONS.map((c) => (
            <option key={c.key} value={c.key}>{c.label}</option>
          ))}
        </select>

        <select
          value={platform}
          onChange={(e) => setPlatform(e.target.value)}
          className="rounded-lg border border-line bg-ink-850 px-3 py-2 text-sm text-slate-200 outline-none"
        >
          <option value="">All platforms</option>
          {platforms.map((p) => (
            <option key={p} value={p}>{platformLabel(p)}</option>
          ))}
        </select>

        <div className="flex w-full items-center gap-2 rounded-lg border border-line bg-ink-850 px-3 py-2 sm:ml-auto sm:w-auto">
          <Search size={15} className="text-faint" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search games…"
            className="w-full bg-transparent text-sm text-slate-100 outline-none placeholder:text-faint sm:w-44"
          />
        </div>

        <div className="flex rounded-lg border border-line bg-ink-850 p-1">
          <button
            onClick={() => changeView("list")}
            title="List view"
            className={`rounded-md p-1.5 transition ${view === "list" ? "bg-ink-700 text-slate-100" : "text-muted hover:text-slate-200"}`}
          >
            <List size={16} />
          </button>
          <button
            onClick={() => changeView("grid")}
            title="Grid view"
            className={`rounded-md p-1.5 transition ${view === "grid" ? "bg-ink-700 text-slate-100" : "text-muted hover:text-slate-200"}`}
          >
            <LayoutGrid size={16} />
          </button>
        </div>
      </div>

      <div className="mb-3 text-xs uppercase tracking-wide text-faint">
        {total.toLocaleString()} {total === 1 ? "game" : "games"}
      </div>

      {/* games */}
      {initialLoading ? (
        <div className={view === "grid" ? "grid grid-cols-1 gap-3 lg:grid-cols-2" : "flex flex-col gap-1.5"}>
          {Array.from({ length: 8 }).map((_, i) =>
            view === "grid" ? <GameCardSkeleton key={i} /> : <GameRowSkeleton key={i} />,
          )}
        </div>
      ) : view === "grid" ? (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {games.map((g) => (
            <GameCard key={g.platform_game_id} game={g} onClick={() => setSelected(g.platform_game_id)} />
          ))}
        </div>
      ) : (
        <div className="flex flex-col gap-1.5">
          {games.map((g) => (
            <GameRow key={g.platform_game_id} game={g} onClick={() => setSelected(g.platform_game_id)} />
          ))}
        </div>
      )}

      {!initialLoading && games.length === 0 && !loading && (
        <div className="py-16 text-center">
          <Gamepad2 size={32} className="mx-auto mb-3 text-faint" />
          {hasAnyAccount === false ? (
            <>
              <div className="text-muted">No accounts connected yet.</div>
              <div className="mt-1 text-sm text-faint">Head to the Accounts tab to connect a platform.</div>
            </>
          ) : (
            <div className="text-muted">No games match your filters.</div>
          )}
        </div>
      )}

      {/* infinite-scroll sentinel + loading indicator */}
      {hasMore && <div ref={sentinelRef} className="h-1" />}
      {loading && !initialLoading && games.length > 0 && (
        <div className="mt-6 text-center text-sm text-muted">Loading…</div>
      )}

      {selected !== null && (
        <GameDetailModal gameId={selected} onClose={() => setSelected(null)} />
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
