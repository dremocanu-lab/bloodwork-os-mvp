#!/usr/bin/env node
/**
 * Temporary lint-regression gate (see BRAGI_INTEROP_PLAN.md's CI section
 * and .eslint-baseline.json's own comment-equivalent below).
 *
 * ci.yml used to run `npx eslint . --max-warnings=100 || true` — the
 * `|| true` meant a real lint FAILURE never failed CI; it just printed and
 * was ignored. That masked 30 pre-existing errors across 19 files (none
 * introduced by the interoperability work — verified by grep against this
 * session's actual diff) that this script now tracks explicitly instead of
 * silently swallowing.
 *
 * This is a RATCHET, not a permanent policy: `.eslint-baseline.json` is the
 * exact, frozen error count per file as of the day this script was
 * introduced. This script fails the build if:
 *   - a file NOT in the baseline has any lint error (a new file/error), or
 *   - a file IN the baseline now has MORE errors than its baseline count
 *     (a regression on top of the known debt).
 * It does NOT fail if a baselined file's error count stays the same or
 * goes down — paying down the baseline is welcome and, over time, this
 * file should shrink to `{}` and this script's baseline check can be
 * deleted in favor of a normal `eslint .` exit-code gate.
 *
 * Warnings are informational only (unchanged from the prior
 * --max-warnings=100 behavior) — this script only ratchets ERRORS.
 */

import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const baselinePath = path.join(rootDir, ".eslint-baseline.json");
const baseline = JSON.parse(readFileSync(baselinePath, "utf-8"));

let report;
try {
  // shell:true is required for Node to locate npx.cmd on Windows
  // (execFileSync without it fails with EINVAL there). Safe here: every
  // argument is a fixed string literal below, never user/environment-
  // derived input, so there is nothing for shell interpolation to exploit.
  const raw = execFileSync("npx", ["eslint", ".", "--format", "json"], {
    cwd: rootDir,
    encoding: "utf-8",
    maxBuffer: 64 * 1024 * 1024,
    shell: true,
  });
  report = JSON.parse(raw);
} catch (err) {
  // eslint exits non-zero when it finds ANY error — that's expected and
  // the actual lint output is still on stdout, captured on the error object.
  if (err.stdout) {
    report = JSON.parse(err.stdout);
  } else {
    console.error("Failed to run eslint:", err.message);
    process.exit(1);
  }
}

let regressions = 0;
let totalErrors = 0;
for (const file of report) {
  if (file.errorCount === 0) continue;
  totalErrors += file.errorCount;
  const rel = path.relative(rootDir, file.filePath).split(path.sep).join("/");
  const allowed = baseline[rel] ?? 0;
  if (file.errorCount > allowed) {
    regressions += file.errorCount - allowed;
    console.error(`LINT REGRESSION: ${rel} has ${file.errorCount} error(s), baseline allows ${allowed}`);
    for (const msg of file.messages) {
      if (msg.severity === 2) {
        console.error(`    ${msg.line}:${msg.column}  ${msg.message}  (${msg.ruleId ?? "unknown-rule"})`);
      }
    }
  }
}

console.log(`Total lint errors: ${totalErrors} (baseline allows ${Object.values(baseline).reduce((a, b) => a + b, 0)})`);

if (regressions > 0) {
  console.error(`\n${regressions} new lint error(s) beyond the frozen baseline — failing.`);
  process.exit(1);
}

console.log("No new lint errors beyond the frozen baseline.");
