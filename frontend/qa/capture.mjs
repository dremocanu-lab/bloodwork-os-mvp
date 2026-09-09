// Bragi visual-QA capture harness.
// Drives the real app in Chromium across every meaningful route, every role and
// every target breakpoint, writing screenshots plus a console/network error report.
//
//   node qa/capture.mjs <label> [--only=<substr>] [--widths=390,1440]
//
// Auth is injected as localStorage (access_token + user) using dev JWTs minted
// from the local dev database, so no credentials are needed and nothing is written.

import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const LABEL = process.argv[2] || "run";
const ARGS = process.argv.slice(3);
const only = (ARGS.find((a) => a.startsWith("--only=")) || "").replace("--only=", "");
const widthArg = (ARGS.find((a) => a.startsWith("--widths=")) || "").replace("--widths=", "");

const BASE = process.env.BRAGI_BASE || "http://localhost:3000";
const TOKENS = JSON.parse(fs.readFileSync(process.env.BRAGI_TOKENS, "utf8"));

const OUT = path.resolve("qa/shots", LABEL);
fs.mkdirSync(OUT, { recursive: true });

// Target viewports from the brief: 360 / 390 / 430 / 768 / 1280 / 1440.
const ALL_WIDTHS = [
  { w: 360, h: 780, name: "360" },
  { w: 390, h: 844, name: "390" },
  { w: 430, h: 932, name: "430" },
  { w: 768, h: 1024, name: "768" },
  { w: 1280, h: 900, name: "1280" },
  { w: 1440, h: 900, name: "1440" },
];
const WIDTHS = widthArg
  ? ALL_WIDTHS.filter((v) => widthArg.split(",").includes(v.name))
  : ALL_WIDTHS;

const AS = {
  patient: "ancutailie@gmail.com",
  patient2: "radumocanu@gmail.com",
  doctor: "wtf@wtf.com",
  pcp: "qa.pcp@bragiqa.com",
  admin: "andreimarin@gmail.com",
  care: "qa.carepartner@bragiqa.com",
  emergency: "qa.emergency@bragiqa.com",
};

// The full route inventory. `as: null` means unauthenticated.
const ROUTES = [
  // --- public / auth ---
  { id: "public-landing", as: null, url: "/" },
  { id: "public-login", as: null, url: "/login" },
  { id: "public-login-patient", as: null, url: "/login/patient" },
  { id: "public-login-doctor", as: null, url: "/login/doctor" },
  { id: "public-login-admin", as: null, url: "/login/admin" },
  { id: "public-signup", as: null, url: "/signup" },
  { id: "public-signup-patient", as: null, url: "/signup/patient" },
  { id: "public-signup-doctor", as: null, url: "/signup/doctor" },
  { id: "public-about", as: null, url: "/about" },
  { id: "public-unverified", as: null, url: "/unverified" },

  // --- patient ---
  { id: "patient-records", as: "patient", url: "/my-records" },
  { id: "patient-timeline", as: "patient", url: "/my-records/timeline" },
  { id: "patient-upload", as: "patient", url: "/my-records/upload" },
  { id: "patient-access", as: "patient", url: "/my-records/access" },
  { id: "patient-settings", as: "patient", url: "/my-records/settings" },
  { id: "patient-medications", as: "patient", url: "/my-records/medications" },
  { id: "patient-medications-new", as: "patient", url: "/my-records/medications/new" },
  { id: "patient-document", as: "patient", url: "/documents/22" },

  // --- doctor ---
  { id: "doctor-my-patients", as: "doctor", url: "/my-patients" },
  { id: "doctor-search", as: "doctor", url: "/patients/search" },
  { id: "doctor-patient", as: "doctor", url: "/patients/6" },
  { id: "doctor-patient-timeline", as: "doctor", url: "/patients/6/timeline" },
  { id: "doctor-patient-analytics", as: "doctor", url: "/patients/6/analytics" },
  { id: "doctor-patient-meds", as: "doctor", url: "/patients/6/medications/list" },
  { id: "doctor-patient-hosp", as: "doctor", url: "/patients/6/hospitalizations" },
  { id: "doctor-patient-upload", as: "doctor", url: "/patients/6/upload" },
  { id: "doctor-patient-note", as: "doctor", url: "/patients/6/notes/new" },
  { id: "doctor-patient-assign", as: "doctor", url: "/patients/6/assign" },
  { id: "doctor-document", as: "doctor", url: "/documents/22" },

  // --- pcp ---
  { id: "pcp-home", as: "pcp", url: "/pcp" },
  { id: "pcp-workspace", as: "pcp", url: "/pcp/workspace" },
  { id: "pcp-my-patients", as: "pcp", url: "/my-patients" },

  // --- admin ---
  { id: "admin-assignments", as: "admin", url: "/assignments" },
  { id: "admin-doctors", as: "admin", url: "/admin/doctors" },
  { id: "admin-doctor-detail", as: "admin", url: "/admin/doctors/4" },
  { id: "admin-analytes", as: "admin", url: "/admin/analytes" },
  { id: "admin-logs", as: "admin", url: "/admin/logs" },

  // --- care partner ---
  { id: "care-home", as: "care", url: "/care-partner" },
  { id: "care-shared", as: "care", url: "/care-partner/shared" },
  { id: "care-dependants", as: "care", url: "/care-partner/dependants" },
  { id: "care-upload", as: "care", url: "/care-partner/upload" },

  // --- emergency ---
  { id: "emergency-landing", as: null, url: "/emergency" },
  { id: "emergency-login", as: null, url: "/emergency/login" },
  { id: "emergency-signup", as: null, url: "/emergency/signup" },
  { id: "emergency-search", as: "emergency", url: "/emergency/search" },
  { id: "emergency-workspace", as: "emergency", url: "/emergency/workspace" },
];

