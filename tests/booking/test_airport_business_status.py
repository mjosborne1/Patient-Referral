"""The airport board marks bookings with the AU business status the booking flow uses."""
from booking import SERVICE_BOOKED
from tests.booking.conftest import BASE, FHIR_HEADERS, searchset

GROUP = {"resourceType": "Task", "id": "g1", "status": "accepted"}
CHILD = {"resourceType": "Task", "id": "t1", "status": "accepted"}


def test_accepted_tasks_offer_service_booked(client):
    statuses = client.get("/api/business-statuses/accepted").get_json()["businessStatuses"]

    assert [(s["code"], s["display"]) for s in statuses] == [("service-booked", "Service booked")]


def test_marking_a_group_booked_writes_the_au_task_business_status_coding(client, fhir):
    fhir.get(f"{BASE}/Task/g1", json=GROUP)
    fhir.get(f"{BASE}/Task", json=searchset(CHILD))
    fhir.patch(f"{BASE}/Task/t1", json=CHILD)
    fhir.patch(f"{BASE}/Task/g1", json=GROUP)

    client.post("/api/task-groups/g1/business-status",
                data={"newBusinessStatus": "service-booked"}, headers=FHIR_HEADERS)

    patches = [r.json()[0]["value"] for r in fhir.request_history if r.method == "PATCH"]
    assert patches and all(p == {"coding": [{k: v for k, v in SERVICE_BOOKED["coding"][0].items()
                                             if k != "display"}]} for p in patches)
