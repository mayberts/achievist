import { describe, expect, it } from "vitest";
import { RARITY_TIER_CLASS, RARITY_TIER_HEX, rarityTier } from "./rarity";

/**
 * These boundaries are duplicated in the backend — app/db.py scores Achievist
 * Points off the same cut-offs and says so in a comment, and /api/statistics
 * buckets unlocks by them. Pinning them here means a change on this side
 * shows up as a failing test rather than as two halves of the app quietly
 * disagreeing about what "Epic" means.
 */
describe("rarityTier", () => {
  it("puts each boundary in the tier it names, inclusive of the upper bound", () => {
    expect(rarityTier(1)).toBe("Legendary");
    expect(rarityTier(5)).toBe("Epic");
    expect(rarityTier(20)).toBe("Rare");
    expect(rarityTier(50)).toBe("Uncommon");
  });

  it("puts anything above the last boundary in Common", () => {
    expect(rarityTier(50.1)).toBe("Common");
    expect(rarityTier(100)).toBe("Common");
  });

  it("treats a hair under a boundary as the rarer tier", () => {
    expect(rarityTier(0.9)).toBe("Legendary");
    expect(rarityTier(4.9)).toBe("Epic");
    expect(rarityTier(19.9)).toBe("Rare");
  });

  it("handles the rarest possible value", () => {
    expect(rarityTier(0)).toBe("Legendary");
  });
});

describe("tier styling", () => {
  it("has a colour and a class for every tier rarityTier can return", () => {
    const tiers = ["Legendary", "Epic", "Rare", "Uncommon", "Common"];
    for (const tier of tiers) {
      expect(RARITY_TIER_HEX[tier], `hex for ${tier}`).toBeTruthy();
      expect(RARITY_TIER_CLASS[tier], `class for ${tier}`).toBeTruthy();
    }
  });
});
