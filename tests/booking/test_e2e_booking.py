"""Live end-to-end booking run against a real FHIR server (opt-in).

Skipped unless FHIR_E2E_URL is set. Creates its own throwaway Organization, Location, Patient,
ServiceRequest and Tasks, walks the whole booking lifecycle, then deletes what it created.
Optional FHIR_E2E_USERNAME / FHIR_E2E_PASSWORD for Basic auth.

    FHIR_E2E_URL=https://my-test-server/fhir pytest tests/booking/test_e2e_booking.py -v -s
"""
import os
import uuid
from datetime import date, time, timedelta

import pytest
import requests

from booking import (IMAGING_SERVICE_TYPES, SERVICE_BOOKED, BookingClient,
                     build_propose_transaction)

E2E_URL = os.environ.get("FHIR_E2E_URL")
pytestmark = pytest.mark.skipif(not E2E_URL, reason="FHIR_E2E_URL not set")

CT = IMAGING_SERVICE_TYPES["310128004"]
TAG = {"system": "urn:e2e-booking", "code": uuid.uuid4().hex[:12]}


class Server:
    def __init__(self, base):
        self.base = base.rstrip("/")
        user, password = os.environ.get("FHIR_E2E_USERNAME"), os.environ.get("FHIR_E2E_PASSWORD")
        self.auth = (user, password) if user and password else None
        self.created = []

    def create(self, resource):
        resource = {**resource, "meta": {"tag": [TAG]}}
        response = requests.post(f"{self.base}/{resource['resourceType']}", json=resource,
                                 auth=self.auth, timeout=30)
        assert response.status_code in (200, 201), response.text
        created = response.json()
        self.created.append(f"{created['resourceType']}/{created['id']}")
        return created

    def read(self, ref):
        response = requests.get(f"{self.base}/{ref}", auth=self.auth, timeout=30)
        assert response.ok, response.text
        return response.json()

    def post_transaction(self, bundle):
        return requests.post(self.base, json=bundle, auth=self.auth, timeout=30)

    def delete(self, ref):
        requests.delete(f"{self.base}/{ref}", auth=self.auth, timeout=30)


def _next_weekday():
    day = date.today() + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


@pytest.fixture
def server():
    srv = Server(E2E_URL)
    yield srv
    # Newest first, so referencing resources (Appointments, Slots...) go before what they reference.
    for ref in reversed(srv.created):
        srv.delete(ref)


@pytest.fixture
def referral(server):
    """An accepted imaging request for a throwaway filler organisation."""
    org = server.create({"resourceType": "Organization", "active": True,
                         "name": f"E2E Imaging {TAG['code']}"})
    location = server.create({"resourceType": "Location", "status": "active",
                              "name": f"E2E Imaging Rooms {TAG['code']}",
                              "managingOrganization": {"reference": f"Organization/{org['id']}"}})
    patient = server.create({"resourceType": "Patient", "name": [{"family": "E2E", "given": ["Booking"]}]})
    service_request = server.create({
        "resourceType": "ServiceRequest", "status": "active", "intent": "order",
        "category": [{"coding": [{"system": "http://snomed.info/sct", "code": "363679005"}]}],
        "code": {"coding": [{"system": "http://snomed.info/sct", "code": "419394000",
                             "display": "Computed tomography of abdomen and pelvis"}]},
        "subject": {"reference": f"Patient/{patient['id']}"},
        "performer": [{"reference": f"Organization/{org['id']}"}],
    })
    group = server.create({"resourceType": "Task", "status": "accepted", "intent": "order",
                           "owner": {"reference": f"Organization/{org['id']}"}})
    task = server.create({"resourceType": "Task", "status": "accepted", "intent": "order",
                          "focus": {"reference": f"ServiceRequest/{service_request['id']}"},
                          "partOf": [{"reference": f"Task/{group['id']}"}],
                          "owner": {"reference": f"Organization/{org['id']}"}})
    return {"org": org, "location": location, "sr": service_request, "task": task, "group": group}


