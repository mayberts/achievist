import { useEffect, useState, useCallback, lazy, Suspense } from "react";
import { RefreshCw } from "lucide-react";
import { api } from "./api";
import type { Summary, SyncProgress } from "./types";
import { Nav, type Tab } from "./components/Nav";
import { SummaryBar } from "./components/SummaryBar";
import { GamesPage } from "./pages/GamesPage";
import { AccountsPage } from "./pages/AccountsPage";

// Statistics pulls in recharts (~340 kB); load it only when the tab is opened.
const StatisticsPage = lazy(() =>
  import("./pages/StatisticsPage").then((m) => ({ default: m.StatisticsPage })),
);

export default function App() {
  const [tab, setTab] = useState<Tab>("games");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [progress, setProgress] = useState<SyncProgress | null>(null);

  const loadSummary = useCallback(() => {
    api.summary().then(setSummary).catch(() => setSummary(null));
  }, []);

  useEffect(() => {
    loadSummary();
  }, [loadSummary]);

  // poll sync progress while a sync is running
  useEffect(() => {
    let timer: number | undefined;
    const tick = async () => {
      try {
        const p = await api.syncProgress();
        setProgress(p);
        if (p.running) {
          timer = window.setTimeout(tick, 2000);
        } else {
          loadSummary();
        }
      } catch {
        /* ignore */
      }
    };
    tick();
    return () => window.clearTimeout(timer);
  }, [loadSummary]);

  const running = progress?.running ?? false;

  async function syncAll() {
    await api.syncAll().catch(() => {});
    setProgress((p) => (p ? { ...p, running: true } : p));
    // kick the poller
    const p = await api.syncProgress().catch(() => null);
    if (p) setProgress(p);
  }

  return (
    <div className="min-h-screen">
      <div className="mx-auto max-w-6xl px-4 py-6">
        {summary && <SummaryBar summary={summary} />}

        <div className="mt-5 flex items-center justify-between gap-4">
          <Nav tab={tab} onChange={setTab} />
          <button
            onClick={syncAll}
            disabled={running}
            className="inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white transition hover:bg-accent/90 disabled:opacity-60"
          >
            <RefreshCw size={15} className={running ? "animate-spin" : ""} />
            {running ? "Syncing…" : "Sync all"}
          </button>
        </div>

        {running && progress && (
          <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted">
            {Object.entries(progress.platforms).map(([plat, s]) => (
              <span key={plat} className="rounded-md bg-ink-850 px-2 py-1">
                {plat}: {s.status}
                {s.games_seen ? ` · ${s.games_seen} games` : ""}
              </span>
            ))}
          </div>
        )}

        <div className="mt-6">
          {tab === "games" && <GamesPage summary={summary} />}
          {tab === "accounts" && <AccountsPage />}
          {tab === "statistics" && (
            <Suspense fallback={<div className="py-16 text-center text-muted">Loading…</div>}>
              <StatisticsPage />
            </Suspense>
          )}
        </div>
      </div>
    </div>
  );
}
