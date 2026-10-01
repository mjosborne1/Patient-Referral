"""
Appointment booking for imaging requests (Radiology Referral IG).

Pure builders for Schedule / Slot / Appointment resources and the transaction
Bundles that move them through the booking lifecycle, plus a thin client that
is the only part that talks to the FHIR server.
"""
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import requests

DEFAULT_TIMEZONE = "Australia/Brisbane"
IG_PROFILE_BASE = "http://aehrc.csiro.au/fhir/radiology-referral/StructureDefinition/"
PROFILE_SCHEDULE = IG_PROFILE_BASE + "booking-schedule"
PROFILE_SLOT = IG_PROFILE_BASE + "booking-slot"
PROFILE_APPOINTMENT = IG_PROFILE_BASE + "referral-appointment"

SNOMED = "http://snomed.info/sct"
IMAGING_CATEGORY = f"{SNOMED}|363679005"
SERVICE_BOOKED = {"coding": [{
    "system": "http://terminology.hl7.org.au/CodeSystem/task-business-status",
    "code": "service-booked", "display": "Service booked"}]}
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


# Modality keywords in ServiceRequest.code display/text -> imaging service type. A keyword match
# is enough for the demo order sets; SNOMED subsumption would be the rigorous alternative.
_MODALITY_PATTERNS = [
    (re.compile(r"\bcomputed tomography\b|\bct\b", re.I), "310128004"),
    (re.compile(r"\bmagnetic resonance\b|\bmri?\b", re.I), "310127009"),
    (re.compile(r"\bultrasound\b|\bultrasonography\b|\bus\b", re.I), "310169008"),
    (re.compile(r"x-ray|\bradiograph", re.I), "933537131000036109"),
    (re.compile(r"\bnuclear\b|scintigraph|\bpet\b", re.I), "788009005"),
]


def service_type_for(service_request):
    """The imaging service type Coding for a ServiceRequest's procedure, or None if unknown."""
    code = service_request.get("code", {})
    terms = [c.get("display", "") for c in code.get("coding", [])] + [code.get("text", "")]
    for term in filter(None, terms):
        for pattern, service_code in _MODALITY_PATTERNS:
            if pattern.search(term):
                return IMAGING_SERVICE_TYPES[service_code]
    return None


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


ACTIVE_APPOINTMENT_STATUSES = {"proposed", "pending", "booked"}


def active_appointment(appointments):
    return next((a for a in appointments if a.get("status") in ACTIVE_APPOINTMENT_STATUSES), None)


def is_bookable(task, appointments):
    """An imaging request is bookable once its Task is accepted and nothing is booked or pending."""
    return bool(task) and task.get("status") == "accepted" and not active_appointment(appointments)


def _ref(resource):
    return f"{resource['resourceType']}/{resource['id']}"


def _for_update(resource, **changes):
    """Copy of a server resource for PUT: server-managed meta dropped, profile claims kept."""
    updated = {k: v for k, v in resource.items() if k != "meta"}
    profiles = resource.get("meta", {}).get("profile")
    if profiles:
        updated["meta"] = {"profile": profiles}
    updated.update(changes)
    return updated


def _update_entry(resource, **changes):
    """Transaction PUT of a changed server resource, guarded by If-Match on the version read."""
    request = {"method": "PUT", "url": _ref(resource)}
    version = resource.get("meta", {}).get("versionId")
    if version:
        request["ifMatch"] = f'W/"{version}"'
    return {"fullUrl": _urn(), "resource": _for_update(resource, **changes), "request": request}


def _schedule_actor(schedule, resource_type):
    return next((a for a in schedule.get("actor", [])
                 if a.get("reference", "").startswith(f"{resource_type}/")), None)


