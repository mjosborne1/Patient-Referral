import uuid
import datetime
import logging
import base64
import random


def _get_localtime_bne():
    utc_plus_10 = datetime.datetime.utcnow() + datetime.timedelta(hours=10)
    return utc_plus_10.strftime("%Y-%m-%dT%H:%M:%S.%f+10:00")


def _narrative(inner_html: str) -> dict:
    return {
        "status": "generated",
        "div": f'<div xmlns="http://www.w3.org/1999/xhtml">{inner_html}</div>',
    }


def _make_entry(resource, resource_type):
    resource_id = resource.get("id", str(uuid.uuid4()))
    return {
        "fullUrl": f"urn:uuid:{resource_id}",
        "resource": resource,
        "request": {"method": "POST", "url": resource_type},
    }


def create_referral_bundle(form_data, fhir_server_url=None, auth_credentials=None):
    """
    Build an AU eRequesting transaction bundle for a specialist referral.

    Bundle contents:
        Encounter         – minimal ambulatory context (required by ServiceRequest)
        ServiceRequest    – the referral order (no ereq profile — no referral profile exists yet)
        Task              – fulfilment tracking, initial status = requested
        DocumentReference – clinical context narrative (LOINC 107903-7, text/plain)
    """
    patient_id = form_data.get("patient_id", "")
    if not patient_id:
        raise ValueError("patient_id is required")

    now = _get_localtime_bne()
    year = datetime.datetime.utcnow().year % 100
    requisition_number = f"{year:02d}-{random.randint(100000, 999999)}"

    sr_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    docref_id = str(uuid.uuid4())
    enc_id = str(uuid.uuid4())

    patient_ref = {"reference": f"Patient/{patient_id}"}

    requester_name = form_data.get("requester_name", "").strip() or "Requesting Practitioner"
    requester_org = form_data.get("requester_org", "").strip() or "Requesting Organisation"
    performer_name = form_data.get("performer_name", "").strip()
    performer_org = form_data.get("performer_org", "").strip()
    specialty_code = form_data.get("specialty_code", "").strip()
    specialty_display = form_data.get("specialty_display", "").strip() or "Specialist Referral"
    indication_code = form_data.get("indication_code", "").strip()
    indication_display = form_data.get("indication_display", "").strip()
    priority = form_data.get("priority", "routine")
    clinical_narrative = form_data.get("clinical_narrative", "").strip()

    # --- Encounter ---
    encounter = {
        "resourceType": "Encounter",
        "id": enc_id,
        "text": _narrative(
            f"<p><b>Encounter</b> — ambulatory, {now[:10]}</p>"
        ),
        "status": "finished",
        "class": {
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code": "AMB",
            "display": "ambulatory",
        },
        "subject": patient_ref,
        "period": {"start": now},
    }

    # --- ServiceRequest ---
    service_code = {"text": specialty_display}
    if specialty_code:
        service_code["coding"] = [
            {
                "system": "http://snomed.info/sct",
                "code": specialty_code,
                "display": specialty_display,
            }
        ]

    reason_code = []
    if indication_display:
        rc = {"text": indication_display}
        if indication_code:
            rc["coding"] = [
                {
                    "system": "http://snomed.info/sct",
                    "code": indication_code,
                    "display": indication_display,
                }
            ]
        reason_code = [rc]

    _sr_indication = f" for {indication_display}" if indication_display else ""
    _sr_performer = f" to {performer_name}" if performer_name else ""
    service_request = {
        "resourceType": "ServiceRequest",
        "id": sr_id,
        "text": _narrative(
            f"<p><b>Referral:</b> {specialty_display}{_sr_indication}{_sr_performer}</p>"
            f"<p><b>Priority:</b> {priority} — <b>Requester:</b> {requester_name}"
            + (f", {requester_org}" if requester_org else "")
            + f" — <b>Authored:</b> {now[:10]}</p>"
        ),
        "identifier": [
            {
                "type": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                            "code": "PLAC",
                        }
                    ]
                },
                "system": "urn:ietf:rfc:3986",
                "value": f"urn:uuid:{sr_id}",
            }
        ],
        "requisition": {
            "type": {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                        "code": "PGN",
                        "display": "Placer Group Number",
                    }
                ]
            },
            "system": "http://myclinic.example.org.au/identifier",
            "value": requisition_number,
        },
        "status": "active",
        "intent": "order",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://snomed.info/sct",
                        "code": "306206005",
                        "display": "Referral to service",
                    }
                ],
                "text": "Referral",
            }
        ],
        "priority": priority,
        "code": service_code,
        "subject": patient_ref,
        "encounter": {"reference": f"urn:uuid:{enc_id}"},
        "authoredOn": now,
        "requester": {"display": requester_name},
        "supportingInfo": [{"reference": f"urn:uuid:{docref_id}"}],
    }

    if reason_code:
        service_request["reasonCode"] = reason_code
    if performer_name:
        service_request["performer"] = [{"display": performer_name}]

    # --- Task ---
    task = {
        "resourceType": "Task",
        "id": task_id,
        "meta": {
            "tag": [
                {
                    "system": "http://terminology.hl7.org.au/CodeSystem/resource-tag",
                    "code": "fulfilment-task",
                }
            ]
        },
        "text": _narrative(
            f"<p><b>Fulfilment Task</b> for referral {requisition_number}</p>"
            f"<p><b>Status:</b> requested — <b>Requester:</b> {requester_name}"
            + (f" — <b>Owner:</b> {performer_org}" if performer_org else "")
            + "</p>"
        ),
        "groupIdentifier": {
            "use": "usual",
            "type": {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                        "code": "PGN",
                        "display": "Placer Group Number",
                    }
                ]
            },
            "system": "http://myclinic.example.org.au/identifier",
            "value": requisition_number,
            "assigner": {"display": requester_org or "Requesting Organisation"},
        },
        "status": "requested",
        "intent": "order",
        "focus": {"reference": f"urn:uuid:{sr_id}"},
        "for": patient_ref,
        "authoredOn": now,
        "requester": {"display": requester_name},
    }
    if performer_org:
        task["owner"] = {"display": performer_org}

    # --- DocumentReference (clinical context, LOINC 107903-7) ---
    narrative_bytes = (clinical_narrative or "No clinical narrative provided").encode("utf-8")
    narrative_b64 = base64.b64encode(narrative_bytes).decode("ascii")

    doc_ref = {
        "resourceType": "DocumentReference",
        "id": docref_id,
        "text": _narrative(
            f"<p><b>Clinical Context</b> — authored by {requester_name}, {now[:10]}</p>"
            + (f"<p>{clinical_narrative}</p>" if clinical_narrative else "")
        ),
        "status": "current",
        "type": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": "107903-7",
                    "display": "Clinical note",
                }
            ]
        },
        "subject": patient_ref,
        "author": [{"display": requester_name}],
        "content": [
            {
                "attachment": {
                    "contentType": "text/plain",
                    "data": narrative_b64,
                }
            }
        ],
    }

    entries = [
        _make_entry(encounter, "Encounter"),
        _make_entry(service_request, "ServiceRequest"),
        _make_entry(task, "Task"),
        _make_entry(doc_ref, "DocumentReference"),
    ]

    # --- Optional: AU Patient Summary attachment ---
    attach_summary = form_data.get("attach_summary", "") in ("on", "true", "1")
    if attach_summary:
        summary_mode = form_data.get("summary_mode", "hint")
        ps_docref_id = str(uuid.uuid4())

        if summary_mode == "inline":
            # Option A: base64-encode the full $summary bundle inline
            summary_json = form_data.get("summary_bundle_json", "")
            if summary_json:
                ps_b64 = base64.b64encode(summary_json.encode("utf-8")).decode("ascii")
                ps_doc_ref = {
                    "resourceType": "DocumentReference",
                    "id": ps_docref_id,
                    "text": _narrative(
                        "<p><b>AU Patient Summary</b> — attached inline (FHIR Bundle, base64-encoded)</p>"
                    ),
                    "status": "current",
                    "type": {
                        "coding": [
                            {
                                "system": "http://loinc.org",
                                "code": "60591-5",
                                "display": "Patient summary Document",
                            }
                        ]
                    },
                    "subject": patient_ref,
                    "content": [
                        {
                            "attachment": {
                                "contentType": "application/fhir+json",
                                "data": ps_b64,
                            }
                        }
                    ],
                }
                entries.append(_make_entry(ps_doc_ref, "DocumentReference"))
                service_request["supportingInfo"].append({"reference": f"urn:uuid:{ps_docref_id}"})
                logging.info(f"AU PS attached inline (base64), docref={ps_docref_id}")

        else:
            # Option B: endpoint hint URL — specialist fetches directly
            summary_url = form_data.get("summary_endpoint_url", "")
            if summary_url:
                ps_doc_ref = {
                    "resourceType": "DocumentReference",
                    "id": ps_docref_id,
                    "text": _narrative(
                        f"<p><b>AU Patient Summary</b> — endpoint hint: {summary_url}</p>"
                    ),
                    "status": "current",
                    "type": {
                        "coding": [
                            {
                                "system": "http://loinc.org",
                                "code": "60591-5",
                                "display": "Patient summary Document",
                            }
                        ]
                    },
                    "subject": patient_ref,
                    "content": [
                        {
                            "attachment": {
                                "contentType": "application/fhir+json",
                                "url": summary_url,
                            }
                        }
                    ],
                }
                entries.append(_make_entry(ps_doc_ref, "DocumentReference"))
                service_request["supportingInfo"].append({"reference": f"urn:uuid:{ps_docref_id}"})
                logging.info(f"AU PS endpoint hint attached: {summary_url}, docref={ps_docref_id}")

    bundle = {
        "resourceType": "Bundle",
        "id": str(uuid.uuid4()),
        "type": "transaction",
        "timestamp": now,
        "entry": entries,
    }

    logging.info(
        f"Referral bundle created: sr={sr_id}, task={task_id}, "
        f"patient={patient_id}, priority={priority}, "
        f"entries={len(entries)}"
    )
    return bundle
