import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useModal } from "./useModal";

/**
 * Every modal in the app could previously only be dismissed with the mouse,
 * and focus stayed behind on the page underneath. These are the behaviours
 * that make one usable from a keyboard at all.
 */
function Dialog({ onClose }: { onClose: () => void }) {
  const { titleId, dialogProps } = useModal(onClose);
  return (
    <div {...dialogProps}>
      <h2 id={titleId}>Edit Profile</h2>
      <button>First</button>
      <button>Last</button>
    </div>
  );
}

function Harness({ onClose, open = true }: { onClose: () => void; open?: boolean }) {
  return (
    <>
      <button>Opener</button>
      {open && <Dialog onClose={onClose} />}
    </>
  );
}

describe("useModal", () => {
  it("labels the dialog by its heading", () => {
    render(<Harness onClose={vi.fn()} />);
    const dialog = screen.getByRole("dialog");
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    // getByRole with a name only resolves if aria-labelledby points at the h2
    expect(screen.getByRole("dialog", { name: "Edit Profile" })).toBe(dialog);
  });

  it("closes on Escape", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<Harness onClose={onClose} />);
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });

  it("moves focus into the dialog when it opens", () => {
    render(<Harness onClose={vi.fn()} />);
    expect(document.activeElement).toBe(screen.getByRole("dialog"));
  });

  it("returns focus to whatever opened it", () => {
    const { rerender } = render(<Harness onClose={vi.fn()} open={false} />);
    const opener = screen.getByRole("button", { name: "Opener" });
    opener.focus();
    expect(document.activeElement).toBe(opener);

    rerender(<Harness onClose={vi.fn()} open />);
    expect(document.activeElement).toBe(screen.getByRole("dialog"));

    // Closing must not drop focus on <body>, which would send the next Tab
    // back to the top of the page instead of where the user was.
    rerender(<Harness onClose={vi.fn()} open={false} />);
    expect(document.activeElement).toBe(opener);
  });

  it("keeps Tab inside the dialog", async () => {
    const user = userEvent.setup();
    render(<Harness onClose={vi.fn()} />);
    const first = screen.getByRole("button", { name: "First" });
    const last = screen.getByRole("button", { name: "Last" });

    last.focus();
    await user.keyboard("{Tab}");
    // without the trap this would land on "Opener", outside the dialog
    expect(document.activeElement).toBe(first);

    await user.keyboard("{Shift>}{Tab}{/Shift}");
    expect(document.activeElement).toBe(last);
  });
});
