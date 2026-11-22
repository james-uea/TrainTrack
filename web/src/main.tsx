import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setWorkerUrl } from "maplibre-gl";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./index.css";

// See vite.config.ts: the worker is served as-is from public/
setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");

const queryClient = new QueryClient();
const root = document.getElementById("root");
if (!root) throw new Error("No #root element");

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
