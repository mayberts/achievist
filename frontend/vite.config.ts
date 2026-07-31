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
});
