---
id: 07-requesting-practitioner-session
type: proposal
status: implemented
scenario-steps: ["②POST request"]
created: 2026-06-29
implemented: 2026-06-29
---

# Requesting Practitioner — Session-Level Selection

## Problem

Every pathology request, imaging request, and referral requires a `ServiceRequest.requester`
identifying the ordering clinician. Previously:

- The **referral form** had two free-text fields (`requester_name`, `requester_org`) that the
  user filled in on every referral — repetitive and error-prone.
- The **diagnostic request form** required the user to re-select their organisation from a
  dropdown, then their name from a second dropdown, on every order — two extra steps per request.
- Neither form kept state across requests; every modal open started blank.
- The requester was never a structured FHIR reference — only a display string in the referral
  path; the diagnostic path fetched the PractitionerRole from the server per request.

## Proposed Change

Add a **session-level ordering practitioner** that is selected once at app startup and reused
for all subsequent orders and referrals in the session.

### UX Flow

1. On first page load (no practitioner in session) the **Set Ordering Practitioner** modal opens
   automatically (600 ms delay, after Bootstrap scripts load).
2. The user selects their organisation from a dropdown loaded from `/fhir/RequesterOrganisations`
   (same data as the old diagnostic request form, filtered to exclude pathology/radiology orgs).
3. Choosing an org populates a practitioner dropdown from `/fhir/Requesters?for=sp`.
4. Clicking **Set as my practitioner** POSTs to `POST /session/requesting-practitioner` which
   stores the selection in `flask.session['requesting_practitioner']`:
   ```python
   {'id': role_id, 'name': role_name, 'org': role_org, 'ref': f'PractitionerRole/{role_id}'}
   ```
5. The modal closes. On subsequent page loads the modal does not auto-open.
6. **Settings modal** (`GET /` → gear icon) shows the current practitioner name/org and a
   **Change** button that closes Settings and re-opens the practitioner selection modal.

### Bundle injection

Both bundler routes inject the session practitioner before calling the bundler function — no
changes to `bundler.py` or `referral_bundler.py`:

```python
# create_diagnostic_request_bundle
_sp = session.get('requesting_practitioner', {})
if _sp.get('id'):
    form_data['requester'] = _sp['id']   # → bundler fetches PractitionerRole from FHIR server

# create_referral_bundle_route
_sp = session.get('requesting_practitioner', {})
form_data['requester_name'] = _sp.get('name', '')
form_data['requester_org']  = _sp.get('org',  '')
```

### Requester fields removed from modals

- **Referral form** (`referral_form.html`): "Requesting Practitioner" section (name + org text
  inputs) removed entirely.
- **Diagnostic request form** (`diag_request.html`): "Select Requesting Organisation" and
  "Select Requester" dropdowns removed entirely.

## Routes Added

| Route | Method | Purpose |
|---|---|---|
| `/session/requesting-practitioner` | POST | Save `role_id`, `role_name`, `role_org` to session; returns 204 |
| `/session/requesting-practitioner-widget` | GET | Returns `rp_widget.html` partial (sidebar widget, retained for programmatic refresh) |
| `/fhir/RequesterOrganisations?for=sp` | GET | Returns `sp_organisations.html` — same data as before, different template/IDs |
| `/fhir/Requesters?for=sp` | GET | Returns `sp_requesters.html` — same data as before, different template/IDs |

## Templates Added / Changed

| File | Change |
|---|---|
| `templates/set_practitioner_modal.html` | New — Bootstrap modal with org → practitioner selection; `spConfirm()` POSTs and updates settings display |
| `templates/partials/sp_organisations.html` | New — org `<select id="spOrgList">` for the set-practitioner modal |
| `templates/partials/sp_requesters.html` | New — practitioner `<select id="spRequesterList">` with `data-name` attribute for JS name extraction |
| `templates/partials/rp_widget.html` | New — small practitioner display partial (used for programmatic refresh after selection) |
| `templates/index.html` | Include `set_practitioner_modal.html`; auto-open script when `session.requesting_practitioner` is falsy |
| `templates/settings.html` | Added "Ordering Practitioner" row before modal footer: current name/org + Change button calling `openChangePractitioner()` |
| `templates/referral_form.html` | Removed "Requesting Practitioner" section |
| `templates/diag_request.html` | Removed requester org and requester dropdown sections |
| `templates/partials/sidebar.html` | Removed the inline practitioner widget (moved to modal flow) |

## Non-goals

- Persisting the practitioner across browser sessions (Flask session is cookie-based, cleared
  on browser close by default).
- Role-based access control — the demo uses a single mock user; anyone can set any practitioner.
- Supporting multiple concurrent practitioners in the same session.
- Displaying the PractitionerRole resource detail beyond name and organisation.
