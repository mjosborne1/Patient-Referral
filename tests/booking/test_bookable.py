"""When an imaging request may be booked (decision 9: Task stays accepted while booked)."""
import pytest

from booking import is_bookable

ACCEPTED = {"resourceType": "Task", "status": "accepted"}


def _appt(status):
    return {"resourceType": "Appointment", "status": status}


def test_accepted_request_with_no_appointment_is_bookable():
    assert is_bookable(ACCEPTED, [])


@pytest.mark.parametrize("task_status", ["requested", "on-hold", "rejected", "in-progress"])
def test_request_not_yet_accepted_or_already_underway_is_not_bookable(task_status):
    assert not is_bookable({"resourceType": "Task", "status": task_status}, [])


@pytest.mark.parametrize("status", ["proposed", "pending", "booked"])
def test_request_with_an_active_appointment_is_not_bookable(status):
    assert not is_bookable(ACCEPTED, [_appt(status)])


def test_cancelled_or_declined_appointment_does_not_block_rebooking():
    assert is_bookable(ACCEPTED, [_appt("cancelled")])


def test_missing_task_is_not_bookable():
    assert not is_bookable(None, [])
