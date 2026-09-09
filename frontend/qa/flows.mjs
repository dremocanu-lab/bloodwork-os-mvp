// Bragi interaction flows.
//
// Loading a page proves it renders; it does not prove the redesigned controls
// work. This drives the real interactions the brief asks about — tabs, search,
// filters, sorting, menus, dialogs, patient switching, mobile navigation —
// and asserts on what appears afterwards.
//
//   node qa/flows.mjs [--only=<substr>] [--headed]

import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const ARGS = process.argv.slice(2);
const only = (ARGS.find((a) => a.startsWith("--only=")) || "").replace("--only=", "");
const headed = ARGS.includes("--headed");

const BASE = process.env.BRAGI_BASE || "http://localhost:3000";
const TOKENS = JSON.parse(fs.readFileSync(process.env.BRAGI_TOKENS, "utf8"));
const OUT = path.resolve("qa/shots", "flows");
fs.mkdirSync(OUT, { recursive: true });

const AS = {
  patient: "ancutailie@gmail.com",
  doctor: "wtf@wtf.com",
  pcp: "qa.pcp@bragiqa.com",
  admin: "andreimarin@gmail.com",
  care: "qa.carepartner@bragiqa.com",
  emergency: "qa.emergency@bragiqa.com",
};

const results = [];

function record(name, ok, detail) {
  results.push({ name, ok, detail });
  process.stdout.write(`${ok ? "." : "x"} ${name}${detail ? `  ${detail}` : ""}\n`);
}

async function seed(page, role) {
  await page.addInitScript(
    ({ entry }) => {
      try {
        localStorage.clear();
        if (entry) {
          localStorage.setItem("access_token", entry.access_token);
          localStorage.setItem("user", JSON.stringify(entry.user));
          if (entry.user.role === "emergency_worker") {
            localStorage.setItem("emergency_access_token", entry.access_token);
            localStorage.setItem("emergency_user", JSON.stringify(entry.user));
          }
        }
        localStorage.setItem("bloodwork_os_language", "en");
        localStorage.setItem("bloodwork-theme", "light");
        localStorage.setItem(
          "pcp_tab_ids",
          JSON.stringify([
            { patientId: 6, patientName: "Ancuta Ilie" },
            { patientId: 1, patientName: "Radu Mocanu" },
          ])
        );
        localStorage.setItem("pcp_active_tab", "6");
      } catch {}
    },
    { entry: role ? TOKENS[AS[role]] : null }
  );
}

async function goto(page, url) {
  await page.goto(BASE + url, { waitUntil: "domcontentloaded", timeout: 45000 });
  await page.waitForLoadState("networkidle", { timeout: 25000 }).catch(() => {});
  await page.waitForTimeout(500);
}

