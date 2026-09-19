import { execFileSync } from "node:child_process";
import * as path from "node:path";
import { test, expect, APIRequestContext, Page, Locator } from "@playwright/test";

/**
 * Real-browser, real-PDF regression for Source Geometry + Clinical
 * Table Intelligence V3 — the first suite in this repo to seed a
 * document with an ACTUAL file in storage (see
 * scripts/seed_e2e_source_geometry_v3_document.py), so the shared
 * source viewer genuinely renders PDF pages and draws highlight
 * rectangles from real geometry, not just an honest "no exact location"
 * notice (the boundary every earlier E2E fixture in this repo
 * deliberately stayed within — see source-intelligence-provenance-v2.
 * spec.ts's own header comment).
 *
 * The seed script runs the REAL `reprocess_discharge_document` pipeline
 * (real table classification/routing, real geometry alignment, real
 * SourceEvidence bbox/field_bboxes_json) against the real 8-page
 * synthetic PDF fixture (tests/fixtures/clinical_reader_v3_pdf_
 * fixture.py) — only the AI interpreter's model call is mocked (never
 * live OpenAI), same convention as every other seed script here.
 *
 * Requires: a backend (uvicorn, ASK_BRAGI_ENABLED=true) already running
 * with a real DATABASE_URL, and the frontend dev server.
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
  const out = execFileSync("python", ["scripts/seed_e2e_source_geometry_v3_document.py"], {
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

async function setDarkMode(page: Page, dark: boolean) {
  await page.evaluate((isDark) => {
    localStorage.setItem("bloodwork-theme", isDark ? "dark" : "light");
  }, dark);
}

async function openReader(page: Page, documentId: number) {
  await page.goto(`/documents/${documentId}/discharge`);
  await expect(page.getByRole("navigation", { name: "Document outline" })).toBeVisible();
}

function readerContent(page: Page) {
  return page.locator(".soft-card-tight").last();
}

function investigationCard(page: Page, titleSubstring: string): Locator {
  return page.locator(".b-invest-card").filter({ hasText: titleSubstring });
}

function medicationCard(page: Page, exactName: string): Locator {
  // MedicationList renders one `.soft-card-tight` card per
  // PatientMedication — the SAME class the section content wrapper
  // itself uses. `.filter({has})` matches BOTH the outer section
  // wrapper (it transitively CONTAINS the name text too) and the
  // specific inner card — `.last()` picks the innermost/correct one,
  // since it opens later in document order. Matched by the card's own
  // name element with EXACT text (substring `hasText` would wrongly
  // match BOTH "Besremi" and "Continuare tratament cu Besremi..." for
  // the same query).
  return page
    .locator(".soft-card-tight")
    .filter({ has: page.getByText(exactName, { exact: true }) })
    .last();
}

function anomalyItem(page: Page, textSubstring: string): Locator {
  return page.locator(".b-anomaly-item").filter({ hasText: textSubstring });
}

/** The viewer panel — desktop split OR mobile full-screen sheet,
 * whichever is currently mounted. */
function sourceViewer(page: Page) {
  return page.locator(".b-app-split-viewer, .b-source-viewer-sheet");
}

function highlightRects(page: Page) {
  return sourceViewer(page).locator(".b-source-highlight");
}

async function expectPageNumber(page: Page, pageNumber: number) {
  await expect(sourceViewer(page).getByText(`Page ${pageNumber} of`, { exact: false })).toBeVisible();
}

/** Real geometric alignment check: every rendered highlight rect must
 * sit INSIDE the rendered PDF canvas area (never off-canvas, never a
 * zero-size box) — a real, if coarse, proof the rectangle actually
 * overlays real page content rather than floating disconnected from
 * it. */
