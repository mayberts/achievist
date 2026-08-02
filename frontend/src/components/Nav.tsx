import { Gamepad2, Settings2, BarChart3, Activity } from "lucide-react";

export type Tab = "games" | "activity" | "accounts" | "statistics";

const TABS: { key: Tab; label: string; icon: React.ReactNode }[] = [
  { key: "games", label: "Games", icon: <Gamepad2 size={16} /> },
  { key: "activity", label: "Activity", icon: <Activity size={16} /> },
  { key: "accounts", label: "Accounts", icon: <Settings2 size={16} /> },
  { key: "statistics", label: "Statistics", icon: <BarChart3 size={16} /> },
];

export function Nav({
  tab,
  onChange,
  accountErrors = 0,
}: {
  tab: Tab;
  onChange: (t: Tab) => void;
  accountErrors?: number;
}) {
  return (
    <nav className="flex gap-1">
      {TABS.map((t) => (
        <button
          key={t.key}
          onClick={() => onChange(t.key)}
          className={`relative inline-flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition ${
            tab === t.key
              ? "bg-ink-800 text-slate-100"
              : "text-muted hover:bg-ink-850 hover:text-slate-200"
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
  );
}
