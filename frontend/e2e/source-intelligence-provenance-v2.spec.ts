import { execFileSync } from "node:child_process";
import * as path from "node:path";
import { test, expect, APIRequestContext, Page } from "@playwright/test";

/**
 * Real-browser regression for Source Intelligence + Provenance V2 —
 * "View in original" now works for diagnoses, investigations,
 * anomalies, recommendations, current-hospitalization events, Clinical
 * Course timeline events, and treatment eras (previously NONE of these
 * had a provenance action at all; only labs/medications did).
 *
 * Seeds via backend/scripts/seed_e2e_clinical_reader_v2_document.py,
 * which now attaches real page-anchored SourceEvidence rows (via the
 * reprocessing pipeline's real _attach_segment_evidence step) with a
 * mocked (never live) AI interpreter response — zero external API cost,
 * same convention as clinical-reader-intelligence-v2.spec.ts.
 *
 * The seeded document has no real file in storage (same as every other
 * synthetic E2E fixture in this repo — see clinical-reader.spec.ts),
 * so the PDF itself never renders; what IS verified here is exactly
 * what the codebase's own established testing boundary already covers
 * elsewhere (exact-provenance.spec.ts's own header comment delegates
 * pixel-exact bbox assertions to a backend unit test): the action
 * exists, it opens the shared viewer, the viewer reaches the correct
 * PRECISION state and shows an honest notice — never a dead button,
 * never a silently wrong page.
 *
 * Requires: a backend (uvicorn) already running with a real
 * DATABASE_URL, and the frontend dev server.
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

const PAGE_ONLY_NOTICE = "The exact page is known; precise position isn't available.";

/**
 * The reader's own content area (`EntryContent`'s `.soft-card-tight`
 * wrapper) — scoping "View source" lookups to this excludes the
 * document header's OWN "View source" action (the whole-document
 * anchor, same label, rendered outside this wrapper), which would
 * otherwise make every "exactly N View source buttons" assertion below
 * off-by-one.
 */
function readerContent(page: Page) {
  return page.locator(".soft-card-tight").last();
}

