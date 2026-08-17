/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Build output goes into app/webdist, which FastAPI serves as the SPA.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../app/webdist",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  test: {
    // jsdom rather than a real browser: these cover rendering and logic, which
    // is where the bugs have actually been. Anything that depends on real
    // layout (an element wrapping onto two lines, say) can't be caught here
    // and still needs looking at.
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
