import { defineConfig } from "@playwright/test";

// Starts its own API on a replay clock and its own Vite, on ports that don't clash with a running dev setup.
// Needs the database loaded with 2026-11-21's timetable and reports (see the README).
const API_PORT = 8010;
const WEB_PORT = 5183;
const REPLAY_FROM = process.env.SMOKE_REPLAY ?? "2026-11-21T14:40Z";

export default defineConfig({
  testDir: "e2e",
  testMatch: "*.e2e.ts",
  timeout: 60_000,
  use: { baseURL: `http://localhost:${WEB_PORT}`, channel: "chrome", trace: "off" },
  webServer: [
    {
      command: `uv run python src/api.py --clock replay:${REPLAY_FROM} --port ${API_PORT}`,
      cwd: "..", // where .env is
      url: `http://localhost:${API_PORT}/api/positions`,
      timeout: 60_000,
      reuseExistingServer: false,
    },
    {
      command: `pnpm exec vite --port ${WEB_PORT} --strictPort`,
      url: `http://localhost:${WEB_PORT}`,
      env: { TRAINTRACK_API: `http://localhost:${API_PORT}` },
      reuseExistingServer: false,
    },
  ],
});
