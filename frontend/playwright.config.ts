import { defineConfig } from "@playwright/test";

// Journeys run against the full stack started by `docker compose up` (UI on :3400).
export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  timeout: 60_000,
  retries: 0,
  workers: 1, // journeys share one organisation's data
  use: { baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3400", trace: "retain-on-failure" },
  reporter: [["list"]],
});
