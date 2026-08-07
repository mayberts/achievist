import { useEffect, useState } from "react";
import { X, Check, Lock, Trophy, ExternalLink } from "lucide-react";
import { api } from "../api";
import type { GameComparison } from "../types";
import { platformLabel } from "../lib/platforms";
import { RARITY_TIER_CLASS, rarityTier } from "../lib/rarity";
import { guideSearchUrl } from "../lib/guideLink";
import { fmtDate } from "../lib/format";

export function GameCompareModal({
  platformGameId,
  onClose,
}: {
  platformGameId: number;
  onClose: () => void;
}) {
  const [data, setData] = useState<GameComparison | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.compareGame(platformGameId)
      .then(setData)
      .catch((e) => setError(String(e instanceof Error ? e.message : e)));
  }, [platformGameId]);

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-2xl flex-col overflow-hidden rounded-card border border-line bg-ink-850 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line p-4">
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold text-slate-100">
              {data ? data.game.name : "Loading…"}
            </h2>
            {data && <div className="text-xs text-faint">{platformLabel(data.game.platform)}</div>}
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-muted transition hover:bg-ink-800 hover:text-slate-200">
            <X size={18} />
          </button>
        </div>

        <div className="overflow-y-auto">
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
                        href={a.guide_url || guideSearchUrl(data.game.platform, data.game.name, a.name)}
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
