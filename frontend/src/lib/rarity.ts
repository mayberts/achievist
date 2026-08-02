// Single source of truth for rarity-tier colors, shared between the game
// detail modal (Tailwind text classes) and the Statistics charts (hex values).
export const RARITY_TIER_HEX: Record<string, string> = {
  Legendary: "#fbbf24",
  Epic: "#e879f9",
  Rare: "#38bdf8",
  Uncommon: "#34d399",
  Common: "#94a3b8",
};

export const RARITY_TIER_CLASS: Record<string, string> = {
  Legendary: "text-amber-400",
  Epic: "text-fuchsia-400",
  Rare: "text-sky-400",
  Uncommon: "text-emerald-400",
  Common: "text-slate-400",
};

export function rarityTier(pct: number): string {
  if (pct <= 1) return "Legendary";
  if (pct <= 5) return "Epic";
  if (pct <= 20) return "Rare";
  if (pct <= 50) return "Uncommon";
  return "Common";
}
