import { defineConfig, devices } from "@playwright/test";

/**
 * Real-browser regression coverage for the workspace/Ask Bragi bugs
 * fixed in BRAGI PRODUCT RELIABILITY PASS (see fix/ask-bragi-workspace-
 * reliability). Assumes the backend (uvicorn, ASK_BRAGI_ENABLED=true)
 * and frontend (`next dev`) are already running — this suite does not
 * manage either server itself (a real Postgres-backed backend isn't
 * something Playwright's own webServer option should spin up/tear down
 * per run), matching this repo's existing manual-server convention for
 * backend pytest (see backend/tests/conftest.py).
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  use: {
    // "localhost", not "127.0.0.1" — Next.js dev mode (Turbopack) blocks
    // its own HMR/dev-resource requests as cross-origin when the page is
    // loaded from a different-looking host than it considers its own
    // origin, which silently prevented the page from ever finishing
    // hydration under Playwright (reproduced directly: the app got stuck
    // on its initial loading spinner forever, with zero network requests
    // ever reaching the backend) — see next dev's own
    // "Blocked cross-origin request to Next.js dev resource" warning.
    baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
