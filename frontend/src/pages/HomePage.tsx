import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Crown, Gamepad2, Medal, Target, Trophy, Zap } from "lucide-react";
import { api } from "../api";
import { platformLabel } from "../lib/platforms";
import { fmtDate, fmtRelative } from "../lib/format";
import { RARITY_TIER_CLASS, rarityTier } from "../lib/rarity";
import type { MilestoneTrack, MilestonesResponse } from "../types";

/**
 * The forward-looking half of the app: what to play next, what's nearly done,
 * and which landmarks you just passed. These panels started out bolted onto
 * the Statistics page, which turned out to be the wrong home for them —
 * Statistics is where you go to look back, not to decide what to do next.
 */

interface ChaseItem {
  platform_game_id: number;
  platform_ach_id: string;
  name: string | null;
  icon_url: string | null;
  rarity_pct: number;
  game_name: string;
  platform: string;
}

interface QuickWinItem {
  platform_game_id: number;
  name: string;
  platform: string;
  icon_url: string | null;
  earned_achievements: number;
  total_achievements: number;
  completion_pct: number;
  remaining: number;
}

// How many of the most-recently-played games to pull locked achievements
// from — keeps the list actionable (games you're actually in the middle of)
// rather than the rarest achievement in your entire library, which could be
// sitting in something you last touched years ago.
const CHASE_RECENT_GAMES = 5;

// A milestone crossed within this many days still reads as "just happened",
// and gets the celebratory treatment rather than being filed away as history.
const MILESTONE_FRESH_DAYS = 30;

function daysSince(iso: string): number {
  return (Date.now() - new Date(iso).getTime()) / 86_400_000;
}

