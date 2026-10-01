"""Behaviour of the transaction Bundle that publishes filler availability."""
from datetime import date, time

from booking import build_publish_transaction, generate_slot_times

CT_SERVICE = {"system": "http://snomed.info/sct", "code": "310128004",
              "display": "Computed tomography service"}
HCS = "HealthcareService/healthcareservice-northside-ct"
LOC = "Location/location-northside-imaging-chermside"


def _times():
    return generate_slot_times(date(2026, 10, 6), date(2026, 10, 6),
                               day_start=time(9, 0), day_end=time(10, 0), slot_minutes=30)


def _resources(bundle, resource_type):
    return [e for e in bundle["entry"] if e["resource"]["resourceType"] == resource_type]


def test_new_schedule_is_created_with_a_free_slot_for_each_time():
    bundle = build_publish_transaction(healthcare_service_ref=HCS, location_ref=LOC,
                                       service_type=CT_SERVICE, slot_times=_times())

    assert bundle["resourceType"] == "Bundle" and bundle["type"] == "transaction"
    [schedule_entry] = _resources(bundle, "Schedule")
    schedule = schedule_entry["resource"]
    assert schedule_entry["request"] == {"method": "POST", "url": "Schedule"}
    assert schedule["active"] is True
    assert [a["reference"] for a in schedule["actor"]] == [HCS, LOC]
    assert schedule["serviceType"] == [{"coding": [CT_SERVICE]}]

    slots = [e["resource"] for e in _resources(bundle, "Slot")]
    assert [(s["start"], s["end"]) for s in slots] == [
        ("2026-10-06T09:00:00+10:00", "2026-10-06T09:30:00+10:00"),
        ("2026-10-06T09:30:00+10:00", "2026-10-06T10:00:00+10:00"),
    ]
    assert all(s["status"] == "free" for s in slots)
    assert all(s["serviceType"] == [{"coding": [CT_SERVICE]}] for s in slots)
    assert all(s["schedule"] == {"reference": schedule_entry["fullUrl"]} for s in slots)
    assert schedule_entry["fullUrl"].startswith("urn:uuid:")


def test_republishing_onto_existing_schedule_skips_already_published_starts():
    existing_schedule = {"resourceType": "Schedule", "id": "schedule-northside-ct"}
    # Servers may hand back instants normalised to UTC; 09:00+10:00 == 23:00Z the day before.
    already_published = ["2026-10-05T23:00:00Z"]

    bundle = build_publish_transaction(healthcare_service_ref=HCS, location_ref=LOC,
                                       service_type=CT_SERVICE, slot_times=_times(),
                                       schedule=existing_schedule,
                                       existing_starts=already_published)

    assert _resources(bundle, "Schedule") == []
    slots = [e["resource"] for e in _resources(bundle, "Slot")]
    assert [s["start"] for s in slots] == ["2026-10-06T09:30:00+10:00"]
    assert slots[0]["schedule"] == {"reference": "Schedule/schedule-northside-ct"}


IG = "http://aehrc.csiro.au/fhir/radiology-referral/StructureDefinition/"


def test_ig_profiles_are_claimed_by_default_and_can_be_turned_off():
    claimed = build_publish_transaction(healthcare_service_ref=HCS, location_ref=LOC,
                                        service_type=CT_SERVICE, slot_times=_times())
    unclaimed = build_publish_transaction(healthcare_service_ref=HCS, location_ref=LOC,
                                          service_type=CT_SERVICE, slot_times=_times(),
                                          claim_profiles=False)

    profiles = {e["resource"]["resourceType"]: e["resource"]["meta"]["profile"]
                for e in claimed["entry"]}
    assert profiles == {"Schedule": [IG + "booking-schedule"], "Slot": [IG + "booking-slot"]}
    assert all("meta" not in e["resource"] for e in unclaimed["entry"])
