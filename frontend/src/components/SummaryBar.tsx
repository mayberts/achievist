import { useEffect, useState } from "react";
import { Trophy, Gamepad2, Crown, Clock, Target, User, Pencil } from "lucide-react";
import type { Profile, Summary } from "../types";
import { fmtNum, fmtPlaytime } from "../lib/format";
import { platformLabel } from "../lib/platforms";
import { api } from "../api";
import { ProfileEditModal } from "./ProfileEditModal";

function Stat({ icon, value, title }: { icon: React.ReactNode; value: string; title: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-slate-200" title={title}>
      <span className="text-faint">{icon}</span>
      <span className="font-semibold tabular-nums">{value}</span>
    </span>
  );
}

export function SummaryBar({ summary }: { summary: Summary }) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    api.profile()
      .then(setProfile)
      .catch(() => setProfile({ display_name: null, avatar_url: null }));
  }, []);

  const totalPlaytime = summary.by_platform.reduce(
    (acc, p) => acc + (p.total_playtime_minutes ?? 0),
    0,
  );
  const platforms = [...summary.by_platform].sort((a, b) => b.earned - a.earned);

  return (
    <div className="flex items-center gap-3 rounded-card border border-line/50 bg-ink-850/45 p-3 backdrop-blur-md sm:gap-4 sm:p-4">
      <button
        onClick={() => setEditing(true)}
        className="group relative flex h-12 w-12 flex-shrink-0 items-center justify-center overflow-hidden rounded-full bg-ink-700 text-muted sm:h-16 sm:w-16"
        title="Edit profile"
      >
        {profile?.avatar_url ? (
          <img src={profile.avatar_url} alt="" className="h-full w-full object-cover" />
        ) : (
          <>
            <User size={24} className="sm:hidden" />
            <User size={30} className="hidden sm:block" />
          </>
        )}
        <span className="absolute inset-0 hidden items-center justify-center bg-black/50 group-hover:flex">
          <Pencil size={16} className="text-slate-100" />
        </span>
      </button>
      <div className="min-w-0">
        <button
          onClick={() => setEditing(true)}
          className="group inline-flex items-center gap-1.5 text-lg font-bold text-slate-100 hover:text-slate-200"
        >
          {profile?.display_name || "Pantheon"}
          <Pencil size={13} className="text-faint opacity-0 transition group-hover:opacity-100" />
        </button>
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm">
          <Stat icon={<Trophy size={15} />} value={fmtNum(summary.total_earned)} title="Achievements earned" />
          <span className="h-4 w-px bg-line" />
          <Stat icon={<Target size={15} />} value={`${summary.overall_pct}%`} title="Overall completion" />
          <span className="h-4 w-px bg-line" />
          <Stat icon={<Gamepad2 size={15} />} value={fmtNum(summary.total_games)} title="Games" />
          <span className="h-4 w-px bg-line" />
          <Stat icon={<Crown size={15} />} value={fmtNum(summary.perfect_games)} title="Perfect games" />
          <span className="h-4 w-px bg-line" />
          <Stat icon={<Clock size={15} />} value={fmtPlaytime(totalPlaytime) ?? "0h"} title="Total playtime" />
        </div>
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {platforms.map((p) => (
            <span
              key={p.platform}
              className="rounded-md border border-line bg-ink-800 px-2 py-0.5 text-[11px] text-muted"
              title={`${platformLabel(p.platform)} — ${fmtNum(p.earned)} earned`}
            >
              {platformLabel(p.platform)} <span className="text-faint tabular-nums">{fmtNum(p.earned)}</span>
            </span>
          ))}
        </div>
      </div>

      {editing && profile && (
        <ProfileEditModal
          profile={profile}
          onClose={() => setEditing(false)}
          onSaved={setProfile}
        />
      )}
    </div>
  );
}
