import type { NextConfig } from "next";

// Backend API origin the frontend talks to — must match lib/api.ts's
// default/NEXT_PUBLIC_API_URL exactly, or every fetch/XHR call breaks under
// connect-src. See docs/security/THREAT_MODEL.md for the header rationale.
const API_ORIGIN = process.env.NEXT_PUBLIC_API_URL || "https://bloodwork-os-api.onrender.com";

// Tuned for what this app actually uses (verified locally with a real
// browser before deploying — see BRAGI_SECURITY_GDPR_PLAN.md):
// - PDF.js (components/source-viewer/pdf-worker.ts) loads its worker via
//   `new URL(..., import.meta.url)`, which Next.js/Turbopack resolves to a
//   same-origin /_next/static/... file — worker-src 'self' covers it. blob:
//   is included defensively since some pdf.js builds construct the worker
//   via a Blob URL depending on bundler output.
// - No external fonts, analytics, or error-monitoring scripts exist in this
//   app (confirmed by repo search) — nothing else needs allow-listing here.
// - script-src still needs 'unsafe-inline' for Next.js's own hydration/
//   bootstrap scripts (this app has no nonce-based CSP infrastructure —
//   see the plan doc's "residual risks" for this trade-off) but NOT
//   'unsafe-eval', which was verified unnecessary against a production
//   build.
const CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  `connect-src 'self' ${API_ORIGIN}`,
  "worker-src 'self' blob:",
  "frame-src 'none'",
  "frame-ancestors 'none'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: CSP },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  {
    key: "Permissions-Policy",
    value: "geolocation=(), microphone=(), camera=(), payment=(), usb=()",
  },
  // Vercel terminates TLS in front of every deployment (preview and
  // production alike use HTTPS), so this is safe unconditionally — unlike
  // the backend's equivalent header, there's no local-HTTP dev server case
  // to guard here since these headers only apply to what `next start`
  // actually serves in a deployed environment; `next dev` does not run
  // through next.config.ts's headers() the same way in practice, but even
  // if it did, HSTS on localhost is harmless (browsers scope it to the
  // exact host:port).
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" },
];

const nextConfig: NextConfig = {
  async headers() {
    return [
      {
        source: "/:path*",
        headers: securityHeaders,
      },
    ];
  },
};

export default nextConfig;
