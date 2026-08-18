import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { CommandPalette, hrefFor, toResults } from "./CommandPalette";
import type { AchievementSearchResult, Game } from "../types";

const navigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return { ...actual, useNavigate: () => navigate };
});

const games = vi.fn();
const searchAchievements = vi.fn();
vi.mock("../api", () => ({
  api: {
    games: (...a: unknown[]) => games(...a),
    searchAchievements: (...a: unknown[]) => searchAchievements(...a),
  },
}));

const GAME = {
  platform_game_id: 7,
  platform: "steam",
  name: "Hollow Knight",
  icon_url: null,
  sgdb_cover_url: null,
  completion_pct: 42.4,
} as unknown as Game;

const ACH = {
  platform_game_id: 9,
  platform_ach_id: "abc",
  platform: "xbox",
  name: "Hollow Victory",
  game_name: "Some Other Game",
  icon_url: null,
  rarity_pct: 1.2,
} as unknown as AchievementSearchResult;

function setup() {
  games.mockResolvedValue({ games: [GAME] });
  searchAchievements.mockResolvedValue({ achievements: [ACH] });
  return render(
    <MemoryRouter>
      <CommandPalette />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("CommandPalette", () => {
  it("spells the shortcut Ctrl, never with a command glyph", () => {
    setup();
    expect(screen.getByText("Ctrl K")).toBeTruthy();
    // This household is on Windows. A stray ⌘ anywhere in the palette is a bug.
    expect(document.body.textContent).not.toContain("⌘");
    expect(document.body.textContent).not.toContain("Cmd");
  });

  it("does not grab focus when the page loads", () => {
    // The focus-restore effect also runs on mount, where the palette is
    // already closed. Restoring unconditionally put focus on the trigger on
    // every page load, which pushed the first Tab past the skip link.
    setup();
    expect(document.activeElement).toBe(document.body);
  });

  it("returns focus to the trigger after it has been opened and closed", async () => {
    const user = userEvent.setup();
    setup();
    await user.keyboard("{Control>}k{/Control}");
    await user.keyboard("{Escape}");
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: /search games and achievements/i }),
    );
  });

  it("opens on Ctrl+K and closes on Escape", async () => {
    const user = userEvent.setup();
    setup();
    expect(screen.queryByRole("dialog")).toBeNull();

    await user.keyboard("{Control>}k{/Control}");
    expect(screen.getByRole("dialog")).toBeTruthy();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("searches both games and achievements and lists them together", async () => {
    const user = userEvent.setup();
    setup();
    await user.click(screen.getByRole("button", { name: /search games and achievements/i }));
    await user.type(screen.getByRole("textbox"), "hollow");

    await waitFor(() => expect(screen.getByText("Hollow Knight")).toBeTruthy());
    expect(screen.getByText("Hollow Victory")).toBeTruthy();
    expect(games).toHaveBeenCalledWith(expect.objectContaining({ search: "hollow" }));
    expect(searchAchievements).toHaveBeenCalledWith(expect.objectContaining({ q: "hollow" }));
  });

  it("does not search on a single character", async () => {
    const user = userEvent.setup();
    setup();
    await user.keyboard("{Control>}k{/Control}");
    await user.type(screen.getByRole("textbox"), "h");
    await new Promise((r) => setTimeout(r, 350));
    expect(games).not.toHaveBeenCalled();
  });

  it("opens the highlighted result on Enter", async () => {
    const user = userEvent.setup();
    setup();
    await user.keyboard("{Control>}k{/Control}");
    await user.type(screen.getByRole("textbox"), "hollow");
    await waitFor(() => expect(screen.getByText("Hollow Knight")).toBeTruthy());

    await user.keyboard("{Enter}");
    expect(navigate).toHaveBeenCalledWith("/games/7");
  });

  it("arrow keys move down the combined list, into the achievements", async () => {
    const user = userEvent.setup();
    setup();
    await user.keyboard("{Control>}k{/Control}");
    await user.type(screen.getByRole("textbox"), "hollow");
    await waitFor(() => expect(screen.getByText("Hollow Victory")).toBeTruthy());

    await user.keyboard("{ArrowDown}{Enter}");
    // the achievement's own game, not the game result above it
    expect(navigate).toHaveBeenCalledWith("/games/9");
  });
});

describe("toResults", () => {
  it("keys achievements by game as well as achievement id", () => {
    const same = { ...ACH, platform_ach_id: "complete" };
    const [a, b] = toResults(
      [],
      [
        { ...same, platform_game_id: 1 },
        { ...same, platform_game_id: 2 },
      ] as AchievementSearchResult[],
    );
    // Two games can both have a "complete" achievement; unkeyed by game they
    // would collide and React would drop one.
    expect(a.id).not.toEqual(b.id);
  });

  it("sends an achievement to the game it belongs to", () => {
    const [r] = toResults([], [ACH]);
    expect(hrefFor(r)).toBe("/games/9");
  });
});
