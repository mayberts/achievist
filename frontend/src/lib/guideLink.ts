// TrueAchievements/TrueSteamAchievements (same company, same URL scheme —
// TSA for Steam, TA for Xbox) key their game pages off a simple slug of the
// game's name, e.g. "Borderlands" -> /game/Borderlands/achievements.
//
// The backend also tries to scrape these pages server-side (see
// app/platforms/trueachievements.py) to find the *exact* per-achievement
// link, but TA/TSA's bot protection blocks server-to-server requests —
// visiting the same guessed URL from your own browser works fine. So this
// client-side guess is a legitimate middle tier, not just a last resort:
// prefer a server-confirmed link when one exists (it's an exact
// achievement-level link), otherwise guess the game's page directly rather
// than jumping straight to a Google search.
function slugify(name: string): string {
  let expanded = name;
  for (const [pattern, replacement] of Object.entries(ABBREVIATION_EXPANSIONS)) {
    expanded = expanded.replace(new RegExp(pattern, "gi"), replacement);
  }
  return expanded
    .normalize("NFKD")
    .replace(/[™®©]/g, "")
    .replace(/['’]/g, "")
    .replace(/[^a-zA-Z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

// Mirrors app/platforms/trueachievements.py's _ABBREVIATION_EXPANSIONS —
// keep the two in sync when adding entries.
const ABBREVIATION_EXPANSIONS: Record<string, string> = {
  "\\bGOTY\\b": "Game of the Year",
  "\\bGOTYE\\b": "Game of the Year Edition",
  "\\bDE\\b": "Definitive Edition",
};

const DIRECT_GAME_PAGE: Record<string, (slug: string) => string> = {
  steam: (slug) => `https://truesteamachievements.com/game/${slug}/achievements`,
  xbox: (slug) => `https://www.trueachievements.com/game/${slug}/achievements`,
};

export function gameDirectUrl(platform: string, gameName: string): string | null {
  const direct = DIRECT_GAME_PAGE[platform];
  return direct ? direct(slugify(gameName)) : null;
}

// True last resort — used when there's no server-confirmed link and no
// direct-guess is possible for this platform (PSN/RetroAchievements key
// games by internal numeric ids, not names).
const GUIDE_SITE_BY_PLATFORM: Record<string, string> = {
  psn: "psnprofiles.com",
  retroachievements: "retroachievements.org",
};

export function guideSearchUrl(platform: string, gameName: string, achievementName?: string | null): string {
  const site = GUIDE_SITE_BY_PLATFORM[platform];
  const terms = [gameName, achievementName, "achievement", "guide"].filter(Boolean).join(" ");
  const query = site ? `site:${site} ${gameName} ${achievementName ?? ""}`.trim() : terms;
  return `https://www.google.com/search?q=${encodeURIComponent(query)}`;
}
