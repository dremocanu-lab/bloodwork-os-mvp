import { execFileSync } from "node:child_process";
import * as path from "node:path";
import { test, expect, APIRequestContext } from "@playwright/test";

/**
 * Real-browser geometry regression for the RightWorkspace half-height
 * bug (BRAGI PRODUCT RELIABILITY PASS Part A / Clinical Document
 * Intelligence V3 Phase 2's own "RIGHT WORKSPACE LAYOUT CONTRACT" —
 * "Do NOT render an empty flex:1 wrapper for a closed panel").
 *
 * Needs a real, processed structured document to reach the reader page
 * that hosts BOTH the Ask Bragi contextual panel and the PDF source
 * viewer (documents/[id]/page.tsx) — which normally means Reducto
 * extraction. That would cost real provider calls just to stand up a
 * fixture, so this instead seeds a Document + LabResult + SourceEvidence
 * row DIRECTLY via the ORM (see backend/scripts/seed_e2e_lab_document.py
 * — the exact same zero-external-cost pattern
 * backend/tests/test_ask_bragi_service.py's own `patient_with_data`
 * fixture already uses), bypassing Reducto entirely. This only exercises
 * layout, not extraction — extraction has its own backend test coverage.
 *
 * Requires: a backend (uvicorn) already running with a real DATABASE_URL
 * (same as ask-bragi-workspace.spec.ts), and the frontend dev server —
 * see playwright.config.ts. Does not require OPENAI_API_KEY/
 * REDUCTO_API_KEY/ASK_BRAGI_ENABLED — this suite never opens a real Ask
 * Bragi conversation, only the panel shell (empty/starting state is
 * enough to measure geometry).
 */

const API_BASE = process.env.PLAYWRIGHT_API_BASE_URL || "http://127.0.0.1:8812";
const BACKEND_DIR = path.resolve(__dirname, "..", "..", "backend");

type SeedResult = {
  token: string;
  user: { id: number; email: string; full_name: string; role: "patient" };
  patient_id: number;
  document_id: number;
  lab_id: number;
};

function seedLabDocument(): SeedResult {
  const out = execFileSync("python", ["scripts/seed_e2e_lab_document.py"], {
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

async function seedAuth(page: import("@playwright/test").Page, token: string, user: unknown) {
  await page.goto("/login");
  await page.evaluate(
    ([t, u]) => {
      localStorage.setItem("access_token", t as string);
      localStorage.setItem("user", JSON.stringify(u));
    },
    [token, user]
  );
}

test.describe("RightWorkspace geometry — single open panel gets full height, not half", () => {
  test("Ask Bragi panel alone fills the split viewer column (no empty sibling wrapper)", async ({
    page,
    request,
  }) => {
    const seed = seedLabDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 }); // desktop split, not the tablet/mobile sheet
      await page.goto(`/documents/${seed.document_id}`);

      const openAskBragi = page.getByRole("button", { name: "Ask Bragi about this record" });
      await expect(openAskBragi).toBeVisible();
      await openAskBragi.click();

      const askBragiDialog = page.getByRole("dialog", { name: "Ask Bragi" });
      await expect(askBragiDialog).toBeVisible();

      const viewerColumn = page.locator(".b-app-split-viewer");
      await expect(viewerColumn).toBeVisible();

      const [viewerBox, dialogBox] = await Promise.all([viewerColumn.boundingBox(), askBragiDialog.boundingBox()]);
      expect(viewerBox).not.toBeNull();
      expect(dialogBox).not.toBeNull();

      // The bug: an unconditionally-rendered empty `flex: 1` sibling
      // wrapper for the closed source-viewer panel split the column
      // roughly in half. Fixed, the one open panel's own dialog should
      // fill essentially the WHOLE column height — allow a few px for
      // borders/rounding, but nothing close to a 50/50 split.
      expect(dialogBox!.height).toBeGreaterThan(viewerBox!.height * 0.9);

      // No tab switcher should exist — that only renders when BOTH
      // panels are open (see right-workspace.tsx's `showTabs`).
      await expect(page.getByRole("tablist", { name: "Workspace panel" })).toHaveCount(0);
    } finally {
      await deletePatient(request, seed.token);
    }
  });

  test("both panels open together show the tab switcher and neither is squeezed", async ({ page, request }) => {
    const seed = seedLabDocument();
    try {
      await seedAuth(page, seed.token, seed.user);
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto(`/documents/${seed.document_id}`);

      await page.getByRole("button", { name: "Ask Bragi about this record" }).click();
      await expect(page.getByRole("dialog", { name: "Ask Bragi" })).toBeVisible();

      const viewSource = page.getByRole("button", { name: "View in original" });
      await expect(viewSource).toBeVisible();
      await viewSource.click();

      const tabs = page.getByRole("tablist", { name: "Workspace panel" });
      await expect(tabs).toBeVisible();

      // Source was just opened, so RightWorkspace's own "a panel that just
      // opened becomes the visible one" rule makes it the active tab —
      // its wrapper has no `hidden` attribute, the Ask Bragi one does.
      // A `hidden` element has no box at all (boundingBox() -> null),
      // which is itself part of what this test is confirming: the
      // INACTIVE panel takes up zero rendered space, not half of it.
      const sourcePanel = page.locator(".b-source-viewer-split");
      await expect(sourcePanel).toBeVisible();
      // Located by its stable wrapper class, not role — the `hidden`
      // attribute (see right-workspace.tsx) removes it from the
      // accessibility tree entirely while inactive, so a role-based
      // locator would never resolve and boundingBox() would hang for the
      // full test timeout instead of promptly reporting "no box".
      const askBragiWrapper = page.locator(".b-ask-bragi-split");

      const viewerColumn = page.locator(".b-app-split-viewer");
      const [viewerBox, sourceBox, askBragiBox] = await Promise.all([
        viewerColumn.boundingBox(),
        sourcePanel.boundingBox(),
        askBragiWrapper.boundingBox(),
      ]);
      expect(viewerBox).not.toBeNull();
      expect(sourceBox).not.toBeNull();
      expect(askBragiBox).toBeNull(); // hidden, not just visually squeezed

      // The active (Source) panel fills the column below the tab bar —
      // not split in half with the inactive one.
      expect(sourceBox!.height).toBeGreaterThan(viewerBox!.height * 0.7);
    } finally {
      await deletePatient(request, seed.token);
    }
  });
});
