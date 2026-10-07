"""Scope presets produce linked _typeFilters (one per type, same criterion via chains)."""
import pytest

from hcpd_export import ExportRequestError, build_export_parameters, scope_filters

CT = "http://snomed.info/sct|310128004"
ALL = ["Organization", "Location", "HealthcareService", "PractitionerRole", "Practitioner", "Endpoint"]


def test_geographic_preset_ties_every_type_to_the_state():
    assert scope_filters("geographic", "QLD", ALL) == [
        "Organization?_has:Location:organization:address-state=QLD",
        "Location?address-state=QLD",
        "HealthcareService?location.address-state=QLD",
        "PractitionerRole?location.address-state=QLD",
        "Practitioner?_has:PractitionerRole:practitioner:location.address-state=QLD",
        "Endpoint?_has:PractitionerRole:endpoint:location.address-state=QLD",
    ]


def test_service_type_preset_can_be_narrowed_to_a_state():
    assert scope_filters("service-type", CT, ["Organization", "HealthcareService"], state="QLD") == [
        f"Organization?_has:HealthcareService:organization:service-type={CT}",
        f"HealthcareService?service-type={CT}&location.address-state=QLD",
    ]


def test_organisation_preset_by_hpio():
    hpio = "http://ns.electronichealth.net.au/id/hi/hpio/1.0|8003623233370062"
    assert scope_filters("organisation", hpio, ["Organization", "Location"]) == [
        f"Organization?identifier={hpio}",
        f"Location?organization.identifier={hpio}",
    ]


def test_organisation_preset_by_name():
    assert scope_filters("organisation", "Northside Imaging", ["Organization"]) == [
        "Organization?name=Northside Imaging"]


def test_preset_filters_form_a_valid_export_request():
    build_export_parameters(ALL, scope_filters("service-type", CT, ALL))


@pytest.mark.parametrize("preset, value", [("geographic", ""), ("bogus", "x")])
def test_unknown_preset_or_empty_value_is_refused(preset, value):
    with pytest.raises(ExportRequestError):
        scope_filters(preset, value, ["Organization"])
