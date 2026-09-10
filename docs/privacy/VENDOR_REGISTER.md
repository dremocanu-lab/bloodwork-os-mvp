# Vendor / Sub-processor Register

Vendors confirmed by code/config review to receive or host personal
data for this application. This is a technical register (what
engineering can observe); it is not a legal sub-processor list until
each row's DPA status is confirmed — see the `[LEGAL REVIEW]` column.

| Vendor | Role | Data received | DPA/contract confirmed? |
|---|---|---|---|
| **Neon** | Database hosting (Postgres) | All application data — the full database | `[UNKNOWN]` |
| **Render** | Backend application hosting (FastAPI), local file storage for uploads | All data passing through the API; raw uploaded files on local disk | `[UNKNOWN]` |
| **Vercel** | Frontend hosting (Next.js) | No direct PHI storage (frontend is stateless — data flows through, not stored), but serves the browser-rendered UI that displays PHI | `[UNKNOWN]` |
| **Reducto** | Document classification/split/parse/extract | Full uploaded file content, for most documents | `[UNKNOWN]` — see `docs/vendors/REDUCTO_PRODUCTION_REQUIREMENTS.md` |
| **OpenAI** | Fallback page extraction, discharge-summary extraction | Full-page rendered images, up to 12,000 chars of OCR text, identity fields | `[UNKNOWN]` — see `docs/vendors/OPENAI_PRODUCTION_REQUIREMENTS.md` |
| **Google Cloud (Document AI)** | OCR, discharge-summary support (`app/services/document_ai_layout.py`, `app/services/google_document_ai_service.py` — confirmed live imports in `main.py`, not dead code) | Document content for OCR processing | `[UNKNOWN]` — no dedicated requirements doc exists yet for this vendor; flagged as a gap in this register itself (this round produced OpenAI/Reducto docs per the original task's explicit list, which named only those two — Google Document AI's equivalent doc should be added as a near-term follow-up) |
| **GitHub** | Source code hosting, (future) CI | Source code only — confirmed no PHI/secrets in the repository (`detect-secrets`, working tree, this round) | N/A (code hosting, not a data processor for patient data) |

## Gaps in this register

1. Google Document AI has no dedicated production-requirements
   document yet, unlike Reducto and OpenAI — the original task
   specification named only those two explicitly; this is flagged
   rather than silently omitted.
2. No row above has a confirmed DPA — every vendor relationship needs
   legal review before any compliance claim can be made about this
   register being complete or adequate.
3. This register does not yet include any email-delivery vendor
   (password reset, notifications) because no such feature was found
   to exist in the codebase — `[NOT APPLICABLE]` unless/until one is
   added.