def build_appointment(service_request, slot, schedule, *, status, claim_profiles=True):
    """A referral Appointment for the request in the given Slot (participants per the design)."""
    participants = [{"actor": service_request["subject"], "required": "required",
                     "status": "accepted"}]
    for resource_type in ("HealthcareService", "Location"):
        actor = _schedule_actor(schedule, resource_type)
        if actor:
            participants.append({"actor": actor, "required": "required",
                                 "status": "accepted" if status == "booked" else "needs-action"})
    if service_request.get("requester"):
        participants.append({"actor": service_request["requester"],
                             "required": "information-only", "status": "accepted"})
    appointment = {
        "resourceType": "Appointment",
        "identifier": [{"system": "urn:ietf:rfc:3986", "value": _urn()}],
        "status": status,
        "serviceType": slot.get("serviceType", []),
        "start": slot["start"],
        "end": slot["end"],
        "created": datetime.now(ZoneInfo(DEFAULT_TIMEZONE)).isoformat(timespec="seconds"),
        "slot": [{"reference": _ref(slot)}],
        "basedOn": [{"reference": _ref(service_request)}],
        "participant": participants,
    }
    for reason in ("reasonCode", "reasonReference"):
        if service_request.get(reason):
            appointment[reason] = service_request[reason]
    return _with_profile(appointment, PROFILE_APPOINTMENT, claim_profiles)


def build_propose_transaction(service_request, slot, schedule, *, claim_profiles=True):
    """Referrer's booking request: POST a proposed Appointment and hold the Slot tentatively."""
    appointment = build_appointment(service_request, slot, schedule, status="proposed",
                                    claim_profiles=claim_profiles)
    return {"resourceType": "Bundle", "type": "transaction", "entry": [
        _entry(appointment, "POST", "Appointment"),
        _update_entry(slot, status="busy-tentative"),
    ]}


SLOT_SEARCH_DAYS = 14


def _parse_fhir_datetime(value, tz, *, end_of_day=False):
    """Parse a FHIR date or dateTime; a bare date is the start (or end) of that local day."""
    if len(value) == 10:
        day = date.fromisoformat(value) + (timedelta(days=1) if end_of_day else timedelta())
        return datetime.combine(day, time(0), tz)
    return _instant(value)


def slot_search_window(service_request, now):
    """(start, end) to search for free Slots: the requested occurrence period, or a fortnight."""
    period = service_request.get("occurrencePeriod", {})
    start = now
    if period.get("start"):
        start = max(now, _parse_fhir_datetime(period["start"], now.tzinfo))
    if period.get("end"):
        end = _parse_fhir_datetime(period["end"], now.tzinfo, end_of_day=True)
    else:
        end = start + timedelta(days=SLOT_SEARCH_DAYS)
    return start, end



@dataclass
class RequestRow:
    service_request: dict
    task: dict | None
    appointment: dict | None  # the active Appointment, else the most recent one
    state: str  # awaiting-triage | rejected | bookable | proposed | booked | declined | cancelled | closed
    bookable: bool
    patient: dict | None = None


def _declined(appointment):
    return any(p.get("status") == "declined" for p in appointment.get("participant", []))


def _booking_state(task, appointment):
    task_status = (task or {}).get("status")
    if appointment and appointment["status"] in ACTIVE_APPOINTMENT_STATUSES:
        return "booked" if appointment["status"] == "booked" else "proposed"
    if task_status in (None, "draft", "requested", "received", "on-hold"):
        return "awaiting-triage"
    if task_status == "rejected":
        return "rejected"
    if task_status != "accepted":
        return "closed"
    if appointment and appointment["status"] == "cancelled":
        return "declined" if _declined(appointment) else "cancelled"
    return "bookable"


def imaging_request_rows(searchset):
    """Panel rows from a ServiceRequest search with Task:focus and Appointment:based-on revincludes."""
    resources = [e.get("resource", {}) for e in searchset.get("entry", [])]
    service_requests = [r for r in resources if r.get("resourceType") == "ServiceRequest"]
    rows = []
    for service_request in service_requests:
        ref = _ref(service_request)
        task = next((r for r in resources if r.get("resourceType") == "Task"
                     and r.get("focus", {}).get("reference") == ref), None)
        appointments = sorted(
            (r for r in resources if r.get("resourceType") == "Appointment"
             and any(b.get("reference") == ref for b in r.get("basedOn", []))),
            key=lambda a: a.get("created", ""), reverse=True)
        appointment = active_appointment(appointments) or next(iter(appointments), None)
        patient = next((r for r in resources if r.get("resourceType") == "Patient"
                        and _ref(r) == service_request.get("subject", {}).get("reference")), None)
        rows.append(RequestRow(service_request, task, appointment,
                               _booking_state(task, appointment),
                               is_bookable(task, appointments), patient))
    return rows