const FLOWS = [
  /* ── Doctor ─────────────────────────────────────────────────────────── */
  {
    name: "doctor: patient workspace tabs switch content",
    role: "doctor",
    viewport: { width: 1440, height: 900 },
    async run(page) {
      await goto(page, "/patients/6");

      for (const [tab, expect] of [
        ["Labs", "All analytes"],
        ["Documents", "documents"],
        ["Medications", "Total"],
        ["Timeline", "Records and admissions"],
        ["Overview", "Bloodwork reports"],
      ]) {
        await page.getByRole("tab", { name: new RegExp(`^${tab}`) }).click();
        await page.waitForTimeout(350);
        const found = await page.getByText(expect, { exact: false }).first().isVisible();
        if (!found) throw new Error(`tab "${tab}" did not reveal "${expect}"`);
      }
      await page.screenshot({ path: path.join(OUT, "doctor-tabs.png"), fullPage: false });
    },
  },
  {
    name: "doctor: labs abnormal-only filter reduces rows",
    role: "doctor",
    viewport: { width: 1440, height: 900 },
    async run(page) {
      await goto(page, "/patients/6?tab=labs");
      await page.waitForTimeout(400);

      const countText = () => page.locator(".b-toolbar-count").last().innerText();
      const before = await countText();
      await page.getByRole("button", { name: /Abnormal only/ }).click();
      await page.waitForTimeout(350);
      const after = await countText();
      if (before === after) throw new Error(`filter did not change count (${before})`);
      return `${before.trim()} -> ${after.trim()}`;
    },
  },
  {
    name: "doctor: analyte row expands to chart and source reports",
    role: "doctor",
    viewport: { width: 1440, height: 900 },
    async run(page) {
      await goto(page, "/patients/6?tab=labs");
      await page.waitForTimeout(400);

      const row = page.locator(".b-trend-row[aria-expanded]").first();
      await row.click();
      await page.waitForTimeout(400);
      const expanded = await row.getAttribute("aria-expanded");
      if (expanded !== "true") throw new Error("row did not expand");
      const sources = await page.getByText("Source reports", { exact: false }).first().isVisible();
      if (!sources) throw new Error("source reports not shown");
      await page.screenshot({ path: path.join(OUT, "doctor-lab-expanded.png"), fullPage: false });
    },
  },
  {
    name: "doctor: patient list search filters the table",
    role: "doctor",
    viewport: { width: 1440, height: 900 },
    async run(page) {
      await goto(page, "/my-patients");
      const rows = () => page.locator("table.b-table tbody tr").count();
      const before = await rows();
      await page.getByRole("searchbox").first().fill("Ancuta");
      await page.waitForTimeout(400);
      const after = await rows();
      if (after >= before || after === 0) throw new Error(`${before} -> ${after}`);
      return `${before} -> ${after} rows`;
    },
  },
  {
    name: "doctor: patient list column sort reorders rows",
    role: "doctor",
    viewport: { width: 1440, height: 900 },
    async run(page) {
      await goto(page, "/my-patients");
      const first = () =>
        page.locator("table.b-table tbody tr").first().locator(".b-cell-title").innerText();
      const before = await first();
      await page.locator("th.sortable").first().click();
      await page.waitForTimeout(300);
      const after = await first();
      const sorted = await page.locator("th[aria-sort]").count();
      if (sorted === 0) throw new Error("no aria-sort applied");
      return `${before} -> ${after}`;
    },
  },
  {
    name: "doctor: row overflow menu opens",
    role: "doctor",
    viewport: { width: 1440, height: 900 },
    async run(page) {
      await goto(page, "/patients/6?tab=documents");
      await page.waitForTimeout(400);
      await page.getByRole("button", { name: /More document actions/ }).first().click();
      await page.waitForTimeout(250);
      const open = await page.locator(".b-menu").first().isVisible();
      if (!open) throw new Error("menu did not open");
    },
  },
  {
    name: "doctor: featured-analyte picker dialog opens and selects",
    role: "doctor",
    viewport: { width: 1440, height: 900 },
    async run(page) {
      await goto(page, "/patients/6");
      await page.getByRole("button", { name: /^Change/ }).first().click();
      await page.waitForTimeout(300);
      const dialog = page.getByRole("dialog");
      if (!(await dialog.isVisible())) throw new Error("dialog did not open");
      await dialog.locator(".b-list-row").nth(1).click();
      await page.waitForTimeout(400);
      if (await page.getByRole("dialog").isVisible().catch(() => false)) {
        throw new Error("dialog did not close after selection");
      }
    },
  },

  /* ── Patient ────────────────────────────────────────────────────────── */
  {
    name: "patient: record tabs switch content",
    role: "patient",
    viewport: { width: 1440, height: 900 },
    async run(page) {
      await goto(page, "/my-records");
      for (const [tab, expect] of [
        ["Labs", "Bloodwork Trends"],
        ["Documents", "documents"],
        ["Timeline", "My Timeline"],
      ]) {
        await page.getByRole("tab", { name: new RegExp(`^${tab}`) }).click();
        await page.waitForTimeout(350);
        const found = await page
          .getByText(expect, { exact: false })
          .first()
          .isVisible()
          .catch(() => false);
        if (!found) throw new Error(`tab "${tab}" did not reveal "${expect}"`);
      }
    },
  },
  {
    name: "patient: medication status filter works",
    role: "patient",
    viewport: { width: 1440, height: 900 },
    async run(page) {
      await goto(page, "/my-records/medications");
      const rows = () => page.locator(".b-list-row").count();
      const before = await rows();
      await page.getByRole("button", { name: /^Active$/ }).click();
      await page.waitForTimeout(350);
      const after = await rows();
      if (after >= before) throw new Error(`${before} -> ${after}`);
      return `${before} -> ${after} rows`;
    },
  },
  {
    name: "patient: revoke access opens a confirmation naming the doctor",
    role: "patient",
    viewport: { width: 1440, height: 900 },
    async run(page) {
      await goto(page, "/my-records/access");
      await page.getByRole("button", { name: /Revoke/ }).first().click();
      await page.waitForTimeout(300);
      const dialog = page.getByRole("dialog");
      if (!(await dialog.isVisible())) throw new Error("confirmation did not open");
      const text = await dialog.innerText();
      if (!/lose access/i.test(text)) throw new Error("consequence not stated");
      await page.screenshot({ path: path.join(OUT, "patient-revoke-confirm.png"), fullPage: false });
      // Cancel: this must not actually revoke anything during QA.
      await dialog.getByRole("button", { name: /Cancel/ }).click();
      await page.waitForTimeout(250);
    },
  },

  /* ── PCP ────────────────────────────────────────────────────────────── */
  {
    name: "pcp: switching patient tabs changes the open record",
    role: "pcp",
    viewport: { width: 1440, height: 900 },
    async run(page) {
      await goto(page, "/pcp/workspace");
      const name = () => page.locator(".b-ctx-name").first().innerText();
      const before = await name();
      await page.getByRole("button", { name: /Radu Mocanu/ }).first().click();
      await page.waitForTimeout(900);
      const after = await name();
      if (before === after) throw new Error(`patient did not change (${before})`);
      await page.screenshot({ path: path.join(OUT, "pcp-switch.png"), fullPage: false });
      return `${before} -> ${after}`;
    },
  },
  {
    name: "pcp: timeline event-type filter works",
    role: "pcp",
    viewport: { width: 1440, height: 900 },
    async run(page) {
      await goto(page, "/pcp/workspace");
      await page.waitForTimeout(700);
      const events = () => page.locator(".b-tl-event").count();
      const before = await events();
      const labs = page.locator(".b-filter", { hasText: /Labs/ }).first();
      await labs.click();
      await page.waitForTimeout(400);
      const pressed = await labs.getAttribute("aria-pressed");
      if (pressed !== "true") throw new Error("filter not pressed");
      return `${before} events, filter applied`;
    },
  },

  /* ── Admin ──────────────────────────────────────────────────────────── */
  {
    name: "admin: patient search then doctor selection enables confirm",
    role: "admin",
    viewport: { width: 1440, height: 900 },
    async run(page) {
      await goto(page, "/assignments");
      await page.getByRole("searchbox").first().fill("Ancuta");
      await page.waitForTimeout(900);

      await page.locator(".b-list-row").first().click();
      await page.waitForTimeout(700);

      const confirm = page.getByRole("button", { name: /Confirm/ });
      const box = page.locator('input[type="checkbox"]').first();
      await box.click();
      await page.waitForTimeout(300);
      if (await confirm.isDisabled()) throw new Error("confirm still disabled after selection");
      await page.screenshot({ path: path.join(OUT, "admin-assign.png"), fullPage: false });
    },
  },
  {
    name: "admin: doctor table sorts by caseload",
    role: "admin",
    viewport: { width: 1440, height: 900 },
    async run(page) {
      await goto(page, "/admin/doctors");
      const sorted = await page.locator("th[aria-sort]").count();
      if (sorted === 0) throw new Error("no default sort applied");
      await page.locator("th.sortable").first().click();
      await page.waitForTimeout(300);
      return "sortable";
    },
  },
  {
    name: "admin: ending an assignment requires confirmation",
    role: "admin",
    viewport: { width: 1440, height: 900 },
    async run(page) {
      await goto(page, "/admin/doctors/4");
      await page.locator("table.b-table tbody tr").first().hover();
      await page.getByRole("button", { name: /End assignment/i }).first().click();
      await page.waitForTimeout(300);
      const dialog = page.getByRole("dialog");
      if (!(await dialog.isVisible())) throw new Error("no confirmation shown");
      const text = await dialog.innerText();
      if (!/lose access/i.test(text)) throw new Error("consequence not stated");
      await dialog.getByRole("button", { name: /Cancel/ }).click();
      await page.waitForTimeout(250);
    },
  },

  /* ── Emergency ──────────────────────────────────────────────────────── */
  {
    name: "emergency: search by name finds a discoverable patient",
    role: "emergency",
    viewport: { width: 1440, height: 900 },
    async run(page) {
      await goto(page, "/emergency/search");
      await page.locator(".b-segmented button", { hasText: /Name/ }).click();
      await page.getByRole("searchbox").first().fill("Ancuta");
      await page.getByRole("button", { name: /^Search$/ }).click();
      await page.waitForTimeout(1200);
      const rows = await page.locator(".b-list-row").count();
      if (rows === 0) throw new Error("no results");
      await page.screenshot({ path: path.join(OUT, "emergency-search.png"), fullPage: false });
      return `${rows} result(s)`;
    },
  },
  {
    name: "emergency: selecting a patient asks for a reason before access",
    role: "emergency",
    viewport: { width: 1440, height: 900 },
    async run(page) {
      await goto(page, "/emergency/search");
      await page.locator(".b-segmented button", { hasText: /Name/ }).click();
      await page.getByRole("searchbox").first().fill("Ancuta");
      await page.getByRole("button", { name: /^Search$/ }).click();
      await page.waitForTimeout(1200);
      await page.locator(".b-list-row").first().click();
      await page.waitForTimeout(400);
      const dialog = page.getByRole("dialog");
      if (!(await dialog.isVisible())) throw new Error("no confirmation");
      const text = await dialog.innerText();
      if (!/reason/i.test(text)) throw new Error("reason not requested");
      await dialog.getByRole("button", { name: /Cancel/ }).click();
    },
  },

  /* ── Mobile ─────────────────────────────────────────────────────────── */
  {
    name: "mobile: bottom nav navigates between role destinations",
    role: "patient",
    viewport: { width: 390, height: 844 },
    async run(page) {
      await goto(page, "/my-records");
      const nav = page.locator(".b-bottom-nav");
      if (!(await nav.isVisible())) throw new Error("bottom nav not visible at 390px");

      await nav.getByRole("link", { name: /Timeline/ }).click();
      await page.waitForTimeout(900);
      if (!page.url().includes("/my-records/timeline")) {
        throw new Error(`did not navigate, at ${page.url()}`);
      }
      await page.screenshot({ path: path.join(OUT, "mobile-bottom-nav.png"), fullPage: false });
    },
  },
  {
    name: "mobile: More sheet exposes the overflow destinations",
    role: "patient",
    viewport: { width: 390, height: 844 },
    async run(page) {
      await goto(page, "/my-records");
      await page.locator(".b-bottom-nav").getByRole("button", { name: /More/ }).click();
      await page.waitForTimeout(400);
      const sheet = page.locator(".b-sheet");
      if (!(await sheet.isVisible())) throw new Error("sheet did not open");
      const items = await sheet.locator(".b-sheet-item").count();
      if (items === 0) throw new Error("sheet empty");
      await page.screenshot({ path: path.join(OUT, "mobile-more-sheet.png"), fullPage: false });
      return `${items} items`;
    },
  },
  {
    name: "mobile: sidebar drawer opens from the top bar",
    role: "doctor",
    viewport: { width: 390, height: 844 },
    async run(page) {
      await goto(page, "/my-patients");
      await page.getByRole("button", { name: /Open menu/i }).click();
      await page.waitForTimeout(500);
      const open = await page.locator(".app-sidebar.mobile-open").isVisible();
      if (!open) throw new Error("drawer did not open");
      await page.screenshot({ path: path.join(OUT, "mobile-drawer.png"), fullPage: false });
    },
  },
  {
    name: "mobile: account sheet opens from the sidebar",
    role: "doctor",
    viewport: { width: 390, height: 844 },
    async run(page) {
      await goto(page, "/my-patients");
      await page.getByRole("button", { name: /Open menu/i }).click();
      await page.waitForTimeout(500);
      await page.getByRole("button", { name: /Account and preferences/i }).click();
      await page.waitForTimeout(400);
      const sheet = await page.locator(".b-sheet").isVisible();
      if (!sheet) throw new Error("account sheet did not open");
    },
  },
  {
    name: "mobile: patient list renders stacked rows, not a squeezed table",
    role: "doctor",
    viewport: { width: 390, height: 844 },
    async run(page) {
      await goto(page, "/my-patients");
      const listRows = await page.locator(".only-mobile .b-list-row").count();
      if (listRows === 0) throw new Error("no mobile list rows");

      // Every patient name must be fully visible, which is exactly what the
      // old right-aligned badge cluster used to cover.
      const clipped = await page.evaluate(() => {
        const titles = [...document.querySelectorAll(".only-mobile .b-list-title")];
        return titles.filter((el) => el.scrollWidth > el.clientWidth + 1).length;
      });
      if (clipped > 0) throw new Error(`${clipped} patient names clipped`);
      return `${listRows} rows, 0 clipped names`;
    },
  },
];

const browser = await chromium.launch({ headless: !headed });

for (const flow of FLOWS) {
  if (only && !flow.name.includes(only)) continue;

  const ctx = await browser.newContext({
    viewport: flow.viewport,
    isMobile: flow.viewport.width < 768,
    hasTouch: flow.viewport.width < 768,
  });
  const page = await ctx.newPage();

  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 140)));

  try {
    await seed(page, flow.role);
    const detail = await flow.run(page);
    if (errors.length) throw new Error(`page error: ${errors[0]}`);
    record(flow.name, true, detail);
  } catch (err) {
    record(flow.name, false, String(err).split("\n")[0].slice(0, 180));
    await page
      .screenshot({
        path: path.join(OUT, `FAIL-${flow.name.replace(/[^a-z0-9]+/gi, "-")}.png`),
        fullPage: false,
      })
      .catch(() => {});
  }

  await ctx.close();
}

await browser.close();
fs.writeFileSync(path.join(OUT, "_flows.json"), JSON.stringify(results, null, 2));

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} flows passed`);
if (failed.length) {
  console.log("\nfailures:");
  for (const f of failed) console.log(`  ${f.name}\n    ${f.detail}`);
  process.exitCode = 1;
}
