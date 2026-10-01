"""Behaviour of the referrer's propose transaction (Appointment proposed + Slot held)."""
from booking import build_propose_transaction
from tests.booking.conftest import SCHEDULE, SERVICE_REQUEST, SLOT


def _by_type(bundle):
    return {e["resource"]["resourceType"]: e for e in bundle["entry"]}


def test_propose_creates_a_proposed_appointment_for_the_slot_and_request():
    bundle = build_propose_transaction(SERVICE_REQUEST, SLOT, SCHEDULE)

    assert bundle["type"] == "transaction"
    entry = _by_type(bundle)["Appointment"]
    appt = entry["resource"]
    assert entry["request"] == {"method": "POST", "url": "Appointment"}
    assert appt["status"] == "proposed"
    assert appt["basedOn"] == [{"reference": "ServiceRequest/sr-ct-1"}]
    assert appt["slot"] == [{"reference": "Slot/slot-0930"}]
    assert (appt["start"], appt["end"]) == (SLOT["start"], SLOT["end"])
    assert appt["serviceType"] == SLOT["serviceType"]
    assert appt["reasonCode"] == [{"text": "RUQ pain"}]
    assert appt["identifier"][0]["value"].startswith("urn:uuid:")
    assert "created" in appt


def test_proposed_appointment_participants_await_the_filler():
    appt = _by_type(build_propose_transaction(SERVICE_REQUEST, SLOT, SCHEDULE))["Appointment"]["resource"]

    assert [(p["actor"]["reference"], p["required"], p["status"]) for p in appt["participant"]] == [
        ("Patient/pat-1", "required", "accepted"),
        ("HealthcareService/healthcareservice-northside-ct", "required", "needs-action"),
        ("Location/location-northside-imaging-chermside", "required", "needs-action"),
        ("PractitionerRole/pr-gp-1", "information-only", "accepted"),
    ]


def test_propose_holds_the_slot_only_if_it_is_unchanged_since_it_was_read():
    entry = _by_type(build_propose_transaction(SERVICE_REQUEST, SLOT, SCHEDULE))["Slot"]

    assert entry["request"] == {"method": "PUT", "url": "Slot/slot-0930", "ifMatch": 'W/"3"'}
    assert entry["resource"]["status"] == "busy-tentative"
    assert "meta" not in entry["resource"] or "versionId" not in entry["resource"]["meta"]


def test_appointment_claims_the_referral_appointment_profile_unless_disabled():
    claimed = _by_type(build_propose_transaction(SERVICE_REQUEST, SLOT, SCHEDULE))
    plain = _by_type(build_propose_transaction(SERVICE_REQUEST, SLOT, SCHEDULE, claim_profiles=False))

    assert claimed["Appointment"]["resource"]["meta"]["profile"] == [
        "http://aehrc.csiro.au/fhir/radiology-referral/StructureDefinition/referral-appointment"]
    assert "meta" not in plain["Appointment"]["resource"]
