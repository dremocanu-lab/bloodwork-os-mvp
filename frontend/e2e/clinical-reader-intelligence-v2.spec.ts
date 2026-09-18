import { execFileSync } from "node:child_process";
import * as path from "node:path";
import { test, expect, APIRequestContext, Page } from "@playwright/test";

/**
 * Real-browser regression for Clinical Reader Intelligence V2 — the
 * rebuilt discharge/clinical reader's new information architecture
 * (Overview / Diagnoses / Current Hospitalization / Clinical Course /
 * Laboratory Results / Investigations / Original) against the full
 * synthetic Romanian discharge fixture (backend/tests/fixtures/
 * clinical_reader_v2_fixture.py, Part 28).
 *
 * Seeds via backend/scripts/seed_e2e_clinical_reader_v2_document.py,
 * which runs the document through the REAL reprocessing pipeline with
 * the AI interpreter's model call mocked to a deterministic, realistic
 * response — no Reducto/OpenAI call, no live network dependency, same
 * zero-external-cost pattern as clinical-reader.spec.ts.
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
};

function seedFixtureDocument(): SeedResult {
  const out = execFileSync("python", ["scripts/seed_e2e_clinical_reader_v2_document.py"], {
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

async function openReader(page: Page, documentId: number) {
  await page.goto(`/documents/${documentId}/discharge`);
  await expect(page.getByRole("navigation", { name: "Document outline" })).toBeVisible();
}

test.describe("Clinical Reader Intelligence V2 — synthetic Romanian discharge fixture", () => {
  test("Overview shows the principal diagnosis and hospitalization window without a giant text dump", async ({
    page,
    request,
  }) => {
    const seed = seedFixtureDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openReader(page, seed.document_id);

      // Overview is the default landing entry.
      await expect(page.getByRole("button", { name: "Overview" })).toBeVisible();
      await expect(page.getByText("2026-03-04").first()).toBeVisible();
      await expect(page.getByText(/D45/)).toBeVisible();
      await expect(page.getByText(/Organized from source/i)).toBeVisible();
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("Diagnoses shows only the real principal diagnosis, never a fabricated secondary one", async ({
    page,
    request,
  }) => {
    const seed = seedFixtureDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openReader(page, seed.document_id);

      await page.getByRole("button", { name: "Diagnoses" }).click();
      await expect(page.getByText("Primary diagnosis")).toBeVisible();
      await expect(page.getByText("D45")).toBeVisible();
      await expect(page.getByText("Policitemie vera")).toBeVisible();
      await expect(page.getByText("Secondary diagnosis")).toHaveCount(0);
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("Current Hospitalization is reachable and shows only the current-encounter events", async ({
    page,
    request,
  }) => {
    const seed = seedFixtureDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openReader(page, seed.document_id);

      await page.getByRole("button", { name: "Current hospitalization" }).click();
      await expect(page.getByText(/AV 1008/i)).toBeVisible();
      await expect(page.getByText(/stare ameliorata/i)).toBeVisible();
      // A historical (2019) event must never appear inside this view.
      await expect(page.getByText(/10\.05\.2019/)).toHaveCount(0);
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("empty investigation and treatment templates are suppressed from the outline, never shown as content", async ({
    page,
    request,
  }) => {
    const seed = seedFixtureDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openReader(page, seed.document_id);

      // Both source sections are pure blank-template noise in this
      // fixture (Part 1D/1E) — is_template_only suppresses their outline
      // entries entirely.
      await expect(page.getByRole("button", { name: "Investigations" })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Treatment" })).toHaveCount(0);
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("real investigations found in narrative render as typed cards", async ({ page, request }) => {
    const seed = seedFixtureDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openReader(page, seed.document_id);

      // Reached via Overview's "Key investigations" list, since the
      // dedicated Investigations outline entry is suppressed above (the
      // deterministic source section is template-only) — the real
      // findings still surface where the interpreter grounded them.
      await expect(page.getByText("JAK2 V617F")).toBeVisible();
      await expect(page.getByText("Biopsie osteomedulara")).toBeVisible();
      await expect(page.getByText("Ecografie abdominala")).toBeVisible();
      await expect(page.getByText("BCR-ABL")).toBeVisible();
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("suspicious date and implausible vital sign are preserved verbatim with an anomaly warning, never corrected", async ({
    page,
    request,
  }) => {
    const seed = seedFixtureDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openReader(page, seed.document_id);

      await expect(page.getByText(/Possible source inconsistency/i).first()).toBeVisible();
      await expect(page.getByText("14.09.3036")).toBeVisible();
      await expect(page.getByText(/AV 1008\/min/)).toBeVisible();
      await expect(page.getByText(/\b2036\b/)).toHaveCount(0); // never "corrected" to a plausible year
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("laboratory results render as a real table with the HGB conflict preserved, never a raw text blob", async ({
    page,
    request,
  }) => {
    const seed = seedFixtureDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openReader(page, seed.document_id);

      await page.getByRole("button", { name: "Laboratory results" }).click();
      await expect(page.getByRole("heading", { name: "Laboratory results" })).toBeVisible();
      await expect(page.getByText("9.8")).toBeVisible();
      await expect(page.getByText("11.2")).toBeVisible();
      await expect(page.getByText("Requires review")).toHaveCount(2);
      // The raw "COD CERERE / DATA" style prose must never also be shown
      // alongside the structured table (Part 1G — no contradictory state).
      await expect(page.getByText(/Niciun rezultat de laborator|No laboratory results are available/i)).toHaveCount(0);
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("Original narrative shows the verbatim-duplicated block, unfiltered, including template sections", async ({
    page,
    request,
  }) => {
    const seed = seedFixtureDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openReader(page, seed.document_id);

      await page.getByRole("button", { name: "Full source narrative" }).click();
      // The blank template sections, hidden everywhere else, are still
      // reachable here — nothing is ever truly deleted.
      await expect(page.getByText("PRODUS")).toBeVisible();
      // The duplicated control-hematologic sentence appears twice.
      await expect(page.getByText(/control hematologic: se mentine tratamentul/i)).toHaveCount(2);
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("split source viewer opens with a usable, non-degenerate geometry", async ({ page, request }) => {
    const seed = seedFixtureDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openReader(page, seed.document_id);

      await page.getByRole("button", { name: "Laboratory results" }).click();
      await page.getByRole("button", { name: "View source" }).first().click();
      const viewer = page.locator(".b-app-split-viewer");
      await expect(viewer).toBeVisible();
      const main = page.locator(".b-app-split-main");
      const mainBox = await main.boundingBox();
      expect(mainBox?.width).toBeGreaterThanOrEqual(480); // the real min-width floor, never 0
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("mobile viewport: section select works, Overview and Current Hospitalization are reachable", async ({
    page,
    request,
  }) => {
    const seed = seedFixtureDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto(`/documents/${seed.document_id}/discharge`);

      const nav = page.getByRole("combobox", { name: "Document section" });
      await expect(nav).toBeVisible();
      await nav.selectOption({ label: "Overview" });
      await expect(page.getByText(/D45/)).toBeVisible();

      await nav.selectOption({ label: "Current hospitalization" });
      await expect(page.getByText(/AV 1008/i)).toBeVisible();
    } finally {
      await deletePatient(request, seed.token);
    }
  });
});
