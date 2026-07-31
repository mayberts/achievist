import { useEffect, useRef, useState, useCallback } from "react";
import { Search } from "lucide-react";
import { api } from "../api";
import type { Game, Summary } from "../types";
import { GameCard } from "../components/GameCard";
import { GameDetailModal } from "../components/GameDetailModal";
import { platformLabel } from "../lib/platforms";

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

  const [selected, setSelected] = useState<number | null>(null);
  const [sort, setSort] = useState("recent");
  const [platform, setPlatform] = useState("");
  const [completion, setCompletion] = useState("");
  const [search, setSearch] = useState("");
  const searchDebounced = useDebounce(search, 300);

  const platforms = summary?.by_platform.map((p) => p.platform) ?? [];

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
        setGames((prev) => (replace ? res.games : [...prev, ...res.games]));
      } finally {
        setLoading(false);
      }
    },
    [sort, platform, completion, searchDebounced],
  );

  // reload from page 1 whenever filters change
  useEffect(() => {
    load(1, true);
  }, [load]);

  const hasMore = games.length < total;

  return (
    <div>
      {/* toolbar */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex rounded-lg border border-line bg-ink-850 p-1">
          {SORTS.map((s) => (
            <button
              key={s.key}
              onClick={() => setSort(s.key)}
              className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${
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

        <div className="ml-auto flex items-center gap-2 rounded-lg border border-line bg-ink-850 px-3 py-2">
          <Search size={15} className="text-faint" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search games…"
            className="w-44 bg-transparent text-sm text-slate-100 outline-none placeholder:text-faint"
          />
        </div>
      </div>

      <div className="mb-3 text-xs uppercase tracking-wide text-faint">
        {total.toLocaleString()} {total === 1 ? "game" : "games"}
      </div>

      {/* grid */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {games.map((g) => (
          <GameCard key={g.platform_game_id} game={g} onClick={() => setSelected(g.platform_game_id)} />
        ))}
      </div>

      {games.length === 0 && !loading && (
        <div className="py-16 text-center text-muted">No games match your filters.</div>
      )}

      {hasMore && (
        <div className="mt-6 flex justify-center">
          <button
            onClick={() => load(page + 1, false)}
            disabled={loading}
            className="rounded-lg border border-line bg-ink-850 px-5 py-2.5 text-sm font-medium text-slate-200 transition hover:bg-ink-800 disabled:opacity-50"
          >
            {loading ? "Loading…" : "Load more"}
          </button>
        </div>
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
