"""Behaviour of the referrer proposing an Appointment in a chosen Slot."""
from booking import BookingClient
from tests.booking.conftest import BASE, SCHEDULE, SERVICE_REQUEST, SLOT


def _server(fhir, slot=SLOT):
    fhir.get(f"{BASE}/ServiceRequest/sr-ct-1", json=SERVICE_REQUEST)
    fhir.get(f"{BASE}/Slot/slot-0930", json=slot)
    fhir.get(f"{BASE}/Schedule/schedule-northside-ct", json=SCHEDULE)


def test_proposing_posts_the_transaction_and_returns_the_new_appointment(fhir):
    _server(fhir)
    fhir.post(BASE, json={"resourceType": "Bundle", "type": "transaction-response", "entry": [
        {"response": {"status": "201 Created", "location": "Appointment/appt-9/_history/1"}},
        {"response": {"status": "200 OK", "location": "Slot/slot-0930/_history/4"}}]})

    result = BookingClient(BASE).propose("sr-ct-1", "slot-0930")

    assert result.ok and not result.conflict
    assert result.appointment_id == "appt-9"
    tx = fhir.last_request.json()
    assert [e["request"]["method"] for e in tx["entry"]] == ["POST", "PUT"]
    assert tx["entry"][1]["request"]["ifMatch"] == 'W/"3"'


def test_a_slot_taken_since_it_was_read_is_reported_as_a_conflict(fhir):
    _server(fhir)
    fhir.post(BASE, status_code=412, json={"resourceType": "OperationOutcome", "issue": [
        {"severity": "error", "code": "conflict", "diagnostics": "Version mismatch"}]})

    result = BookingClient(BASE).propose("sr-ct-1", "slot-0930")

    assert not result.ok and result.conflict


def test_a_slot_no_longer_free_is_a_conflict_without_writing_anything(fhir):
    _server(fhir, slot={**SLOT, "status": "busy-tentative"})

    result = BookingClient(BASE).propose("sr-ct-1", "slot-0930")

    assert not result.ok and result.conflict
    assert all(r.method == "GET" for r in fhir.request_history)


def test_other_server_errors_carry_the_operation_outcome(fhir):
    _server(fhir)
    fhir.post(BASE, status_code=422, json={"resourceType": "OperationOutcome", "issue": [
        {"severity": "error", "code": "invalid", "diagnostics": "Appointment.participant"}]})

    result = BookingClient(BASE).propose("sr-ct-1", "slot-0930")

    assert not result.ok and not result.conflict
    assert result.operation_outcome["issue"][0]["diagnostics"] == "Appointment.participant"
