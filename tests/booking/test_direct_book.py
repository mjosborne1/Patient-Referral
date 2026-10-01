"""Behaviour of the filler's accepted-but-unbooked list and direct booking."""
from booking import BookingClient
from tests.booking.conftest import (BASE, FULFILMENT_TASK, GROUP_TASK, SCHEDULE, SERVICE_REQUEST,
                                    SLOT, searchset)

PATIENT = {"resourceType": "Patient", "id": "pat-1", "name": [{"given": ["Ada"], "family": "Lee"}]}


def test_unbooked_requests_are_the_organisations_accepted_requests_without_appointments(fhir):
    other_sr = {**SERVICE_REQUEST, "id": "sr-ct-2"}
    other_task = {**FULFILMENT_TASK, "id": "task-2", "focus": {"reference": "ServiceRequest/sr-ct-2"}}
    booked = {"resourceType": "Appointment", "id": "a1", "status": "booked",
              "basedOn": [{"reference": "ServiceRequest/sr-ct-2"}], "participant": []}
    fhir.get(f"{BASE}/ServiceRequest", json=searchset(
        SERVICE_REQUEST, other_sr, FULFILMENT_TASK, other_task, booked, PATIENT))

    rows = BookingClient(BASE).unbooked_requests("organization-northside-imaging")

    assert [(r.service_request["id"], r.patient["id"]) for r in rows] == [("sr-ct-1", "pat-1")]
    search = fhir.last_request
    assert search.qs["performer"] == ["organization/organization-northside-imaging"]
    assert search.qs["_include"] == ["servicerequest:patient"]


def test_booking_directly_posts_a_booked_appointment_for_a_free_slot(fhir):
    fhir.get(f"{BASE}/ServiceRequest/sr-ct-1", json=SERVICE_REQUEST)
    fhir.get(f"{BASE}/Slot/slot-0930", json=SLOT)
    fhir.get(f"{BASE}/Schedule/schedule-northside-ct", json=SCHEDULE)
    fhir.get(f"{BASE}/Task", json=searchset(FULFILMENT_TASK))
    fhir.get(f"{BASE}/Task/task-group-1", json=GROUP_TASK)
    fhir.post(BASE, json={"resourceType": "Bundle", "type": "transaction-response", "entry": [
        {"response": {"status": "201 Created", "location": "Appointment/appt-10/_history/1"}}]})

    result = BookingClient(BASE).book_directly("sr-ct-1", "slot-0930", patient_instruction="Fast")

    assert result.ok and result.appointment_id == "appt-10"
    tx = fhir.last_request.json()
    assert sorted(e["request"]["url"] for e in tx["entry"]) == [
        "Appointment", "Slot/slot-0930", "Task/task-1", "Task/task-group-1"]


def test_booking_directly_into_a_taken_slot_is_a_conflict(fhir):
    fhir.get(f"{BASE}/ServiceRequest/sr-ct-1", json=SERVICE_REQUEST)
    fhir.get(f"{BASE}/Slot/slot-0930", json={**SLOT, "status": "busy"})

    result = BookingClient(BASE).book_directly("sr-ct-1", "slot-0930")

    assert not result.ok and result.conflict
    assert all(r.method == "GET" for r in fhir.request_history)
