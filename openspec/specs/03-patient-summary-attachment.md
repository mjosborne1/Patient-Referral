---
id: 03-patient-summary-attachment
type: proposal
status: draft
scenario-steps: ["②POST request"]
created: 2026-06-17
---

# Proposal: AU Patient Summary Attachment

## Problem

An eReferral is significantly more useful when accompanied by an **AU Patient Summary (AU PS)**,
giving the receiving specialist a structured clinical picture of the patient without requiring a
separate query. The current app can retrieve a `$summary` bundle from the FHIR server but has no
way to attach it to a referral as supporting information. Scenario 1 explicitly tests whether
systems can exchange an AU Patient Summary alongside a request (key question 3 at the event).

The AU eRequesting v1.0 profile does not define a `supportingInfo:patientSummary` slice, so
attachment requires a pragmatic approach that is interoperable and clearly documented as a
demo/pre-standard pattern.

## Proposed Change

Extend the referral form and `referral_bundler.py` (proposal 01) to support two attachment modes,
selectable by the user:

### Option A — Inline (Bundle-in-transaction)

The AU PS `$summary` Bundle is fetched from the FHIR server and embedded in the referral
transaction bundle as an additional entry. A `DocumentReference` resource is added to wrap it:

```
DocumentReference
  type     = LOINC 60591-5 (Patient summary Document)
  content.attachment.contentType = application/fhir+json
  content.attachment.data        = base64(JSON.stringify(summaryBundle))
  subject  = Patient reference
```

The `ServiceRequest.supportingInfo` array gains an additional entry referencing this
`DocumentReference`. This keeps the entire referral self-contained in one POST.

### Option B — Endpoint hint (separate fetch, preferred per scenario overview)

A `DocumentReference` is added to the transaction bundle with:

```
DocumentReference
  type     = LOINC 60591-5
  content.attachment.url = "[PS_PRODUCER]/Patient/<id>/$summary"
  content.attachment.contentType = application/fhir+json
```

`ServiceRequest.supportingInfo` references this `DocumentReference`. The specialist system
(Filler) resolves the URL independently to fetch the full AU PS. This approach is lower payload
and aligns with the scenario overview recommendation.

The referral form will offer both modes via a radio button, defaulting to **Option B**. The
`PS_PRODUCER` base URL is configurable via a new env var.

## User-Facing Outcome

On the referral form, the clinician sees an **"Attach Patient Summary"** toggle. When enabled, a
radio button lets them choose:
- **Inline** — fetch and embed the full summary now (larger payload, self-contained)
- **Endpoint hint** — include a link for the specialist to fetch it directly (recommended)

On submit, the resulting bundle JSON reflects the chosen mode. The Mermaid diagram will show the
`DocumentReference` linked from `ServiceRequest.supportingInfo`.

## Non-goals

- Producing a conformant AU PS document — the app uses whatever `$summary` the FHIR server
  returns.
- Defining a new `supportingInfo:patientSummary` slice in the IG — that is out of scope for a
  demo app.
- Transforming or validating the AU PS content.
- SMART on FHIR launch or OAuth for the PS Producer endpoint.
- CDA / PDF patient summary formats — FHIR JSON only.

## FHIR Resources & Profiles

| Resource | Notes |
|---|---|
| `DocumentReference` (AU PS wrapper) | `type` = LOINC 60591-5; `subject` = Patient |
| `ServiceRequest.supportingInfo` | Additional entry referencing the PS DocumentReference |
| `Bundle ($summary)` | Fetched from `GET [FHIR_SERVER]/Patient/<id>/$summary` (Option A) |

## Impact

- **Updated file:** `referral_bundler.py` — new `attach_patient_summary(mode, patient_id)`
  function; adds DocumentReference + supportingInfo entry to bundle
- **Updated template:** `templates/referral_form.html` — "Attach Patient Summary" toggle +
  inline/endpoint-hint radio
- **New env var:** `PS_PRODUCER` — base URL of the AU PS Producer endpoint (defaults to
  `FHIR_SERVER` if the same server exposes `$summary`)
- **No changes** to existing `bundler.py` or diagnostic request flow

## Open Questions

1. Does the Sparked event FHIR server support `$summary`? If not, Option A will need a fallback
   (e.g. construct a minimal summary from available resources).
2. For Option B, should the `DocumentReference.content.attachment.url` be an absolute URL or a
   relative reference? Absolute is safer for cross-system access.
3. Should the toggle default to **off** (no summary) so the demo can show both with- and
   without-summary cases side by side?
