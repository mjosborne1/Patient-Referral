"""Behaviour of the filler imaging booking routes."""
from tests.booking.conftest import BASE, FHIR_HEADERS, searchset, transaction_response

FORM = {
    "organization_id": "organization-northside-imaging",
    "location_id": "location-northside-imaging-chermside",
    "service_type": "310128004",
    "start_date": "2026-10-06", "end_date": "2026-10-06",
    "day_start": "09:00", "day_end": "10:00", "slot_minutes": "30",
}


def test_publishing_availability_reports_how_many_slots_were_created(client, fhir):
    fhir.get(f"{BASE}/HealthcareService", json=searchset(
        {"resourceType": "HealthcareService", "id": "hcs-1"}))
    fhir.get(f"{BASE}/Schedule", json=searchset())
    fhir.post(BASE, json=transaction_response(3))

    response = client.post("/filler/imaging/availability", data=FORM, headers=FHIR_HEADERS)

    assert response.status_code == 200
    assert "Published 2 slots" in response.get_data(as_text=True)
    tx = fhir.request_history[-1].json()
    assert tx["entry"][0]["resource"]["serviceType"][0]["coding"][0]["display"] == \
        "Computed tomography service"


def test_publish_failure_shows_the_operation_outcome(client, fhir):
    fhir.get(f"{BASE}/HealthcareService", json=searchset(
        {"resourceType": "HealthcareService", "id": "hcs-1"}))
    fhir.get(f"{BASE}/Schedule", json=searchset())
    fhir.post(BASE, status_code=422, json={"resourceType": "OperationOutcome", "issue": [
        {"severity": "error", "code": "invalid", "diagnostics": "Slot.start is required"}]})

    response = client.post("/filler/imaging/availability", data=FORM, headers=FHIR_HEADERS)

    body = response.get_data(as_text=True)
    assert "Slot.start is required" in body
    assert "Published" not in body


def test_location_choices_are_the_organisations_locations(client, fhir):
    fhir.get(f"{BASE}/Location", json=searchset(
        {"resourceType": "Location", "id": "loc-chermside", "name": "Northside Imaging Chermside"}))

    response = client.get("/filler/imaging/locations?organization_id=org-1", headers=FHIR_HEADERS)

    body = response.get_data(as_text=True)
    assert fhir.last_request.qs == {"organization": ["org-1"]}
    assert '<option value="loc-chermside">Northside Imaging Chermside</option>' in body


def test_filler_imaging_page_renders_the_availability_form(client):
    response = client.get("/filler/imaging")

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'hx-post="/filler/imaging/availability"' in body
    assert "Computed tomography service" in body