def _participants_with(appointment, status_for):
    """Copy of the Appointment's participants with status replaced where status_for returns one."""
    return [{**p, "status": status_for(p) or p.get("status")}
            for p in appointment.get("participant", [])]


def _service_booked_entries(task, group_task):
    return [_update_entry(t, businessStatus=SERVICE_BOOKED) for t in (task, group_task) if t]


def build_confirm_transaction(appointment, slot, task, group_task, *, patient_instruction=None):
    """Filler confirms: Appointment booked, Slot busy, Tasks stay accepted but service-booked."""
    appointment_changes = {
        "status": "booked",
        "participant": _participants_with(appointment, lambda p: "accepted"),
    }
    if patient_instruction:
        appointment_changes["patientInstruction"] = patient_instruction
    entries = [_update_entry(appointment, **appointment_changes),
               _update_entry(slot, status="busy")]
    entries += _service_booked_entries(task, group_task)
    return {"resourceType": "Bundle", "type": "transaction", "entry": entries}


def build_decline_transaction(appointment, slot, *, reason):
    """Filler declines a proposed Appointment: cancelled with a reason, and the Slot freed."""
    return {"resourceType": "Bundle", "type": "transaction", "entry": [
        _update_entry(appointment, status="cancelled", cancelationReason={"text": reason},
                      participant=_participants_with(
                          appointment,
                          lambda p: "declined" if p["actor"]["reference"].startswith(
                              "HealthcareService/") else None)),
        _update_entry(slot, status="free"),
    ]}



def build_direct_book_transaction(service_request, slot, schedule, task, group_task, *,
                                  patient_instruction=None, claim_profiles=True):
    """Filler books a free Slot outright: booked Appointment, Slot busy, Tasks service-booked."""
    appointment = build_appointment(service_request, slot, schedule, status="booked",
                                    claim_profiles=claim_profiles)
    if patient_instruction:
        appointment["patientInstruction"] = patient_instruction
    entries = [_entry(appointment, "POST", "Appointment"), _update_entry(slot, status="busy")]
    entries += _service_booked_entries(task, group_task)
    return {"resourceType": "Bundle", "type": "transaction", "entry": entries}


# ── FHIR server I/O ─────────────────────────────────────────────────────────

def _created_id(transaction_response, resource_type):
    """Id of the first resource of resource_type created or updated in a transaction response."""
    for entry in transaction_response.get("entry", []):
        location = entry.get("response", {}).get("location", "")
        parts = location.split("/")
        if resource_type in parts:
            return parts[parts.index(resource_type) + 1]
    return None


class FhirError(Exception):
    """A FHIR interaction failed; carries the server's (or a synthesised) OperationOutcome."""

    def __init__(self, response):
        self.status_code = response.status_code
        self.operation_outcome = _operation_outcome(response)
        super().__init__(f"HTTP {response.status_code}")


@dataclass
class SlotSearchResult:
    ok: bool
    service_request: dict | None = None
    slots: list = field(default_factory=list)  # [(slot, schedule)] ordered by start
    operation_outcome: dict | None = None


@dataclass
class BookingResult:
    ok: bool
    conflict: bool = False  # the Slot was taken (or changed) since it was offered
    appointment_id: str | None = None
    operation_outcome: dict | None = None


