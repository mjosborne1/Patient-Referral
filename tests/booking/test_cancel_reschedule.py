"""Behaviour of the referrer cancelling and rescheduling."""
from booking import SERVICE_BOOKED, BookingClient
from tests.booking.conftest import (BASE, FULFILMENT_TASK, GROUP_TASK, HELD_SLOT,
                                    PROPOSED_APPOINTMENT, SCHEDULE, SERVICE_REQUEST, SLOT,
                                    searchset)

BOOKED = {**PROPOSED_APPOINTMENT, "status": "booked"}
NEW_SLOT = {**SLOT, "id": "slot-1030", "start": "2026-10-06T10:30:00+10:00"}
# Response entries align with request entries; servers give a location for updates too.
OK = {"resourceType": "Bundle", "type": "transaction-response", "entry": [
    {"response": {"status": "200 OK", "location": "Appointment/appt-9/_history/2"}},
    {"response": {"status": "200 OK", "location": "Slot/slot-0930/_history/5"}},
    {"response": {"status": "200 OK", "location": "Task/task-1/_history/3"}},
    {"response": {"status": "200 OK", "location": "Task/task-group-1/_history/6"}},
    {"response": {"status": "201 Created", "location": "Appointment/appt-11/_history/1"}},
    {"response": {"status": "200 OK", "location": "Slot/slot-1030/_history/2"}}]}


def _server(fhir, appointment=BOOKED):
    fhir.get(f"{BASE}/Appointment/appt-9", json=appointment)
    fhir.get(f"{BASE}/Slot/slot-0930", json={**HELD_SLOT, "status": "busy"})
    fhir.get(f"{BASE}/Task", json=searchset({**FULFILMENT_TASK, "businessStatus": SERVICE_BOOKED}))
    fhir.get(f"{BASE}/Task/task-group-1", json={**GROUP_TASK, "businessStatus": SERVICE_BOOKED})


def test_cancelling_a_booked_appointment(fhir):
    _server(fhir)
    fhir.post(BASE, json=OK)

    result = BookingClient(BASE).cancel("appt-9", reason="Patient unavailable")

    assert result.ok
    urls = sorted(e["request"]["url"] for e in fhir.last_request.json()["entry"])
    assert urls == ["Appointment/appt-9", "Slot/slot-0930", "Task/task-1", "Task/task-group-1"]


def test_an_already_cancelled_appointment_cannot_be_cancelled_again(fhir):
    _server(fhir, appointment={**BOOKED, "status": "cancelled"})

    result = BookingClient(BASE).cancel("appt-9", reason="x")

    assert not result.ok and result.conflict
    assert all(r.method == "GET" for r in fhir.request_history)


def test_rescheduling_returns_the_new_proposed_appointment(fhir):
    _server(fhir)
    fhir.get(f"{BASE}/ServiceRequest/sr-ct-1", json=SERVICE_REQUEST)
    fhir.get(f"{BASE}/Slot/slot-1030", json=NEW_SLOT)
    fhir.get(f"{BASE}/Schedule/schedule-northside-ct", json=SCHEDULE)
    fhir.post(BASE, json=OK)

    result = BookingClient(BASE).reschedule("appt-9", "slot-1030")

    assert result.ok and result.appointment_id == "appt-11"
    methods = [e["request"]["method"] for e in fhir.last_request.json()["entry"]]
    assert methods.count("POST") == 1


def test_rescheduling_into_a_slot_taken_meanwhile_changes_nothing(fhir):
    _server(fhir)
    fhir.get(f"{BASE}/ServiceRequest/sr-ct-1", json=SERVICE_REQUEST)
    fhir.get(f"{BASE}/Slot/slot-1030", json=NEW_SLOT)
    fhir.get(f"{BASE}/Schedule/schedule-northside-ct", json=SCHEDULE)
    fhir.post(BASE, status_code=412, json={"resourceType": "OperationOutcome", "issue": [
        {"severity": "error", "code": "conflict"}]})

    result = BookingClient(BASE).reschedule("appt-9", "slot-1030")

    assert not result.ok and result.conflict
