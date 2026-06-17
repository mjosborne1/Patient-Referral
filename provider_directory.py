import logging
import os
import requests


def _pd_config():
    return {
        "server": os.environ.get("PD_SERVER", "").rstrip("/"),
        "username": os.environ.get("PD_USERNAME", ""),
        "password": os.environ.get("PD_PASSWORD", ""),
    }


def _fhir_get(url, params, auth_tuple=None):
    headers = {"Accept": "application/fhir+json"}
    kwargs = {"params": params, "headers": headers, "timeout": 10}
    if auth_tuple:
        kwargs["auth"] = auth_tuple
    resp = requests.get(url, **kwargs)
    resp.raise_for_status()
    return resp.json()


def _address_text(resource):
    for addr in resource.get("address", []):
        parts = [addr.get("city", ""), addr.get("state", "")]
        text = ", ".join(p for p in parts if p)
        if text:
            return text
    return ""


def _hpio(resource):
    for ident in resource.get("identifier", []):
        sys = ident.get("system", "").lower()
        if "hpio" in sys or "hi.infra.electronichealth" in sys:
            return ident.get("value", "")
    return ""


def _search_organizations(name, server, auth_tuple):
    try:
        data = _fhir_get(f"{server}/Organization", {"name": name, "_count": 10}, auth_tuple)
    except Exception as exc:
        logging.warning(f"PD Organization search failed: {exc}")
        return []

    results = []
    for entry in data.get("entry", []):
        org = entry.get("resource", {})
        if org.get("resourceType") != "Organization":
            continue
        results.append({
            "id": org.get("id", ""),
            "resource_type": "Organization",
            "name": org.get("name", "—"),
            "specialty": "",
            "org": org.get("name", ""),
            "address": _address_text(org),
            "hpio": _hpio(org),
            "reference": f"Organization/{org.get('id', '')}",
        })
    return results


def _search_practitioner_roles(specialty, suburb, server, auth_tuple):
    params = {
        "_count": 10,
        "_include": "PractitionerRole:practitioner",
    }
    if specialty:
        params["specialty"] = specialty
    if suburb:
        params["location.address-city"] = suburb

    try:
        data = _fhir_get(f"{server}/PractitionerRole", params, auth_tuple)
    except Exception as exc:
        logging.warning(f"PD PractitionerRole search failed: {exc}")
        return []

    practitioners = {}
    orgs = {}
    for entry in data.get("entry", []):
        r = entry.get("resource", {})
        rt = r.get("resourceType", "")
        if rt == "Practitioner":
            practitioners[r.get("id")] = r
        elif rt == "Organization":
            orgs[r.get("id")] = r

    results = []
    for entry in data.get("entry", []):
        role = entry.get("resource", {})
        if role.get("resourceType") != "PractitionerRole":
            continue

        prac_ref = role.get("practitioner", {}).get("reference", "")
        prac_id = prac_ref.split("/")[-1] if "/" in prac_ref else prac_ref
        prac = practitioners.get(prac_id, {})

        name_parts = prac.get("name", [{}])[0] if prac.get("name") else {}
        given = " ".join(name_parts.get("given", []))
        family = name_parts.get("family", "")
        prac_name = (
            f"{name_parts.get('prefix', [''])[0]} {given} {family}".strip()
            if (given or family)
            else role.get("practitioner", {}).get("display", "Unknown Practitioner")
        )

        org_ref = role.get("organization", {}).get("reference", "")
        org_id = org_ref.split("/")[-1] if "/" in org_ref else org_ref
        org = orgs.get(org_id, {})
        org_name = org.get("name", "") or role.get("organization", {}).get("display", "")

        specialties = role.get("specialty", [])
        if specialties:
            codings = specialties[0].get("coding", [])
            specialty_text = specialties[0].get("text") or (codings[0].get("display", "") if codings else "")
        else:
            specialty_text = ""

        results.append({
            "id": role.get("id", ""),
            "resource_type": "PractitionerRole",
            "name": prac_name,
            "specialty": specialty_text,
            "org": org_name,
            "address": _address_text(org),
            "hpio": _hpio(org),
            "reference": f"PractitionerRole/{role.get('id', '')}",
        })
    return results


def search_providers(name="", specialty="", suburb="", pd_server=None, auth_tuple=None):
    """
    Search the HC Provider Directory for organisations and practitioners.

    Returns up to 10 provider dicts:
        {id, resource_type, name, specialty, org, address, hpio, reference}

    Queries Organisation by name when name is given; queries PractitionerRole
    by specialty/suburb otherwise. Falls back gracefully when PD_SERVER is not
    configured.
    """
    cfg = _pd_config()
    server = (pd_server or cfg["server"]).rstrip("/")
    if not server:
        return []

    if auth_tuple is None and cfg["username"]:
        auth_tuple = (cfg["username"], cfg["password"])

    results = []
    if name:
        results.extend(_search_organizations(name, server, auth_tuple))
    if specialty or suburb:
        results.extend(_search_practitioner_roles(specialty, suburb, server, auth_tuple))

    return results[:10]
