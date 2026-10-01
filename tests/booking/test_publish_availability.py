"""Behaviour of publishing availability against a FHIR server."""
from datetime import date, time

from booking import BookingClient
from tests.booking.conftest import BASE, searchset, transaction_response

CT_SERVICE = {"system": "http://snomed.info/sct", "code": "310128004",
              "display": "Computed tomography service"}


def _publish(client):
    return client.publish_availability(
        organization_id="organization-northside-imaging",
        location_id="location-northside-imaging-chermside",
        service_type=CT_SERVICE,
        start_date=date(2026, 10, 6), end_date=date(2026, 10, 6),
        day_start=time(9, 0), day_end=time(10, 0), slot_minutes=30,
    )


def test_first_publish_creates_healthcare_service_then_schedule_and_slots(fhir):
    fhir.get(f"{BASE}/HealthcareService", json=searchset())
    fhir.post(f"{BASE}/HealthcareService", status_code=201,
              json={"resourceType": "HealthcareService", "id": "hcs-new"})
    fhir.post(BASE, json=transaction_response(3))

    result = _publish(BookingClient(BASE))

    assert result.ok and result.created_slots == 2 and result.skipped_slots == 0
    hcs_search, hcs_create, tx = fhir.request_history
    assert hcs_search.qs == {"organization": ["organization-northside-imaging"],
                             "service-type": ["http://snomed.info/sct|310128004"]}
    created = hcs_create.json()
    assert created["providedBy"] == {"reference": "Organization/organization-northside-imaging"}
    assert created["type"] == [{"coding": [CT_SERVICE]}]
    assert created["location"] == [{"reference": "Location/location-northside-imaging-chermside"}]
    schedule = tx.json()["entry"][0]["resource"]
    assert schedule["resourceType"] == "Schedule"
    assert schedule["actor"][0] == {"reference": "HealthcareService/hcs-new"}


def test_republish_reuses_service_and_schedule_and_skips_published_slots(fhir):
    fhir.get(f"{BASE}/HealthcareService", json=searchset(
        {"resourceType": "HealthcareService", "id": "healthcareservice-northside-ct"}))
    fhir.get(f"{BASE}/Schedule", json=searchset(
        {"resourceType": "Schedule", "id": "schedule-northside-ct"}))
    fhir.get(f"{BASE}/Slot", json=searchset(
        {"resourceType": "Slot", "id": "slot-0900", "start": "2026-10-06T09:00:00+10:00"}))
    fhir.post(BASE, json=transaction_response(1))

    result = _publish(BookingClient(BASE))

    assert result.ok and result.created_slots == 1 and result.skipped_slots == 1
    assert not any(r.method == "POST" and r.path.endswith("/healthcareservice")
                   for r in fhir.request_history)
    schedule_search = next(r for r in fhir.request_history if r.path.endswith("/schedule"))
    assert schedule_search.qs["actor"] == ["healthcareservice/healthcareservice-northside-ct"]
    slot_search = next(r for r in fhir.request_history if r.path.endswith("/slot"))
    assert slot_search.qs["schedule"] == ["schedule/schedule-northside-ct"]
    tx = fhir.request_history[-1].json()
    assert [e["resource"]["resourceType"] for e in tx["entry"]] == ["Slot"]
    assert tx["entry"][0]["resource"]["schedule"] == {"reference": "Schedule/schedule-northside-ct"}


def test_rejected_transaction_reports_the_servers_operation_outcome(fhir):
    outcome = {"resourceType": "OperationOutcome", "issue": [
        {"severity": "error", "code": "invalid", "diagnostics": "Slot.start is required"}]}
    fhir.get(f"{BASE}/HealthcareService", json=searchset(
        {"resourceType": "HealthcareService", "id": "hcs-1"}))
    fhir.get(f"{BASE}/Schedule", json=searchset())
    fhir.post(BASE, status_code=422, json=outcome)

    result = _publish(BookingClient(BASE))

    assert not result.ok
    assert result.created_slots == 0
    assert result.operation_outcome == outcome


def test_failed_search_is_reported_rather_than_raised(fhir):
    fhir.get(f"{BASE}/HealthcareService", status_code=401, json={
        "resourceType": "OperationOutcome",
        "issue": [{"severity": "error", "code": "login", "diagnostics": "Unauthorized"}]})

    result = _publish(BookingClient(BASE))

    assert not result.ok
    assert result.operation_outcome["issue"][0]["diagnostics"] == "Unauthorized"


def test_nothing_is_posted_when_every_slot_is_already_published(fhir):
    fhir.get(f"{BASE}/HealthcareService", json=searchset(
        {"resourceType": "HealthcareService", "id": "hcs-1"}))
    fhir.get(f"{BASE}/Schedule", json=searchset({"resourceType": "Schedule", "id": "sch-1"}))
    fhir.get(f"{BASE}/Slot", json=searchset(
        {"resourceType": "Slot", "start": "2026-10-06T09:00:00+10:00"},
        {"resourceType": "Slot", "start": "2026-10-06T09:30:00+10:00"}))

    result = _publish(BookingClient(BASE))

    assert result.ok and result.created_slots == 0 and result.skipped_slots == 2
    assert all(r.method == "GET" for r in fhir.request_history)
