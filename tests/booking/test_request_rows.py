"""What the placer panel shows for each imaging request."""
from booking import imaging_request_rows
from tests.booking.conftest import SERVICE_REQUEST


def _bundle(*resources):
    return {"resourceType": "Bundle", "type": "searchset",
            "entry": [{"resource": r} for r in resources]}


def _task(status):
    return {"resourceType": "Task", "id": "task-1", "status": status,
            "focus": {"reference": "ServiceRequest/sr-ct-1"}}


def _appt(appt_id, status, created, hcs_status="needs-action"):
    return {"resourceType": "Appointment", "id": appt_id, "status": status, "created": created,
            "start": "2026-10-06T09:30:00+10:00",
            "basedOn": [{"reference": "ServiceRequest/sr-ct-1"}],
            "participant": [{"actor": {"reference": "HealthcareService/hcs-1"},
                             "status": hcs_status}]}


def _row(*resources):
    [row] = imaging_request_rows(_bundle(SERVICE_REQUEST, *resources))
    return row


def test_request_awaiting_triage_is_not_bookable():
    row = _row(_task("requested"))
    assert (row.state, row.bookable) == ("awaiting-triage", False)


def test_accepted_request_without_appointment_is_bookable():
    row = _row(_task("accepted"))
    assert (row.state, row.bookable, row.appointment) == ("bookable", True, None)


def test_proposed_and_booked_appointments_show_and_block_booking():
    proposed = _row(_task("accepted"), _appt("a1", "proposed", "2026-10-01T10:00:00+10:00"))
    booked = _row(_task("accepted"), _appt("a1", "booked", "2026-10-01T10:00:00+10:00", "accepted"))

    assert (proposed.state, proposed.bookable, proposed.appointment["id"]) == ("proposed", False, "a1")
    assert (booked.state, booked.bookable) == ("booked", False)


def test_declined_booking_is_shown_and_can_be_rebooked():
    row = _row(_task("accepted"),
               _appt("a1", "cancelled", "2026-10-01T10:00:00+10:00", hcs_status="declined"))
    assert (row.state, row.bookable, row.appointment["id"]) == ("declined", True, "a1")


def test_active_appointment_wins_over_an_older_cancelled_one():
    row = _row(_task("accepted"),
               _appt("old", "cancelled", "2026-10-01T09:00:00+10:00"),
               _appt("new", "booked", "2026-10-01T11:00:00+10:00", "accepted"))
    assert (row.state, row.appointment["id"]) == ("booked", "new")


def test_rows_are_only_for_service_requests_in_the_search():
    assert imaging_request_rows(_bundle(_task("accepted"))) == []
