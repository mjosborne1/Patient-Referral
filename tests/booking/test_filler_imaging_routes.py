"""Behaviour of the filler imaging booking routes."""
from tests.booking.conftest import BASE, FHIR_HEADERS, searchset, transaction_response

FORM = {
    "organization_id": "organization-northside-imaging",
    "location_id": "location-northside-imaging-chermside",
    "service_type": "310128004",
    "start_date": "2026-10-06", "end_date": "2026-10-06",
    "day_start": "09:00", "day_end": "10:00", "slot_minutes": "30",
}


def test_publishing_availability_reports_how_many_slots_were_created(client, fhir):
    fhir.get(f"{BASE}/HealthcareService", json=searchset(
        {"resourceType": "HealthcareService", "id": "hcs-1"}))
    fhir.get(f"{BASE}/Schedule", json=searchset())
    fhir.post(BASE, json=transaction_response(3))

    response = client.post("/filler/imaging/availability", data=FORM, headers=FHIR_HEADERS)

    assert response.status_code == 200
    assert "Published 2 slots" in response.get_data(as_text=True)
    tx = fhir.request_history[-1].json()
    assert tx["entry"][0]["resource"]["serviceType"][0]["coding"][0]["display"] == \
        "Computed tomography service"


def test_publish_failure_shows_the_operation_outcome(client, fhir):
    fhir.get(f"{BASE}/HealthcareService", json=searchset(
        {"resourceType": "HealthcareService", "id": "hcs-1"}))
    fhir.get(f"{BASE}/Schedule", json=searchset())
    fhir.post(BASE, status_code=422, json={"resourceType": "OperationOutcome", "issue": [
        {"severity": "error", "code": "invalid", "diagnostics": "Slot.start is required"}]})

    response = client.post("/filler/imaging/availability", data=FORM, headers=FHIR_HEADERS)

    body = response.get_data(as_text=True)
    assert "Slot.start is required" in body
    assert "Published" not in body


def test_location_choices_are_the_organisations_locations(client, fhir):
    fhir.get(f"{BASE}/Location", json=searchset(
        {"resourceType": "Location", "id": "loc-chermside", "name": "Northside Imaging Chermside"}))

    response = client.get("/filler/imaging/locations?organization_id=org-1", headers=FHIR_HEADERS)

    body = response.get_data(as_text=True)
    assert fhir.last_request.qs == {"organization": ["org-1"]}
    assert '<option value="loc-chermside">Northside Imaging Chermside</option>' in body


def test_filler_imaging_page_renders_the_availability_form(client):
    response = client.get("/filler/imaging")

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'hx-post="/filler/imaging/availability"' in body
    assert "Computed tomography service" in body
    assert 'id="pendingBookings" hx-get="/filler/imaging/pending"' in body
    assert 'id="unbookedRequests" hx-get="/filler/imaging/unbooked"' in body
    assert 'id="fillerBookingModalBody"' in body


from tests.booking.conftest import (FULFILMENT_TASK, GROUP_TASK, HELD_SLOT,  # noqa: E402
                                    PROPOSED_APPOINTMENT, SERVICE_REQUEST)

PATIENT = {"resourceType": "Patient", "id": "pat-1", "name": [{"given": ["Ada"], "family": "Lee"}]}


def _booking_server(fhir):
    fhir.get(f"{BASE}/Appointment/appt-9", json=PROPOSED_APPOINTMENT)
    fhir.get(f"{BASE}/Slot/slot-0930", json=HELD_SLOT)
    fhir.get(f"{BASE}/Task", json=searchset(FULFILMENT_TASK))
    fhir.get(f"{BASE}/Task/task-group-1", json=GROUP_TASK)
    fhir.post(BASE, json=transaction_response(0))


def test_pending_bookings_list_shows_patient_request_time_and_actions(client, fhir):
    fhir.get(f"{BASE}/HealthcareService", json=searchset(
        {"resourceType": "HealthcareService", "id": "hcs-1"}))
    fhir.get(f"{BASE}/Appointment", json=searchset(PROPOSED_APPOINTMENT, PATIENT, SERVICE_REQUEST))

    response = client.get("/filler/imaging/pending?organization_id=org-1", headers=FHIR_HEADERS)

    body = response.get_data(as_text=True)
    assert "Ada Lee" in body and "CT Abdo/Pelvis" in body
    assert "Tue 6 Oct" in body and "09:30" in body
    assert 'hx-post="/filler/imaging/appointment/appt-9/confirm"' in body
    assert 'hx-post="/filler/imaging/appointment/appt-9/decline"' in body


