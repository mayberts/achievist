import { describe, expect, it } from "vitest";
import { PLATFORM_META, platformLabel } from "./platforms";

const game = (over: Partial<{ platform_app_id: string; store_id: string | null; name: string }> = {}) => ({
  platform_app_id: "12345",
  store_id: null,
  name: "Some Game",
  ...over,
});

describe("platformLabel", () => {
  it("gives the display name for a known platform", () => {
    expect(platformLabel("retroachievements")).toBe("Retro");
    expect(platformLabel("googleplay")).toBe("Google Play");
  });

  it("echoes the key back for one it doesn't know", () => {
    // a platform added server-side shows up as its raw key rather than blank
    expect(platformLabel("dreamcast")).toBe("dreamcast");
  });
});

describe("store links", () => {
  it("deep-links Steam by app id", () => {
    expect(PLATFORM_META.steam.storeUrl!(game({ platform_app_id: "220" }))).toBe(
      "https://store.steampowered.com/app/220",
    );
  });

  it("deep-links Google Play by package name", () => {
    expect(PLATFORM_META.googleplay.storeUrl!(game({ platform_app_id: "com.mojang.minecraftpe" }))).toBe(
      "https://play.google.com/store/apps/details?id=com.mojang.minecraftpe",
    );
  });

  it("links Roblox by root place id, not by the universe id it is keyed on", () => {
    // platform_app_id is the universe id, which is not what a game URL takes
    const url = PLATFORM_META.roblox.storeUrl!(game({ platform_app_id: "100", store_id: "200" }));
    expect(url).toBe("https://www.roblox.com/games/200");
  });

  it("falls back to a Roblox search when the place id is missing", () => {
    const url = PLATFORM_META.roblox.storeUrl!(game({ platform_app_id: "100", store_id: null, name: "Cool Game" }));
    expect(url).toContain("/discover/");
    expect(url).toContain("Cool%20Game");
  });

  it("escapes a name so it can't break out of the query string", () => {
    const url = PLATFORM_META.gog.storeUrl!(game({ name: "Baldur's Gate & Co" }));
    // the ampersand is the dangerous one — an unescaped one would start a new
    // query parameter. An apostrophe is legal in a query value, and
    // encodeURIComponent leaves it as-is.
    expect(url).toContain("%26");
    expect(url).toBe("https://www.gog.com/games?query=Baldur's%20Gate%20%26%20Co");
  });

  it("marks search links as searches so the UI can say so", () => {
    expect(PLATFORM_META.gog.storeUrlIsSearch).toBe(true);
    expect(PLATFORM_META.steam.storeUrlIsSearch).toBeFalsy();
  });

  it("gives every platform a label and a badge colour", () => {
    for (const [key, meta] of Object.entries(PLATFORM_META)) {
      expect(meta.label, `label for ${key}`).toBeTruthy();
      expect(meta.badge, `badge for ${key}`).toBeTruthy();
      expect(meta.dot, `dot for ${key}`).toMatch(/^#[0-9a-f]{6}$/i);
    }
  });
});
