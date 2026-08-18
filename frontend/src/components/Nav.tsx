import { Gamepad2, Settings2, BarChart3, Activity, Wrench, Trophy, Crown, House } from "lucide-react";

export type Tab =
  | "home"
  | "games"
  | "achievements"
  | "activity"
  | "accounts"
  | "statistics"
  | "leaderboard"
  | "maintenance";

const TABS: { key: Tab; label: string; icon: React.ReactNode; adminOnly?: boolean }[] = [
  { key: "home", label: "Home", icon: <House size={16} /> },
  { key: "games", label: "Games", icon: <Gamepad2 size={16} /> },
  { key: "achievements", label: "Achievements", icon: <Trophy size={16} /> },
  { key: "activity", label: "Activity", icon: <Activity size={16} /> },
  { key: "accounts", label: "Accounts", icon: <Settings2 size={16} /> },
  { key: "statistics", label: "Statistics", icon: <BarChart3 size={16} /> },
  { key: "leaderboard", label: "Leaderboard", icon: <Crown size={16} /> },
  { key: "maintenance", label: "Maintenance", icon: <Wrench size={16} />, adminOnly: true },
];

export function visibleTabs(isAdmin: boolean): Tab[] {
  return TABS.filter((t) => !t.adminOnly || isAdmin).map((t) => t.key);
}

export function Nav({
  tab,
  onChange,
  accountErrors = 0,
  isAdmin = false,
}: {
  tab: Tab;
  onChange: (t: Tab) => void;
  accountErrors?: number;
  isAdmin?: boolean;
}) {
  const tabs = TABS.filter((t) => !t.adminOnly || isAdmin);
  return (
    <div className="relative -mx-3 sm:mx-0">
      {/* Scrolls sideways on mobile; wraps onto a second row on desktop.
          It used to be overflow-visible and nowrap above the sm breakpoint,
          which assumed the tabs always fit — once there were eight of them
          they did not, and the whole page scrolled sideways at 1024px. */}
      <nav className="flex flex-nowrap gap-1 overflow-x-auto px-3 sm:flex-wrap sm:overflow-visible sm:px-0">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => onChange(t.key)}
            aria-current={tab === t.key ? "page" : undefined}
            className={`relative inline-flex flex-shrink-0 items-center gap-2 rounded-lg border px-3.5 py-2 text-sm font-medium backdrop-blur-sm transition ${
              tab === t.key
                ? "border-accent/40 bg-accent/20 text-accent"
                : "border-line/40 bg-ink-900/40 text-muted hover:bg-ink-800/60 hover:text-slate-200"
            }`}
          >
            {t.icon}
            {t.label}
            {t.key === "accounts" && accountErrors > 0 && (
              <span
                className="absolute -right-1 -top-1 flex h-4 w-4 items-center justify-center rounded-full bg-red-500 text-[10px] font-bold text-white"
                title={`${accountErrors} account${accountErrors > 1 ? "s" : ""} with sync errors`}
              >
                {accountErrors}
              </span>
            )}
          </button>
        ))}
      </nav>
      {/* hint that the tab bar scrolls, on narrow screens only */}
      <div className="pointer-events-none absolute right-0 top-0 h-full w-8 bg-gradient-to-l from-ink-950 to-transparent sm:hidden" />
    </div>
  );
}
