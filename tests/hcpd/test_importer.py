"""Applying exported resources to the referral FHIR server."""
from hcpd_export import IMPORT_TAG, ReferralImporter

REF = "https://referral.test/fhir"
SOURCE = "https://hcpd.test/fhir"
SUPPRESSED = "http://digitalhealth.gov.au/fhir/cc/StructureDefinition/suppressed"
TAG_QS = f"{IMPORT_TAG['system']}|{IMPORT_TAG['code']}".lower()


def _batch_response(*statuses):
    return {"resourceType": "Bundle", "type": "batch-response", "entry": [
        {"response": {"status": s, **({"outcome": {"resourceType": "OperationOutcome", "issue": [
            {"severity": "error", "diagnostics": "Organization.name: required"}]}}
            if not s.startswith("2") else {})}} for s in statuses]}


def test_upserts_are_counted_per_type_from_the_batch_response(http):
    http.post(REF, [{"json": _batch_response("201 Created", "422 Unprocessable Entity")},
                    {"json": _batch_response("200 OK")}])

    counts = ReferralImporter(REF).apply([
        {"resourceType": "Location", "id": "l1"},
        {"resourceType": "Organization", "id": "o1"},
        {"resourceType": "Organization", "id": "o2"},
    ], source=SOURCE)

    assert counts.by_type == {"Organization": {"upserted": 1, "removed": 0, "failed": 1},
                              "Location": {"upserted": 1, "removed": 0, "failed": 0}}
    assert counts.errors == ["Organization/o2: Organization.name: required"]
    assert [r.json()["entry"][0]["request"]["url"] for r in http.request_history] == [
        "Organization/o1", "Location/l1"]


def test_suppressed_records_are_deleted_only_if_they_were_imported(http):
    http.get(f"{REF}/Practitioner/p1", json={"resourceType": "Practitioner", "id": "p1",
                                              "meta": {"tag": [IMPORT_TAG]}})
    http.get(f"{REF}/Practitioner/p2", json={"resourceType": "Practitioner", "id": "p2"})
    http.get(f"{REF}/Practitioner/p3", status_code=404)
    http.delete(f"{REF}/Practitioner/p1", status_code=204)
    suppressed = [{"url": SUPPRESSED, "extension": []}]

    counts = ReferralImporter(REF).apply([
        {"resourceType": "Practitioner", "id": pid, "extension": suppressed} for pid in ("p1", "p2", "p3")
    ], source=SOURCE)

    assert counts.by_type == {"Practitioner": {"upserted": 0, "removed": 1, "failed": 0}}
    assert [r.method for r in http.request_history].count("DELETE") == 1


def test_removal_list_identifiers_are_resolved_among_imported_records_and_deleted(http):
    http.get(f"{REF}/Organization", json={"resourceType": "Bundle", "entry": [
        {"resource": {"resourceType": "Organization", "id": "o9"}}]})
    http.delete(f"{REF}/Organization/o9", status_code=200)
    removal_list = {"resourceType": "List", "entry": [{"item": {"identifier": {
        "system": "http://ns.electronichealth.net.au/id/hi/hpio/1.0", "value": "800362"}}}]}

    counts = ReferralImporter(REF).apply([removal_list], source=SOURCE)

    search = http.request_history[0]
    assert search.qs == {"identifier": ["http://ns.electronichealth.net.au/id/hi/hpio/1.0|800362"],
                         "_tag": [TAG_QS]}
    assert counts.by_type == {"Organization": {"upserted": 0, "removed": 1, "failed": 0}}


def test_a_refused_delete_is_counted_as_failed_not_forced(http):
    http.get(f"{REF}/Organization/o1", json={"resourceType": "Organization", "id": "o1",
                                              "meta": {"tag": [IMPORT_TAG]}})
    http.delete(f"{REF}/Organization/o1", status_code=409, json={
        "resourceType": "OperationOutcome", "issue": [{"severity": "error",
                                                       "diagnostics": "referenced by Task/t1"}]})
    org = {"resourceType": "Organization", "id": "o1", "extension": [
        {"url": SUPPRESSED, "extension": [{"url": "includeSelf", "valueBoolean": True}]}]}

    counts = ReferralImporter(REF).apply([org], source=SOURCE)

    assert counts.by_type["Organization"]["failed"] == 1
    assert counts.errors == ["Organization/o1: referenced by Task/t1"]
