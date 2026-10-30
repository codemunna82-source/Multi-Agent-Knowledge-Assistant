/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const backend = process.env.MKA_BACKEND ?? "http://localhost:8000";
const proxied = ["/auth", "/sources", "/jobs", "/ask", "/conversations", "/eval", "/admin", "/graph", "/transcribe", "/health", "/session", "/search", "/summaries", "/compare", "/analytics", "/web", "/reports", "/memory", "/metrics"];

export default defineConfig({
  plugins: [react()],
  server: { proxy: Object.fromEntries(proxied.map((p) => [p, backend])) },
  build: { outDir: "dist", sourcemap: false },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/test-setup.ts"], css: false },
});
