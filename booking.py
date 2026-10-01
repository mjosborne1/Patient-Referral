"""
Appointment booking for imaging requests (Radiology Referral IG).

Pure builders for Schedule / Slot / Appointment resources and the transaction
Bundles that move them through the booking lifecycle, plus a thin client that
is the only part that talks to the FHIR server.
"""
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import requests

DEFAULT_TIMEZONE = "Australia/Brisbane"
IG_PROFILE_BASE = "http://aehrc.csiro.au/fhir/radiology-referral/StructureDefinition/"
PROFILE_SCHEDULE = IG_PROFILE_BASE + "booking-schedule"
PROFILE_SLOT = IG_PROFILE_BASE + "booking-slot"
PROFILE_APPOINTMENT = IG_PROFILE_BASE + "referral-appointment"

SNOMED = "http://snomed.info/sct"
# Imaging HealthcareService.type / Slot.serviceType choices, keyed by SNOMED code.
IMAGING_SERVICE_TYPES = {
    code: {"system": SNOMED, "code": code, "display": display}
    for code, display in [
        ("310128004", "Computed tomography service"),
        ("310127009", "Magnetic resonance imaging service"),
        ("310169008", "Ultrasound service"),
        ("933537131000036109", "X-ray service"),
        ("788009005", "Nuclear medicine service"),
    ]
}


def generate_slot_times(start_date: date, end_date: date, *, day_start: time, day_end: time,
                        slot_minutes: int, weekdays=(0, 1, 2, 3, 4), tz: str = DEFAULT_TIMEZONE):
    """Return (start, end) timezone-aware datetimes for each whole slot in the range (inclusive).

    weekdays uses date.weekday() numbering (Monday = 0); weekends are skipped by default.
    """
    zone = ZoneInfo(tz)
    length = timedelta(minutes=slot_minutes)
    slots = []
    day = start_date
    while day <= end_date:
        if day.weekday() in weekdays:
            start = datetime.combine(day, day_start, zone)
            close = datetime.combine(day, day_end, zone)
            while start + length <= close:
                slots.append((start, start + length))
                start += length
        day += timedelta(days=1)
    return slots


def _urn():
    return f"urn:uuid:{uuid.uuid4()}"


def _with_profile(resource, profile, claim_profiles):
    if claim_profiles:
        return {"resourceType": resource["resourceType"], "meta": {"profile": [profile]},
                **{k: v for k, v in resource.items() if k != "resourceType"}}
    return resource


def _entry(resource, method, url):
    return {"fullUrl": _urn(), "resource": resource,
            "request": {"method": method, "url": url}}


def _instant(value):
    """Parse a FHIR instant (including a trailing Z) so equal instants compare equal."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def build_publish_transaction(*, healthcare_service_ref, location_ref, service_type, slot_times,
                              schedule=None, existing_starts=(), claim_profiles=True):
    """Transaction publishing a free Slot per (start, end) not already in existing_starts.

    With no existing schedule, a new Schedule for the service/location is created in the same
    transaction; otherwise the Slots reference the given Schedule resource.
    """
    service_types = [{"coding": [service_type]}]
    entries = []
    if schedule is None:
        schedule_entry = _entry(_with_profile({
            "resourceType": "Schedule",
            "active": True,
            "serviceType": service_types,
            "actor": [{"reference": healthcare_service_ref}, {"reference": location_ref}],
        }, PROFILE_SCHEDULE, claim_profiles), "POST", "Schedule")
        entries.append(schedule_entry)
        schedule_ref = schedule_entry["fullUrl"]
    else:
        schedule_ref = f"Schedule/{schedule['id']}"
    published = {_instant(s) for s in existing_starts}
    for start, end in slot_times:
        if start in published:
            continue
        slot = {
            "resourceType": "Slot",
            "serviceType": service_types,
            "schedule": {"reference": schedule_ref},
            "status": "free",
            "start": start.isoformat(),
            "end": end.isoformat(),
        }
        entries.append(_entry(_with_profile(slot, PROFILE_SLOT, claim_profiles), "POST", "Slot"))
    return {"resourceType": "Bundle", "type": "transaction", "entry": entries}


def _token(coding):
    return f"{coding['system']}|{coding['code']}"


def _operation_outcome(response):
    """The OperationOutcome a failed response carries, or one synthesised from its status."""
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and body.get("resourceType") == "OperationOutcome":
        return body
    return {"resourceType": "OperationOutcome", "issue": [{
        "severity": "error", "code": "exception",
        "diagnostics": f"HTTP {response.status_code}: {response.text[:500]}"}]}


class FhirError(Exception):
    """A FHIR interaction failed; carries the server's (or a synthesised) OperationOutcome."""

    def __init__(self, response):
        self.operation_outcome = _operation_outcome(response)
        super().__init__(f"HTTP {response.status_code}")


