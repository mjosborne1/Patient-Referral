"""Behaviour of the placer's Requests & Appointments panel and booking routes."""
from tests.booking.conftest import (BASE, FHIR_HEADERS, SCHEDULE, SERVICE_REQUEST, SLOT,
                                    searchset)

TASK = {"resourceType": "Task", "id": "task-1", "status": "accepted",
        "focus": {"reference": "ServiceRequest/sr-ct-1"}}


def _slot_server(fhir):
    fhir.get(f"{BASE}/ServiceRequest/sr-ct-1", json=SERVICE_REQUEST)
    fhir.get(f"{BASE}/HealthcareService", json=searchset(
        {"resourceType": "HealthcareService", "id": "healthcareservice-northside-ct"}))
    fhir.get(f"{BASE}/Slot", json=searchset(SLOT, SCHEDULE))


def test_panel_lists_the_patients_imaging_requests_with_a_book_action(client, fhir):
    fhir.get(f"{BASE}/ServiceRequest", json=searchset(SERVICE_REQUEST, TASK))

    response = client.get("/booking/patient/pat-1/panel", headers=FHIR_HEADERS)

    body = response.get_data(as_text=True)
    assert fhir.last_request.qs["subject"] == ["patient/pat-1"]
    assert fhir.last_request.qs["category"] == ["http://snomed.info/sct|363679005"]
    assert sorted(fhir.last_request.qs["_revinclude"]) == ["appointment:based-on", "task:focus"]
    assert "CT Abdo/Pelvis" in body
    assert 'hx-get="/booking/sr/sr-ct-1/slots"' in body


def test_slot_picker_offers_free_slots_grouped_by_day(client, fhir):
    _slot_server(fhir)

    response = client.get("/booking/sr/sr-ct-1/slots", headers=FHIR_HEADERS)

    body = response.get_data(as_text=True)
    assert "Tue 6 Oct" in body
    assert "09:30" in body
    assert 'name="slot_id" value="slot-0930"' in body


def test_proposing_confirms_the_request_was_sent_and_refreshes_the_panel(client, fhir):
    fhir.get(f"{BASE}/ServiceRequest/sr-ct-1", json=SERVICE_REQUEST)
    fhir.get(f"{BASE}/Slot/slot-0930", json=SLOT)
    fhir.get(f"{BASE}/Schedule/schedule-northside-ct", json=SCHEDULE)
    fhir.post(BASE, json={"resourceType": "Bundle", "type": "transaction-response", "entry": [
        {"response": {"status": "201 Created", "location": "Appointment/appt-9/_history/1"}}]})

    response = client.post("/booking/sr/sr-ct-1/propose", data={"slot_id": "slot-0930"},
                           headers=FHIR_HEADERS)

    assert "awaiting confirmation" in response.get_data(as_text=True)
    assert response.headers["HX-Trigger"] == "booking-changed"


def test_a_slot_taken_meanwhile_says_so_and_offers_fresh_slots(client, fhir):
    _slot_server(fhir)
    fhir.get(f"{BASE}/Slot/slot-0930", json=SLOT)
    fhir.get(f"{BASE}/Schedule/schedule-northside-ct", json=SCHEDULE)
    fhir.post(BASE, status_code=412, json={"resourceType": "OperationOutcome", "issue": [
        {"severity": "error", "code": "conflict"}]})

    response = client.post("/booking/sr/sr-ct-1/propose", data={"slot_id": "slot-0930"},
                           headers=FHIR_HEADERS)

    body = response.get_data(as_text=True)
    assert "This slot was just taken" in body
    assert 'name="slot_id"' in body  # a fresh slot list follows the message
    assert "HX-Trigger" not in response.headers


def test_patient_details_page_loads_the_booking_panel(client, fhir):
    fhir.get(f"{BASE}/Patient/pat-1", json={
        "resourceType": "Patient", "id": "pat-1", "name": [{"given": ["Ada"], "family": "Lee"}]})

    response = client.get("/fhir/Patient/pat-1", headers=FHIR_HEADERS)

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'hx-get="/booking/patient/pat-1/panel"' in body
    assert 'id="bookingModalBody"' in body


from booking import SERVICE_BOOKED  # noqa: E402
from tests.booking.conftest import (FULFILMENT_TASK, GROUP_TASK, HELD_SLOT,  # noqa: E402
                                    PROPOSED_APPOINTMENT, transaction_response)

BOOKED = {**PROPOSED_APPOINTMENT, "status": "booked", "created": "2026-10-01T10:00:00+10:00"}


def test_booked_rows_offer_cancel_and_reschedule(client, fhir):
    fhir.get(f"{BASE}/ServiceRequest", json=searchset(SERVICE_REQUEST, TASK, BOOKED))

    body = client.get("/booking/patient/pat-1/panel", headers=FHIR_HEADERS).get_data(as_text=True)

    assert 'hx-post="/booking/appointment/appt-9/cancel"' in body
    assert 'hx-get="/booking/sr/sr-ct-1/reschedule/appt-9/slots"' in body
    assert 'hx-get="/booking/sr/sr-ct-1/slots"' not in body


def test_cancelling_requires_a_reason(client, fhir):
    response = client.post("/booking/appointment/appt-9/cancel", data={"reason": ""},
                           headers=FHIR_HEADERS)

    assert "reason is required" in response.get_data(as_text=True)
    assert fhir.call_count == 0


def test_cancelling_refreshes_the_panel(client, fhir):
    fhir.get(f"{BASE}/Appointment/appt-9", json=BOOKED)
    fhir.get(f"{BASE}/Slot/slot-0930", json={**HELD_SLOT, "status": "busy"})
    fhir.get(f"{BASE}/Task", json=searchset({**FULFILMENT_TASK, "businessStatus": SERVICE_BOOKED}))
    fhir.get(f"{BASE}/Task/task-group-1", json=GROUP_TASK)
    fhir.post(BASE, json=transaction_response(0))

    response = client.post("/booking/appointment/appt-9/cancel", data={"reason": "Unwell"},
                           headers=FHIR_HEADERS)

    assert "Cancelled" in response.get_data(as_text=True)
    assert response.headers["HX-Trigger"] == "booking-changed"


def test_reschedule_picker_posts_to_reschedule(client, fhir):
    _slot_server(fhir)

    body = client.get("/booking/sr/sr-ct-1/reschedule/appt-9/slots",
                      headers=FHIR_HEADERS).get_data(as_text=True)

    assert 'hx-post="/booking/sr/sr-ct-1/reschedule/appt-9"' in body


def test_rescheduling_into_a_taken_slot_offers_fresh_slots(client, fhir):
    _slot_server(fhir)
    fhir.get(f"{BASE}/Appointment/appt-9", json=BOOKED)
    fhir.get(f"{BASE}/Slot/slot-0930", json={**SLOT, "status": "busy"})
    fhir.get(f"{BASE}/Task", json=searchset(FULFILMENT_TASK))
    fhir.get(f"{BASE}/Task/task-group-1", json=GROUP_TASK)

    response = client.post("/booking/sr/sr-ct-1/reschedule/appt-9", data={"slot_id": "slot-0930"},
                           headers=FHIR_HEADERS)

    body = response.get_data(as_text=True)
    assert "This slot was just taken" in body
    assert 'hx-post="/booking/sr/sr-ct-1/reschedule/appt-9"' in body
