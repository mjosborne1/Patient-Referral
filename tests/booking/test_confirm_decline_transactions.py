"""Behaviour of the filler's confirm and decline transactions."""
from booking import build_confirm_transaction, build_decline_transaction
from tests.booking.conftest import FULFILMENT_TASK, GROUP_TASK, HELD_SLOT, PROPOSED_APPOINTMENT

SERVICE_BOOKED = {"coding": [{"system": "http://terminology.hl7.org.au/CodeSystem/task-business-status",
                              "code": "service-booked", "display": "Service booked"}]}


def _entries(bundle):
    return {e["request"]["url"]: e for e in bundle["entry"]}


def _confirm(**kwargs):
    return _entries(build_confirm_transaction(PROPOSED_APPOINTMENT, HELD_SLOT, FULFILMENT_TASK,
                                              GROUP_TASK, **kwargs))


def test_confirm_books_the_appointment_and_its_slot():
    entries = _confirm(patient_instruction="Fast for 4 hours before your scan.")

    appt = entries["Appointment/appt-9"]["resource"]
    assert appt["status"] == "booked"
    assert all(p["status"] == "accepted" for p in appt["participant"])
    assert appt["patientInstruction"] == "Fast for 4 hours before your scan."
    assert entries["Slot/slot-0930"]["resource"]["status"] == "busy"


def test_confirm_marks_both_tasks_service_booked_but_leaves_them_accepted():
    entries = _confirm()

    for url in ("Task/task-1", "Task/task-group-1"):
        task = entries[url]["resource"]
        assert task["status"] == "accepted"
        assert task["businessStatus"] == SERVICE_BOOKED


def test_every_confirm_update_is_guarded_by_the_version_read():
    entries = _confirm()

    assert {url: e["request"]["ifMatch"] for url, e in entries.items()} == {
        "Appointment/appt-9": 'W/"1"', "Slot/slot-0930": 'W/"4"',
        "Task/task-1": 'W/"2"', "Task/task-group-1": 'W/"5"'}


def test_confirm_without_instructions_adds_none():
    assert "patientInstruction" not in _confirm()["Appointment/appt-9"]["resource"]


def test_decline_cancels_the_appointment_with_a_reason_and_frees_the_slot():
    entries = _entries(build_decline_transaction(PROPOSED_APPOINTMENT, HELD_SLOT,
                                                 reason="No contrast available that day"))

    appt = entries["Appointment/appt-9"]["resource"]
    assert appt["status"] == "cancelled"
    assert appt["cancelationReason"] == {"text": "No contrast available that day"}
    statuses = {p["actor"]["reference"]: p["status"] for p in appt["participant"]}
    assert statuses["HealthcareService/healthcareservice-northside-ct"] == "declined"
    assert statuses["Patient/pat-1"] == "accepted"
    assert entries["Slot/slot-0930"]["resource"]["status"] == "free"
    assert set(entries) == {"Appointment/appt-9", "Slot/slot-0930"}  # Tasks untouched
