import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Gamepad2, Search, Trophy, X } from "lucide-react";
import { api } from "../api";
import { platformLabel } from "../lib/platforms";
import { RARITY_TIER_CLASS, rarityTier } from "../lib/rarity";
import type { AchievementSearchResult, Game } from "../types";

/**
 * One search box over both games and achievements.
 *
 * Finding a game meant going to Games and filtering; finding an achievement
 * meant a different tab with its own filters. Both are one keystroke now.
 *
 * The shortcut is Ctrl+K and it is spelled "Ctrl K" wherever it appears —
 * this is a Windows household, so no command-key glyph anywhere in the UI.
 * The handler also accepts the meta key, because a Mac visitor pressing what
 * their keyboard says should still work; it is simply never advertised.
 */

const DEBOUNCE_MS = 200;
const PER_KIND = 6;

export type Result =
  | { kind: "game"; id: number; name: string; platform: string; icon: string | null; pct: number }
  | {
      kind: "achievement";
      id: string;
      gameId: number;
      name: string;
      gameName: string;
      platform: string;
      icon: string | null;
      rarity: number | null;
    };

export function toResults(games: Game[], achievements: AchievementSearchResult[]): Result[] {
  return [
    ...games.map(
      (g): Result => ({
        kind: "game",
        id: g.platform_game_id,
        name: g.name,
        platform: g.platform,
        icon: g.icon_url ?? g.sgdb_cover_url,
        pct: g.completion_pct,
      }),
    ),
    ...achievements.map(
      (a): Result => ({
        kind: "achievement",
        // Achievement rows are unique per game, not globally, so the key has
        // to carry the game too or two games' "Complete the game" collide.
        id: `${a.platform_game_id}-${a.platform_ach_id}`,
        gameId: a.platform_game_id,
        name: a.name ?? "Unnamed achievement",
        gameName: a.game_name,
        platform: a.platform,
        icon: a.icon_url,
        rarity: a.rarity_pct,
      }),
    ),
  ];
}

/** Where selecting a result takes you. Achievements live on their game's page. */
export function hrefFor(r: Result): string {
  return r.kind === "game" ? `/games/${r.id}` : `/games/${r.gameId}`;
}

