import { execFileSync } from "node:child_process";
import * as path from "node:path";
import { test, expect, APIRequestContext, Page } from "@playwright/test";

/**
 * Real-browser regression for the Phase 8 rebuilt discharge/clinical
 * reader (`frontend/app/documents/[id]/discharge/page.tsx`), built
 * around `StructuredClinicalDocument` instead of the old ad-hoc
 * `{document_type, sections}` payload.
 *
 * Seeds a synthetic discharge document DIRECTLY via the ORM/service
 * layer (backend/scripts/seed_e2e_discharge_document.py — the same
 * zero-external-cost pattern as seed_e2e_lab_document.py; no Reducto/
 * OpenAI call is required to run this suite), exercising: repeated
 * EPICRIZĂ headings, a suspicious future date (14/09/3036), an
 * implausible vital sign (AV 1008 bpm), canonical lab rows including
 * the MCH conflict, and canonical medication rows including a
 * finite-duration course (derived end date), a PRN medication, and a
 * same-drug status conflict (BESREMI).
 *
 * Requires: a backend (uvicorn) already running with a real
 * DATABASE_URL, and the frontend dev server — see
 * right-workspace-geometry.spec.ts for the same requirement and
 * playwright.config.ts for how baseURL/API base are resolved.
 */

const API_BASE = process.env.PLAYWRIGHT_API_BASE_URL || "http://127.0.0.1:8812";
const BACKEND_DIR = path.resolve(__dirname, "..", "..", "backend");

type SeedResult = {
  token: string;
  user: { id: number; email: string; full_name: string; role: "patient" };
  patient_id: number;
  document_id: number;
};

