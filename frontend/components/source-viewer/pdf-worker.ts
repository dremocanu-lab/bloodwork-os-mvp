"use client";

import * as pdfjsLib from "pdfjs-dist";

let configured = false;

/** One-time PDF.js worker setup — must run before any getDocument() call.
 * Safe to call repeatedly (idempotent). */
export function ensurePdfWorkerConfigured() {
  if (configured || typeof window === "undefined") return;
  pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
    "pdfjs-dist/build/pdf.worker.min.mjs",
    import.meta.url
  ).toString();
  configured = true;
}

export { pdfjsLib };
