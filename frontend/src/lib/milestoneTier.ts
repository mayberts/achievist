// Badge tiers for milestones. A separate axis from achievement rarity (see
// lib/rarity.ts) — rarity says how few people have an unlock, a milestone tier
// says how far into the grind a landmark sits — so the two palettes are kept
// deliberately distinct rather than shared.
//
// Tier names come from the server (app/milestones.py) so the badge shown always
// matches the points awarded; anything unrecognised falls back to neutral.
export interface MilestoneTierStyle {
  label: string;
  /** Text colour for the tier name and the threshold chips. */
  text: string;
  /** Background + border for the badge pill. */
  pill: string;
}

export const MILESTONE_TIER: Record<string, MilestoneTierStyle> = {
  bronze: { label: "Bronze", text: "text-[#d08b52]", pill: "bg-[#d08b52]/15 border-[#d08b52]/40" },
  silver: { label: "Silver", text: "text-[#c3ccd8]", pill: "bg-[#c3ccd8]/15 border-[#c3ccd8]/40" },
  gold: { label: "Gold", text: "text-[#f0b429]", pill: "bg-[#f0b429]/15 border-[#f0b429]/40" },
  platinum: { label: "Platinum", text: "text-[#7fd4e8]", pill: "bg-[#7fd4e8]/15 border-[#7fd4e8]/40" },
  diamond: { label: "Diamond", text: "text-[#b9a7ff]", pill: "bg-[#b9a7ff]/15 border-[#b9a7ff]/40" },
};

const NEUTRAL: MilestoneTierStyle = {
  label: "Milestone",
  text: "text-muted",
  pill: "bg-ink-800 border-line",
};

export function milestoneTier(tier: string | null | undefined): MilestoneTierStyle {
  return (tier && MILESTONE_TIER[tier]) || NEUTRAL;
}
