import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// In development the page is served on 5173 and the API calls go to FastAPI on 8000
const api = process.env.TRAINTRACK_API ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": { target: api, changeOrigin: true },
      "/tiles": { target: api, changeOrigin: true },
    },
  },
  build: { outDir: "dist", sourcemap: true },
  test: { environment: "node" },
});
