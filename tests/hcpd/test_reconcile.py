"""Reconciling HCPD export resources with the referral server (pure rules)."""
from hcpd_export import (IMPORT_TAG, classify, import_batches, prepare_for_import,
                         removal_identifiers)

SUPPRESSED = "http://digitalhealth.gov.au/fhir/cc/StructureDefinition/suppressed"
SOURCE = "https://hcpd.test/fhir"


def _suppressed(resource, include_self=None):
    ext = {"url": SUPPRESSED, "extension": [{"url": "suppressedBy", "valueCodeableConcept": {}}]}
    if include_self is not None:
        ext["extension"].append({"url": "includeSelf", "valueBoolean": include_self})
    return {**resource, "extension": [ext]}


PRACTITIONER = {"resourceType": "Practitioner", "id": "p1", "active": True}
ORG = {"resourceType": "Organization", "id": "o1", "active": True}


def test_active_and_inactive_records_are_upserted():
    assert classify(PRACTITIONER) == "upsert"
    assert classify({**PRACTITIONER, "active": False}) == "upsert"
    assert classify({"resourceType": "Location", "id": "l1", "status": "inactive"}) == "upsert"


def test_suppressed_records_are_removed():
    assert classify(_suppressed(PRACTITIONER)) == "remove"
    assert classify(_suppressed({"resourceType": "Endpoint", "id": "e1", "status": "active"})) == "remove"


def test_organisation_is_removed_only_when_suppression_includes_itself():
    assert classify(_suppressed(ORG, include_self=True)) == "remove"
    assert classify(_suppressed(ORG, include_self=False)) == "upsert"
    assert classify(_suppressed(ORG)) == "upsert"


def test_lists_are_removal_lists_and_provenance_is_skipped():
    assert classify({"resourceType": "List", "id": "l"}) == "removal-list"
    assert classify({"resourceType": "Provenance", "id": "pv"}) == "skip"


def test_prepared_resource_keeps_profile_drops_server_meta_and_is_tagged():
    resource = {**ORG, "meta": {"versionId": "3", "lastUpdated": "2026-01-22T03:51:37Z",
                                "profile": ["http://digitalhealth.gov.au/fhir/hcpd/StructureDefinition/hcpd-organization"],
                                "tag": [{"system": "urn:other", "code": "x"}]}}

    prepared = prepare_for_import(resource, SOURCE)

    assert prepared["meta"] == {
        "profile": ["http://digitalhealth.gov.au/fhir/hcpd/StructureDefinition/hcpd-organization"],
        "tag": [{"system": "urn:other", "code": "x"}, IMPORT_TAG],
        "source": SOURCE,
    }
    assert prepared["id"] == "o1"
    assert resource["meta"]["versionId"] == "3"  # the exported resource itself is not mutated


def test_batches_put_by_id_in_dependency_order_and_respect_the_size():
    resources = [{"resourceType": "PractitionerRole", "id": "r1"},
                 {"resourceType": "Organization", "id": "o1"},
                 {"resourceType": "Location", "id": "l1"},
                 {"resourceType": "Organization", "id": "o2"},
                 {"resourceType": "Organization", "id": "o3"}]

    batches = import_batches(resources, SOURCE, size=2)

    assert [(t, [e["request"]["url"] for e in b["entry"]]) for t, b in batches] == [
        ("Organization", ["Organization/o1", "Organization/o2"]),
        ("Organization", ["Organization/o3"]),
        ("Location", ["Location/l1"]),
        ("PractitionerRole", ["PractitionerRole/r1"]),
    ]
    assert all(b["type"] == "batch" for _, b in batches)
    assert all(e["request"]["method"] == "PUT" for _, b in batches for e in b["entry"])
    assert batches[0][1]["entry"][0]["resource"]["meta"]["tag"] == [IMPORT_TAG]


def test_removal_list_identifiers_map_to_the_resource_types_they_identify():
    hcpd_list = {"resourceType": "List", "entry": [
        {"item": {"identifier": {"system": "http://ns.electronichealth.net.au/id/hi/hpio/1.0", "value": "800362"}}},
        {"item": {"identifier": {"system": "http://ns.electronichealth.net.au/id/hi/hpii/1.0", "value": "800361"}}},
        {"item": {"identifier": {"system": "http://digitalhealth.gov.au/fhir/hcpd/id/hcpd-local-identifier", "value": "pr-1"}}},
        {"item": {"identifier": {"system": "urn:unknown", "value": "?"}}},
    ]}

    assert removal_identifiers(hcpd_list) == [
        (("Organization",), "http://ns.electronichealth.net.au/id/hi/hpio/1.0", "800362"),
        (("Practitioner",), "http://ns.electronichealth.net.au/id/hi/hpii/1.0", "800361"),
        (("Location", "HealthcareService", "PractitionerRole", "Endpoint"),
         "http://digitalhealth.gov.au/fhir/hcpd/id/hcpd-local-identifier", "pr-1"),
    ]
