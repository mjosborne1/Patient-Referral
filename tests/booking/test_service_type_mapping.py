"""Imaging procedure (ServiceRequest.code) to booking service type (Slot.serviceType)."""
import pytest

from booking import service_type_for


def _sr(display=None, text=None):
    code = {}
    if display:
        code["coding"] = [{"system": "http://snomed.info/sct", "code": "x", "display": display}]
    if text:
        code["text"] = text
    return {"resourceType": "ServiceRequest", "code": code}


@pytest.mark.parametrize("sr, expected", [
    (_sr("Computed tomography of abdomen and pelvis"), "310128004"),
    (_sr(text="CT Abdo/Pelvis"), "310128004"),
    (_sr("MRI of head", "MRI Head"), "310127009"),
    (_sr("Ultrasound liver", "US Liver"), "310169008"),
    (_sr("Plain X-ray of chest", "Chest X-ray"), "933537131000036109"),
    (_sr("Bone scintigraphy"), "788009005"),
])
def test_imaging_procedures_map_to_their_modality_service(sr, expected):
    assert service_type_for(sr)["code"] == expected


def test_unrecognised_procedure_has_no_service_type_filter():
    assert service_type_for(_sr(text="Something unusual")) is None
