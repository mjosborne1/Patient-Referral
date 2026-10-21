"""The airport board shows each child Task's ServiceRequest (test, placer order number, ...)."""
import os

import pytest

os.environ["TESTING"] = "true"

BASE = "https://fhir.test/fhir"
HEADERS = {"X-FHIR-Server-URL": BASE}
ORDER_NS = "http://ns.electronichealth.net.au/id/hpio-scoped/order/1.0/8003629900000056"

GROUP = {"resourceType": "Task", "id": "qhc-taskgroup-0014", "status": "requested",
         "meta": {"tag": [{"code": "fulfilment-task-group"}]},
         "groupIdentifier": {"system": ORDER_NS, "value": "RFP-QHC-0014"},
         "for": {"reference": "Patient/qhc-pat-13"}}
CHILD = {"resourceType": "Task", "id": "qhc-task-0014", "status": "requested",
         "meta": {"tag": [{"code": "fulfilment-task"}]},
         "focus": {"reference": "ServiceRequest/qhc-sr-0014"},
         "partOf": [{"reference": "Task/qhc-taskgroup-0014"}]}
# As stored on qh-fhir-test (Radiology Referral IG profile): placer identifier has no PLAC type.
SR = {"resourceType": "ServiceRequest", "id": "qhc-sr-0014", "priority": "routine",
      "authoredOn": "2026-08-12T10:15:00+10:00",
      "identifier": [{"system": ORDER_NS, "value": "RFP-QHC-0014-1"}],
      "requisition": {"system": ORDER_NS, "value": "RFP-QHC-0014"},
      "code": {"coding": [{"system": "http://snomed.info/sct", "code": "840361000",
                           "display": "Plain X-ray of lumbar spine"}]}}
PATIENT = {"resourceType": "Patient", "id": "qhc-pat-13"}


def _bundle(*resources):
    return {"resourceType": "Bundle", "type": "searchset", "total": 1,
            "entry": [{"resource": r} for r in resources]}


@pytest.fixture
def client():
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _child(client):
    body = client.get("/api/tasks/by-org?org_identifier=8003621566684455", headers=HEADERS).get_json()
    [group] = body["groupTasks"]
    [child] = group["childTasks"]
    return child


def test_child_service_requests_are_requested_with_include_iterate(client, requests_mock):
    requests_mock.get(f"{BASE}/Task", json=_bundle(GROUP, CHILD, SR, PATIENT))

    child = _child(client)

    included = requests_mock.request_history[-1].qs
    assert included["_include:iterate"] == ["task:focus"]
    assert child["codeDisplay"] == "Plain X-ray of lumbar spine"
    assert child["authoredOn"] == "2026-08-12T10:15:00+10:00"


def test_child_service_requests_missing_from_the_search_are_fetched_in_one_call(client, requests_mock):
    # A server that ignores _include:iterate returns the child Task without its ServiceRequest.
    requests_mock.get(f"{BASE}/Task", json=_bundle(GROUP, CHILD, PATIENT))
    requests_mock.get(f"{BASE}/ServiceRequest", json=_bundle(SR))

    child = _child(client)

    sr_search = [r for r in requests_mock.request_history if r.path.endswith("/servicerequest")]
    assert [r.qs["_id"] for r in sr_search] == [["qhc-sr-0014"]]
    assert child["codeDisplay"] == "Plain X-ray of lumbar spine"


def test_placer_order_number_prefers_the_plac_typed_identifier(client, requests_mock):
    typed = {**SR, "identifier": [
        {"system": ORDER_NS, "value": "RFP-QHC-0014-1"},
        {"type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0203", "code": "PLAC"}]},
         "system": "http://myclinic.example.org.au/identifier", "value": "26-123456-1"}]}
    requests_mock.get(f"{BASE}/Task", json=_bundle(GROUP, CHILD, typed, PATIENT))

    assert _child(client)["placerOrderNumber"] == "26-123456-1"


def test_placer_order_number_falls_back_to_the_hpio_scoped_order_identifier(client, requests_mock):
    requests_mock.get(f"{BASE}/Task", json=_bundle(GROUP, CHILD, SR, PATIENT))

    assert _child(client)["placerOrderNumber"] == "RFP-QHC-0014-1"