def test_confirming_reports_booked_and_signals_lists_to_refresh(client, fhir):
    _booking_server(fhir)

    response = client.post("/filler/imaging/appointment/appt-9/confirm",
                           data={"patient_instruction": "Fast for 4 hours."}, headers=FHIR_HEADERS)

    assert "Booked" in response.get_data(as_text=True)
    assert response.headers["HX-Trigger"] == "booking-changed"
    appt = next(e for e in fhir.last_request.json()["entry"]
                if e["request"]["url"] == "Appointment/appt-9")["resource"]
    assert appt["patientInstruction"] == "Fast for 4 hours."


def test_declining_requires_a_reason(client, fhir):
    response = client.post("/filler/imaging/appointment/appt-9/decline", data={"reason": " "},
                           headers=FHIR_HEADERS)

    assert "reason is required" in response.get_data(as_text=True)
    assert fhir.call_count == 0


def test_declining_reports_declined(client, fhir):
    _booking_server(fhir)

    response = client.post("/filler/imaging/appointment/appt-9/decline",
                           data={"reason": "Scanner maintenance"}, headers=FHIR_HEADERS)

    assert "Declined" in response.get_data(as_text=True)
    assert response.headers["HX-Trigger"] == "booking-changed"


def test_acting_on_a_booking_changed_elsewhere_asks_to_refresh(client, fhir):
    fhir.get(f"{BASE}/Appointment/appt-9", json={**PROPOSED_APPOINTMENT, "status": "cancelled"})
    fhir.get(f"{BASE}/Slot/slot-0930", json=HELD_SLOT)

    response = client.post("/filler/imaging/appointment/appt-9/confirm", headers=FHIR_HEADERS)

    assert "changed since it was listed" in response.get_data(as_text=True)
    assert response.headers["HX-Trigger"] == "booking-changed"


from tests.booking.conftest import SCHEDULE, SLOT  # noqa: E402


def test_unbooked_list_offers_direct_booking_for_accepted_requests(client, fhir):
    fhir.get(f"{BASE}/ServiceRequest", json=searchset(SERVICE_REQUEST, FULFILMENT_TASK, PATIENT))

    response = client.get("/filler/imaging/unbooked?organization_id=org-1", headers=FHIR_HEADERS)

    body = response.get_data(as_text=True)
    assert "Ada Lee" in body and "CT Abdo/Pelvis" in body
    assert 'hx-get="/filler/imaging/sr/sr-ct-1/slots"' in body


def test_filler_slot_picker_books_directly_and_asks_for_instructions(client, fhir):
    fhir.get(f"{BASE}/ServiceRequest/sr-ct-1", json=SERVICE_REQUEST)
    fhir.get(f"{BASE}/HealthcareService", json=searchset(
        {"resourceType": "HealthcareService", "id": "healthcareservice-northside-ct"}))
    fhir.get(f"{BASE}/Slot", json=searchset(SLOT, SCHEDULE))

    response = client.get("/filler/imaging/sr/sr-ct-1/slots", headers=FHIR_HEADERS)

    body = response.get_data(as_text=True)
    assert 'hx-post="/filler/imaging/sr/sr-ct-1/book"' in body
    assert 'name="patient_instruction"' in body


def test_booking_directly_reports_booked(client, fhir):
    fhir.get(f"{BASE}/ServiceRequest/sr-ct-1", json=SERVICE_REQUEST)
    fhir.get(f"{BASE}/Slot/slot-0930", json=SLOT)
    fhir.get(f"{BASE}/Schedule/schedule-northside-ct", json=SCHEDULE)
    fhir.get(f"{BASE}/Task", json=searchset(FULFILMENT_TASK))
    fhir.get(f"{BASE}/Task/task-group-1", json=GROUP_TASK)
    fhir.post(BASE, json=transaction_response(0))

    response = client.post("/filler/imaging/sr/sr-ct-1/book",
                           data={"slot_id": "slot-0930", "patient_instruction": "Fast"},
                           headers=FHIR_HEADERS)

    assert "Booked" in response.get_data(as_text=True)
    assert response.headers["HX-Trigger"] == "booking-changed"
