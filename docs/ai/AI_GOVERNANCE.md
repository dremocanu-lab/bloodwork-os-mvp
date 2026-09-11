# AI Governance

Covers two distinct things: (1) the AI/OCR document-processing pipeline
that exists today (Reducto, OpenAI, Google Document AI), and (2) the
governance framework for "Ask Bragi," an AI chat feature over a
patient's own record. **Ask Bragi is now implemented, tested, and
feature-flagged** — this section originally described a forward-looking
design for a feature that didn't exist yet; it now describes what was
actually built and verified. See `BRAGI_ASK_BRAGI_PLAN.md` for full
architecture/evidence and current status (frontend flag on in
production, backend flag/key not yet set — see
`BRAGI_SECURITY_GDPR_PLAN.md` §21).

## Part 1: Existing AI processing (document extraction)

Governance of the current pipeline is covered in detail elsewhere; this
section indexes it rather than duplicating it:

- What's sent to each vendor: `docs/vendors/OPENAI_PRODUCTION_REQUIREMENTS.md`,
  `docs/vendors/REDUCTO_PRODUCTION_REQUIREMENTS.md`.
- Output-safety design already in place: extraction results are always
  presented with a source citation (`SourceEvidence`) pointing to the
  exact page/bbox/text they came from, never asserted as authoritative
  without it — this "conservative clinical reader" design predates this
  security round (established in `BRAGI_REDUCTO_PLAN.md`'s Phase 4) and
  is a real, already-implemented AI-safety control, not a gap.
- No AI output is used to make an automated clinical decision or
  silently modify a record — every AI-derived value is written as
  extracted data a human views, not an autonomous action.

## Part 2: Forward-looking — before an AI chat feature ("Ask Bragi") is built

This section is a requirement, not a description of anything that
exists. `[NOT APPLICABLE — FORWARD-LOOKING REQUIREMENT DOCUMENTED]`
for every item below.

### 2.1 Patient-context injection

Patient context (which records the AI can "see" for a given
conversation) must be injected **server-side only**, resolved from the
authenticated user's own authorization scope (reusing
`can_access_patient()` and friends — see
`docs/security/AUTHORIZATION_MATRIX.md`) — never accepted as a
client-supplied or model-controllable parameter. A chat message must
never be able to ask the model to fetch a different `patient_id`; the
scope must be fixed before the model ever sees the request.

### 2.2 Tool-call authorization

If the AI is given tools (e.g. "look up this patient's labs"), every
tool call must independently re-check authorization at execution time,
not rely on the outer conversation's authorization having been checked
once — a compromised or manipulated conversation should not be able to
pivot a tool call to a different patient's data via prompt injection.

### 2.3 Prompt-injection testing (implemented, live-verified)

A synthetic document containing text instructing the model to leak
secrets and access other patients' data was retrieved during a real
conversation and its instructions were completely ignored — live-
verified against the real OpenAI API, not just designed for (see
`BRAGI_ASK_BRAGI_PLAN.md`'s "Real OpenAI testing" section). This
mirrors the existing "conservative clinical reader" design philosophy —
the model treats document content as *data to report on*, never as
*instructions to follow*. A permanent, repeatable adversarial suite
(beyond that one live run) remains a good next step, not yet built.

### 2.4 Missing / conflicting data handling

Should be tested: what the AI does when asked about data that doesn't
exist (must not fabricate an answer — must say so) and when source
documents conflict (must surface the conflict, not silently pick one) —
consistent with the existing conservative-reader precedent already
established for the non-chat extraction pipeline.

### 2.5 Chart safety

Any AI-generated summary/chat response referencing lab trends must cite
its source the same way the existing chart/timeline features already
do (point-to-source, established in `BRAGI_REDUCTO_PLAN.md` Phase 6) —
never present a number without a traceable origin.

### 2.6 Conversation storage

If conversations are persisted, they must be treated with the same
sensitivity as any other PHI-adjacent table in
`docs/privacy/BRAGI_DATA_MAP.md` — access-controlled, included in
deletion/DSAR paths, included in the data map and ROPA, and reviewed
for whether conversation content itself should be sent to any further
third party (e.g. for abuse monitoring) before doing so.

### 2.7 Output safety generally

No AI output should be rendered as raw HTML/markdown without the same
XSS-safety review given to the rest of the frontend
(`BRAGI_SECURITY_GDPR_PLAN.md` §14) — a future markdown-rendering
surface for chat responses would need explicit sanitization, unlike the
current frontend, which has none of that surface today.

## Part 3: Permanent AI evaluation suite

A one-off live evaluation has run against the real OpenAI API across
11 of ~16 planned categories (see `BRAGI_ASK_BRAGI_PLAN.md`); imaging,
a two-source medication conflict, and reverse-language cases remain,
blocked on having a configured `OPENAI_API_KEY` available to run
against. A PERMANENT, repeatable/automated suite (rather than one-off
manual runs) is still not built. This governance document's §2.3/2.4/2.5
items should become concrete,
automated test cases (mirroring how the existing 20-test security
regression suite was built this round), run in CI (§18 of
`BRAGI_SECURITY_GDPR_PLAN.md`) rather than left as manual review.
