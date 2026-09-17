import { execFileSync } from "node:child_process";
import * as path from "node:path";
import { test, expect, APIRequestContext, Page } from "@playwright/test";

/**
 * Pre-Phase-11 exact provenance / source-highlighting session —
 * real-browser coverage for select-source-text -> contextual menu ->
 * "Show in original" (`SelectionSourceMenu`, source-viewer/
 * selection-source-menu.tsx), which reuses the SAME `openSourceEvidence`
 * engine as every existing "View source" button.
 *
 * Reuses the exact same zero-external-cost discharge fixture as
 * clinical-reader.spec.ts (seed_e2e_discharge_document.py) — its
 * embedded lab rows already carry a real `source_evidence_id` (Phase 6's
 * `lab_persistence.py` always creates a SourceEvidence row, even without
 * page/bbox geometry), so `data-source-evidence-id` is present on them
 * exactly as it would be for any real Reducto-backed document.
 *
 * This suite deliberately does NOT attempt pixel-level "this box exactly
 * covers NEUT# and not PCT" assertions against a rendered PDF — that
 * would need a purpose-built PDF fixture with known glyph coordinates.
 * The coordinate math itself (does a field's rect ever overlap a
 * neighboring row's) is proven precisely and deterministically at the
 * unit level in backend/tests/test_reducto_row_bbox.py's
 * TestAdjacentDenseRowsFixture. What this suite covers instead is the
 * real-browser INTERACTION surface this session added: selection
 * detection, the contextual menu's appearance/dismissal rules, and that
 * clicking it opens the same shared RightWorkspace — plus the explicit
 * "UI-only text must never offer this action" requirement.
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

async function openDischargeReader(page: Page, documentId: number) {
  await page.goto(`/documents/${documentId}/discharge`);
  await expect(page.getByRole("navigation", { name: "Document outline" })).toBeVisible();
}

/** Outline navigation occasionally races the reader's own hydration
 * (the button exists and is clickable before its onClick handler is
 * attached) — retries the click rather than tolerating a flaky wait,
 * since a single missed click otherwise looks identical to a real
 * section-switch bug. */
async function goToSection(page: Page, sectionName: string, contentLocator: ReturnType<Page["getByText"]>) {
  const button = page.getByRole("button", { name: sectionName });
  for (let attempt = 0; attempt < 4; attempt++) {
    await button.click();
    try {
      await expect(contentLocator).toBeVisible({ timeout: 8000 });
      return;
    } catch {
      // Next dev/Turbopack can occasionally take a while to finish
      // compiling+hydrating a route it hasn't served recently — retry
      // the click rather than treat that as a real navigation failure.
    }
  }
  await expect(contentLocator).toBeVisible({ timeout: 8000 });
}

/** Double-clicking a word is real-browser text selection, not a custom
 * Range hack — it's what actually fires `selectionchange` the way a
 * genuine user selecting a word would. */
async function selectWordIn(page: Page, locator: ReturnType<Page["getByText"]>) {
  await locator.first().dblclick();
}

test.describe("Exact provenance — select source text -> Show in original", () => {
  test("selecting a lab row's own text shows the contextual menu, and it opens the shared RightWorkspace", async ({
    page,
    request,
  }) => {
    const seed = seedDischargeDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openDischargeReader(page, seed.document_id);

      await goToSection(page, "Laboratory results", page.getByText("White Blood Cell Count").first());

      await selectWordIn(page, page.getByText("White Blood Cell Count"));

      const showInOriginal = page.getByRole("button", { name: "Show in original" });
      await expect(showInOriginal).toBeVisible();

      await showInOriginal.click();
      await expect(page.locator(".b-app-split-viewer")).toBeVisible();
      // The menu itself closes once its action is taken.
      await expect(page.getByRole("button", { name: "Show in original" })).toHaveCount(0);
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("Escape dismisses the menu without opening anything", async ({ page, request }) => {
    const seed = seedDischargeDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openDischargeReader(page, seed.document_id);

      await goToSection(page, "Laboratory results", page.getByText("White Blood Cell Count").first());
      await selectWordIn(page, page.getByText("White Blood Cell Count"));
      await expect(page.getByRole("button", { name: "Show in original" })).toBeVisible();

      await page.keyboard.press("Escape");
      await expect(page.getByRole("button", { name: "Show in original" })).toHaveCount(0);
      await expect(page.locator(".b-app-split-viewer")).toHaveCount(0);
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("selecting a new, unrelated word replaces rather than stacks the menu", async ({ page, request }) => {
    const seed = seedDischargeDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openDischargeReader(page, seed.document_id);

      await goToSection(page, "Laboratory results", page.getByText("White Blood Cell Count").first());
      await selectWordIn(page, page.getByText("White Blood Cell Count"));
      await expect(page.getByRole("button", { name: "Show in original" })).toBeVisible();

      // Collapse that selection from a neutral spot the floating menu
      // cannot itself be covering (the page heading, far above the lab
      // table), then select a different row's own text — proving the
      // OLD menu is really gone and a fresh selection produces exactly
      // one new menu, never two stacked instances.
      await page.getByRole("heading", { name: "Discharge Summary" }).first().click();
      await expect(page.getByRole("button", { name: "Show in original" })).toHaveCount(0);

      await selectWordIn(page, page.getByText("349").first());
      await expect(page.getByRole("button", { name: "Show in original" })).toHaveCount(1);
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("UI-generated 'Requires review' badge text never offers Show in original", async ({ page, request }) => {
    const seed = seedDischargeDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openDischargeReader(page, seed.document_id);

      await goToSection(page, "Laboratory results", page.getByText("Requires review").first());

      await selectWordIn(page, page.getByText("Requires review"));
      await expect(page.getByRole("button", { name: "Show in original" })).toHaveCount(0);
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("UI-generated 'Calculated from a documented course' note never offers Show in original", async ({
    page,
    request,
  }) => {
    const seed = seedDischargeDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openDischargeReader(page, seed.document_id);

      await goToSection(page, "Discharge medications", page.getByText(/Calculated from a documented course/i));

      await selectWordIn(page, page.getByText(/Calculated/i));
      await expect(page.getByRole("button", { name: "Show in original" })).toHaveCount(0);
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("selecting a medication's own name offers Show in original", async ({ page, request }) => {
    const seed = seedDischargeDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openDischargeReader(page, seed.document_id);

      await goToSection(page, "Discharge medications", page.getByText("Amoxicilina"));

      await selectWordIn(page, page.getByText("Amoxicilina"));
      await expect(page.getByRole("button", { name: "Show in original" })).toBeVisible();
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("mobile viewport: reader stays usable, no stray menu blocks the layout", async ({ page, request }) => {
    const seed = seedDischargeDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto(`/documents/${seed.document_id}/discharge`);

      const nav = page.getByRole("combobox", { name: "Document section" });
      await expect(nav).toBeVisible();
      await nav.selectOption({ label: "Laboratory results" });
      await expect(page.getByText("White Blood Cell Count").first()).toBeVisible({ timeout: 15000 });
      // No leftover selection-menu button from a previous test/state.
      await expect(page.getByRole("button", { name: "Show in original" })).toHaveCount(0);
    } finally {
      await deletePatient(request, seed.token);
    }
  });
});