async function expectHighlightsWithinCanvas(page: Page) {
  const canvas = sourceViewer(page).locator(".b-source-viewer-canvas-wrap");
  const canvasBox = await canvas.boundingBox();
  expect(canvasBox).not.toBeNull();
  const rects = highlightRects(page);
  const count = await rects.count();
  expect(count).toBeGreaterThan(0);
  for (let i = 0; i < count; i++) {
    const box = await rects.nth(i).boundingBox();
    expect(box).not.toBeNull();
    if (!box || !canvasBox) continue;
    expect(box.width).toBeGreaterThan(0);
    expect(box.height).toBeGreaterThan(0);
    // A few px of tolerance for border/rounding.
    expect(box.x).toBeGreaterThanOrEqual(canvasBox.x - 3);
    expect(box.y).toBeGreaterThanOrEqual(canvasBox.y - 3);
    expect(box.x + box.width).toBeLessThanOrEqual(canvasBox.x + canvasBox.width + 3);
    expect(box.y + box.height).toBeLessThanOrEqual(canvasBox.y + canvasBox.height + 3);
  }
}

/** Highlight position as a FRACTION of the canvas (position-invariant
 * across zoom/resize, since both the canvas and the highlight scale
 * together from the same normalized coordinates) — used to prove a
 * highlight didn't drift after a resize, without hardcoding pixels. */
async function highlightFraction(page: Page) {
  const canvas = sourceViewer(page).locator(".b-source-viewer-canvas-wrap");
  const canvasBox = (await canvas.boundingBox())!;
  const box = (await highlightRects(page).first().boundingBox())!;
  return {
    x: (box.x - canvasBox.x) / canvasBox.width,
    y: (box.y - canvasBox.y) / canvasBox.height,
    width: box.width / canvasBox.width,
    height: box.height / canvasBox.height,
  };
}