@dataclass
class PublishResult:
    ok: bool
    created_slots: int = 0
    skipped_slots: int = 0
    operation_outcome: dict | None = None


class BookingClient:
    """Thin FHIR client for booking; the only part of this module that does I/O."""

    def __init__(self, base_url, auth=None, bearer=None, verify=True, timeout=30):
        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self.headers = {"Accept": "application/fhir+json"}
        if bearer:
            self.headers["Authorization"] = f"Bearer {bearer}"
            self.auth = None
        self.verify = verify
        self.timeout = timeout

    def _request(self, method, path="", **kwargs):
        url = f"{self.base_url}/{path}" if path else self.base_url
        return requests.request(method, url, auth=self.auth, headers=self.headers,
                                verify=self.verify, timeout=self.timeout, **kwargs)

    def _search(self, resource_type, params):
        response = self._request("GET", resource_type, params=params)
        if not response.ok:
            raise FhirError(response)
        return [e["resource"] for e in response.json().get("entry", [])
                if e.get("resource", {}).get("resourceType") == resource_type]

    def locations_for_organization(self, organization_id):
        return self._search("Location", {"organization": organization_id})

    def _find_or_create_healthcare_service(self, organization_id, location_id, service_type):
        found = self._search("HealthcareService", {"organization": organization_id,
                                                   "service-type": _token(service_type)})
        if found:
            return found[0], False
        response = self._request("POST", "HealthcareService", json={
            "resourceType": "HealthcareService",
            "active": True,
            "providedBy": {"reference": f"Organization/{organization_id}"},
            "type": [{"coding": [service_type]}],
            "name": service_type.get("display"),
            "location": [{"reference": f"Location/{location_id}"}],
        })
        if not response.ok:
            raise FhirError(response)
        return response.json(), True

    def publish_availability(self, **kwargs):
        """Find or create the HealthcareService, then publish free Slots on its Schedule."""
        try:
            return self._publish_availability(**kwargs)
        except FhirError as error:
            return PublishResult(ok=False, operation_outcome=error.operation_outcome)

    def _publish_availability(self, *, organization_id, location_id, service_type, start_date,
                              end_date, day_start, day_end, slot_minutes, claim_profiles=True):
        service, service_is_new = self._find_or_create_healthcare_service(
            organization_id, location_id, service_type)
        service_ref = f"HealthcareService/{service['id']}"
        slot_times = generate_slot_times(start_date, end_date, day_start=day_start,
                                         day_end=day_end, slot_minutes=slot_minutes)
        if not slot_times:
            return PublishResult(ok=True)

        schedule, existing_starts = None, []
        schedules = [] if service_is_new else self._search(
            "Schedule", {"actor": service_ref, "service-type": _token(service_type)})
        if schedules:
            schedule = schedules[0]
            existing_starts = [slot["start"] for slot in self._search("Slot", [
                ("schedule", f"Schedule/{schedule['id']}"),
                ("start", f"ge{slot_times[0][0].isoformat()}"),
                ("start", f"lt{slot_times[-1][1].isoformat()}"),
                ("_count", "1000"),
            ])]

        bundle = build_publish_transaction(
            healthcare_service_ref=service_ref, location_ref=f"Location/{location_id}",
            service_type=service_type, slot_times=slot_times, schedule=schedule,
            existing_starts=existing_starts, claim_profiles=claim_profiles)
        created = sum(1 for e in bundle["entry"] if e["resource"]["resourceType"] == "Slot")
        if created:
            response = self._request("POST", json=bundle)
            if not response.ok:
                raise FhirError(response)
        return PublishResult(ok=True, created_slots=created,
                             skipped_slots=len(slot_times) - created)
