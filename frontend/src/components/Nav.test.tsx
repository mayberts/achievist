import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { Nav, visibleTabs } from "./Nav";

/**
 * Maintenance acts on the whole install — the cover job overwrites everyone's
 * manually chosen art — so it must not be reachable from a non-admin account.
 */
describe("Nav", () => {
  it("hides the Maintenance tab from non-admins", () => {
    render(<Nav tab="home" onChange={vi.fn()} isAdmin={false} />);
    expect(screen.queryByRole("button", { name: /maintenance/i })).toBeNull();
    expect(screen.getByRole("button", { name: /home/i })).toBeTruthy();
  });

  it("shows it to admins", () => {
    render(<Nav tab="home" onChange={vi.fn()} isAdmin />);
    expect(screen.getByRole("button", { name: /maintenance/i })).toBeTruthy();
  });

  it("defaults to hiding it when isAdmin is not passed", () => {
    render(<Nav tab="home" onChange={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /maintenance/i })).toBeNull();
  });

  it("reports the same set through visibleTabs, which App uses to vet ?tab=", () => {
    expect(visibleTabs(false)).not.toContain("maintenance");
    expect(visibleTabs(true)).toContain("maintenance");
    // everything else is for everyone
    expect(visibleTabs(false)).toEqual(
      expect.arrayContaining(["home", "games", "achievements", "activity", "accounts", "statistics", "leaderboard"]),
    );
  });
});