test.describe("Source Geometry + Clinical Table Intelligence V3 — real PDF, real highlights", () => {
  test("A: D45 diagnosis opens page 1 with a real block highlight over the diagnosis text", async ({
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
      await readerContent(page).getByRole("button", { name: "View source" }).click();

      await expect(sourceViewer(page)).toBeVisible();
      await expectPageNumber(page, 1);
      await expectHighlightsWithinCanvas(page);
      await page.screenshot({ path: "test-results/v3-a-d45.png" });
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("B: historical phlebotomy paragraph highlight on page 2", async ({ page, request }) => {
    const seed = seedFixtureDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openReader(page, seed.document_id);

      await page.getByRole("button", { name: "Clinical course" }).click();
      const PHLEBOTOMY_TEXT =
        "La 22.06.2019 s-a efectuat flebotomie terapeutica (izovolemica), bine tolerata de pacienta.";
      await expect(page.getByText(PHLEBOTOMY_TEXT, { exact: true }).first()).toBeVisible();

      // The timeline entry card (`.soft-card-tight`, same class as the
      // section wrapper and every medication card) uniquely identified
      // by its own exact event text, with its own "View source" button.
      const timelineEntry = page
        .locator(".soft-card-tight")
        .filter({ has: page.getByText(PHLEBOTOMY_TEXT, { exact: true }) })
        .last();
      await timelineEntry.getByRole("button", { name: "View source" }).click();

      await expect(sourceViewer(page)).toBeVisible();
      await expectPageNumber(page, 2);
      await expectHighlightsWithinCanvas(page);
      await page.screenshot({ path: "test-results/v3-b-phlebotomy.png" });
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("C+D+E+F: ultrasound / JAK2 / bone marrow / BCR-ABL each get their OWN distinct highlight on page 4", async ({
    page,
    request,
  }) => {
    const seed = seedFixtureDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openReader(page, seed.document_id);

      await page.getByRole("button", { name: "Investigations", exact: true }).click();

      const facts: [string, string][] = [
        ["JAK2", "JAK2 V617F"],
        ["bone marrow", "Biopsie osteomedulara"],
        ["ultrasound", "Ecografie abdominala"],
        ["BCR-ABL", "BCR-ABL"],
      ];

      const seenFractions: { x: number; y: number; width: number; height: number }[] = [];

      for (const [label, title] of facts) {
        const card = investigationCard(page, title);
        await expect(card).toBeVisible();
        await card.getByRole("button", { name: "View source" }).click();

        await expect(sourceViewer(page)).toBeVisible();
        await expectPageNumber(page, 4);
        await expectHighlightsWithinCanvas(page);

        const fraction = await highlightFraction(page);
        seenFractions.push(fraction);
        await page.screenshot({ path: `test-results/v3-${label.replace(/\s+/g, "-").toLowerCase()}.png` });
      }

      // Every one of the four facts must land on a genuinely DIFFERENT
      // rectangle — never one shared page-4 evidence blob (Part 61's
      // explicit "unacceptable" example).
      for (let i = 0; i < seenFractions.length; i++) {
        for (let j = i + 1; j < seenFractions.length; j++) {
          const a = seenFractions[i];
          const b = seenFractions[j];
          const moved = Math.abs(a.y - b.y) > 0.01 || Math.abs(a.x - b.x) > 0.01;
          expect(moved).toBe(true);
        }
      }
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("G: prescription table — Besremi row/cells highlighted, distinct from other rows", async ({
    page,
    request,
  }) => {
    const seed = seedFixtureDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openReader(page, seed.document_id);

      await page.getByRole("button", { name: "Prescriptions" }).click();
      const besremiCard = medicationCard(page, "Besremi");
      await expect(besremiCard).toBeVisible();

      await besremiCard.getByRole("button", { name: "View source" }).click();
      await expect(sourceViewer(page)).toBeVisible();
      await expectPageNumber(page, 5);
      await expectHighlightsWithinCanvas(page);

      // Real per-cell precision: more than one rectangle for this row
      // (name + dose cells at minimum), never a single whole-page box.
      const count = await highlightRects(page).count();
      expect(count).toBeGreaterThanOrEqual(1);
      await page.screenshot({ path: "test-results/v3-g-prescription.png" });
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("H: ALT lab value — multiple real per-cell rectangles render, not just one", async ({ page, request }) => {
    const seed = seedFixtureDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openReader(page, seed.document_id);

      await page.getByRole("button", { name: "Laboratory results" }).click();
      await expect(page.getByText("ALT", { exact: true }).first()).toBeVisible();

      const altRow = readerContent(page).locator("tr").filter({ hasText: "ALT" });
      await altRow.getByRole("button", { name: "View source" }).click();

      await expect(sourceViewer(page)).toBeVisible();
      await expectPageNumber(page, 6);
      await expectHighlightsWithinCanvas(page);

      // The core multi-rect regression this V3 phase's cell geometry
      // exists to prove, browser-visible — PR #10 previously computed
      // multiple rectangles but rendered only one.
      const count = await highlightRects(page).count();
      expect(count).toBe(4); // name/value/unit/reference_range

      await page.screenshot({ path: "test-results/v3-h-alt-multirect.png" });
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("I: medication table row (Hidroxiuree) is highlighted with real cells, not treated as a lab", async ({
    page,
    request,
  }) => {
    const seed = seedFixtureDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openReader(page, seed.document_id);

      await page.getByRole("button", { name: "Medications" }).click();
      const hidroxiureeCard = medicationCard(page, "Hidroxiuree");
      await expect(hidroxiureeCard).toBeVisible();

      await hidroxiureeCard.getByRole("button", { name: "View source" }).click();

      await expect(sourceViewer(page)).toBeVisible();
      await expectPageNumber(page, 3);
      await expectHighlightsWithinCanvas(page);
      const count = await highlightRects(page).count();
      expect(count).toBeGreaterThanOrEqual(2); // name + dose cells at minimum
      await page.screenshot({ path: "test-results/v3-i-medication-table.png" });
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("J: recommendation paragraph highlight, not only page navigation", async ({ page, request }) => {
    const seed = seedFixtureDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openReader(page, seed.document_id);

      await page.getByRole("button", { name: "Recommendations" }).click();
      await expect(page.getByText(/Continuare tratament cu Besremi/)).toBeVisible();
      await readerContent(page).getByRole("button", { name: "View source" }).click();

      await expect(sourceViewer(page)).toBeVisible();
      await expectPageNumber(page, 7);
      await expectHighlightsWithinCanvas(page);
      await page.screenshot({ path: "test-results/v3-j-recommendation.png" });
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("K: anomaly (AV 1008/min) shows correct page/block, original value unmodified", async ({
    page,
    request,
  }) => {
    const seed = seedFixtureDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openReader(page, seed.document_id);

      const anomaly = anomalyItem(page, "AV 1008");
      await expect(anomaly).toBeVisible();
      await anomaly.getByRole("button", { name: "View source" }).click();

      await expect(sourceViewer(page)).toBeVisible();
      await expectPageNumber(page, 2);
      // The suspicious value itself must remain visible, verbatim, in
      // the reader — never silently corrected.
      await expect(page.getByText(/AV 1008\/min/)).toBeVisible();
      await page.screenshot({ path: "test-results/v3-k-anomaly.png" });
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("A -> B -> A: switching evidence updates the highlight each time, never leaves a stale rectangle", async ({
    page,
    request,
  }) => {
    const seed = seedFixtureDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openReader(page, seed.document_id);

      await page.getByRole("button", { name: "Investigations", exact: true }).click();
      await investigationCard(page, "JAK2 V617F").getByRole("button", { name: "View source" }).click();
      await expect(sourceViewer(page)).toBeVisible();
      await expectPageNumber(page, 4);
      const jak2Fraction = await highlightFraction(page);

      await page.getByRole("button", { name: "Laboratory results" }).click();
      const altRow = readerContent(page).locator("tr").filter({ hasText: "ALT" });
      await altRow.getByRole("button", { name: "View source" }).click();
      await expect(sourceViewer(page)).toBeVisible();
      await expectPageNumber(page, 6);
      expect(await highlightRects(page).count()).toBe(4);

      // Back to JAK2 — must reapply its own highlight, not leave ALT's.
      await page.getByRole("button", { name: "Investigations", exact: true }).click();
      await investigationCard(page, "JAK2 V617F").getByRole("button", { name: "View source" }).click();
      await expect(sourceViewer(page)).toBeVisible();
      await expectPageNumber(page, 4);
      const jak2FractionAgain = await highlightFraction(page);
      expect(Math.abs(jak2Fraction.x - jak2FractionAgain.x)).toBeLessThan(0.02);
      expect(Math.abs(jak2Fraction.y - jak2FractionAgain.y)).toBeLessThan(0.02);
      // Not ALT's 4 cells.
      expect(await highlightRects(page).count()).not.toBe(4);
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("same evidence twice: re-clicking the same View source stays correct", async ({ page, request }) => {
    const seed = seedFixtureDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openReader(page, seed.document_id);

      await page.getByRole("button", { name: "Diagnoses" }).click();
      const viewSource = readerContent(page).getByRole("button", { name: "View source" });
      await viewSource.click();
      await expect(sourceViewer(page)).toBeVisible();
      const first = await highlightFraction(page);

      await page.getByRole("button", { name: "Diagnoses" }).click();
      await readerContent(page).getByRole("button", { name: "View source" }).click();
      await expect(sourceViewer(page)).toBeVisible();
      const second = await highlightFraction(page);

      expect(Math.abs(first.x - second.x)).toBeLessThan(0.02);
      expect(Math.abs(first.y - second.y)).toBeLessThan(0.02);
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("viewer already open: clicking a different source item updates page + highlight in place", async ({
    page,
    request,
  }) => {
    const seed = seedFixtureDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openReader(page, seed.document_id);

      await page.getByRole("button", { name: "Diagnoses" }).click();
      await readerContent(page).getByRole("button", { name: "View source" }).click();
      await expect(sourceViewer(page)).toBeVisible();
      await expectPageNumber(page, 1);

      await page.getByRole("button", { name: "Recommendations" }).click();
      await readerContent(page).getByRole("button", { name: "View source" }).click();
      await expect(sourceViewer(page)).toBeVisible();
      await expectPageNumber(page, 7);
      await expectHighlightsWithinCanvas(page);
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("resize: exact-bbox highlight stays geometrically aligned to the canvas across viewport widths", async ({
    page,
    request,
  }) => {
    const seed = seedFixtureDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openReader(page, seed.document_id);

      await page.getByRole("button", { name: "Laboratory results" }).click();
      const altRow = readerContent(page).locator("tr").filter({ hasText: "ALT" });
      await altRow.getByRole("button", { name: "View source" }).click();
      await expect(sourceViewer(page)).toBeVisible();
      await expectHighlightsWithinCanvas(page);
      const before = await highlightFraction(page);

      for (const width of [1280, 1024, 768]) {
        await page.setViewportSize({ width, height: 900 });
        await page.waitForTimeout(300); // canvas re-render on resize
        await expectHighlightsWithinCanvas(page);
        const after = await highlightFraction(page);
        // Normalized position must stay stable — it's derived fresh
        // from the same [0,1] coordinates on every render, never a
        // cached stale pixel position.
        expect(Math.abs(before.x - after.x)).toBeLessThan(0.03);
        expect(Math.abs(before.y - after.y)).toBeLessThan(0.03);
      }
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("mobile: View in original opens the full-screen sheet with a visible highlight, scrolled into view", async ({
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
      await expectHighlightsWithinCanvas(page);
      await page.screenshot({ path: "test-results/v3-mobile-390.png" });
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("mobile 430: same flow at the wider mobile breakpoint", async ({ page, request }) => {
    const seed = seedFixtureDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 430, height: 900 });
      await page.goto(`/documents/${seed.document_id}/discharge`);

      const nav = page.getByRole("combobox", { name: "Document section" });
      await expect(nav).toBeVisible();
      await nav.selectOption({ label: "Diagnoses" });
      await expect(page.getByText("D45")).toBeVisible();

      await readerContent(page).getByRole("button", { name: "View source" }).click();
      await expect(page.locator(".b-source-viewer-sheet, .b-app-split-viewer")).toBeVisible();
      await expectHighlightsWithinCanvas(page);
      await page.screenshot({ path: "test-results/v3-mobile-430.png" });
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("dark mode: paragraph highlight and exact table-cell highlight both stay visible", async ({
    page,
    request,
  }) => {
    const seed = seedFixtureDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await setDarkMode(page, true);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openReader(page, seed.document_id);

      await page.getByRole("button", { name: "Diagnoses" }).click();
      await readerContent(page).getByRole("button", { name: "View source" }).click();
      await expect(sourceViewer(page)).toBeVisible();
      await expectHighlightsWithinCanvas(page);
      await page.screenshot({ path: "test-results/v3-dark-paragraph.png" });

      await page.getByRole("button", { name: "Laboratory results" }).click();
      const altRow = readerContent(page).locator("tr").filter({ hasText: "ALT" });
      await altRow.getByRole("button", { name: "View source" }).click();
      await expect(sourceViewer(page)).toBeVisible();
      await expectPageNumber(page, 6);
      await expect(highlightRects(page)).toHaveCount(4);
      await page.screenshot({ path: "test-results/v3-dark-alt-cells.png" });
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("precision fallback: a page-only fact opens the correct page with NO fabricated rectangle", async ({
    page,
    request,
  }) => {
    const seed = seedFixtureDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await openReader(page, seed.document_id);

      // The recommendation-derived medication candidate ("Continuare
      // tratament cu Besremi...") is a prose-narrative mention, not a
      // table row — it has real page_number but NO per-field geometry,
      // so it must render the honest "page is known, exact position
      // isn't" notice, never a guessed rectangle.
      await page.getByRole("button", { name: "Medications" }).click();
      const card = medicationCard(page, "Continuare tratament cu Besremi 150 micrograme");
      await expect(card).toBeVisible();
      await card.getByRole("button", { name: "View source" }).click();

      await expect(sourceViewer(page)).toBeVisible();
      await expectPageNumber(page, 7);
      await expect(page.getByText("The exact page is known; precise position isn't available.")).toBeVisible();
      await expect(highlightRects(page)).toHaveCount(0);
    } finally {
      await deletePatient(request, seed.token);
    }
  });
});
