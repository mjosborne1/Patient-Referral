import pytest

BASE = "https://fhir.test/fhir"


def searchset(*resources):
    return {"resourceType": "Bundle", "type": "searchset", "total": len(resources),
            "entry": [{"resource": r} for r in resources]}


def transaction_response(n):
    return {"resourceType": "Bundle", "type": "transaction-response",
            "entry": [{"response": {"status": "201 Created"}} for _ in range(n)]}


@pytest.fixture
def fhir(requests_mock):
    """A fake FHIR server at BASE; register responses on it per test."""
    return requests_mock


@pytest.fixture
def client():
    import os
    os.environ["TESTING"] = "true"
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


FHIR_HEADERS = {"X-FHIR-Server-URL": BASE}


# IG-example-shaped resources as the server returns them (server ids, versionIds).
SERVICE_REQUEST = {
    "resourceType": "ServiceRequest", "id": "sr-ct-1", "status": "active", "intent": "order",
    "category": [{"coding": [{"system": "http://snomed.info/sct", "code": "363679005",
                              "display": "Imaging"}]}],
    "code": {"coding": [{"system": "http://snomed.info/sct", "code": "419394000",
                         "display": "Computed tomography of abdomen and pelvis"}],
             "text": "CT Abdo/Pelvis"},
    "subject": {"reference": "Patient/pat-1"},
    "requester": {"reference": "PractitionerRole/pr-gp-1"},
    "performer": [{"reference": "Organization/organization-northside-imaging"}],
    "reasonCode": [{"text": "RUQ pain"}],
}
SCHEDULE = {
    "resourceType": "Schedule", "id": "schedule-northside-ct",
    "actor": [{"reference": "HealthcareService/healthcareservice-northside-ct"},
              {"reference": "Location/location-northside-imaging-chermside"}],
}
SLOT = {
    "resourceType": "Slot", "id": "slot-0930", "meta": {"versionId": "3"},
    "schedule": {"reference": "Schedule/schedule-northside-ct"},
    "serviceType": [{"coding": [{"system": "http://snomed.info/sct", "code": "310128004",
                                 "display": "Computed tomography service"}]}],
    "status": "free",
    "start": "2026-10-06T09:30:00+10:00", "end": "2026-10-06T10:00:00+10:00",
}
PROPOSED_APPOINTMENT = {
    "resourceType": "Appointment", "id": "appt-9", "meta": {"versionId": "1"},
    "status": "proposed",
    "slot": [{"reference": "Slot/slot-0930"}],
    "basedOn": [{"reference": "ServiceRequest/sr-ct-1"}],
    "start": "2026-10-06T09:30:00+10:00", "end": "2026-10-06T10:00:00+10:00",
    "participant": [
        {"actor": {"reference": "Patient/pat-1"}, "required": "required", "status": "accepted"},
        {"actor": {"reference": "HealthcareService/healthcareservice-northside-ct"},
         "required": "required", "status": "needs-action"},
        {"actor": {"reference": "Location/location-northside-imaging-chermside"},
         "required": "required", "status": "needs-action"},
        {"actor": {"reference": "PractitionerRole/pr-gp-1"}, "required": "information-only",
         "status": "accepted"},
    ],
}
HELD_SLOT = {**SLOT, "meta": {"versionId": "4"}, "status": "busy-tentative"}
FULFILMENT_TASK = {
    "resourceType": "Task", "id": "task-1", "meta": {"versionId": "2"}, "status": "accepted",
    "intent": "order", "focus": {"reference": "ServiceRequest/sr-ct-1"},
    "partOf": [{"reference": "Task/task-group-1"}],
}
GROUP_TASK = {"resourceType": "Task", "id": "task-group-1", "meta": {"versionId": "5"},
              "status": "accepted", "intent": "order"}
