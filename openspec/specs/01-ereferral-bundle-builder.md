---
id: 01-ereferral-bundle-builder
type: proposal
status: draft
scenario-steps: ["②POST request"]
created: 2026-06-17
---

# Proposal: eReferral Bundle Builder

## Problem

The app can build AU eRequesting bundles for **diagnostic requests** (pathology / imaging), but
has no support for **specialist referrals**. For Scenario 1 of the Sparked Connected Testing Event,
a GP (Placer) needs to create a complete eReferral bundle — including a ServiceRequest, a tracking
Task, and a plain-text clinical context DocumentReference — and POST it to the AU eRequesting FHIR
server as a transaction bundle.

## Proposed Change

Introduce a new module `referral_bundler.py` and a corresponding Flask route
`GET /patient/<id>/referral` (form) + `POST /patient/<id>/referral` (submit) that:

1. Accepts user input: referred-to specialist/org (by reference), clinical indication, priority,
   and a free-text clinical narrative.
2. Builds a FHIR transaction bundle containing:
   - `ServiceRequest` conforming to the AU eRequesting Diagnostic Request profile (using the
     closest current profile until an eReferral-specific profile exists), with:
     - `performer` pointing to the selected specialist/organisation
     - `reasonCode` (SNOMED CT) for the indication
     - `priority` (routine | urgent | asap | stat)
     - `supportingInfo:clinicalContext` → DocumentReference
   - `Task` (AU eRequesting Diagnostic Request Task) with initial status `requested`,
     referencing the ServiceRequest via `Task.focus`
   - `DocumentReference` (AU eRequesting Clinical Context) with:
     - `type` = LOINC `107903-7`
     - `content.attachment.contentType` = `text/plain`
     - `content.attachment.data` = base64-encoded clinical narrative
3. POSTs the bundle to the configured AU eRequesting FHIR server.
4. Displays the resulting bundle JSON in the existing text area (reusing the Mermaid visualiser).

## User-Facing Outcome

A clinician opens a patient record, clicks **"New Referral"**, fills in the specialist, clinical
indication, priority, and a brief narrative, then clicks **"Submit Referral"**. The app posts the
bundle and shows the resulting JSON (and optionally the Mermaid diagram) confirming the resources
were created. The referral then appears in the patient's referral list with status `requested`.

## Non-goals

- Provider Directory lookup (covered by proposal 02 — the specialist reference is entered manually
  or pasted in for now).
- AU Patient Summary attachment (covered by proposal 03).
- Filler / specialist view (covered by proposal 04).
- eReferral-specific ServiceRequest profile — the existing DiagnosticRequest profile is used as
  a proxy until AU eRequesting defines a referral profile.
- Appointment booking or slot reservation.
- PDF or formatted referral letter — clinical context is plain text only (`text/plain`) as per the
  current AU eRequesting Clinical Context DocumentReference profile.

## FHIR Resources & Profiles

| Resource | Profile | Notes |
|---|---|---|
| `ServiceRequest` | AU eRequesting Diagnostic Request | `category`, `code`, `performer`, `reasonCode`, `priority`, `encounter`, `requisition` |
| `Task` | AU eRequesting Diagnostic Request Task | `status` = `requested`; `focus` → ServiceRequest |
| `DocumentReference` | AU eRequesting Clinical Context | LOINC 107903-7; `text/plain`; base64 inline |
| `Patient` | AU eRequesting Patient | Pulled from existing patient context |
| `Practitioner` | AU Core Practitioner | Requesting GP — from session/config |
| `Organization` | AU Core Organization | Requesting org — from session/config |

## Impact

- **New file:** `referral_bundler.py`
- **New route:** `GET|POST /patient/<id>/referral` in `app.py`
- **New template:** `templates/referral_form.html`
- **New template:** `templates/referral_result.html` (or reuse `patient_details.html` text area)
- **No changes** to existing `bundler.py`, order sets, or diagnostic request flow
- **No new env vars** for this proposal (FHIR server already configured)

## Open Questions

1. Should the referring GP / organisation be pulled from a config file or entered per-referral?
2. Is a `requisition` (AULocalOrderIdentifier) required on the ServiceRequest even for referrals
   (it is Must Support on DiagnosticRequest)? We will generate a UUID-based local identifier.
3. Is `encounter` required on the ServiceRequest for the demo? We will create a minimal inline
   Encounter resource to satisfy the Must Support constraint.
