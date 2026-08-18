import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { LoginScreen } from "./LoginScreen";

vi.mock("../api", () => ({ api: { login: vi.fn(), authSetup: vi.fn() } }));

/**
 * The login labels were plain text sitting above their inputs, not tied to
 * them, so a screen reader announced two anonymous edit boxes. getByLabelText
 * only resolves through a real label association, which is what makes these
 * assertions worth writing rather than querying by placeholder.
 */
describe("LoginScreen labels", () => {
  it("associates both fields with their labels", () => {
    render(<LoginScreen needsSetup={false} onAuthenticated={vi.fn()} />);
    expect(screen.getByLabelText("Username")).toBeTruthy();
    expect(screen.getByLabelText("Password")).toBeTruthy();
  });

  it("tells a password manager which field is which", () => {
    render(<LoginScreen needsSetup={false} onAuthenticated={vi.fn()} />);
    expect(screen.getByLabelText("Username").getAttribute("autocomplete")).toBe("username");
    expect(screen.getByLabelText("Password").getAttribute("autocomplete")).toBe("current-password");
  });

  it("asks for a new password during first-run setup, not the saved one", () => {
    render(<LoginScreen needsSetup onAuthenticated={vi.fn()} />);
    expect(screen.getByLabelText("Password").getAttribute("autocomplete")).toBe("new-password");
  });
});
