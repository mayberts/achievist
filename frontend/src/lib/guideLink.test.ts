import { describe, expect, it } from "vitest";
import { guideUrl, steamGuidesUrl } from "./guideLink";

/**
 * The guide waterfall used to be pasted inline at three call sites, and had
 * drifted: the achievements list skipped the game-level tier entirely. These
 * pin the order down in one place.
 *
 * The motivating complaint: TA/TSA only have guides for popular games, so
 * the name-derived slug lands on a real page with nothing on it. Steam
 * Community Guides go far deeper and, because we hold the appid, the link is
 * exact rather than guessed.
 */

const BASE = { platform: "steam", gameName: "Hollow Knight", achievementName: "Speed Completion" };

describe("steamGuidesUrl", () => {
  it("builds a guides link from the appid", () => {
    expect(steamGuidesUrl("367520")).toBe("https://steamcommunity.com/app/367520/guides/");
  });

  it("gives up rather than building a broken link when there is no appid", () => {
    expect(steamGuidesUrl(null)).toBeNull();
    expect(steamGuidesUrl(undefined)).toBeNull();
    expect(steamGuidesUrl("")).toBeNull();
  });
});

describe("guideUrl ordering", () => {
  it("prefers a server-confirmed achievement link above everything", () => {
    const url = guideUrl({
      ...BASE,
      appId: "367520",
      achievementGuideUrl: "https://truesteamachievements.com/a/exact",
      gameGuideUrl: "https://truesteamachievements.com/game/whatever",
    });
    expect(url).toBe("https://truesteamachievements.com/a/exact");
  });

  it("falls to the game-level confirmed link next", () => {
    const url = guideUrl({ ...BASE, appId: "367520", gameGuideUrl: "https://tsa/game" });
    expect(url).toBe("https://tsa/game");
  });

  it("prefers Steam Community Guides over the guessed TSA slug", () => {
    // The whole point of the change: the slug is derived from the name and
    // can land on the wrong game or a page with no guide; the appid cannot.
    const url = guideUrl({ ...BASE, appId: "367520" });
    expect(url).toBe("https://steamcommunity.com/app/367520/guides/");
  });

  it("still falls back to TSA for a Steam game with no appid", () => {
    const url = guideUrl({ ...BASE, appId: null });
    expect(url).toContain("truesteamachievements.com");
  });

  it("leaves Xbox on TrueAchievements — Steam guides do not apply", () => {
    const url = guideUrl({ platform: "xbox", gameName: "Halo Infinite", appId: "12345" });
    expect(url).toContain("trueachievements.com");
    expect(url).not.toContain("steamcommunity.com");
  });

  it("leaves PSN on its existing site-scoped search", () => {
    const url = guideUrl({ platform: "psn", gameName: "Bloodborne", achievementName: "Moon Presence" });
    expect(url).toContain("google.com/search");
    expect(decodeURIComponent(url)).toContain("site:psnprofiles.com");
  });

  it("escapes an appid rather than pasting it into the path raw", () => {
    const url = steamGuidesUrl("../../evil");
    expect(url).not.toContain("../..");
  });
});
