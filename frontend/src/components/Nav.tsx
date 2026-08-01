import { Gamepad2, Settings2, BarChart3, Activity } from "lucide-react";

export type Tab = "games" | "activity" | "accounts" | "statistics";

const TABS: { key: Tab; label: string; icon: React.ReactNode }[] = [
  { key: "games", label: "Games", icon: <Gamepad2 size={16} /> },
  { key: "activity", label: "Activity", icon: <Activity size={16} /> },
  { key: "accounts", label: "Accounts", icon: <Settings2 size={16} /> },
  { key: "statistics", label: "Statistics", icon: <BarChart3 size={16} /> },
];

export function Nav({ tab, onChange }: { tab: Tab; onChange: (t: Tab) => void }) {
  return (
    <nav className="flex gap-1">
      {TABS.map((t) => (
        <button
          key={t.key}
          onClick={() => onChange(t.key)}
          className={`inline-flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition ${
            tab === t.key
              ? "bg-ink-800 text-slate-100"
              : "text-muted hover:bg-ink-850 hover:text-slate-200"
          }`}
        >
          {t.icon}
          {t.label}
        </button>
      ))}
    </nav>
  );
}
