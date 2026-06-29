---
id: 06-referral-form-enhancements
type: proposal
status: implemented
scenario-steps: ["①provider-lookup", "②POST request"]
created: 2026-06-29
implemented: 2026-06-29
---

# Referral Form Enhancements

## Problem

After the initial Provider Directory search implementation (proposal 02) several UX issues
remained in the referral form:

1. **Three separate search fields** (org name, specialist type, location) created a confusing,
   form-heavy experience. Users had to know which field to use and in what order.
2. **HC Provider Directory search returned no results in the browser** even though the backend
   endpoint worked correctly. The HTMX `hx-include` + `hx-params="none"` combination inside a
   parent `<form hx-post="...">` silently sent an empty `pdUnifiedQuery` parameter.
3. **"Unknown" displayed in bold** for all Practitioner name search results because
   `_parse_practitioner_role_bundle()` did not collect `Practitioner` resources from the bundle,
   so names could not be resolved.
4. **Duplicate PractitionerRole rows** appeared when the same practitioner held multiple roles
   at the same service (e.g., two "Radiation Oncologist" entries for Dr Alex Smith — weekday and
   weekend roles in the HC PD test dataset).
5. **No coded Clinical Indication** — the "Clinical Indication / Reason" field was a plain text
   input with no connection to a clinical terminology.

## Changes Implemented

### 1. Unified single-box provider search

Replaced the three-field panel with a single Google-style search box:

```
[ Name, suburb, postcode or service type — e.g. Balmain, 2041, Dr Smith, Cardiology ]  [Search]
```

`search_unified(query)` in `provider_directory.py` routes the query to the correct FHIR strategy:

| Query pattern | Strategy | FHIR calls |
|---|---|---|
| 4-digit postcode | Geographic | `Location?near=lat\|lon\|20\|km` → `HealthcareService` via `_revinclude` |
| Geocodable suburb (single word or state abbrev) | Geographic | Nominatim geocode → same as above |
| Professional prefix (`Dr`, `Prof`, etc.) | Practitioner name | `Practitioner?name=` + `_revinclude=PractitionerRole:practitioner` |
| Multi-word, no state abbreviation | Name + service | Practitioner name search AND `HealthcareService?name=` — merged |

`_looks_geographic(q)` implements the routing heuristic:
- 4-digit postcode → geographic
- Starts with `Dr`, `Prof`, `Mr`, `Ms`, `Mrs`, `A/Prof`, `Assoc` → text (prevents "Dr Smith" geocoding as "Smith Drive")
- Contains non-postcode digits → text
- Contains AU state abbreviation → geographic
- Single word → geographic (try as suburb)
- Multi-word without state → text

### 2. Fix: `htmx.ajax()` instead of HTMX attributes on search controls

Replaced `hx-get` + `hx-include` + `hx-params="none"` on both the input and button with a
plain JS function using `htmx.ajax()` — the same pattern already used by
`selectOrgAndLoadPractitioners()`:

```javascript
function runPdSearch() {
    var q = (document.getElementById('pdUnifiedSearch').value || '').trim();
    if (!q) return;
    htmx.ajax('GET', '/provider-search?pdUnifiedQuery=' + encodeURIComponent(q), {
        target: '#pdResults', swap: 'innerHTML'
    });
}
```

The input fires `runPdSearch()` on Enter key (`onkeydown`); the button fires on `onclick`.
This bypasses the `hx-params="none"` / `hx-include` interaction bug inside a parent form.

### 3. Fix: Practitioner name resolution in bundles

Added `_practitioner_display_name(prac, role)` helper and `practitioners: dict` lookup to
`_parse_practitioner_role_bundle()`. The Practitioner name search query
(`Practitioner?name=&_revinclude=PractitionerRole:practitioner`) returns Practitioner resources
in the bundle; the function now collects them and resolves names against PractitionerRole entries.

Added `_include:iterate` for `PractitionerRole:service`, `PractitionerRole:organization`, and
`PractitionerRole:location` to the Practitioner name query so HealthcareService data populates
the `services` dict and enables service-level deduplication.

Display logic:
- **Has HealthcareService** → service name is primary (bold); practitioner name + specialty shown
  as subtitle (`Dr Alex Smith · Radiation oncologist`)
- **No HealthcareService** → practitioner name is primary; specialty as subtitle

### 4. Fix: Duplicate role deduplication

Added `seen_prac_roles: set` keyed on `(prac_id, spec_text.lower())` to collapse duplicate
PractitionerRole entries that have the same practitioner and same specialty — a known pattern in
the HC PD test dataset (weekday/weekend split roles).

### 5. Clinical Indication SNOMED typeahead

Added a SNOMED CT typeahead to the "Clinical Indication / Reason" field backed by the
[reason-for-encounter-1](https://healthterminologies.gov.au/fhir/ValueSet/reason-for-encounter-1)
ValueSet from the National Clinical Terminology Service, expanded via CSIRO Ontoserver.

- Route: `GET /fhir/indicationvalueset/expand?indication_display=<query>`
- Partial: `templates/partials/indication_names.html`
- Free text is permitted — if the user types without selecting a concept `indication_code` stays
  empty and only `indication_display` is sent to the bundler
- Selecting a concept populates both `indication_display` (text) and `indication_code` (SNOMED CT
  concept ID), which the referral bundler uses to populate `ServiceRequest.reasonCode`

## FHIR Operations

| Operation | Purpose |
|---|---|
| `GET [PD]/Location?near=lat\|lon\|20\|km&_revinclude=HealthcareService:location&_include:iterate=HealthcareService:organization` | Geo search — services near a suburb/postcode |
| `GET [PD]/Practitioner?name=&_revinclude=PractitionerRole:practitioner&_include:iterate=PractitionerRole:service,PractitionerRole:organization,PractitionerRole:location` | Name search — find practitioners and their roles |
| `GET [PD]/HealthcareService?name=&_include=HealthcareService:organization,HealthcareService:location` | Service name search |
| `GET [ONTO]/ValueSet/$expand?url=https://healthterminologies.gov.au/fhir/ValueSet/reason-for-encounter-1&filter=<q>&count=10` | Indication typeahead expansion |

## Files Changed

| File | Change |
|---|---|
| `provider_directory.py` | `search_unified()`, `_looks_geographic()`, `_practitioner_display_name()`, updated `_parse_practitioner_role_bundle()` with name resolution + dedup |
| `app.py` | `POST /provider-search` unified route; `GET /fhir/indicationvalueset/expand` |
| `templates/referral_form.html` | Single search box; `runPdSearch()` JS function; indication typeahead wiring |
| `templates/partials/provider_results.html` | Differentiates HealthcareService (drill-down) vs PractitionerRole (select) results |
| `templates/partials/indication_names.html` | New — SNOMED indication dropdown |

## Non-goals

- Real-time debounced search on keypress (Enter key + button click is sufficient for demo)
- Caching provider search results in the browser between modal opens
- Displaying HC PD full resource detail beyond name, specialty, org, and address
- Writing back to the Provider Directory
