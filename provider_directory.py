import logging
import math
import os
import re as _re
import time
import uuid

import requests

from geoscape import geocode

_PD_DEFAULT = "https://sit.healthconnect.digitalhealth.gov.au/adha/hcd-api-router/api/v1/fhir"

_NEAR_RADIUS_KM = 20


def pd_server():
    return os.environ.get("PD_SERVER", _PD_DEFAULT).rstrip("/")


class _CircuitBreaker:
    """
    Simple circuit breaker: opens on ConnectionError/Timeout, tries again
    after _RETRY_SECS (half-open). Lets the demo fall back to local data
    when the live PD endpoint is unreachable.
    """
    _RETRY_SECS = 30

    def __init__(self):
        self._open = False
        self._opened_at = 0.0

    def record_error(self, exc: Exception) -> None:
        if isinstance(exc, (requests.exceptions.ConnectionError,
                            requests.exceptions.Timeout)):
            self._open = True
            self._opened_at = time.time()

    def record_success(self) -> None:
        self._open = False

    @property
    def is_open(self) -> bool:
        if not self._open:
            return False
        if time.time() - self._opened_at >= self._RETRY_SECS:
            return False  # half-open: allow one attempt
        return True


_pd_breaker = _CircuitBreaker()


def _fhir_get(url, params):
    request_id = os.environ.get("HCPD_REQUEST_ID") or str(uuid.uuid4())
    headers = {
        "Accept": "application/fhir+json",
        "X-Request-ID": request_id,
        # Azure Application Gateway blocks the default python-requests User-Agent
        "User-Agent": "Mozilla/5.0 (compatible; PatientReferralApp/1.0)",
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        _pd_breaker.record_success()
        return result
    except (requests.exceptions.ConnectionError,
            requests.exceptions.Timeout) as exc:
        _pd_breaker.record_error(exc)
        raise


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _address_text(resource):
    # Organization.address is Address[] ; Location.address is Address (single object)
    raw = resource.get("address", [])
    addresses = raw if isinstance(raw, list) else [raw]
    for addr in addresses:
        if not isinstance(addr, dict):
            continue
        parts = [
            ", ".join(addr.get("line", [])),
            addr.get("city", ""),
            addr.get("state", ""),
            addr.get("postalCode", ""),
        ]
        text = ", ".join(p for p in parts if p)
        if text:
            return text
    return ""


def _hpio(resource):
    for ident in resource.get("identifier", []):
        sys_ = ident.get("system", "").lower()
        if "hpio" in sys_ or "hi.infra.electronichealth" in sys_:
            return ident.get("value", "")
    return ""


def _specialty_text(svc):
    # Prefer the FHIR specialty element; fall back to type (used by HCPD services)
    for field in ("specialty", "type"):
        for s in svc.get(field, []):
            text = s.get("text", "")
            if not text:
                codings = s.get("coding", [])
                text = codings[0].get("display", "") if codings else ""
            if text:
                return text
    return ""


# HC PD IG defines a fixed set of SNOMED service type and role codes.
# The endpoint rejects blank searches, so these are hardcoded from the IG and Bruno tests.
_SCT = "http://snomed.info/sct"

_HCPD_SERVICE_TYPES: list = [
    {"system": _SCT, "code": "394814009",        "display": "General practice"},
    {"system": _SCT, "code": "788007007",        "display": "General practice service"},
    {"system": _SCT, "code": "789718008",        "display": "Cardiology service"},
    {"system": _SCT, "code": "310123008",        "display": "Clinical psychology service"},
    {"system": _SCT, "code": "310074003",        "display": "Diagnostic pathology service"},
    {"system": _SCT, "code": "1584801000168109", "display": "Geriatric evaluation and management service"},
    {"system": _SCT, "code": "1223131000168107", "display": "Allied health service"},
    {"system": _SCT, "code": "708170008",        "display": "Aged care service"},
    {"system": _SCT, "code": "310080006",        "display": "Radiology service"},
    {"system": _SCT, "code": "310102000",        "display": "Rheumatology service"},
    {"system": _SCT, "code": "310113003",        "display": "Oncology service"},
    {"system": _SCT, "code": "310078000",        "display": "Neurology service"},
    {"system": _SCT, "code": "310099002",        "display": "Endocrinology service"},
]

_HCPD_ROLE_CODES: list = [
    {"system": _SCT, "code": "408443003", "display": "General medical practitioner"},
    {"system": _SCT, "code": "17561000",  "display": "Cardiologist"},
    {"system": _SCT, "code": "763292005", "display": "Radiation oncologist"},
    {"system": _SCT, "code": "28229004",  "display": "Physiotherapist"},
    {"system": _SCT, "code": "80546007",  "display": "Occupational therapist"},
    {"system": _SCT, "code": "159026005", "display": "Psychologist"},
    {"system": _SCT, "code": "182211004", "display": "Consultant physician"},
    {"system": _SCT, "code": "405623001", "display": "Pathologist"},
    {"system": _SCT, "code": "41672002",  "display": "Respiratory physician"},
    {"system": _SCT, "code": "11911009",  "display": "Nephrologist"},
    {"system": _SCT, "code": "309367003", "display": "Gastroenterologist"},
    {"system": _SCT, "code": "21450003",  "display": "Neurologist"},
]


def _get_pd_roles() -> list:
    """Return known HC PD PractitionerRole codes (hardcoded from the HC PD IG)."""
    return _HCPD_ROLE_CODES


def _get_pd_service_types() -> list:
    """Return known HC PD HealthcareService type codes (hardcoded from the HC PD IG)."""
    return _HCPD_SERVICE_TYPES


def search_roles(query: str) -> list:
    """Return PD PractitionerRole codes whose display name matches the query text."""
    roles = _get_pd_roles()
    q = query.strip().lower()
    if not q:
        return roles[:10]
    return [r for r in roles if q in r["display"].lower()][:10]


def _parse_near_bundle(data, query_lat, query_lon, name_filter="", specialty_filter=""):
    """
    Parse a Location near-search bundle (Location + _revinclude HealthcareService
    + _include:iterate Organization) into sorted provider dicts.
    """
    orgs = {}
    locations = {}
    services = []

    for entry in data.get("entry", []):
        r = entry.get("resource", {})
        rt = r.get("resourceType")
        if rt == "Organization":
            orgs[r["id"]] = r
        elif rt == "Location":
            locations[r["id"]] = r
        elif rt == "HealthcareService":
            services.append(r)

    name_lower = name_filter.strip().lower()
    spec_lower = specialty_filter.strip().lower()

    results = []
    seen_ids = set()

    for svc in services:
        svc_id = svc.get("id", "")
        if svc_id in seen_ids:
            continue
        seen_ids.add(svc_id)

        svc_name = svc.get("name", "—")
        spec_text = _specialty_text(svc)

        # Client-side text filters (applied on top of geo filter)
        if name_lower and name_lower not in svc_name.lower():
            continue
        if spec_lower and spec_lower not in spec_text.lower() and spec_lower not in svc_name.lower():
            continue

        # Organization
        org_ref = svc.get("providedBy", {}).get("reference", "")
        org_id = org_ref.split("/")[-1] if "/" in org_ref else org_ref
        org = orgs.get(org_id, {})
        org_name = org.get("name", "") or svc.get("providedBy", {}).get("display", "")

        # Find nearest Location distance and address
        distance_km = None
        addr = _address_text(org)
        for loc_ref in svc.get("location", []):
            loc_id = loc_ref.get("reference", "").split("/")[-1]
            loc = locations.get(loc_id, {})
            pos = loc.get("position", {})
            if pos.get("latitude") is not None and pos.get("longitude") is not None:
                d = _haversine_km(query_lat, query_lon, pos["latitude"], pos["longitude"])
                if distance_km is None or d < distance_km:
                    distance_km = d
            if not addr:
                addr = _address_text(loc)

        results.append({
            "name": svc_name,
            "specialty": spec_text,
            "org": org_name,
            "address": addr,
            "hpio": _hpio(org),
            "reference": f"HealthcareService/{svc_id}",
            "resource_type": "HealthcareService",
            "distance_km": round(distance_km, 1) if distance_km is not None else None,
        })

    results.sort(key=lambda r: r["distance_km"] if r["distance_km"] is not None else 9999)
    return results[:10]


def _parse_name_bundle(data):
    """Parse a HealthcareService name-search bundle (with _include org + location)."""
    orgs = {}
    locations = {}
    results = []
    seen_ids = set()

    for entry in data.get("entry", []):
        r = entry.get("resource", {})
        rt = r.get("resourceType")
        if rt == "Organization":
            orgs[r["id"]] = r
        elif rt == "Location":
            locations[r["id"]] = r

    for entry in data.get("entry", []):
        r = entry.get("resource", {})
        if r.get("resourceType") != "HealthcareService":
            continue
        svc_id = r.get("id", "")
        if svc_id in seen_ids:
            continue
        seen_ids.add(svc_id)

        org_ref = r.get("providedBy", {}).get("reference", "")
        org_id = org_ref.split("/")[-1] if "/" in org_ref else org_ref
        org = orgs.get(org_id, {})
        org_name = org.get("name", "") or r.get("providedBy", {}).get("display", "")

        addr = _address_text(org)
        if not addr:
            for loc_ref in r.get("location", []):
                loc_id = loc_ref.get("reference", "").split("/")[-1]
                addr = _address_text(locations.get(loc_id, {}))
                if addr:
                    break

        results.append({
            "name": r.get("name", "—"),
            "specialty": _specialty_text(r),
            "org": org_name,
            "address": addr,
            "hpio": _hpio(org),
            "reference": f"HealthcareService/{svc_id}",
            "resource_type": "HealthcareService",
            "distance_km": None,
        })

        if len(results) >= 10:
            break

    return results


def _parse_org_search_bundle(data: dict) -> list:
    """
    Parse an Organization name-search bundle that includes revincluded Location,
    HealthcareService, and PractitionerRole resources.

    Priority: HealthcareService (drill-in) → PractitionerRole (select) → Location (drill-in).
    """
    orgs: dict = {}
    locations: dict = {}
    services: dict = {}
    practitioners: dict = {}
    roles: list = []

    for entry in data.get("entry", []):
        r = entry.get("resource", {})
        rt = r.get("resourceType")
        if rt == "Organization":
            orgs[r["id"]] = r
        elif rt == "Location":
            locations[r["id"]] = r
        elif rt == "HealthcareService":
            services[r["id"]] = r
        elif rt == "Practitioner":
            practitioners[r["id"]] = r
        elif rt == "PractitionerRole":
            roles.append(r)

    results: list = []
    seen: set = set()

    for svc_id, svc in services.items():
        ref = f"HealthcareService/{svc_id}"
        if ref in seen:
            continue
        seen.add(ref)
        org_ref = svc.get("providedBy", {}).get("reference", "")
        org_id = org_ref.split("/")[-1] if "/" in org_ref else org_ref
        org = orgs.get(org_id, {})
        org_name = org.get("name", "") or svc.get("providedBy", {}).get("display", "")
        addr = _address_text(org)
        if not addr:
            for loc_ref in svc.get("location", []):
                loc_id = loc_ref.get("reference", "").split("/")[-1]
                addr = _address_text(locations.get(loc_id, {}))
                if addr:
                    break
        results.append({
            "name": svc.get("name", "—"),
            "specialty": _specialty_text(svc),
            "org": org_name,
            "address": addr,
            "hpio": _hpio(org),
            "reference": ref,
            "resource_type": "HealthcareService",
            "distance_km": None,
        })

    for role in roles:
        role_ref = f"PractitionerRole/{role.get('id', '')}"
        if role_ref in seen:
            continue
        seen.add(role_ref)
        prac_ref = role.get("practitioner", {}).get("reference", "")
        prac_id = prac_ref.split("/")[-1] if prac_ref else ""
        prac_name = _practitioner_display_name(practitioners.get(prac_id, {}), role)
        org_ref = role.get("organization", {}).get("reference", "")
        org_id = org_ref.split("/")[-1] if org_ref else ""
        org = orgs.get(org_id, {})
        org_name = org.get("name", "") or role.get("organization", {}).get("display", "")
        loc_id = ""
        for loc_ref_obj in role.get("location", []):
            loc_id = loc_ref_obj.get("reference", "").split("/")[-1]
            break
        loc = locations.get(loc_id, {})
        addr = _address_text(loc) or _address_text(org)
        specialty = ""
        for coding_entry in role.get("code", [{}]):
            for c in coding_entry.get("coding", []):
                specialty = c.get("display", "")
                if specialty:
                    break
            if specialty:
                break
        results.append({
            "name": prac_name or "—",
            "specialty": specialty,
            "org": org_name,
            "address": addr,
            "hpio": _hpio(org),
            "reference": role_ref,
            "resource_type": "PractitionerRole",
            "distance_km": None,
        })

    # Fall back to Location entries when the org has no HealthcareService or roles
    if not results:
        for loc_id, loc in locations.items():
            ref = f"Location/{loc_id}"
            if ref in seen:
                continue
            seen.add(ref)
            org_ref = loc.get("managingOrganization", {}).get("reference", "")
            org_id = org_ref.split("/")[-1] if "/" in org_ref else org_ref
            org = orgs.get(org_id, {})
            org_name = org.get("name", "") or loc.get("managingOrganization", {}).get("display", "")
            addr = _address_text(loc) or _address_text(org)
            results.append({
                "name": loc.get("name", org_name or "—"),
                "specialty": _specialty_text(org),
                "org": org_name,
                "address": addr,
                "hpio": _hpio(org),
                "reference": ref,
                "resource_type": "HealthcareService",
                "distance_km": None,
            })

    return results[:10]


def _practitioner_display_name(prac: dict, role: dict) -> str:
    """Extract a display name from a Practitioner resource, falling back to the role reference display."""
    name_parts = (prac.get("name") or [{}])[0]
    prefix = " ".join(name_parts.get("prefix", []))
    given  = " ".join(name_parts.get("given",  []))
    family = name_parts.get("family", "")
    display = " ".join(p for p in [prefix, given, family] if p)
    return display or role.get("practitioner", {}).get("display", "")


def _parse_practitioner_role_bundle(data, query_lat=None, query_lon=None):
    """
    Parse a PractitionerRole role-search bundle (with _include location/organization/service)
    into provider dicts sorted by distance when coordinates are provided.
    """
    practitioners = {}
    orgs = {}
    locations = {}
    services = {}
    roles = []

    for entry in data.get("entry", []):
        r = entry.get("resource", {})
        rt = r.get("resourceType")
        if rt == "PractitionerRole":
            roles.append(r)
        elif rt == "Practitioner":
            practitioners[r["id"]] = r
        elif rt == "Organization":
            orgs[r["id"]] = r
        elif rt == "Location":
            locations[r["id"]] = r
        elif rt == "HealthcareService":
            services[r["id"]] = r

    results = []
    seen_svc_ids: set = set()
    seen_prac_roles: set = set()

    for role in roles:
        # Practitioner name
        prac_ref = role.get("practitioner", {}).get("reference", "")
        prac_id = prac_ref.split("/")[-1] if prac_ref else ""
        prac_name = _practitioner_display_name(practitioners.get(prac_id, {}), role)

        # Prefer HealthcareService name
        svc_name = None
        svc_id = None
        for svc_ref_obj in role.get("healthcareService", []):
            sid = svc_ref_obj.get("reference", "").split("/")[-1]
            svc = services.get(sid)
            if svc:
                svc_name = svc.get("name")
                svc_id = sid
                break

        if svc_id and svc_id in seen_svc_ids:
            continue
        if svc_id:
            seen_svc_ids.add(svc_id)

        # Organization
        org_ref = role.get("organization", {}).get("reference", "")
        org_id = org_ref.split("/")[-1] if org_ref else ""
        org = orgs.get(org_id, {})
        org_name = org.get("name", "") or role.get("organization", {}).get("display", "")

        # Location → distance + address
        distance_km = None
        addr = _address_text(org)
        for loc_ref_obj in role.get("location", []):
            loc_id = loc_ref_obj.get("reference", "").split("/")[-1]
            loc = locations.get(loc_id, {})
            pos = loc.get("position", {})
            if query_lat is not None and pos.get("latitude") is not None:
                d = _haversine_km(query_lat, query_lon, pos["latitude"], pos["longitude"])
                if distance_km is None or d < distance_km:
                    distance_km = d
            if not addr:
                addr = _address_text(loc)

        # Role code display as specialty label
        spec_text = ""
        for code_cc in role.get("code", []):
            for coding in code_cc.get("coding", []):
                spec_text = coding.get("display", "")
                if spec_text:
                    break
            if spec_text:
                break

        # Collapse duplicate roles: same practitioner + same specialty at the same/no service
        prac_role_key = (prac_id, spec_text.lower())
        if prac_id and prac_role_key in seen_prac_roles:
            continue
        if prac_id:
            seen_prac_roles.add(prac_role_key)

        if svc_name:
            # Known service: service name is primary; show practitioner underneath
            display_name = svc_name
            subtitle = " · ".join(p for p in [prac_name, spec_text] if p)
        else:
            # No service: practitioner name is primary; org name is already in org field
            display_name = prac_name or org_name or "Unknown"
            subtitle = spec_text

        ref = f"HealthcareService/{svc_id}" if svc_id else f"PractitionerRole/{role.get('id', '')}"

        results.append({
            "name": display_name,
            "specialty": subtitle,
            "org": org_name,
            "address": addr,
            "hpio": _hpio(org),
            "reference": ref,
            "resource_type": "PractitionerRole",
            "distance_km": round(distance_km, 1) if distance_km is not None else None,
        })

    results.sort(key=lambda r: r["distance_km"] if r["distance_km"] is not None else 9999)
    return results[:10]


_SPECIALTY_SUFFIXES = (
    "ology", "iatry", "iatrics", "surgery", "surgeon",
    "therapy", "therapist", "ician", "iatrist",
)


def _looks_geographic(q: str) -> bool:
    """
    True when the query is more likely a location than a person/service name.
    Prevents "Dr Smith" being geocoded as "Smith Drive" by Nominatim,
    and prevents specialty terms like "Psychology" being geocoded to a
    building name that Nominatim happens to find.
    """
    # 4-digit Australian postcode
    if _re.match(r'^\d{4}$', q):
        return True
    # Professional/honorific prefix → practitioner name
    if _re.match(r'^(dr|prof|mr|ms|mrs|a/prof|assoc)\b', q, _re.IGNORECASE):
        return False
    # Contains any digit but is not a postcode → not geographic
    if _re.search(r'\d', q):
        return False
    # Explicit state abbreviation → geographic
    if _re.search(r'\b(nsw|vic|qld|sa|wa|tas|nt|act)\b', q, _re.IGNORECASE):
        return True
    # Single-word specialty/service names end in recognisable clinical suffixes
    # (e.g. "Psychology", "Cardiology", "Psychiatry", "Physiotherapy")
    # → route to service-type / practitioner-role search, not geocoding
    if any(q.strip().lower().endswith(s) for s in _SPECIALTY_SUFFIXES):
        return False
    # Single word → try as suburb/town
    # Multi-word without a state → likely a name or service name → text search
    return len(q.split()) == 1


def search_unified(query: str) -> list:
    """
    Single-box provider search — routes to the best FHIR strategy based on
    what the user typed:

      • Postcode / geocodable suburb → Location near-search → HealthcareService
        results sorted by distance (click to drill into practitioners).
      • Practitioner name (e.g. "Dr Smith") → Practitioner?name= +
        _revinclude=PractitionerRole:practitioner → directly-selectable results.
      • Service / specialty name (e.g. "Cardiology") → HealthcareService?name=
        → service results (click to drill into practitioners).

    Non-geo results from both name searches are merged and deduplicated.
    Falls back to local demo data (pd_fallback) when the PD API is unreachable.
    """
    q = query.strip()
    if not q:
        return []

    if _pd_breaker.is_open:
        logging.warning("PD circuit open — using local fallback for %r", q)
        from pd_fallback import search_fallback
        return search_fallback(q)

    server = pd_server()
    _any_fail = False  # tracks whether every live call errored (network or HTTP)

    # ── Geographic path: postcode or geocodable suburb/address ───────────────
    if _looks_geographic(q):
        geo = geocode(q)
        if geo:
            lat, lon, _ = geo
            params = {
                "near": f"{lat}|{lon}|{_NEAR_RADIUS_KM}|km",
                "_count": 30,
                "_revinclude": "HealthcareService:location",
                "_include:iterate": "HealthcareService:organization",
                "_format": "json",
            }
            try:
                data = _fhir_get(f"{server}/Location", params)
                results = _parse_near_bundle(data, lat, lon)
                if results:
                    return results
            except Exception as exc:
                _any_fail = True
                logging.warning(f"Unified geo search failed: {exc}")
        # fall through to text search if geo returned nothing

    # ── Text path: practitioner name + service name ───────────────────────────
    results: list = []
    seen: set = set()
    _text_attempts = 0  # live calls attempted in the text path

    def _add(items):
        for r in items:
            if r["reference"] not in seen:
                seen.add(r["reference"])
                results.append(r)

    # 1. Practitioner name — HC PD SEARCH-08.02 pattern: each word as a separate name=
    #    param (OR logic on the server).  "Sarah Chen" → name=Sarah&name=Chen finds
    #    the practitioner whose given/family are stored separately.
    _name_params = q.split() if len(q.split()) > 1 else [q]
    _text_attempts += 1
    try:
        data = _fhir_get(f"{server}/Practitioner", {
            "name": _name_params,
            "_revinclude": "PractitionerRole:practitioner",
            "_include:iterate": [
                "PractitionerRole:service",
                "PractitionerRole:organization",
                "PractitionerRole:location",
            ],
            "_count": 10,
            "_format": "json",
        })
        _add(_parse_practitioner_role_bundle(data))
    except Exception as exc:
        _any_fail = True
        logging.warning(f"Practitioner name search failed: {exc}")

    # 2. HealthcareService name (partial match) → service / org results
    _text_attempts += 1
    try:
        data = _fhir_get(f"{server}/HealthcareService", {
            "name:contains": q,
            "_include": ["HealthcareService:organization", "HealthcareService:location"],
            "_count": 10,
            "_format": "json",
        })
        _add(_parse_name_bundle(data))
    except Exception as exc:
        _any_fail = True
        logging.warning(f"HS name search failed: {exc}")

    # 3. Service-type token search — match query against known HealthcareService type
    #    codes (e.g. "Psychology" → "Psychology service" → SNOMED 310123008).
    #    This finds clinics whose *type* matches even when the clinic name does not.
    q_lower = q.lower()
    matched_type = next(
        (t for t in _get_pd_service_types() if q_lower in t["display"].lower()),
        None,
    )
    if matched_type:
        _text_attempts += 1
        try:
            data = _fhir_get(f"{server}/HealthcareService", {
                "service-type": f"{matched_type['system']}|{matched_type['code']}",
                "_include": ["HealthcareService:organization", "HealthcareService:location"],
                "_count": 10,
                "_format": "json",
            })
            _add(_parse_name_bundle(data))
        except Exception as exc:
            _any_fail = True
            logging.warning(f"HS service-type search failed: {exc}")

    # 4. PractitionerRole code search — match query against known role codes
    #    (e.g. "Psychology" → "Psychologist" role code).
    matched_roles = [r for r in _get_pd_roles() if q_lower in r["display"].lower()]
    for role in matched_roles[:2]:
        _text_attempts += 1
        try:
            data = _fhir_get(f"{server}/PractitionerRole", {
                "role": f"{role['system']}|{role['code']}",
                "_include": [
                    "PractitionerRole:location",
                    "PractitionerRole:organization",
                    "PractitionerRole:service",
                ],
                "_count": 10,
                "_format": "json",
            })
            _add(_parse_practitioner_role_bundle(data))
        except Exception as exc:
            _any_fail = True
            logging.warning(f"PractitionerRole role search failed: {exc}")

    # 5. Organization name search — catches "Wesley Health Care Cronulla" etc.
    #    Try the full query as name:contains, then (for multi-word queries) split
    #    the last word off as a potential city/postcode qualifier.
    _org_variants: list = [{"name:contains": q}]
    _words = q.split()
    if len(_words) > 1:
        _last = _words[-1]
        _prefix = " ".join(_words[:-1])
        if _re.match(r'^\d{4}$', _last):
            _org_variants.append({"name:contains": _prefix, "address-postalcode": _last})
        else:
            _org_variants.append({"name:contains": _prefix, "address-city": _last})

    for _org_extra in _org_variants:
        _text_attempts += 1
        try:
            data = _fhir_get(f"{server}/Organization", {
                **_org_extra,
                "_revinclude": [
                    "Location:organization",
                    "HealthcareService:organization",
                    "PractitionerRole:organization",
                ],
                "_include:iterate": "PractitionerRole:practitioner",
                "_count": 10,
                "_format": "json",
            })
            _add(_parse_org_search_bundle(data))
        except Exception as exc:
            _any_fail = True
            logging.warning(f"Org name search failed: {exc}")

    # Fall back to local demo data when:
    #   • the circuit opened during this call (connection/timeout), OR
    #   • every text-path attempt failed (e.g. 403/5xx on all endpoints)
    #     and no results were found
    if not results and (_pd_breaker.is_open or (_any_fail and _text_attempts > 0)):
        logging.warning("PD unavailable/all-failed — using local fallback for %r", q)
        from pd_fallback import search_fallback
        results = search_fallback(q)

    # If the query contained a postcode (e.g. "Cardiology 2041"), annotate results
    # whose address contains that postcode with 0.0 km — the geo path was skipped
    # because the query wasn't purely geographic, so distance_km is otherwise None.
    _pc = _re.search(r'\b(\d{4})\b', q)
    if _pc:
        _postcode = _pc.group(1)
        for r in results:
            if r.get('distance_km') is None and _postcode in r.get('address', ''):
                r['distance_km'] = 0.0

    return results[:10]


def search_practitioners_by_service(service_ref: str) -> list:
    """
    Return PractitionerRoles linked to a HealthcareService or Location.

    Accepts either a full FHIR reference ("HealthcareService/id", "Location/id")
    or a bare ID (assumed HealthcareService).  Location references use the
    `location` search param; everything else uses `service`.

    Falls back to demo data for fallback IDs or when the PD is unreachable.
    """
    # Normalise: split "ResourceType/id" → (type, bare_id)
    if "/" in service_ref:
        ref_type, service_id = service_ref.split("/", 1)
    else:
        ref_type, service_id = "HealthcareService", service_ref

    # Demo service IDs (from pd_fallback) always go straight to the fallback
    if service_id.startswith("demo-") or service_id.startswith("example-healthconnect-"):
        from pd_fallback import search_practitioners_fallback
        return search_practitioners_fallback(service_id)

    if _pd_breaker.is_open:
        from pd_fallback import search_practitioners_fallback
        return search_practitioners_fallback(service_id)

    server = pd_server()
    search_param = "location" if ref_type == "Location" else "service"
    params = {
        search_param: service_id,
        "_include": [
            "PractitionerRole:practitioner",
            "PractitionerRole:organization",
            "PractitionerRole:location",
        ],
        "_count": 20,
        "_format": "json",
    }
    try:
        data = _fhir_get(f"{server}/PractitionerRole", params)
    except Exception as exc:
        logging.warning(f"Practitioners by service {service_ref!r} failed: {exc}")
        from pd_fallback import search_practitioners_fallback
        return search_practitioners_fallback(service_id)

    practitioners: dict = {}
    orgs: dict = {}
    locations: dict = {}
    roles = []

    for entry in data.get("entry", []):
        r = entry.get("resource", {})
        rt = r.get("resourceType")
        if rt == "PractitionerRole":
            roles.append(r)
        elif rt == "Practitioner":
            practitioners[r["id"]] = r
        elif rt == "Organization":
            orgs[r["id"]] = r
        elif rt == "Location":
            locations[r["id"]] = r

    results = []
    for role in roles:
        # Practitioner display name
        prac_ref = role.get("practitioner", {}).get("reference", "")
        prac_id = prac_ref.split("/")[-1] if prac_ref else ""
        prac = practitioners.get(prac_id, {})
        name_parts = (prac.get("name") or [{}])[0]
        prefix = " ".join(name_parts.get("prefix", []))
        given  = " ".join(name_parts.get("given",  []))
        family = name_parts.get("family", "")
        display_name = " ".join(p for p in [prefix, given, family] if p)
        if not display_name:
            display_name = role.get("practitioner", {}).get("display", "Unknown practitioner")

        # Organization
        org_ref = role.get("organization", {}).get("reference", "")
        org_id  = org_ref.split("/")[-1] if org_ref else ""
        org     = orgs.get(org_id, {})
        org_name = org.get("name", "") or role.get("organization", {}).get("display", "")

        # Address — prefer location, fall back to org
        addr = ""
        for loc_ref_obj in role.get("location", []):
            loc_id = loc_ref_obj.get("reference", "").split("/")[-1]
            addr = _address_text(locations.get(loc_id, {}))
            if addr:
                break
        if not addr:
            addr = _address_text(org)

        # Role code as specialty label
        spec_text = ""
        for code_cc in role.get("code", []):
            for coding in code_cc.get("coding", []):
                spec_text = coding.get("display", "")
                if spec_text:
                    break
            if spec_text:
                break

        results.append({
            "name": display_name,
            "specialty": spec_text,
            "org": org_name,
            "address": addr,
            "hpio": _hpio(org),
            "reference": f"PractitionerRole/{role.get('id', '')}",
            "resource_type": "PractitionerRole",
            "distance_km": None,
        })

    return results


def search_providers(name="", specialty="", suburb="",
                     role_code="", role_system="http://snomed.info/sct"):
    """
    Search the Australian Provider Directory for healthcare services.

    When role_code is given: searches PractitionerRole?role=<system>|<code> with
    includes, geocodes suburb for distance sorting.

    Otherwise, when a suburb/address is given, geocodes it via Geoscape and runs a
    FHIR Location near-search (radius _NEAR_RADIUS_KM km) with results sorted by
    distance.  Falls back to HealthcareService name-search when geocoding is
    unavailable or the query is name/specialty-only.

    Returns up to 10 dicts compatible with provider_results.html:
        {name, org, specialty, address, hpio, reference, resource_type, distance_km}
    """
    if _pd_breaker.is_open:
        from pd_fallback import search_providers_fallback
        return search_providers_fallback(name or specialty or suburb)

    server = pd_server()

    # ── Role-based path (PractitionerRole.code / SNOMED occupation code) ─────
    if role_code.strip():
        query_lat, query_lon = None, None
        if suburb.strip():
            geo = geocode(suburb.strip())
            if geo:
                query_lat, query_lon, _ = geo

        params = {
            "role": f"{role_system}|{role_code}",
            "_include": [
                "PractitionerRole:location",
                "PractitionerRole:organization",
                "PractitionerRole:service",
            ],
            "_count": 30,
            "_format": "json",
        }
        try:
            data = _fhir_get(f"{server}/PractitionerRole", params)
            return _parse_practitioner_role_bundle(data, query_lat, query_lon)
        except Exception as exc:
            logging.warning(f"Provider Directory role search failed: {exc}")
            return []

    # ── Geo path ─────────────────────────────────────────────────────────────
    if suburb.strip():
        geo = geocode(suburb.strip())
        if geo:
            lat, lon, _ = geo
            params = {
                "near": f"{lat}|{lon}|{_NEAR_RADIUS_KM}|km",
                "_count": 30,
                "_revinclude": "HealthcareService:location",
                "_include:iterate": "HealthcareService:organization",
                "_format": "json",
            }
            try:
                data = _fhir_get(f"{server}/Location", params)
                return _parse_near_bundle(data, lat, lon,
                                          name_filter=name,
                                          specialty_filter=specialty)
            except Exception as exc:
                logging.warning(f"Provider Directory near search failed: {exc}")
                # fall through to name search

    # ── Name / specialty fallback ─────────────────────────────────────────────
    query = " ".join(t for t in [name, specialty, suburb] if t).strip()
    if not query:
        return []

    params = {
        "_count": 20,
        "_include": ["HealthcareService:organization", "HealthcareService:location"],
        "_format": "json",
        "name": query,
    }
    try:
        data = _fhir_get(f"{server}/HealthcareService", params)
    except Exception as exc:
        logging.warning(f"Provider Directory name search failed: {exc}")
        from pd_fallback import search_providers_fallback
        return search_providers_fallback(query)

    return _parse_name_bundle(data)
