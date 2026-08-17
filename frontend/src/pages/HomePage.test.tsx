import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ChaseListItem, MilestonesResponse, MilestoneTrack } from "../types";

vi.mock("../api", () => ({
  api: {
    accounts: vi.fn(),
    milestones: vi.fn(),
    games: vi.fn(),
    chaseList: vi.fn(),
  },
}));

// imported after the mock so HomePage picks up the stub
const { api } = await import("../api");
const { HomePage } = await import("./HomePage");

const emptyTrack = (over: Partial<MilestoneTrack> = {}): MilestoneTrack => ({
  reached: [],
  next: { threshold: 100, current: 0, remaining: 100, tier: "bronze", points: 100 },
  points_earned: 0,
  ...over,
});

const milestones = (over: Partial<MilestonesResponse> = {}): MilestonesResponse => ({
  achievements: emptyTrack(),
  mastered: emptyTrack(),
  ...over,
});

function setup({
  accounts = [{ id: 1 }],
  milestonesData = milestones(),
  games = { games: [] },
  chase = [] as ChaseListItem[],
}: {
  accounts?: unknown[];
  milestonesData?: MilestonesResponse | null;
  games?: { games: unknown[] };
  chase?: ChaseListItem[];
} = {}) {
  vi.mocked(api.accounts).mockResolvedValue(accounts as never);
  vi.mocked(api.milestones).mockResolvedValue(milestonesData as never);
  vi.mocked(api.games).mockResolvedValue(games as never);
  vi.mocked(api.chaseList).mockResolvedValue(chase as never);
  return render(
    <MemoryRouter>
      <HomePage />
    </MemoryRouter>,
  );
}

beforeEach(() => vi.clearAllMocks());

describe("milestone wording", () => {
  it("says '1 game mastered', not '1 games mastered'", async () => {
    // the first mastered milestone is 1, so this is the state most accounts
    // hit first — it shipped reading "1 games mastered"
    setup({
      milestonesData: milestones({
        mastered: emptyTrack({
          reached: [
            {
              threshold: 1,
              tier: "bronze",
              points: 100,
              reached_at: "2026-01-01T00:00:00Z",
              achievement_name: null,
              game_name: "Some Game",
              platform: "steam",
              icon_url: null,
            },
          ],
          points_earned: 100,
        }),
      }),
    });

    expect(await screen.findByText("game mastered")).toBeInTheDocument();
    expect(screen.queryByText("games mastered")).not.toBeInTheDocument();
  });

  it("pluralises above one", async () => {
    setup({
      milestonesData: milestones({
        mastered: emptyTrack({
          reached: [
            {
              threshold: 5,
              tier: "bronze",
              points: 500,
              reached_at: "2026-01-01T00:00:00Z",
              achievement_name: null,
              game_name: "Some Game",
              platform: "steam",
              icon_url: null,
            },
          ],
          points_earned: 600,
        }),
      }),
    });

    expect(await screen.findByText("games mastered")).toBeInTheDocument();
  });

  it("uses the singular for a lone achievement milestone too", async () => {
    setup({
      milestonesData: milestones({
        achievements: emptyTrack({
          reached: [
            {
              threshold: 1,
              tier: "bronze",
              points: 1,
              reached_at: "2026-01-01T00:00:00Z",
              achievement_name: "First",
              game_name: "Some Game",
              platform: "steam",
              icon_url: null,
            },
          ],
          points_earned: 1,
        }),
      }),
    });

    expect(await screen.findByText("achievement")).toBeInTheDocument();
  });
});

describe("chase list", () => {
  const item = (over: Partial<ChaseListItem>): ChaseListItem => ({
    platform_game_id: 1,
    platform_ach_id: "a",
    name: "Some Achievement",
    icon_url: null,
    rarity_pct: 4.2,
    game_name: "Some Game",
    platform: "steam",
    ...over,
  });

  it("renders what the server sends, in the order it sends it", async () => {
    setup({
      chase: [
        item({ platform_ach_id: "a", name: "Rarest", rarity_pct: 0.5 }),
        item({ platform_ach_id: "b", name: "Less rare", rarity_pct: 30 }),
      ],
    });

    expect(await screen.findByText("Rarest")).toBeInTheDocument();
    const names = screen.getAllByText(/Rarest|Less rare/).map((n) => n.textContent);
    expect(names).toEqual(["Rarest", "Less rare"]);
  });

  it("spans several games rather than showing one game's list", async () => {
    // a single achievement-farm title used to fill every slot
    setup({
      chase: [
        item({ platform_ach_id: "p1", name: "Puzzle 1", game_name: "Pixel Puzzles", rarity_pct: 0 }),
        item({ platform_ach_id: "p2", name: "Puzzle 2", game_name: "Pixel Puzzles", rarity_pct: 0 }),
        item({ platform_ach_id: "r1", name: "Outlaw", game_name: "Red Dead", rarity_pct: 4.2 }),
      ],
    });

    await screen.findByText("Puzzle 1");
    expect(screen.getAllByText(/Pixel Puzzles/)).toHaveLength(2);
    expect(screen.getByText(/Red Dead/)).toBeInTheDocument();
  });

  it("is hidden entirely when there is nothing to chase", async () => {
    setup({ chase: [] });
    await waitFor(() => expect(api.chaseList).toHaveBeenCalled());
    expect(screen.queryByText(/Chase list/)).not.toBeInTheDocument();
  });
});

describe("empty states", () => {
  it("points a brand-new account at the Accounts tab instead of showing a blank page", async () => {
    setup({ accounts: [] });
    expect(await screen.findByText(/No accounts connected yet/)).toBeInTheDocument();
    // and none of the widgets render behind it
    expect(screen.queryByText(/Quick wins/)).not.toBeInTheDocument();
    expect(screen.queryByText(/milestones/i)).not.toBeInTheDocument();
  });

  it("nudges a connected but unsynced account to run a sync", async () => {
    setup({ accounts: [{ id: 1 }], chase: [], games: { games: [] } });
    expect(await screen.findByText(/Nothing synced yet/)).toBeInTheDocument();
  });

  it("keeps rendering the rest when one panel's request fails", async () => {
    // each panel is fetched separately, so one failure shouldn't blank the page
    vi.mocked(api.accounts).mockResolvedValue([{ id: 1 }] as never);
    vi.mocked(api.milestones).mockRejectedValue(new Error("boom"));
    vi.mocked(api.games).mockResolvedValue({ games: [] } as never);
    vi.mocked(api.chaseList).mockResolvedValue([
      {
        platform_game_id: 1,
        platform_ach_id: "a",
        name: "Still Here",
        icon_url: null,
        rarity_pct: 1,
        game_name: "Some Game",
        platform: "steam",
      },
    ] as never);

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Still Here")).toBeInTheDocument();
  });
});