def test_full_booking_lifecycle(server, referral):
    client = BookingClient(server.base, auth=server.auth)
    day = _next_weekday()

    # Publish two 30-minute slots, then republish: nothing new.
    published = client.publish_availability(
        organization_id=referral["org"]["id"], location_id=referral["location"]["id"],
        service_type=CT, start_date=day, end_date=day,
        day_start=time(9, 0), day_end=time(10, 0), slot_minutes=30)
    assert published.ok, published.operation_outcome
    assert published.created_slots == 2
    republished = client.publish_availability(
        organization_id=referral["org"]["id"], location_id=referral["location"]["id"],
        service_type=CT, start_date=day, end_date=day,
        day_start=time(9, 0), day_end=time(10, 0), slot_minutes=30)
    assert (republished.created_slots, republished.skipped_slots) == (0, 2)
    _track_published(server, client, referral)

    # Search (chained schedule.actor) finds both free slots.
    search = client.free_slots(referral["sr"]["id"])
    assert search.ok, search.operation_outcome
    slot_a, slot_b = [slot for slot, _ in search.slots]
    stale_slot_a = server.read(f"Slot/{slot_a['id']}")

    # Propose slot A.
    proposed = client.propose(referral["sr"]["id"], slot_a["id"])
    assert proposed.ok, proposed.operation_outcome
    server.created.append(f"Appointment/{proposed.appointment_id}")
    assert server.read(f"Slot/{slot_a['id']}")["status"] == "busy-tentative"

    # A second referrer holding a stale copy of slot A is refused by If-Match.
    schedule = server.read(stale_slot_a["schedule"]["reference"])
    stale = server.post_transaction(build_propose_transaction(referral["sr"], stale_slot_a, schedule))
    assert stale.status_code in (409, 412), (
        f"server accepted a stale If-Match (HTTP {stale.status_code}); double-booking is possible")

    # Filler sees and confirms it.
    pending = client.pending_appointments(referral["org"]["id"])
    assert [p.appointment["id"] for p in pending] == [proposed.appointment_id]
    confirmed = client.confirm(proposed.appointment_id, patient_instruction="E2E: fast 4 hours")
    assert confirmed.ok, confirmed.operation_outcome
    assert server.read(f"Appointment/{proposed.appointment_id}")["status"] == "booked"
    assert server.read(f"Slot/{slot_a['id']}")["status"] == "busy"
    for ref in (f"Task/{referral['task']['id']}", f"Task/{referral['group']['id']}"):
        task = server.read(ref)
        assert task["status"] == "accepted"
        assert task["businessStatus"]["coding"][0]["code"] == SERVICE_BOOKED["coding"][0]["code"]

    # Reschedule into slot B atomically.
    rescheduled = client.reschedule(proposed.appointment_id, slot_b["id"])
    assert rescheduled.ok, rescheduled.operation_outcome
    assert rescheduled.appointment_id not in (None, proposed.appointment_id)
    server.created.append(f"Appointment/{rescheduled.appointment_id}")
    assert server.read(f"Appointment/{proposed.appointment_id}")["status"] == "cancelled"
    assert server.read(f"Slot/{slot_a['id']}")["status"] == "free"
    assert server.read(f"Slot/{slot_b['id']}")["status"] == "busy-tentative"
    assert "businessStatus" not in server.read(f"Task/{referral['task']['id']}")

    # Cancel the new proposal.
    cancelled = client.cancel(rescheduled.appointment_id, reason="E2E cleanup")
    assert cancelled.ok, cancelled.operation_outcome
    assert server.read(f"Slot/{slot_b['id']}")["status"] == "free"


def _track_published(server, client, referral):
    """Record the HealthcareService, Schedule and Slots publishing created, for teardown."""
    for service in client._services_of(referral["org"]["id"]):
        server.created.append(f"HealthcareService/{service['id']}")
        for schedule in client._search("Schedule", {"actor": f"HealthcareService/{service['id']}"}):
            server.created.append(f"Schedule/{schedule['id']}")
            for slot in client._search("Slot", {"schedule": f"Schedule/{schedule['id']}"}):
                server.created.append(f"Slot/{slot['id']}")
