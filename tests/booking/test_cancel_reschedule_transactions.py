"""Behaviour of the referrer's cancel and atomic reschedule transactions."""
from booking import SERVICE_BOOKED, build_cancel_transaction, build_reschedule_transaction
from tests.booking.conftest import (FULFILMENT_TASK, GROUP_TASK, HELD_SLOT, PROPOSED_APPOINTMENT,
                                    SCHEDULE, SERVICE_REQUEST, SLOT)

BOOKED = {**PROPOSED_APPOINTMENT, "status": "booked"}
BOOKED_SLOT = {**HELD_SLOT, "status": "busy"}
BOOKED_TASK = {**FULFILMENT_TASK, "businessStatus": SERVICE_BOOKED}
BOOKED_GROUP = {**GROUP_TASK, "businessStatus": SERVICE_BOOKED}
NEW_SLOT = {**SLOT, "id": "slot-1030", "meta": {"versionId": "1"},
            "start": "2026-10-06T10:30:00+10:00", "end": "2026-10-06T11:00:00+10:00"}


def _entries(bundle):
    return [(e["request"]["method"], e["request"]["url"], e["resource"]) for e in bundle["entry"]]


def test_cancelling_a_booking_frees_the_slot_and_clears_service_booked():
    entries = {url: r for _, url, r in _entries(build_cancel_transaction(
        BOOKED, BOOKED_SLOT, BOOKED_TASK, BOOKED_GROUP, reason="Patient unavailable"))}

    assert entries["Appointment/appt-9"]["status"] == "cancelled"
    assert entries["Appointment/appt-9"]["cancelationReason"] == {"text": "Patient unavailable"}
    assert entries["Slot/slot-0930"]["status"] == "free"
    for url in ("Task/task-1", "Task/task-group-1"):
        assert entries[url]["status"] == "accepted"
        assert "businessStatus" not in entries[url]


def test_cancelling_a_proposal_leaves_tasks_that_were_never_marked_booked_alone():
    entries = _entries(build_cancel_transaction(PROPOSED_APPOINTMENT, HELD_SLOT, FULFILMENT_TASK,
                                                GROUP_TASK, reason="Changed my mind"))

    assert [url for _, url, _ in entries] == ["Appointment/appt-9", "Slot/slot-0930"]


def test_reschedule_cancels_the_old_booking_and_proposes_the_new_slot_in_one_transaction():
    bundle = build_reschedule_transaction(BOOKED, BOOKED_SLOT, BOOKED_TASK, BOOKED_GROUP,
                                          SERVICE_REQUEST, NEW_SLOT, SCHEDULE)

    entries = _entries(bundle)
    assert bundle["type"] == "transaction"
    assert [(m, u) for m, u, _ in entries] == [
        ("PUT", "Appointment/appt-9"), ("PUT", "Slot/slot-0930"),
        ("PUT", "Task/task-1"), ("PUT", "Task/task-group-1"),
        ("POST", "Appointment"), ("PUT", "Slot/slot-1030")]
    old, new = entries[0][2], entries[4][2]
    assert old["status"] == "cancelled" and old["cancelationReason"] == {"text": "Rescheduled"}
    assert new["status"] == "proposed" and new["slot"] == [{"reference": "Slot/slot-1030"}]
    assert entries[5][2]["status"] == "busy-tentative"
    assert bundle["entry"][5]["request"]["ifMatch"] == 'W/"1"'
