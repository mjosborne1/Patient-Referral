"""The airport board classifies task-owning Organisations as pathology/radiology by SNOMED type code."""
import os

import pytest

os.environ["TESTING"] = "true"

BASE = "https://fhir.test/fhir"
HEADERS = {"X-FHIR-Server-URL": BASE}
HPIO = "http://ns.electronichealth.net.au/id/hi/hpio/1.0"
SCT = "http://snomed.info/sct"


def _org(org_id, name, code, display):
    return {"resourceType": "Organization", "id": org_id, "name": name,
            "identifier": [{"system": HPIO, "value": f"800362{org_id}"}],
            "type": [{"coding": [{"system": SCT, "code": code, "display": display}]}]}


@pytest.fixture
def client():
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.mark.parametrize("code,display,expected", [
    ("310074003", "Pathology service", "pathology"),
    ("309950003", "Pathology department", "pathology"),
    ("708175003", "Radiology service", "radiology"),
    ("284546000", "Diagnostic imaging service", "radiology"),
])
def test_org_type_comes_from_snomed_code(client, requests_mock, code, display, expected):
    # Name carries no type hint, so only the SNOMED code can classify it.
    org = _org("0001", "Laverty", code, display)
    requests_mock.get(f"{BASE}/Task", json={"resourceType": "Bundle", "entry": [{"resource": org}]})

    [result] = client.get("/api/organisations/with-tasks", headers=HEADERS).get_json()

    assert result["type"] == expected


def test_owners_on_later_pages_are_included(client, requests_mock):
    # The server pages group tasks; pathology owners may only appear after page 1.
    imaging = _org("0002", "Moreton Bay Imaging Partners", "708175003", "Diagnostic imaging service")
    pathology = _org("0003", "Coral Coast Pathology", "310074003", "Pathology service")
    next_url = f"{BASE}?_getpages=abc&_getpagesoffset=20"
    requests_mock.get(f"{BASE}/Task", json={"resourceType": "Bundle", "entry": [{"resource": imaging}],
                                            "link": [{"relation": "next", "url": next_url}]})
    requests_mock.get(next_url, json={"resourceType": "Bundle", "entry": [{"resource": pathology}]})

    orgs = client.get("/api/organisations/with-tasks", headers=HEADERS).get_json()

    assert {o["name"]: o["type"] for o in orgs} == {
        "Coral Coast Pathology": "pathology", "Moreton Bay Imaging Partners": "radiology"}