function MilestoneTrackCard({
  label,
  unit,
  icon,
  track,
}: {
  label: string;
  // Takes the count because the first milestone in both tracks can be 1
  // ("1 game mastered", not "1 games mastered").
  unit: (n: number) => string;
  icon: React.ReactNode;
  track: MilestoneTrack;
}) {
  const latest = track.reached[0] ?? null;
  const older = track.reached.slice(1);
  const fresh = !!latest?.reached_at && daysSince(latest.reached_at) <= MILESTONE_FRESH_DAYS;
  const next = track.next;
  // Progress runs from zero rather than from the last milestone: "1,240 of
  // 2,500" is the number people actually track toward, and it keeps the bar
  // comparable between the two cards.
  const pct = next ? Math.min(100, (next.current / next.threshold) * 100) : 100;

  return (
    <div
      className={`rounded-card border bg-ink-850 p-4 ${
        fresh ? "border-accent/60 ring-1 ring-accent/25" : "border-line"
      }`}
    >
      <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-faint">
        {icon}
        {label}
      </div>

      {latest ? (
        <div className="mt-3 flex items-start gap-3">
          {latest.icon_url ? (
            <img src={latest.icon_url} alt="" className="h-10 w-10 shrink-0 rounded" />
          ) : (
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded bg-ink-800">
              <Trophy size={16} className="text-faint" />
            </div>
          )}
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="text-xl font-bold tabular-nums text-slate-100">
                {latest.threshold.toLocaleString()}
              </span>
              <span className="text-sm text-muted">{unit(latest.threshold)}</span>
              {fresh && (
                <span className="rounded-md bg-accent/20 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-accent">
                  New
                </span>
              )}
            </div>
            <div className="mt-0.5 truncate text-xs text-muted">
              {latest.achievement_name
                ? `${latest.achievement_name} · ${latest.game_name}`
                : latest.game_name ?? "milestone passed"}
            </div>
            {latest.reached_at && (
              <div className="mt-0.5 text-[11px] text-faint">
                {fresh ? fmtRelative(latest.reached_at) : fmtDate(latest.reached_at)}
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="mt-3 text-sm text-muted">No milestones yet — the first one's in reach.</div>
      )}

      {next && (
        <div className="mt-4">
          <div className="mb-1 flex items-baseline justify-between text-xs">
            <span className="text-muted">
              Next: <span className="font-semibold text-slate-200">{next.threshold.toLocaleString()}</span>
            </span>
            <span className="tabular-nums text-faint">{next.remaining.toLocaleString()} to go</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-ink-700">
            <div className="h-full rounded-full bg-accent-soft" style={{ width: `${pct}%` }} />
          </div>
        </div>
      )}

      {older.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {older.map((m) => (
            <span
              key={m.threshold}
              className="rounded-md bg-ink-800 px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-faint"
            >
              {m.threshold.toLocaleString()}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export function HomePage() {
  const [milestones, setMilestones] = useState<MilestonesResponse | null>(null);
  const [quickWins, setQuickWins] = useState<QuickWinItem[]>([]);
  const [chaseList, setChaseList] = useState<ChaseItem[]>([]);
  const [hasAnyAccount, setHasAnyAccount] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    const accounts = api
      .accounts()
      .then((a) => setHasAnyAccount(a.length > 0))
      .catch(() => setHasAnyAccount(null));

    const milestonesReq = api.milestones().then(setMilestones).catch(() => setMilestones(null));

    const wins = api
      .games({ sort: "completion", completion: "in_progress", page_size: 200 })
      .then((r) => {
        setQuickWins(
          r.games
            .map((g) => ({
              platform_game_id: g.platform_game_id,
              name: g.name,
              platform: g.platform,
              icon_url: g.icon_url,
              earned_achievements: g.earned_achievements,
              total_achievements: g.total_achievements,
              completion_pct: g.completion_pct,
              remaining: g.total_achievements - g.earned_achievements,
            }))
            .sort((a, b) => a.remaining - b.remaining)
            .slice(0, 8),
        );
      })
      .catch(() => setQuickWins([]));

    const chase = api
      .games({ sort: "recent", page_size: CHASE_RECENT_GAMES })
      .then(async (r) => {
        const recent = r.games.filter((g) => g.last_played_at && g.earned_achievements < g.total_achievements);
        const perGame = await Promise.all(
          recent.map(async (g) => {
            const achievements = await api.gameAchievements(g.platform_game_id).catch(() => []);
            // A game with a huge locked achievement list (e.g. an
            // achievement-farm title with thousands of near-0%-rarity
            // entries) would otherwise fill every slot on rarity alone —
            // cap each game's contribution so the list actually spans your
            // recently played games instead of just the spammiest one.
            return achievements
              .filter((a) => !a.unlocked && a.rarity_pct != null)
              .sort((a, b) => (a.rarity_pct as number) - (b.rarity_pct as number))
              .slice(0, 2)
              .map((a) => ({
                platform_game_id: g.platform_game_id,
                platform_ach_id: a.platform_ach_id,
                name: a.name,
                icon_url: a.icon_url,
                rarity_pct: a.rarity_pct as number,
                game_name: g.name,
                platform: g.platform,
              }));
          }),
        );
        setChaseList(perGame.flat().sort((a, b) => a.rarity_pct - b.rarity_pct).slice(0, 8));
      })
      .catch(() => setChaseList([]));

    Promise.allSettled([accounts, milestonesReq, wins, chase]).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="py-16 text-center text-muted">Loading…</div>;

  if (hasAnyAccount === false) {
    return (
      <div className="py-16 text-center">
        <Gamepad2 size={32} className="mx-auto mb-3 text-faint" />
        <div className="text-muted">No accounts connected yet.</div>
        <div className="mt-1 text-sm text-faint">Head to the Accounts tab to connect a platform.</div>
      </div>
    );
  }

  const nothingTracked =
    quickWins.length === 0 &&
    chaseList.length === 0 &&
    !milestones?.achievements.reached.length &&
    !milestones?.mastered.reached.length;

  return (
    <div className="space-y-6">
      {milestones && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <MilestoneTrackCard
            label="Achievement milestones"
            unit={(n) => (n === 1 ? "achievement" : "achievements")}
            icon={<Medal size={13} />}
            track={milestones.achievements}
          />
          <MilestoneTrackCard
            label="Mastered-game milestones"
            unit={(n) => (n === 1 ? "game mastered" : "games mastered")}
            icon={<Crown size={13} />}
            track={milestones.mastered}
          />
        </div>
      )}

      {nothingTracked && (
        <div className="rounded-card border border-line bg-ink-850 p-4 text-sm text-muted">
          Nothing synced yet — hit <span className="font-medium text-slate-200">Sync all</span> to pull in your
          library, and this page will fill up with what to play next.
        </div>
      )}

      {quickWins.length > 0 && (
        <div className="rounded-card border border-line bg-ink-850 p-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-200">
            <Zap size={15} className="text-faint" /> Quick wins
            <span className="font-normal text-faint">— closest to done</span>
          </div>
          <div className="space-y-2">
            {quickWins.map((g) => (
              <button
                key={g.platform_game_id}
                onClick={() => navigate(`/games/${g.platform_game_id}`)}
                className="flex w-full items-center gap-3 rounded-lg bg-ink-800 px-3 py-2 text-left transition hover:bg-ink-700"
              >
                {g.icon_url ? (
                  <img src={g.icon_url} alt="" className="h-8 w-8 shrink-0 rounded" />
                ) : (
                  <div className="h-8 w-8 shrink-0 rounded bg-ink-700" />
                )}
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-slate-100">{g.name}</div>
                  <div className="mt-1 flex items-center gap-2">
                    <div className="h-1.5 max-w-40 flex-1 overflow-hidden rounded-full bg-ink-900/80">
                      <div className="h-full rounded-full bg-accent-soft" style={{ width: `${g.completion_pct}%` }} />
                    </div>
                    <span className="shrink-0 text-[11px] text-muted">{platformLabel(g.platform)}</span>
                  </div>
                </div>
                <div className="shrink-0 text-right text-xs font-semibold text-slate-200">
                  {g.remaining} left
                  <div className="font-normal text-faint">{Math.round(g.completion_pct)}%</div>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {chaseList.length > 0 && (
        <div className="rounded-card border border-line bg-ink-850 p-4">
          <div className="mb-3 flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
              <Target size={15} className="text-faint" /> Chase list
              <span className="font-normal text-faint">— rarest locked, in what you're playing now</span>
            </div>
            <button
              onClick={() => navigate("/?tab=achievements&unlocked=false&sort=rarity")}
              className="shrink-0 text-xs text-muted transition hover:text-slate-200"
            >
              See rarest locked in your whole library →
            </button>
          </div>
          <div className="space-y-2">
            {chaseList.map((a) => (
              <button
                key={`${a.platform_game_id}-${a.platform_ach_id}`}
                onClick={() => navigate(`/games/${a.platform_game_id}`)}
                className="flex w-full items-center gap-3 rounded-lg bg-ink-800 px-3 py-2 text-left transition hover:bg-ink-700"
              >
                {a.icon_url ? (
                  <img src={a.icon_url} alt="" className="h-8 w-8 shrink-0 rounded grayscale" />
                ) : (
                  <div className="h-8 w-8 shrink-0 rounded bg-ink-700" />
                )}
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-slate-100">{a.name}</div>
                  <div className="truncate text-xs text-muted">
                    {a.game_name} · {platformLabel(a.platform)}
                  </div>
                </div>
                <div className={`shrink-0 text-xs font-semibold ${RARITY_TIER_CLASS[rarityTier(a.rarity_pct)]}`}>
                  {a.rarity_pct}%
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
