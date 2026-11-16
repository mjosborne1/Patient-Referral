"""Routes that render the AU Patient Summary view."""
import json

from tests.aups.conftest import BASE, HEADERS, load


def test_summary_view_renders_sections_from_server(client, requests_mock):
    requests_mock.get(f"{BASE}/Patient/p1/$summary", json=load("referral-endoconsult-autogen"))
    html = client.get("/fhir/Patient/p1/aups-view", headers=HEADERS).get_data(as_text=True)
    for title in ("Past Medical History (Problems)", "Pregnancy Information", "Social History",
                  "Appendicitis", "Lifetime non-smoker", "Metformin (Tablet)"):
        assert title in html


def test_summary_view_shows_server_error(client, requests_mock):
    requests_mock.get(f"{BASE}/Patient/p1/$summary", status_code=404,
                      json={"resourceType": "OperationOutcome"})
    html = client.get("/fhir/Patient/p1/aups-view", headers=HEADERS).get_data(as_text=True)
    assert "Could not show the patient summary" in html and "404" in html


def test_uploaded_bundle_is_rendered(client):
    html = client.post("/aups/view", data={"bundle": json.dumps(load("patient-story")),
                                           "filename": "story.json"}).get_data(as_text=True)
    assert "Patient Story" in html and "story.json" in html
    assert "No information available" in html


def test_uploaded_invalid_json_is_reported(client):
    html = client.post("/aups/view", data={"bundle": "{not json"}).get_data(as_text=True)
    assert "Could not parse JSON" in html



def test_patient_page_shows_only_the_summary_card(client, requests_mock):
    requests_mock.get(f"{BASE}/Patient/p1", json={
        "resourceType": "Patient", "id": "p1", "name": [{"given": ["Ada"], "family": "Lee"}]})
    html = client.get("/fhir/Patient/p1", headers=HEADERS).get_data(as_text=True)
    assert 'hx-get="/fhir/Patient/p1/aups-view"' in html
    for removed in ("/fhir/LabResults/", "/fhir/VitalSigns/", "/fhir/Medications/", "/fhir/Allergies/",
                    "/fhir/Procedures/", "/fhir/Immunisation/", "/booking/patient/p1/panel"):
        assert removed not in html
