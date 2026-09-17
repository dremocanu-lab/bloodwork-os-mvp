import { execFileSync } from "node:child_process";
import * as path from "node:path";
import { test, expect, APIRequestContext, Page } from "@playwright/test";

/**
 * Pre-Phase-11 Romanian discharge classification + reader-routing closure
 * session — real-browser proof that a document whose document_type/
 * section came from REAL classification (not hardcoded test metadata,
 * unlike every prior "discharge routing" Playwright fixture) actually
 * reaches the real Phase 8 discharge reader.
 *
 * Seeds via backend/scripts/seed_e2e_bilet_de_iesire_discharge.py, which
 * itself calls the real `document_classifier.classify_document_text`
 * against the exact "BILET DE IEȘIRE DIN SPITAL / SCRISOARE MEDICALĂ"
 * title + dense embedded-labs text this session's fixture uses
 * (tests/fixtures/synthetic_documents.py), and asserts CLASSIFIED/
 * discharge_summary before persisting anything — if the classifier ever
 * regresses, the seed script itself fails loudly rather than silently
 * falling back to hardcoded metadata.
 *
 * Requires: a backend (uvicorn) already running with a real
 * DATABASE_URL, and the frontend dev server — see
 * clinical-reader.spec.ts for the same requirement.
 */

const API_BASE = process.env.PLAYWRIGHT_API_BASE_URL || "http://127.0.0.1:8812";
const BACKEND_DIR = path.resolve(__dirname, "..", "..", "backend");

type SeedResult = {
  token: string;
  user: { id: number; email: string; full_name: string; role: "patient" };
  patient_id: number;
  document_id: number;
  classification_candidates: Record<string, number>;
};

function seedBiletDeIesireDischarge(): SeedResult {
  const out = execFileSync("python", ["scripts/seed_e2e_bilet_de_iesire_discharge.py"], {
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

test.describe("Romanian discharge classification -> reader closure", () => {
  test("a real BILET DE IEȘIRE classification confidently wins over laboratory_results", async ({ request }) => {
    const seed = seedBiletDeIesireDischarge();
    try {
      // The seed script's own assertion already proves this server-side;
      // re-asserting the returned candidate scores here keeps the real
      // margin visible in this suite's own report, not just the seed
      // script's stdout.
      const discharge = seed.classification_candidates["discharge_summary"] ?? 0;
      const lab = seed.classification_candidates["laboratory_results"] ?? 0;
      expect(discharge - lab).toBeGreaterThanOrEqual(1.5);
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("Documents list opens it directly into the real Phase 8 discharge reader", async ({ page, request }) => {
    const seed = seedBiletDeIesireDischarge();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });

      await page.goto("/my-records");
      await page.getByText("Bilet de ieșire din spital").first().click();

      await expect(page).toHaveURL(new RegExp(`/documents/${seed.document_id}/discharge$`));
      await expect(page.getByRole("navigation", { name: "Document outline" })).toBeVisible();
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("direct URL and hard refresh both load the real Phase 8 discharge reader", async ({ page, request }) => {
    const seed = seedBiletDeIesireDischarge();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });

      await page.goto(`/documents/${seed.document_id}/discharge`);
      await expect(page.getByRole("navigation", { name: "Document outline" })).toBeVisible();

      await page.reload();
      await expect(page).toHaveURL(new RegExp(`/documents/${seed.document_id}/discharge$`));
      await expect(page.getByRole("navigation", { name: "Document outline" })).toBeVisible();
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("the real Phase 8 reader renders, not the old generic document page", async ({ page, request }) => {
    const seed = seedBiletDeIesireDischarge();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto(`/documents/${seed.document_id}/discharge`);

      // Real structured content from the seeded legacy discharge payload.
      // Clinical Reader Intelligence V2 made "Overview" the default
      // landing entry (never a raw diagnosis dump on first paint) — the
      // real diagnosis content is one click away on its own section,
      // same as any other canonical section.
      await expect(page.getByRole("button", { name: "Clinical course" })).toBeVisible();
      const diagnosesButton = page.getByRole("button", { name: "Diagnoses" });
      await expect(diagnosesButton).toBeVisible();
      await diagnosesButton.click();
      await expect(page.getByText("D45")).toBeVisible();

      // Old generic-reader-only UI must not be present on this page.
      await expect(page.getByText("Original layout")).toHaveCount(0);
      await expect(page.getByText("Structured reader")).toHaveCount(0);
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("GET /documents/{id}/clinical-reader returns document_type=discharge_summary", async ({ page, request }) => {
    const seed = seedBiletDeIesireDischarge();
    try {
      await seedAuth(page, seed.token, seed.user);
      const response = await request.get(`${API_BASE}/documents/${seed.document_id}/clinical-reader`, {
        headers: { Authorization: `Bearer ${seed.token}` },
      });
      expect(response.status()).toBe(200);
      const body = await response.json();
      expect(body.document.document_type).toBe("discharge_summary");
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("mobile viewport: the real reader stays usable for the classified document", async ({ page, request }) => {
    const seed = seedBiletDeIesireDischarge();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto(`/documents/${seed.document_id}/discharge`);

      const nav = page.getByRole("combobox", { name: "Document section" });
      await expect(nav).toBeVisible();
      await nav.selectOption({ label: "Diagnoses" });
      await expect(page.getByText("D45")).toBeVisible();
    } finally {
      await deletePatient(request, seed.token);
    }
  });
});
