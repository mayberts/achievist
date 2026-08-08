import { useEffect, useState, useCallback, useRef, lazy, Suspense } from "react";
import { Route, Routes, useNavigate } from "react-router-dom";
import { LogOut, RefreshCw, Trophy } from "lucide-react";
import { api } from "./api";
import type { Summary, SyncProgress } from "./types";
import { useAuth } from "./lib/auth";
import { AppBackground } from "./components/AppBackground";
import { Nav, type Tab } from "./components/Nav";
import { SummaryBar } from "./components/SummaryBar";
import { BackToTop } from "./components/BackToTop";
import { useToast } from "./components/Toast";
import { GamesPage } from "./pages/GamesPage";
import { AchievementsPage } from "./pages/AchievementsPage";
import { ActivityPage } from "./pages/ActivityPage";
import { AccountsPage } from "./pages/AccountsPage";
import { LeaderboardPage } from "./pages/LeaderboardPage";
import { MaintenancePage } from "./pages/MaintenancePage";
import { GameDetailPage } from "./pages/GameDetailPage";

// Statistics pulls in recharts (~340 kB); load it only when the tab is opened.
const StatisticsPage = lazy(() =>
  import("./pages/StatisticsPage").then((m) => ({ default: m.StatisticsPage })),
);

export default function App() {
  const [tab, setTab] = useState<Tab>("games");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [progress, setProgress] = useState<SyncProgress | null>(null);
  const [accountErrors, setAccountErrors] = useState(0);
  const toast = useToast();
  const wasRunning = useRef(false);
  const navigate = useNavigate();
  const { user, logout } = useAuth();

  const loadSummary = useCallback(() => {
    api.summary().then(setSummary).catch(() => setSummary(null));
  }, []);

  const loadAccountErrors = useCallback(() => {
    api.accounts()
      .then((a) => setAccountErrors(a.filter((x) => x.status === "error").length))
      .catch(() => {});
  }, []);

  // Poll for newly-unlocked achievements (from any sync, manual or scheduled)
  // independent of whether a sync is actively running right now, so
  // background scheduled syncs still surface a toast while the tab is open.
  const UNLOCK_CURSOR_KEY = "pantheon.lastUnlockSeen";
  const checkUnlocks = useCallback(async () => {
    try {
      // First time this ships (no stored cursor yet): start from "now" so we
      // don't dump every historical unlock ever buffered as a toast flood.
      if (!localStorage.getItem(UNLOCK_CURSOR_KEY)) {
        localStorage.setItem(UNLOCK_CURSOR_KEY, new Date().toISOString());
        return;
      }
      const since = localStorage.getItem(UNLOCK_CURSOR_KEY) ?? "";
      const { events } = await api.familyActivity(since);
      for (const e of events) {
        const who = e.is_you ? null : e.display_name || e.username;
        toast.achievement({
          name: e.achievement_name || "Achievement unlocked",
          subtitle: (who ? `${who} · ` : "") + e.game_name + (e.points ? ` · ${e.points} pts` : ""),
          icon: e.icon_url,
        });
      }
      if (events.length > 0) {
        localStorage.setItem(UNLOCK_CURSOR_KEY, events[events.length - 1].unlocked_at);
      }
    } catch {
      /* ignore */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    loadSummary();
    loadAccountErrors();
  }, [loadSummary, loadAccountErrors]);

  // poll sync progress while a sync is running
  useEffect(() => {
    let timer: number | undefined;
    const tick = async () => {
      try {
        const p = await api.syncProgress();
        setProgress(p);
        if (p.running) {
          wasRunning.current = true;
          timer = window.setTimeout(tick, 2000);
        } else {
          if (wasRunning.current) {
            const errors = Object.entries(p.platforms).filter(([, s]) => s.status === "error");
            if (errors.length > 0) {
              toast.error(`Sync finished with ${errors.length} error${errors.length > 1 ? "s" : ""}: ${errors.map(([plat]) => plat).join(", ")}`);
            } else if (Object.keys(p.platforms).length > 0) {
              toast.success("Sync complete");
            }
            checkUnlocks();
          }
          wasRunning.current = false;
          loadSummary();
          loadAccountErrors();
        }
      } catch {
        /* ignore */
      }
    };
    tick();
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadSummary, loadAccountErrors, checkUnlocks]);

  // background poll, so scheduled syncs (not just manually-triggered ones)
  // also surface a toast while the tab is open
  useEffect(() => {
    let timer: number | undefined;
    const tick = async () => {
      await checkUnlocks();
      timer = window.setTimeout(tick, 45000);
    };
    timer = window.setTimeout(tick, 45000);
    return () => window.clearTimeout(timer);
  }, [checkUnlocks]);

  const running = progress?.running ?? false;

  async function syncAll() {
    try {
      await api.syncAll();
      toast.info("Sync started");
    } catch (e) {
      toast.error(String(e instanceof Error ? e.message : e));
      return;
    }
    setProgress((p) => (p ? { ...p, running: true } : p));
    const p = await api.syncProgress().catch(() => null);
    if (p) setProgress(p);
  }

  return (
    <div className="min-h-screen">
      <AppBackground />
      <div className="mx-auto max-w-6xl px-3 py-4 sm:px-4 sm:py-6">
        <div className="mb-4 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Trophy size={20} className="text-accent" />
            <span className="text-lg font-bold tracking-tight text-slate-100">Achievist</span>
          </div>
          <button
            onClick={logout}
            title={`Log out (${user.username})`}
            className="inline-flex items-center gap-1.5 rounded-lg border border-line/40 bg-ink-900/40 px-2.5 py-1.5 text-xs font-medium text-muted backdrop-blur-sm transition hover:bg-ink-800/60 hover:text-slate-200"
          >
            <LogOut size={13} />
            {user.username}
          </button>
        </div>

        {summary && <SummaryBar summary={summary} />}

        <div className="mt-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <Nav
            tab={tab}
            onChange={(t) => {
              setTab(t);
              navigate("/");
              if (t === "accounts") loadAccountErrors();
            }}
            accountErrors={accountErrors}
          />
          <button
            onClick={syncAll}
            disabled={running}
            className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white transition hover:bg-accent/90 disabled:opacity-60 sm:w-auto"
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
          <Routes>
            <Route path="/games/:id" element={<GameDetailPage />} />
            <Route
              path="*"
              element={
                <>
                  {tab === "games" && <GamesPage summary={summary} />}
                  {tab === "achievements" && <AchievementsPage />}
                  {tab === "activity" && <ActivityPage />}
                  {tab === "accounts" && <AccountsPage />}
                  {tab === "leaderboard" && <LeaderboardPage />}
                  {tab === "maintenance" && <MaintenancePage isAdmin={user.is_admin} />}
                  {tab === "statistics" && (
                    <Suspense fallback={<div className="py-16 text-center text-muted">Loading…</div>}>
                      <StatisticsPage />
                    </Suspense>
                  )}
                </>
              }
            />
          </Routes>
        </div>
      </div>
      <BackToTop />
    </div>
  );
}
