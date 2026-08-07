// This is the *last-resort* fallback, used only when the backend hasn't
// (yet, or ever) confirmed a real TrueSteamAchievements/TrueAchievements
// link for this achievement/game — see app/platforms/trueachievements.py.
// Guessing a game's TSA/TA slug client-side from our own stored name isn't
// safe to link to directly: edition/subtitle abbreviations (Steam's
// "Borderlands GOTY Enhanced" vs. TSA's "Borderlands: Game of the Year
// Enhanced") mean an unconfirmed guess is wrong often enough to land on a
// dead page. A scoped Google search always lands on *something* relevant.
const GUIDE_SITE_BY_PLATFORM: Record<string, string> = {
  steam: "truesteamachievements.com",
  xbox: "trueachievements.com",
  psn: "psnprofiles.com",
  retroachievements: "retroachievements.org",
};

export function guideSearchUrl(platform: string, gameName: string, achievementName?: string | null): string {
  const site = GUIDE_SITE_BY_PLATFORM[platform];
  const terms = [gameName, achievementName, "achievement", "guide"].filter(Boolean).join(" ");
  const query = site ? `site:${site} ${gameName} ${achievementName ?? ""}`.trim() : terms;
  return `https://www.google.com/search?q=${encodeURIComponent(query)}`;
}
