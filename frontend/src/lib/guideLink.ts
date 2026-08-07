// Achievist doesn't have (and won't try to maintain) a mapping of every
// achievement to a specific guide page — instead this builds a Google
// search scoped to whichever site tends to have the best guides for that
// platform, via the `site:` operator. Falls back to a plain search for
// platforms with no obvious go-to site.
const GUIDE_SITE_BY_PLATFORM: Record<string, string> = {
  xbox: "trueachievements.com",
  psn: "psnprofiles.com",
  steam: "steamcommunity.com",
  retroachievements: "retroachievements.org",
};

export function guideSearchUrl(platform: string, gameName: string, achievementName?: string | null): string {
  const site = GUIDE_SITE_BY_PLATFORM[platform];
  const terms = [gameName, achievementName, "achievement", "guide"].filter(Boolean).join(" ");
  const query = site ? `site:${site} ${gameName} ${achievementName ?? ""}`.trim() : terms;
  return `https://www.google.com/search?q=${encodeURIComponent(query)}`;
}
