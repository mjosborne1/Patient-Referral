"""
Offline fallback for the HealthConnect Provider Directory.

Serves demo data (HCPD IG examples + synthetic extras) when the live PD API is
unreachable, keeping the New Referral specialist search functional without
network access to the provider directory.

All search functions return dicts in the same format as provider_directory.py.
"""
import logging
import math


# ── Haversine ─────────────────────────────────────────────────────────────────
def _km(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(
        math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


# ── Demo provider catalogue ────────────────────────────────────────────────────
# _pos: (lat, lon) for geo sorting; None for virtual/telehealth entries.
# _tags: lowercase bag-of-words used for text matching.
_PROVIDERS = [
    # ── From HCPD IG example package (hcpd-package.tgz) ──────────────────────
    {
        "name": "Healthcare service with Residential Aged Care service type",
        "specialty": "Geriatric evaluation and management service",
        "org": "Example Aged Care Facility",
        "address": "Level 2, 147-153 Castlereagh Street, SYDNEY NSW 2000",
        "hpio": "",
        "reference": "HealthcareService/example-healthconnect-healthcareservice-1",
        "resource_type": "HealthcareService",
        "distance_km": None,
        "_pos": (-33.8688, 151.2093),
        "_tags": (
            "residential aged care geriatric evaluation management service "
            "example aged care facility sydney castlereagh nsw 2000"
        ),
    },
    # ── Cardiology ────────────────────────────────────────────────────────────
    {
        "name": "Balmain Cardiology Clinic",
        "specialty": "Cardiology service",
        "org": "Balmain Cardiology Clinic",
        "address": "25 Darling Street, Balmain NSW 2041",
        "hpio": "",
        "reference": "HealthcareService/demo-balmain-cardiology-1",
        "resource_type": "HealthcareService",
        "distance_km": None,
        "_pos": (-33.8631, 151.1795),
        "_tags": "balmain cardiology clinic cardiology service darling street nsw 2041",
    },
    {
        "name": "Balmain Cardiology Services",
        "specialty": "Cardiology service",
        "org": "Balmain Medical Centre",
        "address": "10 Mullens Street, Balmain NSW 2041",
        "hpio": "",
        "reference": "HealthcareService/demo-balmain-cardiology-2",
        "resource_type": "HealthcareService",
        "distance_km": None,
        "_pos": (-33.8640, 151.1800),
        "_tags": "balmain cardiology services balmain medical centre cardiology service nsw 2041",
    },
    {
        "name": "Sydney CBD Cardiology Service",
        "specialty": "Cardiology service",
        "org": "Sydney CBD Cardiology Service",
        "address": "Level 8, 135 Macquarie Street, Sydney NSW 2000",
        "hpio": "",
        "reference": "HealthcareService/demo-sydneycbd-cardiology-1",
        "resource_type": "HealthcareService",
        "distance_km": None,
        "_pos": (-33.8688, 151.2093),
        "_tags": "sydney cbd cardiology service macquarie street nsw 2000",
    },
    {
        "name": "Dr Sarah Chen",
        "specialty": "Cardiologist",
        "org": "Sydney CBD Cardiology Service",
        "address": "Level 8, 135 Macquarie Street, Sydney NSW 2000",
        "hpio": "",
        "reference": "HealthcareService/demo-sydneycbd-cardiology-1",
        "resource_type": "PractitionerRole",
        "distance_km": None,
        "_pos": (-33.8688, 151.2093),
        "_tags": "dr sarah chen cardiologist sydney cbd cardiology macquarie street nsw 2000",
    },
    {
        "name": "Cardiology Telehealth Service (2041)",
        "specialty": "Cardiology service",
        "org": "Heart Health Australia",
        "address": "Virtual / Telehealth",
        "hpio": "",
        "reference": "HealthcareService/demo-telehealth-cardiology-1",
        "resource_type": "HealthcareService",
        "distance_km": None,
        "_pos": None,
        "_tags": "cardiology telehealth service heart health australia virtual 2041",
    },
    # ── Psychology ────────────────────────────────────────────────────────────
    {
        "name": "Sydney CBD Psychology Service",
        "specialty": "Psychology service",
        "org": "Sydney CBD Psychology Service",
        "address": "Level 4, 200 George Street, Sydney NSW 2000",
        "hpio": "",
        "reference": "HealthcareService/demo-sydneycbd-psychology-1",
        "resource_type": "HealthcareService",
        "distance_km": None,
        "_pos": (-33.8688, 151.2093),
        "_tags": "sydney cbd psychology service george street nsw 2000",
    },
    {
        "name": "NSW Telehealth Psychology Services",
        "specialty": "Psychology service",
        "org": "NSW Telehealth Psychology Services",
        "address": "Virtual / Telehealth",
        "hpio": "",
        "reference": "HealthcareService/demo-telehealth-psychology-1",
        "resource_type": "HealthcareService",
        "distance_km": None,
        "_pos": None,
        "_tags": "nsw telehealth psychology services psychology service virtual",
    },
    # ── General practice ──────────────────────────────────────────────────────
    {
        "name": "AfterHours GP Service",
        "specialty": "General practice service",
        "org": "AfterHours GP Service",
        "address": "88 George Street, Sydney NSW 2000",
        "hpio": "",
        "reference": "HealthcareService/demo-afterhours-gp-1",
        "resource_type": "HealthcareService",
        "distance_km": None,
        "_pos": (-33.8688, 151.2093),
        "_tags": "afterhours gp service general practice service george street sydney nsw 2000",
    },
    {
        "name": "Balmain General Practice",
        "specialty": "General practice service",
        "org": "Balmain Medical Centre",
        "address": "10 Mullens Street, Balmain NSW 2041",
        "hpio": "",
        "reference": "HealthcareService/demo-balmain-gp-1",
        "resource_type": "HealthcareService",
        "distance_km": None,
        "_pos": (-33.8640, 151.1800),
        "_tags": "balmain general practice general practice service mullens street nsw 2041",
    },
    # ── Pathology ─────────────────────────────────────────────────────────────
    {
        "name": "Balmain Pathology Laboratory Services",
        "specialty": "Pathology service",
        "org": "Balmain Pathology Laboratory Services",
        "address": "22 Darling Street, Balmain NSW 2041",
        "hpio": "",
        "reference": "HealthcareService/demo-balmain-pathology-1",
        "resource_type": "HealthcareService",
        "distance_km": None,
        "_pos": (-33.8630, 151.1793),
        "_tags": "balmain pathology laboratory services pathology service darling street nsw 2041",
    },
    # ── Allied health ─────────────────────────────────────────────────────────
    {
        "name": "Caring Hands Allied Health",
        "specialty": "Allied health service",
        "org": "Caring Hands Home Support",
        "address": "Suite 15, 88 Liverpool Street, Sydney NSW 2000",
        "hpio": "",
        "reference": "HealthcareService/demo-caringhands-allied-1",
        "resource_type": "HealthcareService",
        "distance_km": None,
        "_pos": (-33.8720, 151.2060),
        "_tags": (
            "caring hands allied health allied health service "
            "liverpool street sydney nsw 2000"
        ),
    },
    {
        "name": "Northern Beaches Allied Health",
        "specialty": "Allied health service",
        "org": "Northern Beaches Allied Health",
        "address": "35 Sydney Road, Manly NSW 2095",
        "hpio": "",
        "reference": "HealthcareService/demo-northernbeaches-allied-1",
        "resource_type": "HealthcareService",
        "distance_km": None,
        "_pos": (-33.7969, 151.2868),
        "_tags": "northern beaches allied health allied health service sydney road manly nsw 2095",
    },
]


# ── Demo practitioners, keyed by HealthcareService ID ─────────────────────────
# Drawn from IG example data (Dr Alex Smith, Dr Alice Anderson) + synthetics.
_PRACTITIONERS_BY_SERVICE: dict[str, list[dict]] = {
    # IG example — Dr Alex Smith (Medical pathologist)
    "example-healthconnect-healthcareservice-1": [
        {
            "name": "Dr Alex Smith",
            "specialty": "Medical pathologist",
            "org": "Example Aged Care Facility",
            "address": "Level 2, 147-153 Castlereagh Street, SYDNEY NSW 2000",
            "hpio": "",
            "reference": "PractitionerRole/example-healthconnect-practitionerrole-1",
            "resource_type": "PractitionerRole",
            "distance_km": None,
        }
    ],
    # Synthetic cardiology services — Dr Alice Anderson (Cardiologist)
    "demo-balmain-cardiology-1": [
        {
            "name": "Dr Alice Anderson",
            "specialty": "Cardiologist",
            "org": "Balmain Cardiology Clinic",
            "address": "25 Darling Street, Balmain NSW 2041",
            "hpio": "",
            "reference": "PractitionerRole/demo-balmain-pr-1",
            "resource_type": "PractitionerRole",
            "distance_km": None,
        }
    ],
    "demo-balmain-cardiology-2": [
        {
            "name": "Dr Alice Anderson",
            "specialty": "Cardiologist",
            "org": "Balmain Medical Centre",
            "address": "10 Mullens Street, Balmain NSW 2041",
            "hpio": "",
            "reference": "PractitionerRole/demo-balmain-pr-2",
            "resource_type": "PractitionerRole",
            "distance_km": None,
        }
    ],
    "demo-sydneycbd-cardiology-1": [
        {
            "name": "Dr James Chen",
            "specialty": "Cardiologist",
            "org": "Sydney CBD Cardiology Service",
            "address": "Level 8, 135 Macquarie Street, Sydney NSW 2000",
            "hpio": "",
            "reference": "PractitionerRole/demo-sydneycbd-cardiology-pr-1",
            "resource_type": "PractitionerRole",
            "distance_km": None,
        },
        {
            "name": "Dr Sarah Chen",
            "specialty": "Cardiologist",
            "org": "Sydney CBD Cardiology Service",
            "address": "Level 8, 135 Macquarie Street, Sydney NSW 2000",
            "hpio": "",
            "reference": "PractitionerRole/demo-sydneycbd-cardiology-pr-2",
            "resource_type": "PractitionerRole",
            "distance_km": None,
        },
    ],
    # Psychology
    "demo-sydneycbd-psychology-1": [
        {
            "name": "Dr Sarah Williams",
            "specialty": "Psychologist",
            "org": "Sydney CBD Psychology Service",
            "address": "Level 4, 200 George Street, Sydney NSW 2000",
            "hpio": "",
            "reference": "PractitionerRole/demo-sydneycbd-psychology-pr-1",
            "resource_type": "PractitionerRole",
            "distance_km": None,
        }
    ],
    # GP
    "demo-afterhours-gp-1": [
        {
            "name": "Dr Michael Roberts",
            "specialty": "General medical practitioner",
            "org": "AfterHours GP Service",
            "address": "88 George Street, Sydney NSW 2000",
            "hpio": "",
            "reference": "PractitionerRole/demo-afterhours-gp-pr-1",
            "resource_type": "PractitionerRole",
            "distance_km": None,
        }
    ],
    "demo-balmain-gp-1": [
        {
            "name": "Dr Alex Smith",
            "specialty": "Family medicine specialist",
            "org": "Balmain Medical Centre",
            "address": "10 Mullens Street, Balmain NSW 2041",
            "hpio": "",
            "reference": "PractitionerRole/demo-balmain-gp-pr-1",
            "resource_type": "PractitionerRole",
            "distance_km": None,
        }
    ],
}


def _result(entry: dict, distance_km=None) -> dict:
    r = {k: v for k, v in entry.items() if not k.startswith("_")}
    r["distance_km"] = distance_km
    return r


# ── Public API ─────────────────────────────────────────────────────────────────

def search_fallback(query: str) -> list:
    """
    Fallback for search_unified. Searches _PROVIDERS by text then (if needed)
    by proximity when the query geocodes to a known location.
    """
    q = query.strip()
    if not q:
        return []

    logging.info("PD fallback: search for %r", q)
    q_lower = q.lower()

    # For geographic queries (suburb/postcode), geocode so we can attach
    # distances to every matched result — not just proximity-only results.
    geo = None
    try:
        from provider_directory import _looks_geographic
        from geoscape import geocode as _geocode
        if _looks_geographic(q):
            geo = _geocode(q)
    except Exception:
        pass

    # Text match: try exact substring first, then word-by-word AND logic for multi-word queries
    text_matches = [e for e in _PROVIDERS if q_lower in e["_tags"]]
    if not text_matches and len(q_lower.split()) > 1:
        words = q_lower.split()
        text_matches = [e for e in _PROVIDERS if all(w in e["_tags"] for w in words)]

    # Pure geo match — no tag hit but query is a suburb/postcode
    if not text_matches and geo:
        lat, lon, _ = geo
        nearby = [
            (e, round(_km(lat, lon, e["_pos"][0], e["_pos"][1]), 1))
            for e in _PROVIDERS if e["_pos"]
            and _km(lat, lon, e["_pos"][0], e["_pos"][1]) <= 50
        ]
        nearby.sort(key=lambda t: t[1])
        if nearby:
            return [_result(e, d) for e, d in nearby[:10]]

    candidates = text_matches or list(_PROVIDERS)

    # Attach distances when we have a geo reference point
    if geo:
        lat, lon, _ = geo
        results = [
            _result(e, round(_km(lat, lon, e["_pos"][0], e["_pos"][1]), 1)
                    if e["_pos"] else None)
            for e in candidates
        ]
        results.sort(key=lambda r: r["distance_km"] if r["distance_km"] is not None else 9999)
    else:
        results = [_result(e) for e in candidates]

    return results[:10]


def search_providers_fallback(name: str) -> list:
    """Fallback for search_providers (legacy typeahead)."""
    return search_fallback(name)


def search_practitioners_fallback(service_id: str) -> list:
    """
    Fallback for search_practitioners_by_service.
    Returns demo practitioners for known demo service IDs.
    """
    practitioners = _PRACTITIONERS_BY_SERVICE.get(service_id, [])
    if practitioners:
        logging.info("PD fallback: practitioners for service %r", service_id)
    return list(practitioners)
