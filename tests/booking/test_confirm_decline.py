"""Behaviour of the filler finding, confirming and declining proposed Appointments."""
from booking import BookingClient
from tests.booking.conftest import (BASE, FULFILMENT_TASK, GROUP_TASK, HELD_SLOT,
                                    PROPOSED_APPOINTMENT, SERVICE_REQUEST, searchset)

PATIENT = {"resourceType": "Patient", "id": "pat-1", "name": [{"given": ["Ada"], "family": "Lee"}]}
OK = {"resourceType": "Bundle", "type": "transaction-response", "entry": []}


def test_pending_bookings_are_the_proposed_appointments_for_the_organisations_services(fhir):
    fhir.get(f"{BASE}/HealthcareService", json=searchset(
        {"resourceType": "HealthcareService", "id": "healthcareservice-northside-ct"}))
    fhir.get(f"{BASE}/Appointment", json=searchset(PROPOSED_APPOINTMENT, PATIENT, SERVICE_REQUEST))

    [pending] = BookingClient(BASE).pending_appointments("organization-northside-imaging")

    assert pending.appointment["id"] == "appt-9"
    assert pending.patient["id"] == "pat-1"
    assert pending.service_request["id"] == "sr-ct-1"
    search = fhir.last_request
    assert search.qs["actor"] == ["healthcareservice/healthcareservice-northside-ct"]
    assert search.qs["status"] == ["proposed"]
    assert sorted(search.qs["_include"]) == ["appointment:based-on", "appointment:patient"]


def _booking_server(fhir, appointment=PROPOSED_APPOINTMENT):
    fhir.get(f"{BASE}/Appointment/appt-9", json=appointment)
    fhir.get(f"{BASE}/Slot/slot-0930", json=HELD_SLOT)
    fhir.get(f"{BASE}/Task", json=searchset(FULFILMENT_TASK))
    fhir.get(f"{BASE}/Task/task-group-1", json=GROUP_TASK)


def test_confirming_updates_appointment_slot_and_both_tasks_in_one_transaction(fhir):
    _booking_server(fhir)
    fhir.post(BASE, json=OK)

    result = BookingClient(BASE).confirm("appt-9", patient_instruction="Arrive 30 minutes early.")

    assert result.ok
    task_search = next(r for r in fhir.request_history if r.path.endswith("/task") and r.method == "GET")
    assert task_search.qs["focus"] == ["servicerequest/sr-ct-1"]
    tx = fhir.last_request.json()
    assert sorted(e["request"]["url"] for e in tx["entry"]) == [
        "Appointment/appt-9", "Slot/slot-0930", "Task/task-1", "Task/task-group-1"]


def test_an_appointment_no_longer_proposed_cannot_be_confirmed(fhir):
    _booking_server(fhir, appointment={**PROPOSED_APPOINTMENT, "status": "cancelled"})

    result = BookingClient(BASE).confirm("appt-9")

    assert not result.ok and result.conflict
    assert all(r.method == "GET" for r in fhir.request_history)


def test_declining_cancels_and_frees_the_slot(fhir):
    _booking_server(fhir)
    fhir.post(BASE, json=OK)

    result = BookingClient(BASE).decline("appt-9", reason="Scanner maintenance")

    assert result.ok
    tx = fhir.last_request.json()
    assert sorted(e["request"]["url"] for e in tx["entry"]) == ["Appointment/appt-9", "Slot/slot-0930"]
