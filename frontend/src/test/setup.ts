import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// React Testing Library leaves the rendered tree in the document between
// tests unless told otherwise, which makes getByText ambiguous the moment two
// tests render the same component.
afterEach(cleanup);
