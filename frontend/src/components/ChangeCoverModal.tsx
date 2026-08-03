import { useEffect, useRef, useState } from "react";
import { X, Search, ImageOff } from "lucide-react";
import { api } from "../api";
import type { SgdbSearchResult } from "../types";
import { useToast } from "./Toast";

export function ChangeCoverModal({
  gameId,
  initialQuery,
  onClose,
  onChanged,
}: {
  gameId: number;
  initialQuery: string;
  onClose: () => void;
  onChanged: (url: string) => void;
}) {
  const [query, setQuery] = useState(initialQuery);
  const [games, setGames] = useState<SgdbSearchResult[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [applying, setApplying] = useState<string | null>(null);
  const toast = useToast();
  const debounceRef = useRef<number>();

  function runSearch(q: string) {
    if (!q.trim()) {
      setGames([]);
      return;
    }
    setGames(null);
    setError(null);
    api.sgdbSearch(q)
      .then((r) => {
        if (r.error) {
          setError(r.error);
          setGames([]);
        } else {
          setGames(r.games ?? []);
        }
      })
      .catch((e) => {
        setError(String(e instanceof Error ? e.message : e));
        setGames([]);
      });
  }

  useEffect(() => {
    runSearch(initialQuery);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  function onQueryChange(v: string) {
    setQuery(v);
    window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => runSearch(v), 350);
  }

  async function pick(url: string) {
    setApplying(url);
    try {
      await api.sgdbSet(gameId, url);
      toast.success("Cover updated");
      onChanged(url);
      onClose();
    } catch (e) {
      toast.error(String(e instanceof Error ? e.message : e));
    } finally {
      setApplying(null);
    }
  }

  async function clear() {
    setApplying("__clear__");
    try {
      await api.sgdbSet(gameId, "");
      toast.success("Cover reset to default");
      onChanged("");
      onClose();
    } catch (e) {
      toast.error(String(e instanceof Error ? e.message : e));
    } finally {
      setApplying(null);
    }
  }

  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center overflow-y-auto bg-black/70 p-4"
      onClick={(e) => {
        // Nested inside GameDetailModal's own backdrop div — stop the click
        // here so it doesn't also bubble up and close that modal too.
        e.stopPropagation();
        onClose();
      }}
    >
      <div
        className="my-8 w-full max-w-2xl rounded-card border border-line bg-ink-850 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line p-4">
          <h2 className="text-base font-semibold text-slate-100">Change Cover</h2>
          <button onClick={onClose} className="rounded-lg p-1.5 text-muted transition hover:bg-ink-800 hover:text-slate-200">
            <X size={18} />
          </button>
        </div>

        <div className="p-4">
          <div className="flex items-center gap-2 rounded-lg border border-line bg-ink-900 px-3 py-2">
            <Search size={15} className="text-faint" />
            <input
              autoFocus
              value={query}
              onChange={(e) => onQueryChange(e.target.value)}
              placeholder="Search SteamGridDB by name, or paste a numeric game ID…"
              className="w-full bg-transparent text-sm text-slate-100 outline-none placeholder:text-faint"
            />
          </div>

          <button
            onClick={clear}
            disabled={applying !== null}
            className="mt-3 text-xs text-muted underline decoration-dotted transition hover:text-slate-200 disabled:opacity-50"
          >
            Remove custom cover (use default)
          </button>

          <div className="mt-4 max-h-[55vh] space-y-5 overflow-y-auto">
            {error && (
              <div className="rounded-lg border border-red-900/50 bg-red-950/30 px-3 py-2 text-sm text-red-400">
                {error}
              </div>
            )}

            {games === null ? (
              <div className="py-10 text-center text-sm text-muted">Searching…</div>
            ) : games.length === 0 && !error ? (
              <div className="py-10 text-center text-sm text-muted">
                {query.trim() ? "No results." : "Start typing to search SteamGridDB."}
              </div>
            ) : (
              games.map((g) => {
                const images = [...g.heroes.map((u) => ({ u, wide: true })), ...g.grids.map((u) => ({ u, wide: false }))];
                return (
                  <div key={g.id}>
                    <div className="mb-2 text-sm font-medium text-slate-200">{g.name}</div>
                    {images.length === 0 ? (
                      <div className="flex items-center gap-2 text-xs text-faint">
                        <ImageOff size={13} /> No art found for this game.
                      </div>
                    ) : (
                      <div className="flex gap-2 overflow-x-auto pb-1">
                        {images.map(({ u, wide }) => (
                          <button
                            key={u}
                            onClick={() => pick(u)}
                            disabled={applying !== null}
                            className="group relative flex-shrink-0 overflow-hidden rounded-md border border-line ring-1 ring-transparent transition hover:ring-accent disabled:opacity-50"
                          >
                            <img
                              src={u}
                              alt=""
                              className={`h-20 object-cover ${wide ? "w-36" : "w-16"}`}
                              loading="lazy"
                            />
                            {applying === u && (
                              <div className="absolute inset-0 flex items-center justify-center bg-black/50 text-[10px] text-slate-100">
                                Applying…
                              </div>
                            )}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
