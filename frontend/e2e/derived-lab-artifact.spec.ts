import { execFileSync } from "node:child_process";
import * as path from "node:path";
import { test, expect, APIRequestContext, Page } from "@playwright/test";

/**
 * Real-browser regression for Clinical Document Intelligence V3 Phase 9
 * — a coherent lab report embedded inside a discharge document must
 * appear in Documents as a real, independently openable clinical
 * artifact, rendering `StructuredLabReport(mode="standalone")` against
 * the SAME canonical `LabResult` rows Phase 6 created on the parent
 * (`frontend/app/documents/[id]/lab-report/page.tsx`) — never a copy,
 * never a second lab datastore, never a fake PDF.
 *
 * Seeds via `backend/scripts/seed_e2e_discharge_document.py` (extended
 * for Phase 9: a second coherent lab group to prove multiple derived
 * artifacts stay distinct, plus a plain Reducto Split child to prove it
 * is never mislabeled as a derived artifact) — same zero-external-cost
 * ORM/service-layer seeding pattern as clinical-reader.spec.ts.
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

async function openDocumentsBloodworkFilter(page: Page) {
  await page.goto("/my-records");
  await page.getByRole("tab", { name: /Documents/ }).click();
  await page.getByRole("button", { name: /^Bloodwork/ }).click();
}

test.describe("Derived lab artifact in Documents (Phase 9)", () => {
  test("a derived lab report appears in Documents, titled and attributed to its parent — never a raw internal name", async ({
    page,
    request,
  }) => {
    const seed = seedDischargeDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openDocumentsBloodworkFilter(page);

      const row = page.locator("tr", { hasText: "Laboratory report" }).first();
      await expect(row).toBeVisible();
      await expect(row.getByText("Derived from: Discharge Summary")).toBeVisible();
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("opening the derived artifact renders the same canonical lab values as the embedded discharge view", async ({
    page,
    request,
  }) => {
    const seed = seedDischargeDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto(`/documents/${seed.derived_document_id}/lab-report`);

      await expect(page.getByRole("heading", { name: "Laboratory report" }).first()).toBeVisible();
      await expect(page.getByText("Derived from: Discharge Summary")).toBeVisible();

      // Same canonical values the Phase 8 embedded view proves — resolved
      // from the SAME LabResult rows, not a copy inside the artifact.
      await expect(page.getByText("White Blood Cell Count")).toBeVisible();
      await expect(page.getByText("349")).toBeVisible(); // PLT value
      await expect(page.getByText("29.0")).toBeVisible();
      await expect(page.getByText("31.5")).toBeVisible();
      await expect(page.getByText("Requires review")).toHaveCount(2); // MCH conflict preserved here too
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("a lab row's source action opens the shared RightWorkspace against the parent's real file", async ({
    page,
    request,
  }) => {
    const seed = seedDischargeDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto(`/documents/${seed.derived_document_id}/lab-report`);

      await page.getByRole("button", { name: "View source", exact: true }).first().click();
      await expect(page.locator(".b-app-split-viewer")).toBeVisible();
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("parent navigation: 'View source document' opens the real parent discharge reader", async ({
    page,
    request,
  }) => {
    const seed = seedDischargeDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto(`/documents/${seed.derived_document_id}/lab-report`);

      await page.getByRole("button", { name: /Open source document/i }).click();
      await expect(page).toHaveURL(new RegExp(`/documents/${seed.document_id}/discharge$`));
      await expect(page.getByRole("navigation", { name: "Document outline" })).toBeVisible();
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("multiple derived lab reports on the same parent stay distinct, never merged", async ({ page, request }) => {
    const seed = seedDischargeDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openDocumentsBloodworkFilter(page);

      await expect(page.getByText("Laboratory report")).toHaveCount(2);
      expect(seed.derived_document_id).not.toBe(seed.second_derived_document_id);
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("a plain Reducto Split child is never mislabeled as a derived lab artifact", async ({ page, request }) => {
    const seed = seedDischargeDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto("/my-records");
      await page.getByRole("tab", { name: /Documents/ }).click();
      await page.getByRole("button", { name: /^Discharge summaries/i }).click();

      // The split child shares parent_document_id with the real derived
      // artifacts, but must never show derived-artifact framing.
      const rows = page.locator("tr");
      await expect(rows.filter({ hasText: "Laboratory report" })).toHaveCount(0);

      // Opening it goes to the ordinary discharge reader, not the
      // standalone lab-report reader.
      await page.goto(`/documents/${seed.split_child_id}`);
      await expect(page).toHaveURL(new RegExp(`/documents/${seed.split_child_id}/discharge$`));
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("the standalone derived artifact reader exposes no delete action", async ({ page, request }) => {
    const seed = seedDischargeDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto(`/documents/${seed.derived_document_id}/lab-report`);
      await expect(page.getByRole("heading", { name: "Laboratory report" }).first()).toBeVisible();

      await expect(page.getByRole("button", { name: /Delete/i })).toHaveCount(0);
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("mobile viewport: the standalone derived artifact reader stays usable", async ({ page, request }) => {
    const seed = seedDischargeDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto(`/documents/${seed.derived_document_id}/lab-report`);

      await expect(page.getByRole("heading", { name: "Laboratory report" }).first()).toBeVisible();
      await expect(page.getByText("349")).toBeVisible();
    } finally {
      await deletePatient(request, seed.token);
    }
  });
});
