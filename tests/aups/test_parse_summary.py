"""aups_view.parse_summary turns an AU PS document Bundle into per-section blocks."""
import pytest

from aups_view import parse_summary, sanitise_narrative
from tests.aups.conftest import FIXTURES, load


def section(view, code):
    [sec] = [s for s in view["sections"] if s["code"] == code]
    return sec


def rows(sec, resource_type):
    return [g["rows"] for g in sec["groups"] if g["type"] == resource_type][0]


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*.json")), ids=lambda p: p.stem)
def test_every_test_bundle_parses_with_all_references_resolved(path):
    import json
    view = parse_summary(json.loads(path.read_text()))
    assert view["sections"]
    assert all(not s["unresolved"] for s in view["sections"])


def test_sections_follow_composition_order():
    view = parse_summary(load("referral-endoconsult-autogen"))
    assert [s["code"] for s in view["sections"]] == [
        "48765-2", "10160-0", "11450-4", "11369-6", "11348-0", "10162-6", "30954-2", "29762-2"]


def test_header_names_author_custodian_and_attester():
    view = parse_summary(load("referral-endoconsult-curated"))
    header = view["header"]
    assert header["authors"] == ["Ginger BURROWS, General Practitioner – Bungabbee Medical Clinic"]
    assert header["custodian"] == "Bungabbee Medical Clinic"
    assert header["attesters"][0].startswith("Ginger BURROWS")
    assert view["patient"]["name"] == "Joyce JOHNSON"
    assert "IHI: 8003608500314679" in view["patient"]["identifiers"]


def test_contained_medication_is_named():
    view = parse_summary(load("referral-endoconsult-curated"))
    meds = [r["Medicine"] for r in rows(section(view, "10160-0"), "MedicationStatement")]
    assert "Metformin (Tablet)" in meds
    assert "Unknown medicine" not in meds


def test_no_known_assertions_are_statements_not_rows():
    view = parse_summary(load("noknownx"))
    for code, text in [("48765-2", "No known allergy"), ("10160-0", "No known current medicines"),
                       ("11450-4", "No current problems or disability")]:
        sec = section(view, code)
        assert sec["no_known"] == [text]
        assert sec["groups"] == []


def test_empty_reason_is_reported():
    view = parse_summary(load("section-emptyreason"))
    assert {s["code"]: s["empty_reason"] for s in view["sections"]} == {
        "48765-2": "No information available", "11450-4": "No information available",
        "10160-0": "No information available", "11369-6": "No information available"}
    assert not any(s["narrative_primary"] for s in view["sections"])


def test_narrative_only_section_shows_its_narrative():
    sec = section(parse_summary(load("patient-story")), "81338-6")
    assert sec["groups"] == [] and sec["narrative_primary"]
    assert "<script" not in sec["narrative_html"]


def test_past_history_pregnancy_and_social_history_blocks():
    view = parse_summary(load("referral-endoconsult-autogen"))
    past = rows(section(view, "11348-0"), "Condition")
    assert {r["Problem"]: r["Status"] for r in past}["Appendicitis"] == "resolved"
    pregnancy = rows(section(view, "10162-6"), "Observation")
    assert [(r["Observation"], r["Result"], r["_level"]) for r in pregnancy] == [
        ("Pregnancy status", "Pregnant", 0), ("Estimated date of delivery", "2025-02-03", 1)]
    social = rows(section(view, "29762-2"), "Observation")
    assert social[0]["Result"] == "Lifetime non-smoker"


def test_result_panel_members_are_nested_under_the_panel():
    results = rows(section(parse_summary(load("basicsummarywihpath")), "30954-2"), "Observation")
    names = [(r["Observation"], r["_level"]) for r in results]
    panel = names.index(("Blood type and Indirect antibody screen panel - Blood", 0))
    assert names[panel + 1] == ("Blood Group", 1)
    assert names[panel + 2] == ("Blood Group Antibody Screen", 1)


def test_missing_composition_elements_are_warned_and_patient_still_found():
    view = parse_summary(load("basicsummary-missing-comp-elements"))
    assert view["patient"]["name"] == "Mia Leanne Banks"
    assert any("Composition.subject is absent" in w for w in view["warnings"])
    assert view["header"]["authors"] == ["Not recorded (unknown)"]


def test_unresolved_entry_is_listed():
    bundle = load("basicsummary")
    bundle["entry"][0]["resource"]["section"][0]["entry"].append({"reference": "urn:uuid:missing"})
    assert section(parse_summary(bundle), "11450-4")["unresolved"] == ["urn:uuid:missing"]


def test_non_document_is_rejected():
    with pytest.raises(ValueError):
        parse_summary({"resourceType": "Bundle", "type": "searchset", "entry": []})
    with pytest.raises(ValueError):
        parse_summary({"resourceType": "Patient"})


def test_sanitiser_strips_scripts_attributes_and_links():
    html = ('<div xmlns="http://www.w3.org/1999/xhtml"><p onclick="x()">Hi <a href="javascript:x">l</a>'
            '<script>alert(1)</script><img src=x onerror=y></p><td colspan="2">c</td></div>')
    assert sanitise_narrative(html) == '<div><p>Hi l</p><td colspan="2">c</td></div>'


def test_known_sections_get_a_standard_heading_and_icon_with_document_title_as_subtitle():
    view = parse_summary(load("gpvisit-retrieval"))
    problems = section(view, "11450-4")
    assert (problems["heading"], problems["subtitle"], problems["icon"]) == (
        "Problems", "Current Medical Information", "fa-notes-medical")
    assert problems["count"] == 5
    assert section(view, "48765-2")["heading"] == "Allergies & Intolerances"
    assert section(view, "10160-0")["heading"] == "Medications"
    assert all(s["icon"] and s["anchor"] for s in view["sections"])