@dataclass
class PendingBooking:
    appointment: dict
    patient: dict | None
    service_request: dict | None


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

    def _read(self, resource_type, resource_id):
        response = self._request("GET", f"{resource_type}/{resource_id}")
        if not response.ok:
            raise FhirError(response)
        return response.json()

    def free_slots(self, service_request_id, *, now=None, start=None, end=None):
        """Free Slots offered by the request's performer for its imaging service, by start time."""
        try:
            service_request = self._read("ServiceRequest", service_request_id)
            now = now or datetime.now(ZoneInfo(DEFAULT_TIMEZONE))
            default_start, default_end = slot_search_window(service_request, now)
            return SlotSearchResult(ok=True, service_request=service_request,
                                    slots=self._free_slots(service_request, start or default_start,
                                                           end or default_end))
        except FhirError as error:
            return SlotSearchResult(ok=False, operation_outcome=error.operation_outcome)

    def _free_slots(self, service_request, start, end):
        organizations = [p["reference"].split("/", 1)[1] for p in service_request.get("performer", [])
                         if p.get("reference", "").startswith("Organization/")]
        if not organizations:
            return []
        params = {"organization": ",".join(organizations)}
        service_type = service_type_for(service_request)
        if service_type:
            params["service-type"] = _token(service_type)
        services = self._search("HealthcareService", params)
        if not services:
            return []
        response = self._request("GET", "Slot", params=[
            ("schedule.actor", ",".join(_ref(s) for s in services)),
            ("status", "free"),
            ("start", f"ge{start.isoformat()}"),
            ("start", f"lt{end.isoformat()}"),
            ("_include", "Slot:schedule"),
            ("_sort", "start"),
            ("_count", "100"),
        ])
        if not response.ok:
            raise FhirError(response)
        resources = [e.get("resource", {}) for e in response.json().get("entry", [])]
        schedules = {_ref(r): r for r in resources if r.get("resourceType") == "Schedule"}
        return [(r, schedules.get(r["schedule"]["reference"], {}))
                for r in resources if r.get("resourceType") == "Slot"]

    def _transact(self, bundle):
        """POST a transaction; return the response Bundle or raise FhirError."""
        response = self._request("POST", json=bundle)
        if not response.ok:
            raise FhirError(response)
        return response.json()

    def _booking(self, action):
        """Run a booking action, mapping version conflicts and server errors to a BookingResult."""
        try:
            return action()
        except FhirError as error:
            return BookingResult(ok=False, conflict=error.status_code in (409, 412),
                                 operation_outcome=error.operation_outcome)

    def propose(self, service_request_id, slot_id, *, claim_profiles=True):
        """Referrer proposes an Appointment in a free Slot, holding the Slot as busy-tentative."""
        def action():
            service_request = self._read("ServiceRequest", service_request_id)
            slot = self._read("Slot", slot_id)
            if slot.get("status") != "free":
                return BookingResult(ok=False, conflict=True)
            schedule = self._read("Schedule", slot["schedule"]["reference"].split("/", 1)[1])
            response = self._transact(build_propose_transaction(
                service_request, slot, schedule, claim_profiles=claim_profiles))
            return BookingResult(ok=True, appointment_id=_created_id(response, "Appointment"))
        return self._booking(action)

    def patient_imaging_requests(self, patient_id):
        """Panel rows for the patient's imaging ServiceRequests, newest first."""
        response = self._request("GET", "ServiceRequest", params=[
            ("subject", f"Patient/{patient_id}"),
            ("category", IMAGING_CATEGORY),
            ("_revinclude", "Task:focus"),
            ("_revinclude", "Appointment:based-on"),
            ("_sort", "-authored"),
            ("_count", "50"),
        ])
        if not response.ok:
            raise FhirError(response)
        return imaging_request_rows(response.json())

    def _services_of(self, organization_id):
        return self._search("HealthcareService", {"organization": organization_id})

    def pending_appointments(self, organization_id):
        """Proposed Appointments awaiting the organisation's confirmation, earliest first."""
        services = self._services_of(organization_id)
        if not services:
            return []
        response = self._request("GET", "Appointment", params=[
            ("actor", ",".join(_ref(s) for s in services)),
            ("status", "proposed"),
            ("_include", "Appointment:patient"),
            ("_include", "Appointment:based-on"),
            ("_sort", "date"),
            ("_count", "100"),
        ])
        if not response.ok:
            raise FhirError(response)
        resources = [e.get("resource", {}) for e in response.json().get("entry", [])]
        by_ref = {_ref(r): r for r in resources if r.get("id")}
        pending = []
        for appointment in (r for r in resources if r.get("resourceType") == "Appointment"):
            patient = next((by_ref.get(p["actor"]["reference"]) for p in appointment["participant"]
                            if p.get("actor", {}).get("reference", "").startswith("Patient/")), None)
            based_on = next(iter(appointment.get("basedOn", [])), {}).get("reference")
            pending.append(PendingBooking(appointment, patient, by_ref.get(based_on)))
        return pending

    def _proposed_booking(self, appointment_id):
        """The Appointment and its Slot as stored, or None if it is no longer awaiting the filler."""
        appointment = self._read("Appointment", appointment_id)
        slot = self._read("Slot", appointment["slot"][0]["reference"].split("/", 1)[1])
        if appointment.get("status") not in ("proposed", "pending"):
            return None
        return appointment, slot

    def _tasks_for(self, service_request_ref):
        """The fulfilment Task for the ServiceRequest and its group Task."""
        tasks = self._search("Task", {"focus": service_request_ref})
        task = next((t for t in tasks if t.get("partOf")), next(iter(tasks), None))
        group_task = None
        if task and task.get("partOf"):
            group_task = self._read("Task", task["partOf"][0]["reference"].split("/", 1)[1])
        return task, group_task

    def confirm(self, appointment_id, *, patient_instruction=None):
        """Filler confirms a proposed Appointment (booked, Slot busy, Tasks service-booked)."""
        def action():
            booking = self._proposed_booking(appointment_id)
            if booking is None:
                return BookingResult(ok=False, conflict=True)
            appointment, slot = booking
            task, group_task = self._tasks_for(appointment["basedOn"][0]["reference"])
            self._transact(build_confirm_transaction(appointment, slot, task, group_task,
                                                     patient_instruction=patient_instruction))
            return BookingResult(ok=True, appointment_id=appointment_id)
        return self._booking(action)

    def decline(self, appointment_id, *, reason):
        """Filler declines a proposed Appointment (cancelled with reason, Slot freed)."""
        def action():
            booking = self._proposed_booking(appointment_id)
            if booking is None:
                return BookingResult(ok=False, conflict=True)
            appointment, slot = booking
            self._transact(build_decline_transaction(appointment, slot, reason=reason))
            return BookingResult(ok=True, appointment_id=appointment_id)
        return self._booking(action)

    def unbooked_requests(self, organization_id):
        """The organisation's accepted imaging requests that have no active Appointment."""
        response = self._request("GET", "ServiceRequest", params=[
            ("performer", f"Organization/{organization_id}"),
            ("category", IMAGING_CATEGORY),
            ("_include", "ServiceRequest:patient"),
            ("_revinclude", "Task:focus"),
            ("_revinclude", "Appointment:based-on"),
            ("_sort", "authored"),
            ("_count", "100"),
        ])
        if not response.ok:
            raise FhirError(response)
        return [row for row in imaging_request_rows(response.json()) if row.bookable]

    def book_directly(self, service_request_id, slot_id, *, patient_instruction=None,
                      claim_profiles=True):
        """Filler books a free Slot for an accepted request without a proposal step."""
        def action():
            service_request = self._read("ServiceRequest", service_request_id)
            slot = self._read("Slot", slot_id)
            if slot.get("status") != "free":
                return BookingResult(ok=False, conflict=True)
            schedule = self._read("Schedule", slot["schedule"]["reference"].split("/", 1)[1])
            task, group_task = self._tasks_for(_ref(service_request))
            response = self._transact(build_direct_book_transaction(
                service_request, slot, schedule, task, group_task,
                patient_instruction=patient_instruction, claim_profiles=claim_profiles))
            return BookingResult(ok=True, appointment_id=_created_id(response, "Appointment"))
        return self._booking(action)

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
