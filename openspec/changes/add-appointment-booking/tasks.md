# Tasks: Imaging Appointment Booking

Tags: ③ GET filler · ④ PUT Task status · ⑤ GET placer monitor · Ⓑ booking (new step)

Each slice is built test-first: red, then green, then refactor.

## 0. Prerequisites

- [ ] 0.1 Rebuild the Radiology Referral IG package (`sushi` + IG Publisher) with the current canonical; note its package path for validation
- [x] 0.2 Move `get_fhir_server_url`, `get_fhir_auth_credentials` and `get_fhir_bearer_token` from `app.py` to `fhirutils.py`; re-export them from `app.py`
- [x] 0.3 Add a pytest scaffold for booking (`tests/booking/conftest.py`: Flask test client, `requests-mock` fixture, FHIR fixtures adapted from the IG examples)
- [x] 0.4 Create the `booking.py` skeleton and the `booking_routes.py` blueprint; register it in `app.py`

## 1. Publish availability — Ⓑ③

Backend
- [x] 1.1 `generate_slot_times()`: range, weekdays, hours, slot length, timezone (unit tests incl. weekend skip and day boundary)
- [x] 1.2 `build_healthcare_service()`, `build_schedule()`, `build_slot()` with optional `meta.profile`
- [x] 1.3 `build_publish_transaction()`: idempotent (skip Slots whose start already exists)
- [x] 1.4 Client: find-or-create HealthcareService by `organization` + `service-type`; find-or-create Schedule
- [x] 1.5 Route `POST /filler/imaging/availability` (route test with mocked FHIR)
- [x] 1.6 `scripts/seed_slots.py` CLI over 1.3 and 1.4

Frontend
- [x] 1.7 `templates/filler_imaging.html` with an org selector (reuse `/api/organisations/with-tasks`) and an availability form
- [x] 1.8 Smoke test: `GET /filler/imaging` renders and the availability form posts

## 2. Placer panel, Slot search and propose — Ⓑ⑤

Backend
- [x] 2.1 `SERVICE_TYPE_MAP` plus `service_type_for(sr)` with a no-filter fallback
- [x] 2.2 `is_bookable(task, appointments)` gating
- [x] 2.3 Client: patient imaging SRs with `_revinclude=Task:focus` and `_revinclude=Appointment:based-on`
- [x] 2.4 Client: SR → HealthcareService → Slot search (window defaults to `occurrencePeriod` or today+14d)
- [x] 2.5 `build_appointment()` (participants per design) and `build_propose_transaction()` with Slot `ifMatch`
- [x] 2.6 Routes: `GET /booking/patient/<pid>/panel`, `GET /booking/sr/<id>/slots`, `POST /booking/sr/<id>/propose`
- [x] 2.7 Route test: 412 from the server produces the "slot just taken" message plus a re-search

Frontend
- [x] 2.8 `partials/booking_panel.html` on `patient_details.html` (hx-get on load, refresh button)
- [x] 2.9 `partials/booking_slot_picker.html` modal (Slots grouped by day)
- [x] 2.10 `partials/operation_outcome.html`
- [x] 2.11 Smoke test: panel renders for a patient with an accepted imaging Task

## 3. Confirm and decline — Ⓑ③④

Backend
- [x] 3.1 `build_confirm_transaction()`: Appointment `booked`, Slot `busy`, Task and Group Task `service-booked`, all `ifMatch`; Task status unchanged
- [x] 3.2 `build_decline_transaction()`: Appointment `cancelled` with HealthcareService participant `declined` and `cancelationReason`; Slot `free`
- [x] 3.3 Client: pending Appointments for HealthcareService(s) with `_include` patient and based-on; resolve Task and Group Task from the SR
- [x] 3.4 Routes `POST /filler/imaging/appointment/<id>/confirm` and `/decline`

Frontend
- [x] 3.5 "Pending bookings" list with a confirm form (patient instructions) and a decline form (reason)
- [x] 3.6 Smoke test: confirm, then the placer panel shows *Booked*

## 4. Filler direct-book — Ⓑ③④

- [x] 4.1 `build_direct_book_transaction()` (POST Appointment `booked` + Slot `busy` + Tasks)
- [x] 4.2 "Accepted, unbooked" list plus **Book directly** using the shared slot picker partial
- [x] 4.3 Route `POST /filler/imaging/sr/<id>/book` (route test)

## 5. Cancel and atomic reschedule — Ⓑ⑤④

- [ ] 5.1 `build_cancel_transaction()` (Appointment `cancelled`, Slot `free`, Task businessStatus removed)
- [ ] 5.2 `build_reschedule_transaction()` = cancel entries + propose entries in one transaction
- [ ] 5.3 Routes `POST /booking/appointment/<id>/cancel` and `/reschedule` (route tests incl. 412 on the new Slot)
- [ ] 5.4 Panel actions: Cancel (reason) and Reschedule (opens the slot picker)

## 6. Business-status fix and IG feedback — ④

- [ ] 6.1 `app.py` `BUSINESS_STATUS_BY_TASK_STATUS['accepted']`: `booked` → `service-booked` ("Service booked"); test in `tests/booking/`
- [ ] 6.2 Add an open issue to `radiology-referral/input/pagecontent/open-issues.md`: Task stays `accepted` on booking (no path from `in-progress` back to `accepted` on cancel)

## 7. Validation and e2e

- [ ] 7.1 `tests/booking/validate_booking.py`: run generated Schedule, Slot and Appointment through the HL7 validator jar with `-ig <rebuilt package>`; skipped if the jar or package is missing
- [ ] 7.2 `tests/e2e_booking.py` (skipped unless `FHIR_E2E_URL`): publish → search → propose → second propose expects 412 → confirm → cancel → reschedule
- [ ] 7.3 Run the e2e against the default Aidbox; record any `ifMatch` or search-parameter gaps in the design's "Server assumptions"
- [ ] 7.4 Update `.env.example` with `CLAIM_BOOKING_PROFILES`, `BOOKING_TIMEZONE` and `FHIR_E2E_URL`
