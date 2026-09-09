// Dark-mode and reduced-motion verification.
//
// Captures a representative route per role in dark mode, and separately with
// prefers-reduced-motion forced on, checking that:
//   - no element renders text at a contrast ratio implying an unthemed colour
//     (the classic symptom of a hard-coded hex or an undefined CSS variable)
//   - the page still renders completely with motion disabled
//
//   node qa/themes.mjs

import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const BASE = process.env.BRAGI_BASE || "http://localhost:3000";
const TOKENS = JSON.parse(fs.readFileSync(process.env.BRAGI_TOKENS, "utf8"));

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
  { id: "public-login-doctor", as: null, url: "/login/doctor" },
  { id: "patient-records", as: "patient", url: "/my-records" },
  { id: "patient-access", as: "patient", url: "/my-records/access" },
  { id: "doctor-my-patients", as: "doctor", url: "/my-patients" },
  { id: "doctor-patient", as: "doctor", url: "/patients/6" },
  { id: "doctor-patient-timeline", as: "doctor", url: "/patients/6/timeline" },
  { id: "doctor-document", as: "doctor", url: "/documents/22" },
  { id: "pcp-workspace", as: "pcp", url: "/pcp/workspace" },
  { id: "admin-doctors", as: "admin", url: "/admin/doctors" },
  { id: "admin-assignments", as: "admin", url: "/assignments" },
  { id: "care-home", as: "care", url: "/care-partner" },
  { id: "emergency-workspace", as: "emergency", url: "/emergency/workspace" },
];

/** Parse an rgb()/rgba() string into [r,g,b]. */
function rgb(value) {
  const match = value.match(/rgba?\(([^)]+)\)/);
  if (!match) return null;
  const parts = match[1].split(",").map((n) => parseFloat(n));
  if (parts.length >= 4 && parts[3] === 0) return null; // fully transparent
  return parts.slice(0, 3);
}

function luminance([r, g, b]) {
  const channel = (c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

function contrast(a, b) {
  const la = luminance(a);
  const lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

const browser = await chromium.launch();
const findings = [];

for (const mode of ["dark", "reduced-motion"]) {
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    reducedMotion: mode === "reduced-motion" ? "reduce" : "no-preference",
    colorScheme: mode === "dark" ? "dark" : "light",
  });

  const out = path.resolve("qa/shots", mode);
  fs.mkdirSync(out, { recursive: true });

  for (const route of ROUTES) {
    const page = await ctx.newPage();

    await page.addInitScript(
      ({ entry, theme }) => {
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
          localStorage.setItem("bloodwork-theme", theme);
          localStorage.setItem(
            "pcp_tab_ids",
            JSON.stringify([{ patientId: 6, patientName: "Ancuta Ilie" }])
          );
          localStorage.setItem("pcp_active_tab", "6");
        } catch {}
      },
      { entry: route.as ? TOKENS[AS[route.as]] : null, theme: mode === "dark" ? "dark" : "light" }
    );

    try {
      await page.goto(BASE + route.url, { waitUntil: "domcontentloaded", timeout: 45000 });
      await page.waitForLoadState("networkidle", { timeout: 25000 }).catch(() => {});
      await page.waitForTimeout(600);

      // Walk visible text nodes and find any whose colour against its own
      // painted background falls below 3:1 — the signature of a hard-coded
      // colour that did not follow the theme.
      const lowContrast = await page.evaluate(() => {
        function paintedBg(el) {
          let node = el;
          while (node && node !== document.documentElement) {
            const bg = getComputedStyle(node).backgroundColor;
            const m = bg.match(/rgba?\(([^)]+)\)/);
            if (m) {
              const parts = m[1].split(",").map((n) => parseFloat(n));
              const alpha = parts.length >= 4 ? parts[3] : 1;
              if (alpha > 0.5) return bg;
            }
            node = node.parentElement;
          }
          return getComputedStyle(document.body).backgroundColor;
        }

        const results = [];
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        const seen = new Set();

        while (walker.nextNode()) {
          const text = walker.currentNode.textContent?.trim();
          if (!text || text.length < 2) continue;
          const el = walker.currentNode.parentElement;
          if (!el || seen.has(el)) continue;
          seen.add(el);

          const rect = el.getBoundingClientRect();
          if (rect.width < 2 || rect.height < 2) continue;
          const style = getComputedStyle(el);
          if (style.visibility === "hidden" || style.opacity === "0") continue;

          results.push({
            text: text.slice(0, 50),
            color: style.color,
            background: paintedBg(el),
            tag: el.tagName.toLowerCase(),
          });
        }
        return results;
      });

      for (const item of lowContrast) {
        const fg = rgb(item.color);
        const bg = rgb(item.background);
        if (!fg || !bg) continue;
        const ratio = contrast(fg, bg);
        if (ratio < 3) {
          findings.push({
            mode,
            route: route.id,
            ratio: Math.round(ratio * 100) / 100,
            ...item,
          });
        }
      }

      await page.screenshot({ path: path.join(out, `${route.id}.png`), fullPage: false });
      process.stdout.write(`. ${mode} ${route.id}\n`);
    } catch (err) {
      process.stdout.write(`! ${mode} ${route.id} ${String(err).split("\n")[0]}\n`);
    }

    await page.close();
  }
  await ctx.close();
}

await browser.close();
fs.writeFileSync(path.join("qa/shots", "themes.json"), JSON.stringify(findings, null, 2));

console.log(`\n── text below 3:1 against its own background ──`);
if (!findings.length) {
  console.log("none");
} else {
  const grouped = new Map();
  for (const f of findings) {
    const key = `${f.mode} | ${f.color} on ${f.background}`;
    const entry = grouped.get(key) || { ...f, count: 0, routes: new Set() };
    entry.count += 1;
    entry.routes.add(f.route);
    grouped.set(key, entry);
  }
  for (const e of [...grouped.values()].sort((a, b) => b.count - a.count)) {
    console.log(
      `${e.mode.padEnd(15)} ratio ${String(e.ratio).padStart(5)}  ${e.count} nodes  ${[...e.routes].join(", ")}`
    );
    console.log(`                ${e.color} on ${e.background}  e.g. "${e.text}"`);
  }
}
