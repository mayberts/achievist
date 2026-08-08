import { useEffect, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Check, Lock, Trophy, ExternalLink } from "lucide-react";
import { api } from "../api";
import type { GameComparison } from "../types";
import { platformLabel } from "../lib/platforms";
import { RARITY_TIER_CLASS, rarityTier } from "../lib/rarity";
import { gameDirectUrl, guideSearchUrl } from "../lib/guideLink";
import { fmtDate } from "../lib/format";

export function GameComparePage() {
  const { id } = useParams<{ id: string }>();
  const platformGameId = Number(id);
  const [data, setData] = useState<GameComparison | null>(null);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    setData(null);
    setError(null);
    api.compareGame(platformGameId)
      .then(setData)
      .catch((e) => setError(String(e instanceof Error ? e.message : e)));
  }, [platformGameId]);

  function back() {
    if (location.key !== "default") navigate(-1);
    else navigate("/");
  }

  return (
    <div>
      <button
        onClick={back}
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted transition hover:text-slate-200"
      >
        <ArrowLeft size={15} /> Back to Leaderboard
      </button>

      <div className="rounded-card border border-line bg-ink-850">
        <div className="border-b border-line p-4">
          <h2 className="truncate text-base font-semibold text-slate-100">
            {data ? data.game.name : "Loading…"}
          </h2>
          {data && <div className="text-xs text-faint">{platformLabel(data.game.platform)}</div>}
        </div>

        <div className="overflow-x-auto">
          {error && <div className="p-4 text-sm text-red-300">{error}</div>}
          {!data && !error && <div className="py-16 text-center text-muted">Loading…</div>}

          {data && (
            <>
              {/* sticky header row naming each owner column */}
              <div className="sticky top-0 z-10 flex items-center gap-3 border-b border-line bg-ink-850 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-faint">
                <div className="flex-1">Achievement</div>
                {data.owners.map((o) => (
                  <div key={o.user_id} className="w-16 flex-shrink-0 truncate text-center" title={o.display_name || o.username}>
                    {o.display_name || o.username}
                  </div>
                ))}
              </div>

              <div className="divide-y divide-line">
                {data.achievements.map((a) => {
                  const tier = a.rarity_pct != null ? rarityTier(a.rarity_pct) : null;
                  return (
                    <div key={a.id} className="flex items-center gap-3 px-4 py-3">
                      <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center overflow-hidden rounded-lg bg-ink-700 text-muted">
                        {a.icon_url ? (
                          <img src={a.icon_url} alt="" className="h-full w-full object-cover" />
                        ) : (
                          <Trophy size={15} />
                        )}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium text-slate-100">{a.name || "Hidden achievement"}</div>
                        <div className="flex items-center gap-2 text-xs text-faint">
                          {tier && <span className={RARITY_TIER_CLASS[tier]}>{tier}</span>}
                          {a.points != null && <span>{a.points} pts</span>}
                        </div>
                      </div>
                      {data.owners.map((o) => {
                        const u = a.per_user.find((p) => p.user_id === o.user_id);
                        return (
                          <div key={o.user_id} className="flex w-16 flex-shrink-0 justify-center">
                            {u?.unlocked ? (
                              <span
                                className="flex h-6 w-6 items-center justify-center rounded-full bg-good/15 text-good"
                                title={u.unlocked_at ? fmtDate(u.unlocked_at) ?? undefined : undefined}
                              >
                                <Check size={13} />
                              </span>
                            ) : (
                              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-ink-800 text-faint">
                                <Lock size={11} />
                              </span>
                            )}
                          </div>
                        );
                      })}
                      <a
                        href={
                          a.guide_url ||
                          data.game.guide_url ||
                          gameDirectUrl(data.game.platform, data.game.name) ||
                          guideSearchUrl(data.game.platform, data.game.name, a.name)
                        }
                        target="_blank"
                        rel="noopener noreferrer"
                        title="Find a guide for this achievement"
                        className="flex-shrink-0 rounded-md p-1.5 text-faint transition hover:bg-ink-700 hover:text-accent"
                      >
                        <ExternalLink size={14} />
                      </a>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