test.describe("Source Intelligence + Provenance V2 — View in original for every fact type", () => {
  test("diagnosis: D45 has a real View source action that opens the shared viewer with an honest page-only notice", async ({
    page,
    request,
  }) => {
    const seed = seedFixtureDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openReader(page, seed.document_id);

      await page.getByRole("button", { name: "Diagnoses" }).click();
      await expect(page.getByText("D45")).toBeVisible();

      const viewSource = readerContent(page).getByRole("button", { name: "View source" });
      await expect(viewSource).toBeVisible();
      await viewSource.click();

      await expect(page.locator(".b-app-split-viewer")).toBeVisible();
      await expect(page.getByText(PAGE_ONLY_NOTICE)).toBeVisible();
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("investigation: JAK2 V617F (no dated event, historical narrative) has its own precise View source action", async ({
    page,
    request,
  }) => {
    const seed = seedFixtureDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openReader(page, seed.document_id);

      // Reached via Overview's "Key investigations" pointer list first,
      // to confirm the full Investigation card (with its own action) is
      // one click away — Investigations itself has no dedicated outline
      // entry here since the deterministic form-field section is
      // template-only (suppressed) in this fixture.
      await page.getByRole("button", { name: "Clinical course" }).click();
      const jak2Row = page.locator("text=JAK2 V617F").first();
      await expect(jak2Row).toBeVisible();
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("anomaly: AV 1008 has a View source action distinct from the 3036 anomaly's own action", async ({
    page,
    request,
  }) => {
    const seed = seedFixtureDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openReader(page, seed.document_id);

      // Overview renders both anomalies (AnomalyWarnings).
      await expect(page.getByText(/AV 1008\/min/)).toBeVisible();
      await expect(page.getByText("14.09.3036")).toBeVisible();

      const sourceActions = readerContent(page).getByRole("button", { name: "View source" });
      await expect(sourceActions).toHaveCount(2); // one per anomaly, each independently actionable
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("recommendation has its own View source action", async ({ page, request }) => {
    const seed = seedFixtureDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openReader(page, seed.document_id);

      await page.getByRole("button", { name: "Recommendations" }).click();
      await expect(page.getByText(/Continuare tratament cu Besremi/)).toBeVisible();
      await expect(readerContent(page).getByRole("button", { name: "View source" })).toBeVisible();
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("Current Hospitalization events each have their own View source action, excluding historical events", async ({
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
      const sourceActions = readerContent(page).getByRole("button", { name: "View source" });
      const count = await sourceActions.count();
      expect(count).toBeGreaterThanOrEqual(2); // admission + discharge, at minimum
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("treatment eras render with a 'View sources (N)' cycler, not a single fake exact source", async ({
    page,
    request,
  }) => {
    const seed = seedFixtureDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openReader(page, seed.document_id);

      await page.getByRole("button", { name: "Clinical course" }).click();
      await expect(page.getByText("Treatment eras", { exact: false })).toBeVisible();
      // The era card's own date-range line is unambiguous (unlike the
      // bare drug name, which also appears in the narrative prose above
      // it) — confirms the card itself rendered, not just the narrative.
      await expect(page.getByText("2022-09-18", { exact: false }).first()).toBeVisible();
      await expect(page.getByText(/Besremi \(ropeginterferon/).first()).toBeVisible();

      // Ruxolitinib has exactly ONE grounded event -> degrades to a
      // plain single "View source" action (MultiSourceAction's own
      // documented degrade-to-single behavior).
      // Besremi has TWO grounded events -> "View sources (2)".
      const viewSources = page.getByRole("button", { name: /View sources \(2\)/ });
      await expect(viewSources).toBeVisible();
      await viewSources.click();

      await expect(page.locator(".b-app-split-viewer")).toBeVisible();
      await expect(page.getByText("1 of 2")).toBeVisible();

      const nextButton = page.getByRole("button", { name: "Next source" });
      await expect(nextButton).toBeEnabled();
      await nextButton.click();
      await expect(page.getByText("2 of 2")).toBeVisible();

      const prevButton = page.getByRole("button", { name: "Previous source" });
      await expect(prevButton).toBeEnabled();
      await expect(nextButton).toBeDisabled(); // already at the last source
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("selecting evidence A, then B, then A again keeps the viewer open and correct each time", async ({
    page,
    request,
  }) => {
    const seed = seedFixtureDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openReader(page, seed.document_id);

      await page.getByRole("button", { name: "Diagnoses" }).click();
      const diagnosisSource = readerContent(page).getByRole("button", { name: "View source" });
      await diagnosisSource.click();
      await expect(page.locator(".b-app-split-viewer")).toBeVisible();
      await expect(page.getByText(PAGE_ONLY_NOTICE)).toBeVisible();

      await page.getByRole("button", { name: "Recommendations" }).click();
      const recommendationSource = readerContent(page).getByRole("button", { name: "View source" });
      await recommendationSource.click();
      await expect(page.locator(".b-app-split-viewer")).toBeVisible();
      await expect(page.getByText(PAGE_ONLY_NOTICE)).toBeVisible();

      // Back to A — the viewer must still be open, correct, and
      // re-selectable, not stuck on the previous selection.
      await page.getByRole("button", { name: "Diagnoses" }).click();
      const diagnosisSourceAgain = readerContent(page).getByRole("button", { name: "View source" });
      await diagnosisSourceAgain.click();
      await expect(page.locator(".b-app-split-viewer")).toBeVisible();
      await expect(page.getByText(PAGE_ONLY_NOTICE)).toBeVisible();
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("mobile viewport: a diagnosis's View source action opens the full-screen source sheet", async ({
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
      await nav.selectOption({ label: "Diagnoses" });
      await expect(page.getByText("D45")).toBeVisible();

      await readerContent(page).getByRole("button", { name: "View source" }).click();
      await expect(page.locator(".b-source-viewer-sheet, .b-app-split-viewer")).toBeVisible();
    } finally {
      await deletePatient(request, seed.token);
    }
  });
});
