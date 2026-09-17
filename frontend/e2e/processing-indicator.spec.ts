import { execFileSync } from "node:child_process";
import * as path from "node:path";
import { test, expect, APIRequestContext, Page } from "@playwright/test";

/**
 * P0 upload reliability / processing-indicator session — real-browser
 * geometry regression for the "N document(s) is/are being processed"
 * banner's status dot on My Records. A prior session (docs handoff, B2)
 * fixed a real bug (dot and text not sharing a flex container at all);
 * a user then reported via a real screenshot that the dot STILL reads
 * as visibly above the text's vertical center. Root-caused this time by
 * direct CSS measurement (see docs handoff for the full diagnosis): the
 * shared `.b-status` class has no `line-height` of its own and inherits
 * an unitless 1.5 from `.b-notice`/`body`, inflating its flex cross-size
 * well past the text glyphs' own visual footprint, so `align-items:
 * center` centers the dot against that inflated geometric box rather
 * than the glyphs. Fixed with a banner-scoped `.b-processing-status`
 * class (real DOM dot instead of a `::before` pseudo-element, tight
 * `line-height: 1`) — never touching the shared `.b-status` other tone
 * badges across the app rely on.
 *
 * A class-name assertion would not have caught the original bug (the
 * classes were already "correct" per the B2 fix) — this suite asserts
 * actual rendered geometry instead.
 *
 * Seeds via backend/scripts/seed_e2e_processing_job.py (a real UploadJob
 * row with status="processing", zero external API cost, no dependency
 * on real classification completing).
 */

const API_BASE = process.env.PLAYWRIGHT_API_BASE_URL || "http://127.0.0.1:8812";
const BACKEND_DIR = path.resolve(__dirname, "..", "..", "backend");

type SeedResult = {
  token: string;
  user: { id: number; email: string; full_name: string; role: "patient" };
  patient_id: number;
};

function seedProcessingJob(): SeedResult {
  const out = execFileSync("python", ["scripts/seed_e2e_processing_job.py"], {
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

async function assertDotCenteredOnText(page: Page, toleranceCssPx = 2) {
  const dot = page.getByTestId("processing-status-dot");
  const text = page.getByTestId("processing-status-text");
  await expect(dot).toBeVisible();
  await expect(text).toBeVisible();

  const [dotBox, textBox] = await Promise.all([dot.boundingBox(), text.boundingBox()]);
  expect(dotBox).not.toBeNull();
  expect(textBox).not.toBeNull();

  const dotCenterY = dotBox!.y + dotBox!.height / 2;
  const textCenterY = textBox!.y + textBox!.height / 2;
  const delta = Math.abs(dotCenterY - textCenterY);

  expect(delta, `dot center Y=${dotCenterY}, text center Y=${textCenterY}, delta=${delta}`).toBeLessThanOrEqual(
    toleranceCssPx
  );
}

test.describe("Processing indicator dot — vertical geometry", () => {
  test("desktop 1920x1080: dot is vertically centered on the banner text", async ({ page, request }) => {
    const seed = seedProcessingJob();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1920, height: 1080 });
      await page.goto("/my-records");
      await assertDotCenteredOnText(page);
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("desktop 1440x900: dot is vertically centered on the banner text", async ({ page, request }) => {
    const seed = seedProcessingJob();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto("/my-records");
      await assertDotCenteredOnText(page);
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("mobile 390x844: dot is vertically centered on the banner text", async ({ page, request }) => {
    const seed = seedProcessingJob();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto("/my-records");
      await assertDotCenteredOnText(page);
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("banner text reads correctly for exactly one active job", async ({ page, request }) => {
    const seed = seedProcessingJob();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto("/my-records");
      await expect(page.getByTestId("processing-status-text")).toHaveText(
        "1 document is being processed. It will appear here automatically."
      );
    } finally {
      await deletePatient(request, seed.token);
    }
  });
});