function seedDischargeDocument(): SeedResult {
  const out = execFileSync("python", ["scripts/seed_e2e_discharge_document.py"], {
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

/**
 * The reader's outline only exists once the async `GET /documents/{id}/
 * clinical-reader` fetch resolves and React commits `activeSectionId`
 * for the first time. Asserting the FIRST outline button is visible
 * (rather than clicking immediately after `goto`) is the real settle
 * point that matters — this is what gives a genuine human's reaction
 * time before their first click, which automation otherwise skips.
 */
async function openDischargeReader(page: Page, documentId: number) {
  await page.goto(`/documents/${documentId}/discharge`);
  await expect(page.getByRole("navigation", { name: "Document outline" })).toBeVisible();
}

test.describe("Clinical reader — rebuilt discharge document (Phase 8)", () => {
  test("header, canonical outline, diagnoses, and repeated-EPICRIZĂ consolidation all render", async ({
    page,
    request,
  }) => {
    const seed = seedDischargeDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openDischargeReader(page, seed.document_id);

      // Header — both the AppShell page title and the reader's own
      // document header legitimately say "Discharge Summary".
      await expect(page.getByRole("heading", { name: "Discharge Summary" }).first()).toBeVisible();

      // Canonical outline — labels, never raw source headings like "EPICRIZĂ".
      const diagnosesButton = page.getByRole("button", { name: "Diagnoses" });
      const clinicalCourseButton = page.getByRole("button", { name: "Clinical course" });
      await expect(diagnosesButton).toBeVisible();
      await expect(clinicalCourseButton).toBeVisible();
      await expect(page.getByRole("button", { name: "EPICRIZĂ" })).toHaveCount(0);

      await diagnosesButton.click();
      await expect(page.getByText("K80.2")).toBeVisible();

      await clinicalCourseButton.click();
      // Only ONE "Clinical course" section heading exists, even though the
      // source repeated "EPICRIZĂ" twice — both bodies survive as content,
      // not as two separate outline entries.
      await expect(page.getByRole("heading", { name: "Clinical course", exact: true })).toHaveCount(1);
      // Both segment bodies appear (also legitimately repeated inside the
      // dated-event timeline below, which shares the same source text
      // per event derived from that segment) — .first() is enough proof.
      await expect(page.getByText("dureri abdominale").first()).toBeVisible();
      await expect(page.getByText("ameliorat").first()).toBeVisible();
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("dated Clinical Course events render and a suspicious source date is preserved, never corrected", async ({
    page,
    request,
  }) => {
    const seed = seedDischargeDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openDischargeReader(page, seed.document_id);

      await page.getByRole("button", { name: "Clinical course" }).click();

      // Real dated events (admission/discharge) render.
      await expect(page.getByText("2026-01-10")).toBeVisible();
      await expect(page.getByText("2026-01-20")).toBeVisible();

      // The suspicious future date is preserved verbatim (3036), never
      // silently "corrected" to a plausible year — and its own warning
      // renders, not hidden.
      await expect(page.getByText("3036-09-14")).toBeVisible();
      await expect(page.getByText(/outside the plausible range/i)).toBeVisible();
      await expect(page.getByText(/\b2036-09-14\b/)).toHaveCount(0); // never "corrected"

      // The implausible vital sign is flagged, not silently rewritten —
      // it legitimately appears both in the raw event text and in the
      // warning quoting it verbatim.
      await expect(page.getByText(/AV 1008/i).first()).toBeVisible();
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("canonical lab table renders and the MCH conflict is preserved, not collapsed", async ({ page, request }) => {
    const seed = seedDischargeDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openDischargeReader(page, seed.document_id);

      await page.getByRole("button", { name: "Laboratory results" }).click();

      // The canonical display name renders (resolve_analyte()'s resolved
      // name), not the raw "WBC" abbreviation — correct, clinician-
      // friendly behavior, not a bug.
      await expect(page.getByText("White Blood Cell Count")).toBeVisible();
      await expect(page.getByText("349")).toBeVisible(); // PLT value

      // Both conflicting MCH observations are shown, each flagged — two
      // rows both carry the "Requires review" indicator.
      await expect(page.getByText("29.0")).toBeVisible();
      await expect(page.getByText("31.5")).toBeVisible();
      await expect(page.getByText("Requires review")).toHaveCount(2);
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("medications: derived end date is labeled as calculated, PRN and status conflict are honest", async ({
    page,
    request,
  }) => {
    const seed = seedDischargeDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openDischargeReader(page, seed.document_id);

      await page.getByRole("button", { name: "Discharge medications" }).click();
      await expect(page.getByText("Amoxicilina")).toBeVisible();
      // A calculated end date is explicitly labeled as calculated — never
      // presented as if the source itself wrote that date.
      await expect(page.getByText(/Calculated from a documented course/i)).toBeVisible();
      await expect(page.getByText("Ibuprofen")).toBeVisible();
      await expect(page.getByText("As needed")).toBeVisible();

      await page.getByRole("button", { name: "Medications", exact: true }).click();
      await expect(page.getByText("BESREMI").first()).toBeVisible();
      // Both conflicting BESREMI rows carry the conflict note.
      await expect(page.getByText(/Conflicting status across sources/i)).toHaveCount(2);
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("a lab row's source action opens the shared RightWorkspace", async ({ page, request }) => {
    const seed = seedDischargeDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openDischargeReader(page, seed.document_id);

      await page.getByRole("button", { name: "Laboratory results" }).click();
      await page.getByRole("button", { name: "View source" }).first().click();

      // The shared split-view workspace mounts — same RightWorkspace
      // system used everywhere else in the app, never a second viewer.
      await expect(page.locator(".b-app-split-viewer")).toBeVisible();
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("mobile viewport: section navigation degrades to a select, content stays usable", async ({
    page,
    request,
  }) => {
    const seed = seedDischargeDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto(`/documents/${seed.document_id}/discharge`);

      const nav = page.getByRole("combobox", { name: "Document section" });
      await expect(nav).toBeVisible();
      await nav.selectOption({ label: "Diagnoses" });
      await expect(page.getByText("K80.2")).toBeVisible();
    } finally {
      await deletePatient(request, seed.token);
    }
  });
});
