// TrueAchievements/TrueSteamAchievements (same company, same URL scheme —
// TSA for Steam, TA for Xbox) key their game pages off a simple slug of the
// game's name, e.g. "Borderlands" -> /game/Borderlands/achievements. Good
// enough for straightforward titles; unusual punctuation/subtitles can still
// miss, but it lands on the right site's search at worst.
function slugify(name: string): string {
  return name
    .normalize("NFKD")
    .replace(/[™®©]/g, "")
    .replace(/['’]/g, "")
    .replace(/[^a-zA-Z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

const DIRECT_GAME_PAGE: Record<string, (slug: string) => string> = {
  steam: (slug) => `https://truesteamachievements.com/game/${slug}/achievements`,
  xbox: (slug) => `https://www.trueachievements.com/game/${slug}/achievements`,
};

// For platforms without a reliable name-based URL (PSNProfiles/RetroAchievements
// key games by internal numeric ids we don't have), fall back to a Google
// search scoped to whichever site tends to have the best guides there, via
// the `site:` operator.
const GUIDE_SITE_BY_PLATFORM: Record<string, string> = {
  psn: "psnprofiles.com",
  retroachievements: "retroachievements.org",
};

export function guideSearchUrl(platform: string, gameName: string, achievementName?: string | null): string {
  const direct = DIRECT_GAME_PAGE[platform];
  if (direct) return direct(slugify(gameName));

  const site = GUIDE_SITE_BY_PLATFORM[platform];
  const terms = [gameName, achievementName, "achievement", "guide"].filter(Boolean).join(" ");
  const query = site ? `site:${site} ${gameName} ${achievementName ?? ""}`.trim() : terms;
  return `https://www.google.com/search?q=${encodeURIComponent(query)}`;
}
