import { execFileSync } from "node:child_process";
import * as path from "node:path";
import { test, expect, APIRequestContext, Page } from "@playwright/test";

/**
 * P0 upload reliability session — real-browser regression for a
 * confirmed frontend bug: the backend's security-scan quarantine path
 * sets `UploadJob.status = "security_quarantined"` (a real, distinct
 * terminal state from the identity-review "quarantined" path), but
 * `statusFromBackend()` (components/upload-provider.tsx) had NO case for
 * it — it fell through to `"queued"`, which IS "active", so a job the
 * backend had already finished (finished_at set, a real user-facing
 * message written) stayed displayed as stuck "processing" forever. This
 * is very likely what "upload remained processing" manual QA was
 * actually seeing for a file the security scanner set aside — not an
 * actual hang in the backend pipeline (which already terminal-izes this
 * case correctly server-side; see docs handoff for the full trace).
 *
 * Seeds via backend/scripts/seed_e2e_security_quarantined_job.py — a
 * real UploadJob row with status="security_quarantined", zero external
 * API cost, no dependency on a real file actually triggering the scanner.
 */

const API_BASE = process.env.PLAYWRIGHT_API_BASE_URL || "http://127.0.0.1:8812";
const BACKEND_DIR = path.resolve(__dirname, "..", "..", "backend");

type SeedResult = {
  token: string;
  user: { id: number; email: string; full_name: string; role: "patient" };
  patient_id: number;
};

function seedSecurityQuarantinedJob(): SeedResult {
  const out = execFileSync("python", ["scripts/seed_e2e_security_quarantined_job.py"], {
    cwd: BACKEND_DIR,
    encoding: "utf-8",
  });
  return JSON.parse(out.trim().split("\n").pop()!);
}

async function deletePatient(request: APIRequestContext, token: string) {
  await request.delete(`${API_BASE}/my/account`, {
    headers: { Authorization: `Bearer ${token}` },
  });
}

async function seedAuth(page: Page, token: string, user: unknown) {
  await page.goto("/login");
  await page.evaluate(
    ([t, u]) => {
      localStorage.setItem("access_token", t as string);
      localStorage.setItem("user", JSON.stringify(u));
    },
    [token, user]
  );
}

test.describe("Upload reliability — security-quarantined jobs never look stuck", () => {
  test("a security-quarantined job shows 'Set aside', not Processing, and doesn't count as active", async ({
    page,
    request,
  }) => {
    const seed = seedSecurityQuarantinedJob();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto("/my-records/upload");

      await expect(page.getByText("suspicious.pdf")).toBeVisible();

      const row = page.locator(".b-queue-row", { has: page.getByText("suspicious.pdf") }).first();
      await expect(row.getByText("Set aside", { exact: true })).toBeVisible();
      await expect(row.getByText("Processing", { exact: true })).toHaveCount(0);

      // The My Records Overview "N document(s) processing" banner must
      // NOT count this job as active — it already reached a real
      // terminal state server-side.
      await page.goto("/my-records");
      await expect(page.getByTestId("processing-status-text")).toHaveCount(0);
    } finally {
      await deletePatient(request, seed.token);
    }
  });
});
