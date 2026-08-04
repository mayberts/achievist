import { useEffect, useState } from "react";
import { Crown, Medal, Trophy, Gamepad2, CheckCircle2 } from "lucide-react";
import { api } from "../api";
import type { LeaderboardEntry, LeaderboardResponse } from "../types";
import { fmtNum } from "../lib/format";

const RANK_STYLE = [
  "border-amber-400/40 bg-amber-400/10 text-amber-300",
  "border-slate-300/30 bg-slate-300/10 text-slate-200",
  "border-orange-400/30 bg-orange-400/10 text-orange-300",
];

function RankBadge({ rank }: { rank: number }) {
  if (rank < 3) {
    return (
      <div
        className={`flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full border text-sm font-bold ${RANK_STYLE[rank]}`}
      >
        <Crown size={16} />
      </div>
    );
  }
  return (
    <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full border border-line bg-ink-800 text-sm font-bold text-muted">
      {rank + 1}
    </div>
  );
}

function Row({ entry, rank }: { entry: LeaderboardEntry; rank: number }) {
  return (
    <div className="flex items-center gap-3 rounded-card border border-line bg-ink-850 p-3.5 sm:p-4">
      <RankBadge rank={rank} />
      <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center overflow-hidden rounded-full bg-ink-700 text-muted">
        {entry.avatar_url ? (
          <img src={entry.avatar_url} alt="" className="h-full w-full object-cover" />
        ) : (
          <Medal size={18} />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate font-semibold text-slate-100">
          {entry.display_name || entry.username}
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
          <span className="inline-flex items-center gap-1">
            <Trophy size={12} /> {fmtNum(entry.achievements_unlocked)} unlocked
          </span>
          <span className="inline-flex items-center gap-1">
            <Gamepad2 size={12} /> {fmtNum(entry.games_played)} games
          </span>
          <span className="inline-flex items-center gap-1">
            <CheckCircle2 size={12} /> {fmtNum(entry.games_completed)} completed
          </span>
        </div>
      </div>
      <div className="flex-shrink-0 text-right">
        <div className="text-xl font-bold tabular-nums text-slate-100">{fmtNum(entry.achievist_points)}</div>
        <div className="text-[10px] uppercase tracking-wide text-faint">Achievist Pts</div>
      </div>
    </div>
  );
}

export function LeaderboardPage() {
  const [data, setData] = useState<LeaderboardResponse | null>(null);

  useEffect(() => {
    api.leaderboard().then(setData).catch(() => setData(null));
  }, []);

  if (!data) {
    return <div className="py-16 text-center text-muted">Loading…</div>;
  }

  const { entries, you_share } = data;

  return (
    <div>
      <div className="mb-2 text-lg font-semibold text-slate-100">Leaderboard</div>
      <p className="mb-5 text-sm text-muted">
        Achievist Points weight each unlock by how rare it is (Legendary unlocks are worth far more
        than common ones), so it stays fair across platforms and games. Only family members who've
        opted in to sharing are shown here — you always see your own row.
      </p>

      {!you_share && (
        <div className="mb-5 rounded-card border border-accent/30 bg-accent/10 px-4 py-3 text-sm text-slate-200">
          You're not sharing your stats yet — turn on <strong>Compare achievements with family</strong>{" "}
          from your profile (click your avatar above) so you show up for everyone else too.
        </div>
      )}

      {entries.length === 0 ? (
        <div className="rounded-card border border-line bg-ink-850 p-6 text-center text-sm text-muted">
          No data yet — connect and sync a platform to get on the board.
        </div>
      ) : (
        <div className="space-y-2.5">
          {entries.map((e, i) => (
            <Row key={e.user_id} entry={e} rank={i} />
          ))}
        </div>
      )}
    </div>
  );
}
