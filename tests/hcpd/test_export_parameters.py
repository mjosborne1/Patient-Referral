"""Behaviour of building an HCPD Export Request Parameters resource."""
import pytest

from hcpd_export import ExportRequestError, build_export_parameters

PROFILE = "http://digitalhealth.gov.au/fhir/hcpd/StructureDefinition/hcpd-export-request-parameters"


def _params(p):
    return [(x["name"], x.get("valueString", x.get("valueInstant"))) for x in p["parameter"]]


def test_standard_export_has_output_format_types_and_one_entry_per_filter():
    p = build_export_parameters(
        ["Organization", "HealthcareService"],
        ["Organization?_has:HealthcareService:organization:service-type=http://snomed.info/sct|310128004",
         "HealthcareService?service-type=http://snomed.info/sct|310128004"])

    assert p["resourceType"] == "Parameters"
    assert p["meta"]["profile"] == [PROFILE]
    assert _params(p) == [
        ("_outputFormat", "application/fhir+ndjson"),
        ("_type", "Organization,HealthcareService"),
        ("_typeFilter", "Organization?_has:HealthcareService:organization:service-type=http://snomed.info/sct|310128004"),
        ("_typeFilter", "HealthcareService?service-type=http://snomed.info/sct|310128004"),
    ]


def test_incremental_export_adds_since_as_an_instant():
    p = build_export_parameters(["Organization"], ["Organization?address-state=QLD"],
                                since="2026-02-19T10:27:53.423+11:00")

    assert p["parameter"][-1] == {"name": "_since", "valueInstant": "2026-02-19T10:27:53.423+11:00"}


@pytest.mark.parametrize("types, filters, problem", [
    (["Patient"], ["Patient?name=x"], "not exportable"),
    (["Organization", "Location"], ["Organization?name=x"], "Location has no _typeFilter"),
    (["Organization"], ["Organization?name=x", "Location?address-state=QLD"], "Location is not in _type"),
    (["Organization"], ["Organization?name=x&_include=Organization:endpoint"], "_include"),
    (["Organization"], ["name=x"], "must start with a resource type"),
    ([], [], "at least one resource type"),
])
def test_requests_the_server_would_reject_are_refused_up_front(types, filters, problem):
    with pytest.raises(ExportRequestError, match=problem):
        build_export_parameters(types, filters)


def test_since_must_be_a_full_instant():
    with pytest.raises(ExportRequestError, match="instant"):
        build_export_parameters(["Organization"], ["Organization?name=x"], since="2025-02-01")


from hcpd_export import scope_key  # noqa: E402


def test_scope_key_ignores_since_and_ordering_but_not_the_scope():
    a = build_export_parameters(["Organization", "Location"],
                                ["Organization?name=x", "Location?address-state=QLD"])
    a_later = build_export_parameters(["Location", "Organization"],
                                      ["Location?address-state=QLD", "Organization?name=x"],
                                      since="2026-02-19T10:27:53Z")
    other = build_export_parameters(["Organization"], ["Organization?name=y"])

    assert scope_key(a) == scope_key(a_later)
    assert scope_key(a) != scope_key(other)
