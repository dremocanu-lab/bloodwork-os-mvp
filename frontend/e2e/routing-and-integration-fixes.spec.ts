import { execFileSync } from "node:child_process";
import * as path from "node:path";
import { test, expect, APIRequestContext, Page } from "@playwright/test";

/**
 * Real-browser regression for the post-Phase-10 integration-correction
 * pass — see docs/clinical_document_v3/ROUTER_AUDIT.md for the full
 * investigation this proves: canonical document routing consolidated
 * into ONE shared resolver (`frontend/lib/document-routing.ts`), a real
 * missing derived-artifact-routing gap fixed on both Timeline pages, and
 * a real Ask Bragi `patientId` bug fixed on the discharge reader.
 *
 * Seeds via `backend/scripts/seed_e2e_routing_fixture.py` — same zero-
 * external-cost ORM/service-layer pattern as every other CDI V3
 * Playwright fixture.
 */

const API_BASE = process.env.PLAYWRIGHT_API_BASE_URL || "http://127.0.0.1:8812";
const BACKEND_DIR = path.resolve(__dirname, "..", "..", "backend");

type SeedResult = {
  token: string;
  user: { id: number; email: string; full_name: string; role: "patient" };
  doctor_token: string;
  doctor_user: { id: number; email: string; full_name: string; role: "doctor" };
  patient_id: number;
  new_style_document_id: number;
  legacy_document_id: number;
  derived_document_id: number;
};

function seedRoutingFixture(): SeedResult {
  const out = execFileSync("python", ["scripts/seed_e2e_routing_fixture.py"], {
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

test.describe("Canonical document routing + Ask Bragi target fixes (post-Phase-10)", () => {
  test("a document identified only by document_type (section mismatched) opens the canonical discharge reader", async ({
    page,
    request,
  }) => {
    const seed = seedRoutingFixture();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto(`/documents/${seed.new_style_document_id}`);

      await expect(page).toHaveURL(new RegExp(`/documents/${seed.new_style_document_id}/discharge$`));
      await expect(page.getByRole("navigation", { name: "Document outline" })).toBeVisible();
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("a legacy document identified only by section still opens the canonical discharge reader", async ({
    page,
    request,
  }) => {
    const seed = seedRoutingFixture();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto(`/documents/${seed.legacy_document_id}`);

      await expect(page).toHaveURL(new RegExp(`/documents/${seed.legacy_document_id}/discharge$`));
      await expect(page.getByRole("navigation", { name: "Document outline" })).toBeVisible();
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("a derived lab artifact opened from the Timeline reaches the standalone lab-report reader, not the generic one", async ({
    page,
    request,
  }) => {
    const seed = seedRoutingFixture();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto("/my-records/timeline");

      const labReportRow = page.locator(".b-tl-event", { hasText: "Laboratory report" }).first();
      await expect(labReportRow).toBeVisible();
      await labReportRow.click();

      await expect(page).toHaveURL(new RegExp(`/documents/${seed.derived_document_id}/lab-report$`));
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("a direct hard navigation to the discharge URL works without a redirect loop", async ({ page, request }) => {
    const seed = seedRoutingFixture();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto(`/documents/${seed.new_style_document_id}/discharge`);

      await expect(page.getByRole("navigation", { name: "Document outline" })).toBeVisible();
      await expect(page).toHaveURL(new RegExp(`/documents/${seed.new_style_document_id}/discharge$`));
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("a doctor opening Ask Bragi from the discharge reader sends the real patient id, never the document id", async ({
    page,
    request,
  }) => {
    const seed = seedRoutingFixture();
    try {
      await seedAuth(page, seed.doctor_token, seed.doctor_user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto(`/documents/${seed.new_style_document_id}/discharge`);
      await expect(page.getByRole("navigation", { name: "Document outline" })).toBeVisible();

      const conversationRequest = page.waitForRequest(
        (req) => req.url().includes("/ask-bragi/conversations") && req.method() === "POST"
      );
      await page.getByRole("button", { name: "Ask Bragi" }).click();
      const suggestionButton = page.getByRole("button", { name: /Why was I admitted\?/i });
      await suggestionButton.click();

      const req = await conversationRequest;
      const body = req.postDataJSON();
      expect(body.patient_id).toBe(seed.patient_id);
      expect(body.patient_id).not.toBe(seed.new_style_document_id);
    } finally {
      await deletePatient(request, seed.token);
    }
  });
});
