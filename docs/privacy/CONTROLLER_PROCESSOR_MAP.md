# Controller / Processor Map

`[LEGAL REVIEW]` — this document records what engineering can observe
about data flows; it does NOT establish legal controller/processor
status. That determination depends on contracts (terms of service,
DPAs, clinic/hospital agreements) this codebase cannot see.

## What engineering can observe

- Bragi (the platform operator) determines the technical means and, to
  a significant degree, the purposes of processing (what fields are
  extracted, how long data is kept, who can access it via role grants).
  This is characteristic of a **controller** role, but is not a legal
  conclusion.
- Patients self-register and self-upload their own documents — there
  is no evidence in the codebase of a hospital/clinic system pushing
  data into Bragi on a patient's behalf under its own controller
  authority. If such an integration is ever built, the controller/
  processor analysis would need to be redone for that flow specifically.
- Doctors, PCPs, and care partners access data through role-based
  grants that patients or admins configure — the platform does not
  appear to act as a mere processor for these clinicians' own separate
  systems; there is no evidence of a data-processing agreement flow
  between Bragi and individual clinicians in this codebase.

## Sub-processors (technical fact, not a legal register)

Reducto, OpenAI, and Google (Document AI) receive document content as
part of the platform's own processing — see `docs/privacy/VENDOR_REGISTER.md`
for the full list and `docs/vendors/` for per-vendor detail. Whether
each is a GDPR Art.28 processor of Bragi, a sub-processor, or something
else again depends on the actual contract/DPA terms each vendor
offers — `[EXTERNAL ACTION]`/`[LEGAL REVIEW]` to confirm.

## Open questions requiring legal input

1. Is Bragi the sole controller, or a joint controller with the
   clinics/hospitals whose doctors use the platform?
2. What is Bragi's actual contractual relationship with Reducto,
   OpenAI, and Google for this specific use case (health data, not
   general-purpose API usage)? Do their standard DPAs cover Art.9
   special-category data processing?
3. Does Romanian national law (CNP is a nationally-regulated identifier
   with its own specific legal handling requirements) impose
   requirements beyond baseline GDPR that affect the controller
   determination or processing basis?

None of these can be answered from the codebase; all are flagged
`[LEGAL REVIEW]` in `BRAGI_SECURITY_GDPR_PLAN.md`.
