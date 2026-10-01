---
id: add-appointment-booking
type: proposal
status: draft
scenario-steps: ["③GET filler", "④PUT Task status", "⑤GET placer monitor"]
created: 2026-10-01
ig: http://aehrc.csiro.au/fhir/radiology-referral (v0.1.0, draft)
---

# Proposal: Imaging Appointment Booking (Slot → Appointment → Confirm)

## Problem

The app can submit an AU eRequesting imaging request and lets a filler triage the Task. That is
where it stops. The Radiology Referral IG (QH 2026 Connectathon, "FHIR For Services") adds a
booking step after triage:

1. The filler publishes availability (a Schedule plus free Slots).
2. The referrer searches for free Slots and POSTs a `proposed` Appointment.
3. The filler confirms it: Appointment `booked`, Slot `busy`, Task businessStatus `service-booked`.

None of this is in the app, so we can't demonstrate the booking half of the IG.

## Proposed Change

Booking attaches to the **diagnostic imaging request** flow (`bundler.py`). That flow already
conforms to AU eRequesting and carries a filler Organization and a Group Task. The specialist
referral flow is out of scope. Both booking variants in IG open issue #4 are supported:

- **Referrer-books (main flow).** Once the imaging Task is `accepted`, the placer searches Slots
  and proposes an Appointment. The filler confirms or declines it.
- **Filler-books (variant).** The filler picks a Slot for an accepted Task and books it directly.

### Placer: "Requests & Appointments" panel on the patient details page

- Lists the patient's imaging ServiceRequests with Task status, businessStatus and any
  Appointment.
- A **Book slot** action is shown when the Task is `accepted` and there is no active Appointment.
  It opens an htmx modal with a date range (default: today → +14 days, or the SR
  `occurrencePeriod`) and a Location filter. Free Slots are shown grouped by day; picking one
  proposes the Appointment.
- Row states: *Proposed – awaiting confirmation*, *Booked <date time>*, *Declined: <reason>*,
  *Cancelled*. A refresh button re-polls (no Subscriptions).
- **Cancel** and **Reschedule** actions. A reschedule is one atomic transaction that cancels the
  old Appointment, frees the old Slot and proposes against the new Slot.

### Filler: new `/filler/imaging` page

- **Publish availability.** Pick the filler Organization, modality (HealthcareService type),
  Location, date range, working hours and slot length. The app finds or creates the
  HealthcareService and Schedule, then creates `free` Slots in one transaction. A seed CLI wraps
  the same generator.
- **Pending bookings.** Lists proposed Appointments for the filler's HealthcareService(s) with
  **Confirm** (with optional patient instructions) and **Decline** (with a reason).
- **Accepted, unbooked requests.** A **Book directly** action uses the same Slot picker and
  creates a `booked` Appointment in one step.

### Business-status fix (airport board)

The airport board offers Task businessStatus `booked`. That code does not resolve in
`http://terminology.hl7.org.au/CodeSystem/task-business-status`. Replace it with
`service-booked` ("Service booked"), which is the code the IG uses.

## User-Facing Outcome

1. A filler user publishes CT availability for Northside Imaging.
2. A GP submits a CT request and the filler accepts it.
3. The GP opens the patient, clicks **Book slot**, picks Tue 09:30 and sees *Proposed*.
4. The filler confirms with "Fast for 4 hours".
5. The GP refreshes and sees *Booked Tue 6 Oct 09:30* with the instructions shown.

If two GPs try to take the same Slot, the second sees "This slot was just taken — please choose
another" and gets a fresh search.

## Non-goals

- Attendance tracking (`arrived`, `fulfilled`, `noshow`) and moving the Task to `completed`.
- Subscriptions or push notifications. The placer polls.
- A patient app or patient self-booking. The Patient participant is `accepted` at propose time.
- A cross-patient placer dashboard.
- Booking for the specialist referral flow, or upgrading `referral_bundler.py` to the IG's
  `ReferralServiceRequest`.
- Slot capacity or overbooking, and `$find` / `$book` / `$hold` operations.
- In-place edits of an Appointment's time or Slot. A reschedule is always cancel plus propose.
- Real role separation between placer and filler (the single mock user remains).

## IG Divergence (to raise in IG open-issues.md)

The IG moves the Task to `in-progress` on booking. Its Task state machine has no transition from
`in-progress` back to `accepted`, so a cancelled booking would leave the Task stuck. This change
keeps the Task **`accepted`** and sets `businessStatus = service-booked`, removing the
businessStatus again on cancel or decline. `in-progress` is kept for imaging work actually having
started (`acquired`, `preliminary`).

## Impact

- **FHIR:** new writes of HealthcareService, Schedule, Slot and Appointment, plus Task
  businessStatus updates. All multi-resource writes are transactions with `request.ifMatch`.
- **Profiles:** claims `booking-schedule`, `booking-slot` and `referral-appointment` from the IG
  (toggle with `CLAIM_BOOKING_PROFILES`).
- **Bundle pipeline:** no change to `bundler.py` or `referral_bundler.py`.
- **Code:** new `booking.py` (pure builders plus a thin client), new `booking_routes.py` Flask
  blueprint (the app's first), new templates and partials, and a one-line fix in `app.py`
  business statuses.
- **IGs in scope:** adds Radiology Referral IG v0.1.0 alongside AU eRequesting 1.0.1.
