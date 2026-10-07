"""Behaviour of finding free Slots for an imaging request."""
from datetime import datetime
from zoneinfo import ZoneInfo

from booking import BookingClient, slot_search_window
from tests.booking.conftest import BASE, SCHEDULE, SERVICE_REQUEST, SLOT, searchset

BNE = ZoneInfo("Australia/Brisbane")
NOW = datetime(2026, 10, 1, 14, 0, tzinfo=BNE)


def test_window_defaults_to_the_next_fortnight():
    assert slot_search_window(SERVICE_REQUEST, NOW) == (
        datetime(2026, 10, 1, 14, 0, tzinfo=BNE), datetime(2026, 10, 15, 14, 0, tzinfo=BNE))


def test_window_follows_the_requested_occurrence_period_but_never_starts_in_the_past():
    sr = {**SERVICE_REQUEST, "occurrencePeriod": {"start": "2026-09-29", "end": "2026-10-13"}}

    start, end = slot_search_window(sr, NOW)

    assert start == NOW
    assert end == datetime(2026, 10, 14, 0, 0, tzinfo=BNE)  # end date is inclusive


def test_free_slots_are_found_via_the_performers_healthcare_service(fhir):
    fhir.get(f"{BASE}/ServiceRequest/sr-ct-1", json=SERVICE_REQUEST)
    fhir.get(f"{BASE}/HealthcareService", json=searchset(
        {"resourceType": "HealthcareService", "id": "healthcareservice-northside-ct"}))
    fhir.get(f"{BASE}/Slot", json={"resourceType": "Bundle", "type": "searchset", "entry": [
        {"resource": SLOT, "search": {"mode": "match"}},
        {"resource": SCHEDULE, "search": {"mode": "include"}}]})

    result = BookingClient(BASE).free_slots("sr-ct-1", now=NOW)

    assert result.ok
    assert [(slot["id"], schedule["id"]) for slot, schedule in result.slots] == [
        ("slot-0930", "schedule-northside-ct")]
    hcs_search, slot_search = fhir.request_history[1:]
    assert hcs_search.qs == {"organization": ["organization-northside-imaging"],
                             "service-type": ["http://snomed.info/sct|310128004"]}
    assert slot_search.qs["schedule.actor"] == ["healthcareservice/healthcareservice-northside-ct"]
    assert slot_search.qs["status"] == ["free"]
    assert slot_search.qs["start"] == ["ge2026-10-01t14:00:00+10:00", "lt2026-10-15t14:00:00+10:00"]
    assert slot_search.qs["_include"] == ["slot:schedule"]
    assert slot_search.qs["_sort"] == ["start"]


def test_no_slots_when_the_filler_publishes_no_matching_service(fhir):
    fhir.get(f"{BASE}/ServiceRequest/sr-ct-1", json=SERVICE_REQUEST)
    fhir.get(f"{BASE}/HealthcareService", json=searchset())

    result = BookingClient(BASE).free_slots("sr-ct-1", now=NOW)

    assert result.ok and result.slots == []
    assert len(fhir.request_history) == 2
