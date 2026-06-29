import logging
import os

import requests

_GEOSCAPE_BASE = "https://api.psma.com.au"
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_NOMINATIM_UA  = "PatientReferralApp/1.0 (research prototype)"


def _geoscape(query: str, key: str):
    """
    Geoscape GNAF address lookup — precise for street-level addresses.
    Returns (lat, lon, formatted) or None.
    The /v1/addresses endpoint only matches specific street addresses,
    not suburb or postcode strings.
    """
    headers = {"Authorization": key, "Accept": "application/json"}
    try:
        resp = requests.get(
            f"{_GEOSCAPE_BASE}/v1/addresses",
            params={"addressString": query.strip(), "maxNumberOfCandidates": 1},
            headers=headers,
            timeout=5,
        )
        resp.raise_for_status()
        candidates = resp.json().get("data", [])
        if not candidates:
            return None
        address_id = candidates[0]["addressId"]
        formatted = candidates[0].get("formattedAddress", query)
    except Exception as exc:
        logging.warning(f"Geoscape address match failed for {query!r}: {exc}")
        return None

    try:
        resp = requests.get(
            f"{_GEOSCAPE_BASE}/v1/addresses/{address_id}/geo/",
            headers=headers,
            timeout=5,
        )
        resp.raise_for_status()
        coords = resp.json().get("geo", {}).get("geometry", {}).get("coordinates", [])
        if len(coords) < 2:
            return None
        lon, lat = coords[0], coords[1]  # GeoJSON is [lon, lat]
        return lat, lon, formatted
    except Exception as exc:
        logging.warning(f"Geoscape geo fetch for {address_id} failed: {exc}")
        return None


def _nominatim(query: str):
    """
    Nominatim (OpenStreetMap) fallback — handles suburbs and postcodes.
    Returns (lat, lon, display_name) or None.
    """
    try:
        resp = requests.get(
            _NOMINATIM_URL,
            params={
                "q": query + ", Australia",
                "format": "json",
                "limit": 1,
                "countrycodes": "au",
            },
            headers={"User-Agent": _NOMINATIM_UA},
            timeout=5,
        )
        resp.raise_for_status()
        results = resp.json()
        if not results:
            return None
        r = results[0]
        return float(r["lat"]), float(r["lon"]), r.get("display_name", query)
    except Exception as exc:
        logging.warning(f"Nominatim geocode failed for {query!r}: {exc}")
        return None


def geocode(query: str):
    """
    Return (lat, lon, formatted_address) for a street address, suburb, or postcode.
    Returns None if geocoding fails entirely.

    Strategy:
      1. Geoscape /v1/addresses — precise for full street addresses (requires GNAF_CONSUMER_KEY)
      2. Nominatim (OSM) — fallback for suburbs and postcodes
    """
    if not query.strip():
        return None

    key = os.environ.get("GNAF_CONSUMER_KEY", "")
    if key:
        result = _geoscape(query, key)
        if result:
            return result

    # Fallback: Nominatim handles suburbs, postcodes, and anything Geoscape can't match
    return _nominatim(query)
