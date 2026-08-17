import { describe, expect, it } from "vitest";
import { MILESTONE_TIER, milestoneTier } from "./milestoneTier";

describe("milestoneTier", () => {
  it("styles each tier the server can send", () => {
    // mirrors app/milestones.py
    for (const tier of ["bronze", "silver", "gold", "platinum", "diamond"]) {
      const style = milestoneTier(tier);
      expect(style, tier).toBe(MILESTONE_TIER[tier]);
      expect(style.label, `label for ${tier}`).toBeTruthy();
      expect(style.text, `text class for ${tier}`).toBeTruthy();
      expect(style.pill, `pill class for ${tier}`).toBeTruthy();
    }
  });

  it("falls back to neutral rather than blowing up on an unknown tier", () => {
    // a new tier added server-side reaches an older frontend as a bare string
    const style = milestoneTier("mythic");
    expect(style.label).toBe("Milestone");
    expect(style.text).toBeTruthy();
  });

  it("falls back when there is no tier at all", () => {
    expect(milestoneTier(null).label).toBe("Milestone");
    expect(milestoneTier(undefined).label).toBe("Milestone");
  });
});
