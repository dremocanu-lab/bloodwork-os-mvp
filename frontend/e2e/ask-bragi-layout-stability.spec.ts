import { test, expect, APIRequestContext, Page } from "@playwright/test";

/**
 * Real-browser geometry regression for the Ask Bragi dedicated-page
 * width-collapse bug (BRAGI — UNIVERSAL DOCUMENT INGESTION + ASK BRAGI
 * STABLE LAYOUT, Part P).
 *
 * Root cause (see components/ask-bragi/ask-bragi-chat.tsx): the assistant
 * bubble used `alignSelf: "flex-start"` with no floor width, so its box
 * was sized by CSS shrink-to-fit. A long completed answer's preferred
 * width exceeds the available column width, so shrink-to-fit resolves to
 * the full available width (looks "normal") — but the PENDING bubble's
 * only content is a short "Checking your record…" label, whose preferred
 * width is tiny, so it visibly collapsed into a narrow floating card
 * before re-expanding once the real answer arrived. Fixed by making the
 * assistant bubble `alignSelf: "stretch"` in both states, so its width is
 * the message column's width regardless of content — this test proves
 * that stays true across idle/pending/completed.
 *
 * The streaming endpoint is mocked via page.route() with an artificial
 * delay before the (single, non-chunked) response is fulfilled — this
 * gives a real, deterministic window where `generating` is true and no
 * answer text has arrived yet (the exact "Checking your record…" state
 * from the bug report), without depending on OPENAI_API_KEY/a real model
 * call. No ASK_BRAGI_ENABLED/OPENAI_API_KEY required, matching
 * ask-bragi-workspace.spec.ts's own convention — the assertions target
 * layout, not real answer content.
 */

const API_BASE = process.env.PLAYWRIGHT_API_BASE_URL || "http://127.0.0.1:8812";
const SYNTHETIC_ANSWER =
  "This is a realistic, multi-sentence synthetic answer used only to verify the assistant bubble reaches " +
  "its normal width once a real response arrives, matching the width measured while Bragi was still thinking " +
  "about your record.";

function uniqueEmail(label: string): string {
  return `pw-${label}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@example.com`;
}

async function signupPatient(request: APIRequestContext, label: string) {
  const email = uniqueEmail(label);
  const res = await request.post(`${API_BASE}/auth/signup`, {
    data: {
      email,
      full_name: `Playwright ${label}`,
      password: "TestPass123!",
      role: "patient",
      cnp: `600010${Math.floor(1000000 + Math.random() * 8999999)}`,
    },
  });
  expect(res.ok(), `signup failed: ${res.status()} ${await res.text()}`).toBeTruthy();
  const body = await res.json();
  return { token: body.access_token as string, user: body.user, email };
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

async function mockDelayedStream(page: Page) {
  await page.route("**/ask-bragi/conversations/*/messages/stream", async (route) => {
    const body =
      `event: status\ndata: ${JSON.stringify({ label: "Checking your record…" })}\n\n` +
      `event: completed\ndata: ${JSON.stringify({
        answer: SYNTHETIC_ANSWER,
        citations: [],
        chart: null,
        follow_ups: [],
        status: "answered",
        scope_used: "patient_record",
      })}\n\n`;
    // The whole SSE-shaped body is fulfilled in one shot (Playwright's
    // route.fulfill() has no real incremental-chunk timing control), so
    // the delay BEFORE fulfilling is what creates the real "pending, no
    // answer text yet" window — during it, `generating` is true and
    // `streamingAnswer` is still empty, exactly the reported bug state.
    await new Promise((resolve) => setTimeout(resolve, 1200));
    await route.fulfill({ status: 200, contentType: "text/event-stream", body });
  });
}

async function runStabilityCheck(page: Page, request: APIRequestContext, label: string) {
  const account = await signupPatient(request, label);
  try {
    await seedAuth(page, account.token, account.user);
    await mockDelayedStream(page);
    await page.goto("/ask-bragi");
    await expect(page.getByRole("heading", { name: "Ask Bragi" })).toBeVisible();

    const messagesSurface = page.locator(".ask-bragi-messages");
    await expect(messagesSurface).toBeVisible();
    const idleBox = await messagesSurface.boundingBox();
    expect(idleBox).not.toBeNull();

    const composer = page.getByPlaceholder("Ask about your record…");
    await composer.fill("What are my medications?");
    await composer.press("Enter");

    const assistantBubble = page.locator(".ask-bragi-bubble-assistant");
    await expect(assistantBubble).toBeVisible();
    await expect(page.getByText("Checking your record")).toBeVisible();
    const pendingBox = await assistantBubble.boundingBox();
    expect(pendingBox).not.toBeNull();

    await expect(page.getByText(SYNTHETIC_ANSWER)).toBeVisible({ timeout: 5000 });
    const completedBox = await assistantBubble.boundingBox();
    expect(completedBox).not.toBeNull();

    // The regression: the pending bubble must not be dramatically
    // narrower than the completed one (or the idle surface it sits
    // inside). A very small px tolerance for layout rounding — not a
    // loose percentage — is the point of this test.
    const TOLERANCE_PX = 4;
    expect(Math.abs(pendingBox!.width - completedBox!.width)).toBeLessThanOrEqual(TOLERANCE_PX);

    // Both bubble states occupy the same message column, so their width
    // should track the (constant, always-stretched) surface width minus
    // its own fixed horizontal padding — never collapse toward the
    // thinking-indicator label's own tiny content width.
    expect(pendingBox!.width).toBeGreaterThan(idleBox!.width * 0.7);
    expect(completedBox!.width).toBeGreaterThan(idleBox!.width * 0.7);

    // No composer horizontal jump, no sidebar movement: the surface's
    // own box (not just the bubble inside it) must also stay put.
    const finalSurfaceBox = await messagesSurface.boundingBox();
    expect(finalSurfaceBox).not.toBeNull();
    expect(Math.abs(finalSurfaceBox!.width - idleBox!.width)).toBeLessThanOrEqual(TOLERANCE_PX);
  } finally {
    await deletePatient(request, account.token);
  }
}

test.describe("Ask Bragi dedicated page — assistant bubble geometry stays stable (Part P)", () => {
  test("desktop viewport: no width collapse across idle / pending / completed", async ({ page, request }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await runStabilityCheck(page, request, "layout-stability-desktop");
  });

  test("mobile viewport: no width collapse across idle / pending / completed", async ({ page, request }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await runStabilityCheck(page, request, "layout-stability-mobile");
  });
});
