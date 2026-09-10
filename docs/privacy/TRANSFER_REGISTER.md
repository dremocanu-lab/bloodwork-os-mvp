# International Transfer Register

`[UNKNOWN]`/`[LEGAL REVIEW]` throughout — the actual data-center
region(s) used by each vendor for this specific account/project is an
account-configuration fact this codebase cannot verify, and the
applicable transfer safeguard (adequacy decision, SCCs, etc.) is a
legal determination.

## What would need to be confirmed, per vendor

| Vendor | Question | Status |
|---|---|---|
| Neon | Which region is the actual project's database hosted in? | `[UNKNOWN]` |
| Render | Which region is the backend service deployed in? | `[UNKNOWN]` |
| Vercel | Which region(s) serve the frontend (Vercel's edge network may serve from multiple regions globally by default)? | `[UNKNOWN]` |
| Reducto | Where does Reducto process/store submitted documents geographically? | `[UNKNOWN]` |
| OpenAI | Where does the OpenAI API process requests for this account/region? | `[UNKNOWN]` |
| Google Cloud (Document AI) | Which region is the Document AI processor configured for? | `[UNKNOWN]` |

## Why this matters here specifically

The patient population implied by CNP usage (Romania's national ID
system) suggests EU/EEA data subjects are a core, not incidental, part
of this system's user base. If any vendor above processes data outside
the EU/EEA without an adequacy decision, GDPR Chapter V requires a
valid transfer mechanism (Standard Contractual Clauses being the most
common) — but this is a legal determination that also depends on facts
(actual processing region, actual contract terms) not established in
this codebase.

## Status

Every row is `[UNKNOWN]` pending account-configuration confirmation,
and the overall transfer-adequacy conclusion is `[LEGAL REVIEW]`.
Nothing in this document should be read as asserting transfers are
either compliant or non-compliant — only that the question has not yet
been answered.
