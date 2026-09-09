// Bragi accessibility sweep.
//
// Runs axe-core against every meaningful route in every role, at desktop and
// phone widths, and reports serious/critical violations grouped by rule so
// systemic problems (a token's contrast, a missing label pattern) surface as
// one finding rather than hundreds.
//
//   node qa/a11y.mjs [--widths=390,1440] [--only=<substr>]

import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const axePath = require.resolve("axe-core/axe.min.js");
const axeSource = fs.readFileSync(axePath, "utf8");

const ARGS = process.argv.slice(2);
const only = (ARGS.find((a) => a.startsWith("--only=")) || "").replace("--only=", "");
const widthArg = (ARGS.find((a) => a.startsWith("--widths=")) || "").replace("--widths=", "");

const BASE = process.env.BRAGI_BASE || "http://localhost:3000";
const TOKENS = JSON.parse(fs.readFileSync(process.env.BRAGI_TOKENS, "utf8"));

const ALL_WIDTHS = [
  { w: 390, h: 844, name: "390" },
  { w: 1440, h: 900, name: "1440" },
];
const WIDTHS = widthArg
  ? ALL_WIDTHS.filter((v) => widthArg.split(",").includes(v.name))
  : ALL_WIDTHS;

const AS = {
  patient: "ancutailie@gmail.com",
  doctor: "wtf@wtf.com",
  pcp: "qa.pcp@bragiqa.com",
  admin: "andreimarin@gmail.com",
  care: "qa.carepartner@bragiqa.com",
  emergency: "qa.emergency@bragiqa.com",
};

const ROUTES = [
  { id: "public-landing", as: null, url: "/" },
  { id: "public-login", as: null, url: "/login" },
  { id: "public-login-doctor", as: null, url: "/login/doctor" },
  { id: "public-signup-patient", as: null, url: "/signup/patient" },
  { id: "patient-records", as: "patient", url: "/my-records" },
  { id: "patient-timeline", as: "patient", url: "/my-records/timeline" },
  { id: "patient-upload", as: "patient", url: "/my-records/upload" },
  { id: "patient-access", as: "patient", url: "/my-records/access" },
  { id: "patient-settings", as: "patient", url: "/my-records/settings" },
  { id: "patient-medications", as: "patient", url: "/my-records/medications" },
  { id: "doctor-my-patients", as: "doctor", url: "/my-patients" },
  { id: "doctor-search", as: "doctor", url: "/patients/search" },
  { id: "doctor-patient", as: "doctor", url: "/patients/6" },
  { id: "doctor-patient-timeline", as: "doctor", url: "/patients/6/timeline" },
  { id: "doctor-document", as: "doctor", url: "/documents/22" },
  { id: "pcp-workspace", as: "pcp", url: "/pcp/workspace" },
  { id: "admin-assignments", as: "admin", url: "/assignments" },
  { id: "admin-doctors", as: "admin", url: "/admin/doctors" },
  { id: "admin-doctor-detail", as: "admin", url: "/admin/doctors/4" },
  { id: "admin-analytes", as: "admin", url: "/admin/analytes" },
  { id: "care-home", as: "care", url: "/care-partner" },
  { id: "care-dependants", as: "care", url: "/care-partner/dependants" },
  { id: "emergency-search", as: "emergency", url: "/emergency/search" },
  { id: "emergency-workspace", as: "emergency", url: "/emergency/workspace" },
];

const filtered = only ? ROUTES.filter((r) => r.id.includes(only)) : ROUTES;

const browser = await chromium.launch();
const byRule = new Map();
const perRoute = [];

for (const vp of WIDTHS) {
  const ctx = await browser.newContext({
    viewport: { width: vp.w, height: vp.h },
    isMobile: vp.w < 768,
    hasTouch: vp.w < 768,
  });

  for (const route of filtered) {
    const page = await ctx.newPage();

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
            JSON.stringify([{ patientId: 6, patientName: "Ancuta Ilie" }])
          );
          localStorage.setItem("pcp_active_tab", "6");
        } catch {}
      },
      { entry: route.as ? TOKENS[AS[route.as]] : null }
    );

    try {
      await page.goto(BASE + route.url, { waitUntil: "domcontentloaded", timeout: 45000 });
      await page.waitForLoadState("networkidle", { timeout: 25000 }).catch(() => {});
      await page.waitForTimeout(600);

      await page.addScriptTag({ content: axeSource });
      const result = await page.evaluate(async () => {
        // @ts-ignore - axe is injected above.
        return await window.axe.run(document, {
          resultTypes: ["violations"],
          runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] },
        });
      });

      const serious = result.violations.filter(
        (v) => v.impact === "serious" || v.impact === "critical"
      );

      for (const violation of serious) {
        const entry = byRule.get(violation.id) || {
          id: violation.id,
          impact: violation.impact,
          help: violation.help,
          nodes: 0,
          routes: new Set(),
          sample: violation.nodes[0]?.html?.slice(0, 160),
        };
        entry.nodes += violation.nodes.length;
        entry.routes.add(`${route.id}@${vp.name}`);
        byRule.set(violation.id, entry);
      }

      perRoute.push({
        route: `${route.id}@${vp.name}`,
        violations: serious.map((v) => `${v.id} (${v.nodes.length})`),
      });

      process.stdout.write(
        `${serious.length ? "x" : "."} ${route.id}@${vp.name} ${serious
          .map((v) => v.id)
          .join(", ")}\n`
      );
    } catch (err) {
      process.stdout.write(`! ${route.id}@${vp.name} ${String(err).split("\n")[0]}\n`);
    }

    await page.close();
  }
  await ctx.close();
}

await browser.close();

const summary = [...byRule.values()]
  .map((e) => ({ ...e, routes: [...e.routes] }))
  .sort((a, b) => b.nodes - a.nodes);

fs.mkdirSync("qa/shots", { recursive: true });
fs.writeFileSync(
  path.join("qa/shots", "a11y.json"),
  JSON.stringify({ summary, perRoute }, null, 2)
);

console.log("\n── serious/critical violations by rule ──");
if (!summary.length) {
  console.log("none");
} else {
  for (const rule of summary) {
    console.log(
      `${rule.impact.padEnd(8)} ${rule.id.padEnd(28)} ${String(rule.nodes).padStart(4)} nodes  ${rule.routes.length} routes`
    );
    console.log(`         ${rule.help}`);
    if (rule.sample) console.log(`         e.g. ${rule.sample}`);
  }
}
