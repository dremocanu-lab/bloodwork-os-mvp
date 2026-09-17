import { execFileSync } from "node:child_process";
import * as path from "node:path";
import { test, expect, APIRequestContext, Page } from "@playwright/test";

/**
 * Real-browser regression for Clinical Document Intelligence V3 Phase 10
 * — canonical medication state changes (start/completion) now appear on
 * the patient's Timeline as real, navigable `PatientEvent` projections
 * (`frontend/components/clinical-timeline.tsx` + `frontend/app/my-
 * records/timeline/page.tsx`), alongside the derived lab artifact
 * (Phase 9) and manually-created hospitalization events — never a
 * second Timeline system, never a duplicated document card. See
 * `backend/app/services/clinical_document/timeline_projection.py`'s own
 * module docstring for the full architectural reasoning this proves.
 *
 * Seeds via `backend/scripts/seed_e2e_discharge_document.py` (extended
 * for Phase 10: calls `project_clinical_document_to_timeline` after
 * persisting medications, and adds one manual hospitalization event) —
 * same zero-external-cost ORM/service-layer seeding pattern as
 * clinical-reader.spec.ts / derived-lab-artifact.spec.ts.
 */

const API_BASE = process.env.PLAYWRIGHT_API_BASE_URL || "http://127.0.0.1:8812";
const BACKEND_DIR = path.resolve(__dirname, "..", "..", "backend");

type SeedResult = {
  token: string;
  user: { id: number; email: string; full_name: string; role: "patient" };
  patient_id: number;
  document_id: number;
  derived_document_id: number;
  second_derived_document_id: number;
  split_child_id: number;
  amoxicilina_medication_id: number;
  manual_event_id: number;
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

test.describe("Timeline medication projection (Phase 10)", () => {
  test("a projected medication start and completion both appear as distinct, correctly-labeled Timeline events", async ({
    page,
    request,
  }) => {
    const seed = seedDischargeDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto("/my-records/timeline");

      const started = page.locator(".b-tl-event", { hasText: "Amoxicilina" }).filter({ hasText: "Medication started" });
      const completed = page
        .locator(".b-tl-event", { hasText: "Amoxicilina" })
        .filter({ hasText: "Medication completed" });

      await expect(started).toBeVisible();
      await expect(completed).toBeVisible();
      // The derived completion date is explicitly marked as calculated —
      // never reads as if the source itself wrote it.
      await expect(completed.getByText(/Calculated from a documented course/i)).toBeVisible();
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("clicking a projected medication event opens that medication's own detail page", async ({ page, request }) => {
    const seed = seedDischargeDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto("/my-records/timeline");

      const started = page.locator(".b-tl-event", { hasText: "Amoxicilina" }).filter({ hasText: "Medication started" });
      await started.click();

      await expect(page).toHaveURL(new RegExp(`/my-records/medications/${seed.amoxicilina_medication_id}$`));
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("a PRN medication with no reliable date never appears as a Timeline event", async ({ page, request }) => {
    const seed = seedDischargeDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto("/my-records/timeline");

      await expect(page.getByText("Amoxicilina").first()).toBeVisible(); // page has settled
      await expect(page.locator(".b-tl-event", { hasText: "Ibuprofen" })).toHaveCount(0);
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("conflicting same-drug mentions never project a false state-change event", async ({ page, request }) => {
    const seed = seedDischargeDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto("/my-records/timeline");

      await expect(page.getByText("Amoxicilina").first()).toBeVisible(); // page has settled
      await expect(page.locator(".b-tl-event", { hasText: "BESREMI" })).toHaveCount(0);
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("a manually-created hospitalization event coexists with projected medication events", async ({
    page,
    request,
  }) => {
    const seed = seedDischargeDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto("/my-records/timeline");

      await expect(page.locator(".b-tl-event", { hasText: "Manual admission note" })).toBeVisible();
      await expect(page.locator(".b-tl-event", { hasText: "Amoxicilina" }).first()).toBeVisible();
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("the derived lab artifact appears on the Timeline with restrained framing and opens the standalone reader", async ({
    page,
    request,
  }) => {
    const seed = seedDischargeDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto("/my-records/timeline");

      const labReportRow = page.locator(".b-tl-event", { hasText: "Laboratory report" }).first();
      await expect(labReportRow).toBeVisible();
      await expect(labReportRow.getByText(/Derived from: Discharge Summary/)).toBeVisible();

      await labReportRow.click();
      await expect(page).toHaveURL(new RegExp(`/documents/${seed.derived_document_id}/lab-report$`));
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("mobile viewport: the Timeline with mixed event kinds stays usable", async ({ page, request }) => {
    const seed = seedDischargeDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto("/my-records/timeline");

      await expect(page.locator(".b-tl-event", { hasText: "Amoxicilina" }).first()).toBeVisible();
      await expect(page.locator(".b-tl-event", { hasText: "Manual admission note" })).toBeVisible();
    } finally {
      await deletePatient(request, seed.token);
    }
  });
});
