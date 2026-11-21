import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vitest/config";

const WORKER_PATH = "maplibre/maplibre-gl-worker.mjs";

/**
 * MapLibre 6 runs its tiles in a module worker loaded from a file next to its own. Vite's dev server rewrites that
 * file (adding its client, which can't run in a worker), so this serves the file untouched in development, adds it
 * to the build as-is, and the page points MapLibre at it (src/main.tsx).
 */
function maplibreWorker(): Plugin {
  const worker = () => {
    const root = dirname(createRequire(import.meta.url).resolve("maplibre-gl/package.json"));
    return readFileSync(join(root, "dist", "maplibre-gl-worker.mjs"));
  };
  return {
    name: "maplibre-worker",
    configureServer(server) {
      server.middlewares.use(`/${WORKER_PATH}`, (_request, response) => {
        response.setHeader("Content-Type", "text/javascript");
        response.end(worker());
      });
    },
    generateBundle() {
      this.emitFile({ type: "asset", fileName: WORKER_PATH, source: worker() });
    },
  };
}

// In development the page is served on 5173 and the API calls go to FastAPI on 8000
const api = process.env.TRAINTRACK_API ?? "http://localhost:8000";

export default defineConfig({
  plugins: [maplibreWorker(), react()],
  server: {
    proxy: {
      "/api": { target: api, changeOrigin: true },
      "/tiles": { target: api, changeOrigin: true },
    },
  },
  build: { outDir: "dist", sourcemap: true },
  test: { environment: "node" },
});
