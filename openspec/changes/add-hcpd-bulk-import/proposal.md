---
id: add-hcpd-bulk-import
type: proposal
status: draft
scenario-steps: ["①provider lookup"]
created: 2026-10-02
ig: au.gov.digitalhealth.hcpd 26.0.0 (Health Connect Provider Directory)
---

# Proposal: Import Providers from the HCPD Bulk Export

## Problem

The app looks providers up in the Health Connect Provider Directory (HCPD) one search at a time.
When the PD is unreachable it falls back to hard-coded demo data in `pd_fallback.py`. Other parts
of the app need those providers to exist as resources on the referral FHIR server:

- The imaging-provider dropdown lists local Organizations.
- Task owners are Organization references.
- The booking flow's Schedules point at local HealthcareServices.

Today someone has to create those resources by hand. HCPD provides a FHIR Bulk Data `$export`
for exactly this kind of synchronisation, and its IG says the Search API must not be used for it
(results are capped at 150).

## Proposed Change

Add a **Directory Import** feature. It runs an HCPD bulk export and loads the results into the
configured referral FHIR server.

1. **Build the request.** A form builds an
   [HCPD Export Request Parameters](http://digitalhealth.gov.au/fhir/hcpd/StructureDefinition/hcpd-export-request-parameters)
   resource:
   - Choose the resource types (Organization, Location, HealthcareService, PractitionerRole,
     Practitioner, Endpoint).
   - Choose a scope preset: geographic (state, city or postcode), service type (SNOMED), or
     organisation (HPI-O or name).
   - The app generates **linked** `_typeFilter`s, one per type, using chained and `_has:`
     reverse-chained parameters so every type is constrained by the same criteria.
   - An "advanced" mode accepts raw `_typeFilter` lines.
2. **Kickoff.** `POST [HCPD]/$export` with `Prefer: respond-async`, using an OAuth
   client-credentials Bearer token.
3. **Background job.** A worker thread polls the `Content-Location` status URL, honouring
   `Retry-After` (at least 120 s, per the HCPD rate limit) and recording `X-Progress`. On
   completion it downloads each NDJSON output file and imports it. Job state is persisted under
   `instance/` so the page survives a restart; an interrupted job can be resumed.
4. **Import.** Resources are PUT to the referral server, keeping their HCPD ids so references
   between them stay intact. They are written in dependency order: Organization → Location →
   HealthcareService → Practitioner → PractitionerRole → Endpoint. Each record is tagged as
   HCPD-imported.
5. **Standard and incremental modes.**
   - **Standard** (no `_since`): an initial or wholesale load of active, non-suppressed records.
   - **Incremental**: `_since` is set to the `transactionTime` of the last *fully applied* export
     with the same scope. Records are reconciled as follows:
     - new or changed records are upserted
     - inactive records are upserted, which keeps `active` / `status` showing inactive
     - suppressed records are deleted locally (an Organization only when `includeSelf` is true)
     - identifiers on the HCPD Export Response List are resolved to local resources and deleted
6. **Progress and results.** The page lists jobs with their status, `X-Progress` and per-type
   counts (upserted, removed, failed), and has **Cancel** (`DELETE` on the status URL) and **Run
   incremental** actions.

## User-Facing Outcome

1. An admin opens **Directory Import** and picks "Service type: CT service, QLD".
2. They start a standard export and watch the status go *Submitted → Polling (found 954 of 1,000)
   → Importing → Complete: 41 Organizations, 63 Locations, 72 HealthcareServices…*.
3. The imported imaging organisations now appear in the diagnostic request provider dropdown and
   can publish booking availability.
4. A week later the admin clicks **Run incremental**. Only changes are applied, and suppressed
   records disappear.

## Non-goals

- Scheduled or cron synchronisation. Runs are started by hand (the IG notes sub-minute sync is
  impossible anyway).
- Importing `Provenance`.
- Replacing live PD search, or changing `provider_directory.py` / `pd_fallback.py`.
- Multi-worker coordination. Only one export runs at a time per app instance, which matches the
  IG's "one export at a time per dataset".
- Rewriting HCPD references or identifiers. Resources are stored as HCPD publishes them.
- An authorisation model for who may run imports (the single mock user remains).

## Impact

- **New modules:**
  - `hcpd_export.py`: pure request and reconciliation builders, an HCPD client, a job runner
    and a token cache.
  - `hcpd_routes.py`: a blueprint.
- **New templates:** a page, a job list partial and a job detail partial. Plus a sidebar link.
- **New env vars:** `HCPD_EXPORT_SERVER`, `HCPD_TOKEN_ENDPOINT`, `HCPD_CLIENT_ID`,
  `HCPD_CLIENT_SECRET`, `HCPD_SCOPE`.
- **Writes to the referral FHIR server:** a potentially large number of directory resources.
  Deletes are limited to HCPD-tagged records.
- **Branch:** stacked on `feature/appointment-booking`, because it reuses the `fhirutils` request
  helpers moved there.