const filtered = only ? ROUTES.filter((r) => r.id.includes(only)) : ROUTES;
const report = [];

const browser = await chromium.launch();

for (const vp of WIDTHS) {
  const ctx = await browser.newContext({
    viewport: { width: vp.w, height: vp.h },
    deviceScaleFactor: 1,
    isMobile: vp.w < 768,
    hasTouch: vp.w < 768,
  });

  for (const route of filtered) {
    const page = await ctx.newPage();
    const problems = [];

    page.on("console", (m) => {
      if (m.type() === "error") problems.push(`console: ${m.text().slice(0, 220)}`);
    });
    page.on("pageerror", (e) => problems.push(`pageerror: ${String(e).slice(0, 220)}`));
    page.on("response", (r) => {
      if (r.status() >= 500) problems.push(`http ${r.status()}: ${r.url().slice(0, 160)}`);
    });

    try {
      // Seed auth before any app code runs.
      await page.addInitScript(
        ({ entry }) => {
          try {
            localStorage.removeItem("access_token");
            localStorage.removeItem("user");
            if (entry) {
              localStorage.setItem("access_token", entry.access_token);
              localStorage.setItem("user", JSON.stringify(entry.user));
            }
            // Deterministic screenshots: pin language + theme.
            localStorage.setItem("bloodwork_os_language", "en");
            localStorage.setItem("bloodwork-theme", "light");
            // Seed the PCP workspace with open patient tabs, otherwise every
            // PCP capture only ever shows the "add a patient" empty state.
            localStorage.setItem(
              "pcp_tab_ids",
              JSON.stringify([
                { patientId: 6, patientName: "Ancuta Ilie" },
                { patientId: 1, patientName: "Radu Mocanu" },
                { patientId: 2, patientName: "Bogdan Popescu" },
              ])
            );
            localStorage.setItem("pcp_active_tab", "6");
            // The emergency portal authenticates against its own token, so
            // seeding only access_token would bounce every emergency capture
            // back to the sign-in screen.
            if (entry && entry.user.role === "emergency_worker") {
              localStorage.setItem("emergency_access_token", entry.access_token);
              localStorage.setItem("emergency_user", JSON.stringify(entry.user));
            }
          } catch {}
        },
        { entry: route.as ? TOKENS[AS[route.as]] : null }
      );

      await page.goto(BASE + route.url, { waitUntil: "domcontentloaded", timeout: 45000 });
      await page.waitForLoadState("networkidle", { timeout: 25000 }).catch(() => {});
      await page.waitForTimeout(700);

      // Horizontal-overflow probe: the page body must never scroll sideways.
      const overflow = await page.evaluate(() => {
        const de = document.documentElement;
        const over = de.scrollWidth - de.clientWidth;
        const wide = [...document.querySelectorAll("*")]
          .filter((el) => el.getBoundingClientRect().right > de.clientWidth + 2)
          .slice(0, 4)
          .map((el) => `${el.tagName.toLowerCase()}.${(el.className || "").toString().slice(0, 40)}`);
        return { over, wide };
      });
      if (overflow.over > 2) {
        problems.push(`h-overflow ${overflow.over}px [${overflow.wide.join(" | ")}]`);
      }

      await page.screenshot({
        path: path.join(OUT, `${route.id}@${vp.name}.png`),
        fullPage: true,
      });
    } catch (err) {
      problems.push(`FAIL: ${String(err).split("\n")[0].slice(0, 220)}`);
    }

    if (problems.length) {
      report.push({ route: route.id, url: route.url, width: vp.name, problems });
      process.stdout.write(`x ${route.id}@${vp.name}  ${problems[0]}\n`);
    } else {
      process.stdout.write(`. ${route.id}@${vp.name}\n`);
    }
    await page.close();
  }
  await ctx.close();
}

await browser.close();
fs.writeFileSync(path.join(OUT, "_report.json"), JSON.stringify(report, null, 2));
console.log(`\n${LABEL}: ${filtered.length * WIDTHS.length} captures, ${report.length} with problems`);
console.log(`shots -> ${OUT}`);
