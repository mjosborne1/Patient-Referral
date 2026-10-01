"""Behaviour of the filler booking a Slot directly for an accepted request (IG variant)."""
from booking import build_direct_book_transaction
from tests.booking.conftest import FULFILMENT_TASK, GROUP_TASK, SCHEDULE, SERVICE_REQUEST, SLOT


def _entries(**kwargs):
    bundle = build_direct_book_transaction(SERVICE_REQUEST, SLOT, SCHEDULE, FULFILMENT_TASK,
                                           GROUP_TASK, **kwargs)
    return {e["request"]["url"]: e for e in bundle["entry"]}


def test_direct_booking_creates_a_booked_appointment_with_every_participant_accepted():
    entries = _entries(patient_instruction="Arrive 30 minutes early.")

    entry = entries["Appointment"]
    assert entry["request"]["method"] == "POST"
    appt = entry["resource"]
    assert appt["status"] == "booked"
    assert appt["basedOn"] == [{"reference": "ServiceRequest/sr-ct-1"}]
    assert all(p["status"] == "accepted" for p in appt["participant"])
    assert appt["patientInstruction"] == "Arrive 30 minutes early."


def test_direct_booking_takes_the_slot_and_marks_both_tasks_service_booked():
    entries = _entries()

    assert entries["Slot/slot-0930"]["resource"]["status"] == "busy"
    assert entries["Slot/slot-0930"]["request"]["ifMatch"] == 'W/"3"'
    for url in ("Task/task-1", "Task/task-group-1"):
        assert entries[url]["resource"]["status"] == "accepted"
        assert entries[url]["resource"]["businessStatus"]["coding"][0]["code"] == "service-booked"