function isTypingTarget(el: EventTarget | null): boolean {
  const node = el as HTMLElement | null;
  if (!node) return false;
  const tag = node.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || node.isContentEditable;
}

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Result[]>([]);
  const [loading, setLoading] = useState(false);
  const [active, setActive] = useState(0);
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  // Bumped per keystroke so a slow early request can't overwrite the results
  // of a later, more specific one.
  const seq = useRef(0);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key.toLowerCase() === "k" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        setOpen((v) => !v);
      } else if (e.key === "/" && !isTypingTarget(e.target)) {
        e.preventDefault();
        setOpen(true);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (open) inputRef.current?.focus();
    else {
      setQ("");
      setResults([]);
      setActive(0);
    }
  }, [open]);

  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) {
      setResults([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    const mine = ++seq.current;
    const timer = window.setTimeout(async () => {
      const [games, achievements] = await Promise.all([
        api.games({ search: term, page_size: PER_KIND, sort: "name" }).catch(() => null),
        api.searchAchievements({ q: term, page_size: PER_KIND, sort: "rarity" }).catch(() => null),
      ]);
      if (mine !== seq.current) return;
      setResults(toResults(games?.games ?? [], achievements?.achievements ?? []));
      setActive(0);
      setLoading(false);
    }, DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [q]);

  const choose = useCallback(
    (r: Result) => {
      setOpen(false);
      navigate(hrefFor(r));
    },
    [navigate],
  );

  function onInputKey(e: React.KeyboardEvent) {
    if (e.key === "Escape") setOpen(false);
    else if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => (results.length ? (i + 1) % results.length : 0));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => (results.length ? (i - 1 + results.length) % results.length : 0));
    } else if (e.key === "Enter" && results[active]) {
      e.preventDefault();
      choose(results[active]);
    }
  }

  const term = q.trim();

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        aria-label="Search games and achievements"
        className="inline-flex items-center gap-2 rounded-lg border border-line/40 bg-ink-900/40 px-2.5 py-1.5 text-xs font-medium text-muted backdrop-blur-sm transition hover:bg-ink-800/60 hover:text-slate-200"
      >
        <Search size={13} />
        <span className="hidden sm:inline">Search</span>
        <kbd className="hidden rounded border border-line/60 bg-ink-850 px-1.5 py-0.5 font-sans text-[10px] text-faint sm:inline">
          Ctrl K
        </kbd>
      </button>

      {open && (
        <div
          className="fixed inset-0 z-[70] flex items-start justify-center bg-black/70 p-4 pt-[10vh]"
          onClick={() => setOpen(false)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Search games and achievements"
            className="flex max-h-[70vh] w-full max-w-xl flex-col overflow-hidden rounded-card border border-line bg-ink-850 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-2 border-b border-line px-3">
              <Search size={16} className="shrink-0 text-faint" />
              <input
                ref={inputRef}
                value={q}
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={onInputKey}
                placeholder="Search games and achievements…"
                aria-label="Search games and achievements"
                className="flex-1 bg-transparent py-3 text-sm text-slate-100 outline-none placeholder:text-faint"
              />
              <button
                onClick={() => setOpen(false)}
                aria-label="Close search"
                className="rounded-lg p-1.5 text-muted transition hover:bg-ink-800 hover:text-slate-200"
              >
                <X size={16} />
              </button>
            </div>

            <div className="overflow-y-auto">
              {term.length < 2 ? (
                <div className="px-4 py-6 text-center text-sm text-faint">
                  Type at least two characters. Press <Kbd>Esc</Kbd> to close.
                </div>
              ) : loading ? (
                <div className="px-4 py-6 text-center text-sm text-faint">Searching…</div>
              ) : results.length === 0 ? (
                <div className="px-4 py-6 text-center text-sm text-muted">
                  Nothing matching “{term}”.
                </div>
              ) : (
                <ul role="listbox" aria-label="Search results" className="p-2">
                  {results.map((r, i) => (
                    <li key={`${r.kind}-${r.id}`}>
                      <button
                        role="option"
                        aria-selected={i === active}
                        onMouseEnter={() => setActive(i)}
                        onClick={() => choose(r)}
                        className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left transition ${
                          i === active ? "bg-ink-700" : "hover:bg-ink-800"
                        }`}
                      >
                        {r.icon ? (
                          <img src={r.icon} alt="" className="h-8 w-8 shrink-0 rounded object-cover" />
                        ) : (
                          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded bg-ink-800 text-faint">
                            {r.kind === "game" ? <Gamepad2 size={14} /> : <Trophy size={14} />}
                          </div>
                        )}
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm font-medium text-slate-100">{r.name}</div>
                          <div className="truncate text-xs text-muted">
                            {r.kind === "game"
                              ? `Game · ${platformLabel(r.platform)}`
                              : `${r.gameName} · ${platformLabel(r.platform)}`}
                          </div>
                        </div>
                        <div className="shrink-0 text-xs font-semibold tabular-nums">
                          {r.kind === "game" ? (
                            <span className="text-muted">{Math.round(r.pct)}%</span>
                          ) : r.rarity !== null ? (
                            <span className={RARITY_TIER_CLASS[rarityTier(r.rarity)]}>{r.rarity}%</span>
                          ) : null}
                        </div>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="flex items-center gap-3 border-t border-line px-3 py-2 text-[11px] text-faint">
              <span>
                <Kbd>↑</Kbd> <Kbd>↓</Kbd> to move
              </span>
              <span>
                <Kbd>Enter</Kbd> to open
              </span>
              <span>
                <Kbd>Esc</Kbd> to close
              </span>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="rounded border border-line/60 bg-ink-900 px-1 py-0.5 font-sans text-[10px] text-muted">
      {children}
    </kbd>
  );
}
