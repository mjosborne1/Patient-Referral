---
id: 02-provider-directory-search
type: proposal
status: implemented
scenario-steps: ["①provider-lookup"]
created: 2026-06-17
implemented: 2026-06-29
---

# Proposal: Provider Directory Search

## Problem

When creating an eReferral the GP needs to identify the receiving specialist or service.
Currently the app has no connection to the **Health Connect Australia (HC) Provider Directory**,
so a clinician must manually enter or paste a provider reference. This breaks the Scenario 1
workflow at step ① and makes the demo unconvincing for participants testing the HC PD Requester
role.

## Proposed Change

Introduce a new module `provider_directory.py` and a search widget embedded in the referral form
(`/patient/<id>/referral`) that:

1. Accepts search terms (name, specialty, suburb/postcode) from the user.
2. Calls the HC Provider Directory FHIR API:
   - `GET [PD]/Organization?name=...&type=...` — find organisations offering a service
   - `GET [PD]/PractitionerRole?specialty=...&location.address-city=...` — find individual
     providers by specialty and location
3. Returns a short list of matching providers (name, specialty, address, identifier) rendered
   via an HTMX partial — no full page reload.
4. Lets the user select one result; the selection populates `ServiceRequest.performer` in the
   referral bundle (proposal 01) as a `Reference` with display name and NPI/HPI-O identifier.

The provider search is surfaced as a collapsible panel inside the existing referral form, not as
a standalone page, so the workflow stays on a single screen.

## User-Facing Outcome

On the referral form the clinician types a specialty (e.g. "Cardiology") and suburb, clicks
**Search Providers**, and sees a short list of matching specialists or services returned from the
HC Provider Directory. Clicking a result pre-fills the **Referred To** field and locks it.
The GP can clear the selection and search again if needed.

## Non-goals

- Standalone provider search page (`/provider-search` is listed in config as planned but is lower
  priority than inline search on the referral form).
- Booking / slot reservation against the provider's calendar.
- Caching or local storage of provider search results between sessions.
- Writing back to the Provider Directory (Requester role only — no create/update).
- Displaying the full HC PD Organisation or PractitionerRole resource detail view.

## FHIR Operations

| Operation | Endpoint | Purpose |
|---|---|---|
| `GET Organization` | `[PD]/Organization?name=&type=` | Find organisations by name / service type |
| `GET PractitionerRole` | `[PD]/PractitionerRole?specialty=&location.address-city=` | Find practitioners by specialty + location |
| `GET Location` | `[PD]/Location?address-city=` | (optional) resolve location details |

All calls are read-only (HC PD Requester actor). Results are paged — display first page (10
results) with a **Load more** button using HTMX `hx-swap="beforeend"`.

## Impact

- **New file:** `provider_directory.py` — wraps HC PD FHIR calls, returns list of
  `{id, name, specialty, address, identifier}` dicts
- **New route:** `GET /provider-search` in `app.py` — HTMX partial returning provider rows
- **Updated template:** `templates/referral_form.html` — inline search panel + result list
- **New env var:** `PD_SERVER` — HC Provider Directory base URL (e.g.
  `https://hcpd.example.com/fhir`)
- **New env var:** `PD_USERNAME` / `PD_PASSWORD` — if HC PD requires Basic Auth (may differ from
  eRequesting server credentials)
- **No changes** to `bundler.py`, `referral_bundler.py`, or existing diagnostic request flow

## Open Questions

1. Does the HC PD sandbox used for the Sparked event require auth, and if so what scheme
   (Basic, Bearer, mutual TLS)?
2. Should the specialty search use SNOMED CT practitioner-specialty codes or the HC PD-specific
   value set? Need to confirm with HC PD IG.
3. Is `PractitionerRole` the correct resource for the `ServiceRequest.performer` reference, or
   should `performer` point to `Organization` for service-level referrals?
