import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ProfileEditModal } from "./ProfileEditModal";

vi.mock("../api", () => ({ api: { updateProfile: vi.fn() } }));
vi.mock("./Toast", () => ({ useToast: () => ({ success: vi.fn(), error: vi.fn() }) }));

const profile = {
  display_name: "Sam",
  avatar_url: null,
  background_url: null,
  share_stats: true,
};

/**
 * Export used to live on the Maintenance tab. Hiding that tab from non-admins
 * would have taken away their only way to get their own data out, so this
 * asserts it now hangs off the profile, which every account can open.
 */
describe("ProfileEditModal", () => {
  it("offers a download of your own data", () => {
    render(<ProfileEditModal profile={profile} onClose={vi.fn()} onSaved={vi.fn()} />);
    const link = screen.getByRole("link", { name: /export my data/i });
    expect(link.getAttribute("href")).toBe("/api/export");
    expect(link.hasAttribute("download")).toBe(true);
  });
});
