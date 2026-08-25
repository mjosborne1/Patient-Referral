# Using the form data passed in from form_data = get_form_data(request) in create_diagnostic_request_bundle():
# Create a ServiceRequest Transaction Bundle that includes the following resources:
#    - all ServiceRequests in an Order Episode
#    - Patient (subject)
#.   - coverage as contained resources
#.   - Encounter
#.   - Practitioner
#    - Practitionerrole
#    - Location
#.   - Tasks for each ServiceRequest
#.   - Task group 
#.   - CommunicationRequest for copy-to another recipient
#.   - Consent (MHRConsent Withdrawl profile)
#.   - DocumentReference for Clinical notes

import uuid
import datetime
import logging
import html
from json import dumps
import ast

# When True, prefix urn:uuid references with resource type (e.g., "Observation/urn:uuid:...")
# When False, use plain urn:uuid references (e.g., "urn:uuid:...")
USE_BROKEN_SMILECDR_MODE = False

def _build_servicerequest_code(test):
    """
    Build the code element for ServiceRequest based on test data.
    If no code is provided, only include text field (no coding array).
    If code is provided, include both coding and text.
    - 'display' = official SNOMED CT display term (used in coding.display)
    - 'text' = short/friendly name e.g. "FBC" (used in CodeableConcept.text)
    If only 'display' is provided, it is used for both.
    """
    import logging
    logging.info(f"_build_servicerequest_code called with test: {test}")
    
    test_code = test.get("code", "").strip() if test.get("code") else ""
    test_display = test.get("display", "")
    test_text = test.get("text", "") or test_display  # fall back to display if no text
    
    logging.info(f"Extracted: code='{test_code}', display='{test_display}', text='{test_text}'")
    
    if not test_code:
        # No code provided - only use text field (free-text test)
        logging.info("No code provided, returning text-only format")
        return {
            "text": test_text
        }
    else:
        # Code provided - use display for coding.display, text for CodeableConcept.text
        logging.info(f"Code provided: {test_code}, display: '{test_display}', text: '{test_text}'")
        return {
            "coding": [{
                "system": "http://snomed.info/sct",  
                "code": test_code,
                "display": test_display
            }],
            "text": test_text
        }

import os
from fhirutils import fhir_get
import base64
import requests
from fhirclient.models import bundle, servicerequest, patient, encounter, practitioner, practitionerrole
from fhirclient.models import location, task, communicationrequest, consent, documentreference, coverage, specimen

def lookup_snomed_code(display_text, valueset_url):
    """
    Look up SNOMED code for a display text using terminology server.
    
    Args:
        display_text (str): The display text to search for
        valueset_url (str): The ValueSet URL to search in
        
    Returns:
        str: The SNOMED code if found, empty string otherwise
    """
    if not display_text or not valueset_url:
        return ""
    
    try:
        terminology_server = "https://r4.ontoserver.csiro.au/fhir"
        expand_url = f"{terminology_server}/ValueSet/$expand"
        params = {
            "url": valueset_url,
            "filter": display_text,
            "count": 10
        }
        
        resp = requests.get(expand_url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        contains = data.get("expansion", {}).get("contains", [])
        for item in contains:
            # Look for exact match on display text
            if item.get("display", "").lower() == display_text.lower():
                return item.get("code", "")
        
        # If no exact match, return the first result's code
        if contains:
            return contains[0].get("code", "")
            
    except Exception as e:
        logging.warning(f"Failed to lookup SNOMED code for '{display_text}': {e}")
        
        # Fallback to common SNOMED codes for testing
        fallback_codes = {
            # Specimen types
            'blood': '119297000',
            'serum': '119364003',
            'plasma': '119361006',
            'urine': '122575003',
            'saliva': '119342007',
            'stool': '119339001',
            'swab': '258603007',
            'tissue': '119376003',
            
            # Collection methods
            'venipuncture': '22778000', 
            'needle biopsy': '129314006',
            'capillary blood sampling': '277762005',
            'clean catch urine': '71181003',
            'midstream urine': '258574006',
            
            # Body sites
            'arm': '53120007',
            'left arm': '368208006',
            'right arm': '368209003',
            'finger': '7569003',
            'hand': '85562004',
            'leg': '61685007',
            'neck': '45048000'
        }
        return fallback_codes.get(display_text.lower(), "")
    
    return ""

def generate_narrative_text(resource):
    """
    Generate a simple narrative text for a FHIR resource.
    
    Args:
        resource (dict): The FHIR resource
        
    Returns:
        dict: Narrative object with status and div
    """
    resource_type = resource.get("resourceType", "")
    esc = lambda v: html.escape(str(v))
    narrative_text = f"<div xmlns=\"http://www.w3.org/1999/xhtml\"><h3>{esc(resource_type)}</h3>"

    # Helper function to extract display value from coding
    def get_display_value(value):
        if isinstance(value, dict):
            if "coding" in value and isinstance(value["coding"], list) and len(value["coding"]) > 0:
                return value["coding"][0].get("display", value["coding"][0].get("code", ""))
            elif "text" in value:
                return value["text"]
            elif "display" in value:
                return value["display"]
        elif isinstance(value, list) and len(value) > 0:
            if isinstance(value[0], dict) and "coding" in value[0]:
                return get_display_value(value[0])
        return str(value) if value else ""
    
    # Generate narrative based on resource type
    if resource_type == "ServiceRequest":
        status = resource.get("status", "")
        intent = resource.get("intent", "")
        code_display = get_display_value(resource.get("code", {}))
        category_display = get_display_value(resource.get("category", [{}])[0] if resource.get("category") else {})
        
        narrative_text += f"<p><strong>Status:</strong> {esc(status)}</p>"
        narrative_text += f"<p><strong>Intent:</strong> {esc(intent)}</p>"
        narrative_text += f"<p><strong>Test:</strong> {esc(code_display)}</p>"
        if category_display:
            narrative_text += f"<p><strong>Category:</strong> {esc(category_display)}</p>"

        # Add sequence if available
        extensions = resource.get("extension", [])
        for ext in extensions:
            if ext.get("url") == "http://hl7.org.au/fhir/ereq/StructureDefinition/au-erequesting-displaysequence":
                sequence = ext.get("valueInteger", "")
                narrative_text += f"<p><strong>Sequence:</strong> {esc(sequence)}</p>"

        # Add reasons if available
        reason_codes = resource.get("reasonCode", [])
        if reason_codes:
            reasons = [get_display_value(reason) for reason in reason_codes]
            narrative_text += f"<p><strong>Reasons:</strong> {esc(', '.join(reasons))}</p>"

    elif resource_type == "Encounter":
        status = resource.get("status", "")
        class_display = get_display_value(resource.get("class", {}))

        narrative_text += f"<p><strong>Status:</strong> {esc(status)}</p>"
        narrative_text += f"<p><strong>Class:</strong> {esc(class_display)}</p>"

    elif resource_type == "Specimen":
        # Add specimen specific narrative elements
        if "type" in resource:
            type_display = get_display_value(resource["type"])
            if type_display:
                narrative_text += f"<p><strong>Specimen Type:</strong> {esc(type_display)}</p>"

        if "collection" in resource:
            collection = resource["collection"]
            if "method" in collection:
                method_display = get_display_value(collection["method"])
                if method_display:
                    narrative_text += f"<p><strong>Collection Method:</strong> {esc(method_display)}</p>"

            if "bodySite" in collection:
                site_display = get_display_value(collection["bodySite"])
                if site_display:
                    narrative_text += f"<p><strong>Body Site:</strong> {esc(site_display)}</p>"

            if "collectedDateTime" in collection:
                narrative_text += f"<p><strong>Collection Date/Time:</strong> {esc(collection['collectedDateTime'])}</p>"

    elif resource_type == "Task":
        status = resource.get("status", "")
        intent = resource.get("intent", "")
        description = resource.get("description", "")

        narrative_text += f"<p><strong>Status:</strong> {esc(status)}</p>"
        narrative_text += f"<p><strong>Intent:</strong> {esc(intent)}</p>"
        if description:
            narrative_text += f"<p><strong>Description:</strong> {esc(description)}</p>"

    elif resource_type == "DocumentReference":
        status = resource.get("status", "")
        type_display = get_display_value(resource.get("type", {}))

        narrative_text += f"<p><strong>Status:</strong> {esc(status)}</p>"
        narrative_text += f"<p><strong>Type:</strong> {esc(type_display)}</p>"

        # Add content info
        content = resource.get("content", [])
        if content and len(content) > 0:
            attachment = content[0].get("attachment", {})
            title = attachment.get("title", "")
            content_type = attachment.get("contentType", "")
            data = attachment.get("data", "")

            if title:
                narrative_text += f"<p><strong>Title:</strong> {esc(title)}</p>"
            if content_type:
                narrative_text += f"<p><strong>Content Type:</strong> {esc(content_type)}</p>"

            # Decode and display the clinical context if it's base64 encoded text
            if data and content_type == "text/plain":
                try:
                    import base64
                    decoded_content = base64.b64decode(data).decode('utf-8')
                    # Escape HTML characters for safe display
                    escaped_content = html.escape(decoded_content)
                    narrative_text += f"<p><strong>Clinical Context:</strong></p>"
                    narrative_text += f"<div style='border: 1px solid #ccc; padding: 10px; margin: 5px 0; background-color: #f9f9f9;'>{escaped_content}</div>"
                except Exception:
                    # If decoding fails, just show that content is present
                    narrative_text += f"<p><strong>Content:</strong> Encoded clinical notes</p>"

    elif resource_type == "CommunicationRequest":
        status = resource.get("status", "")
        narrative_text += f"<p><strong>Status:</strong> {esc(status)}</p>"
        narrative_text += f"<p>Request for communication regarding patient care.</p>"

    elif resource_type == "Consent":
        status = resource.get("status", "")
        scope_display = get_display_value(resource.get("scope", {}))
        category_display = get_display_value(resource.get("category", [{}])[0] if resource.get("category") else {})

        narrative_text += f"<p><strong>Status:</strong> {esc(status)}</p>"
        if scope_display:
            narrative_text += f"<p><strong>Scope:</strong> {esc(scope_display)}</p>"
        if category_display:
            narrative_text += f"<p><strong>Category:</strong> {esc(category_display)}</p>"

        provision = resource.get("provision", {})
        if provision:
            provision_type = provision.get("type", "")
            narrative_text += f"<p><strong>Provision:</strong> {esc(provision_type)}</p>"

    elif resource_type == "Coverage":
        status = resource.get("status", "")
        type_display = get_display_value(resource.get("type", {}))

        narrative_text += f"<p><strong>Status:</strong> {esc(status)}</p>"
        if type_display:
            narrative_text += f"<p><strong>Type:</strong> {esc(type_display)}</p>"
    
    narrative_text += "</div>"
    
    return {
        "status": "generated",
        "div": narrative_text
    }

def create_request_bundle(form_data, fhir_server_url=None, auth_credentials=None):
    """
    Creates a FHIR Transaction Bundle for diagnostic requests based on form data.
    
    Args:
        form_data (dict): The processed form data from the request containing patient_id
        
    Returns:
        dict: A FHIR Bundle resource with type 'transaction' containing all required resources
    """
    
    logging.info("Starting bundle creation process")
    try:
        logging.debug(f"Form data received: {dumps(form_data, indent=2, default=str)}")
    except (TypeError, ValueError) as e:
        logging.debug(f"Form data received (raw): {form_data}")
        logging.warning(f"Could not serialize form_data to JSON: {e}")
    
    # Get timestamp in BNE time
    def get_localtime_bne():
        """Helper function to get timestamp in UTC+10:00 timezone"""
        utc_time = datetime.datetime.utcnow()
        # Add 10 hours to UTC
        utc_plus_10 = utc_time + datetime.timedelta(hours=10)
        # Format with timezone indicator
        return utc_plus_10.strftime("%Y-%m-%dT%H:%M:%S.%f+10:00")
    
    # Extract patient_id from form_data
    patient_id = form_data.get('patient_id', '')
    if not patient_id:
        raise ValueError("Patient ID is required but was not found in form_data")
    
    # Create a Bundle with type "transaction"
    bundle_id = str(uuid.uuid4())
    transaction_bundle = {
        "resourceType": "Bundle",
        "id": bundle_id,
        "type": "transaction",
        "entry": []
    }

    # Add timestamp
    transaction_bundle["timestamp"] = get_localtime_bne()
    
    # Get request category (Pathology or Radiology)
    request_category = form_data.get('requestCategory', 'Pathology')
    
    # Inside create_request_bundle function, update the test data handling:

    # Extract test and reason data
    tests = form_data.get('selectedTests', [])
    logging.info(f"Raw selectedTests from form: {tests}")
    logging.info(f"selectedTests type: {type(tests)}")
    
    if isinstance(tests, str):
        try:
            # Try to safely parse the string representation to a list
            import json
            tests = json.loads(tests)
            logging.info(f"Successfully parsed tests as JSON: {tests}")
        except json.JSONDecodeError:
            # If it's not valid JSON, try a more forgiving approach
            try:
                import ast
                tests = ast.literal_eval(tests)
                logging.info(f"Successfully parsed tests using ast.literal_eval: {tests}")
            except (ValueError, SyntaxError):
                logging.warning("Failed to parse tests string, defaulting to empty list")
                tests = []

    # Ensure each test is a dictionary with the required keys
    processed_tests = []
    for i, test in enumerate(tests):
        logging.info(f"Processing test #{i}: {test} (type: {type(test)})")
        if isinstance(test, dict) and "code" in test and ("display" in test or "text" in test):
            logging.info(f"Test #{i} has code='{test.get('code')}', display='{test.get('display','')}', text='{test.get('text','')}' ")
            processed_tests.append(test)
        elif isinstance(test, str):
            # If it's just a string (perhaps just the display name), create a simple dict
            logging.warning(f"Test #{i} is just a string, creating dict with empty code")
            processed_tests.append({"code": "", "display": test, "text": test})
        else:
            # Log unexpected test format
            logging.warning(f"Skipping invalid test format: {test}")

    # Replace original tests list with processed version
    tests = processed_tests
    logging.info(f"Final processed tests: {tests}")
            
    reasons = form_data.get('selectedReasons', [])
    logging.debug(f"Raw selectedReasons from form: {reasons}")
    
    if isinstance(reasons, str):
        try:
            # Try to safely parse the string representation to a list
            import json
            reasons = json.loads(reasons)
            logging.debug("Successfully parsed reasons as JSON")
        except json.JSONDecodeError:
            # If it's not valid JSON, try a more forgiving approach
            try:
                reasons = ast.literal_eval(reasons)
                logging.debug("Successfully parsed reasons using ast.literal_eval")
            except (ValueError, SyntaxError):
                logging.warning("Failed to parse reasons string, defaulting to empty list")
                reasons = []

    # Ensure each reason is a dictionary with the required keys
    processed_reasons = []
    for i, reason in enumerate(reasons):
        if isinstance(reason, dict) and "code" in reason and "display" in reason:
            processed_reasons.append(reason)
            logging.debug(f"Reason {i}: {reason['display']} ({reason['code']})")
        elif isinstance(reason, str):
            # If it's just a string (perhaps just the display name), create a simple dict
            processed_reasons.append({"code": "", "display": reason})
            logging.warning(f"Reason {i}: Converting string '{reason}' to dict with empty code")
        else:
            # Log unexpected reason format
            logging.warning(f"Skipping invalid reason format at index {i}: {reason}")

    # Replace original reasons list with processed version
    reasons = processed_reasons
    logging.info(f"Processing {len(reasons)} reasons")
    
    # Get requester info
    requester_id = form_data.get('requester', '')
    
    # Get organization info
    organization_id = form_data.get('organisation', '')
    
    # Create and add Patient reference (assumed to exist already)
    patient_reference = {
        "reference": f"Patient/{patient_id}"
    }
    
    # Create and add reference to Practitioner (requester)
    practitioner_reference = None
    if requester_id:
        practitioner_reference = {
            "reference": f"PractitionerRole/{requester_id}"
        }
        
        # Fetch and add PractitionerRole resource to the bundle
        try:
            server_url = fhir_server_url or os.environ.get('FHIR_SERVER_URL', 'https://aucore.aidbox.beda.software/fhir')
            response = fhir_get(f"/PractitionerRole/{requester_id}?_include=PractitionerRole:practitioner", 
                              fhir_server_url=server_url, auth_credentials=auth_credentials, timeout=10)
            if response.status_code == 200:
                practitioner_role_data = response.json()
                if practitioner_role_data.get('resourceType') == 'PractitionerRole':
                    # Add PractitionerRole resource to bundle
                    transaction_bundle["entry"].append({
                        "fullUrl": f"urn:uuid:{str(uuid.uuid4())}",
                        "resource": practitioner_role_data,
                        "request": {
                            "method": "PUT",
                            "url": f"PractitionerRole/{requester_id}"
                        }
                    })
                    
                    # If the response includes a practitioner, add it too
                    if practitioner_role_data.get('entry'):
                        for entry in practitioner_role_data.get('entry', []):
                            resource = entry.get('resource', {})
                            if resource.get('resourceType') == 'Practitioner':
                                practitioner_id = resource.get('id')
                                transaction_bundle["entry"].append({
                                    "fullUrl": f"urn:uuid:{str(uuid.uuid4())}",
                                    "resource": resource,
                                    "request": {
                                        "method": "PUT",
                                        "url": f"Practitioner/{practitioner_id}"
                                    }
                                })
                elif practitioner_role_data.get('resourceType') == 'Bundle':
                    # Handle bundle response with _include
                    for entry in practitioner_role_data.get('entry', []):
                        resource = entry.get('resource', {})
                        if resource.get('resourceType') == 'PractitionerRole':
                            transaction_bundle["entry"].append({
                                "fullUrl": f"urn:uuid:{str(uuid.uuid4())}",
                                "resource": resource,
                                "request": {
                                    "method": "PUT",
                                    "url": f"PractitionerRole/{requester_id}"
                                }
                            })
                        elif resource.get('resourceType') == 'Practitioner':
                            practitioner_id = resource.get('id')
                            transaction_bundle["entry"].append({
                                "fullUrl": f"urn:uuid:{str(uuid.uuid4())}",
                                "resource": resource,
                                "request": {
                                    "method": "PUT",
                                    "url": f"Practitioner/{practitioner_id}"
                                }
                            })
            else:
                # If response status is not 200, fall back to GET request
                print(f"Failed to fetch PractitionerRole {requester_id}, status: {response.status_code}")
                transaction_bundle["entry"].append({
                    "fullUrl": f"urn:uuid:{str(uuid.uuid4())}",
                    "request": {
                        "method": "GET",
                        "url": f"PractitionerRole/{requester_id}"
                    }
                })
        except Exception as e:
            print(f"Failed to fetch PractitionerRole {requester_id}: {e}")
            # Fall back to GET request if fetch fails
            transaction_bundle["entry"].append({
                "fullUrl": f"urn:uuid:{str(uuid.uuid4())}",
                "request": {
                    "method": "GET",
                    "url": f"PractitionerRole/{requester_id}"
                }
            })
    
    # Create and add reference to Organization (if provided)
    organization_name = form_data.get('organisationName', '').strip()
    organization_reference = None
    if organization_id:
        organization_reference = {
            "reference": f"Organization/{organization_id}"
        }
        if organization_name:
            organization_reference["display"] = organization_name
        
        # Add Organization as a GET request in the bundle
        transaction_bundle["entry"].append({
            "fullUrl": f"urn:uuid:{str(uuid.uuid4())}",
            "request": {
                "method": "GET",
                "url": f"Organization/{organization_id}"
            }
        })
    
    # Generate a unique requisition number for this order (8 digits starting with current year)
    current_year = datetime.datetime.now().year % 100  # Get last 2 digits of year (e.g., 25 for 2025)
    import random
    requisition_number = f"{current_year:02d}-{random.randint(100000, 999999)}"
    logging.info(f"Generated requisition number: {requisition_number}")
    
    # Generate task group ID early so individual tasks can reference it
    group_task_id = str(uuid.uuid4())
    
    # Create supporting resources first (before ServiceRequests that reference them)
    pregnancy_obs_id = None
    doc_ref_id = None
    
    # Create Pregnancy Observation if pregnancy status is indicated
    is_pregnant = form_data.get('isPregnant', False)
    if is_pregnant == 'true' or is_pregnant is True:
        pregnancy_obs_id = str(uuid.uuid4())
        
        pregnancy_obs = {
            "resourceType": "Observation",
            "meta": {
                "profile": [
                    "http://hl7.org/fhir/uv/ips/StructureDefinition/Observation-pregnancy-status-uv-ips"
                ]
            },
            "id": pregnancy_obs_id,
            "status": "final",
            "category": [{
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                    "code": "exam",
                    "display": "Exam"
                }]
            }],
            "code": {
                "coding": [
                {
                    "system": "http://loinc.org",
                    "code": "82810-3",
                    "display": "Pregnancy status"
                }]
            },
            "subject": patient_reference,
            "effectiveDateTime": get_localtime_bne(),
            "valueCodeableConcept": {
                "coding": [{
                    "system": "http://snomed.info/sct",
                    "code": "77386006",
                    "display": "Pregnant"
                }]
            }
        }
        
        # Add Pregnancy Observation to bundle
        transaction_bundle["entry"].append({
            "fullUrl": f"urn:uuid:{pregnancy_obs_id}",
            "resource": pregnancy_obs,
            "request": {
                "method": "POST",
                "url": "Observation"
            }
        })
    
    # Create DocumentReference for clinical notes if provided
    clinical_context = form_data.get('clinicalContext', '')
    if clinical_context:
        doc_ref_id = str(uuid.uuid4())
        
        # Base64 encode the clinical context
        encoded_notes = base64.b64encode(clinical_context.encode('utf-8')).decode('utf-8')
        
        doc_ref = {
            "resourceType": "DocumentReference",
            "meta": {
                "profile": [
                    "http://hl7.org.au/fhir/ereq/StructureDefinition/au-erequesting-clinicalcontext-documentreference"
                ]
            },
            "id": doc_ref_id,
            "status": "current",
            "type": {
                "coding": [{
                    "system": "http://loinc.org",
                    "code": "107903-7",
                    "display": "Clinical note"
                }],
                "text": "Clinical context"
            },
            "subject": patient_reference,
            "author": [practitioner_reference] if practitioner_reference else [],
            "date": get_localtime_bne(),
            "content": [{
                "attachment": {
                    "contentType": "text/plain",
                    "data": encoded_notes,
                    "title": "Clinical Context"
                }
            }]
        }
        
        # Add DocumentReference to bundle
        transaction_bundle["entry"].append({
            "fullUrl": f"urn:uuid:{doc_ref_id}",
            "resource": doc_ref,
            "request": {
                "method": "POST",
                "url": "DocumentReference"
            }
        })
    
    # Get request status and status reason from form data
    request_status = form_data.get('requestStatus', 'active')  # Default to 'active'
    status_reason = form_data.get('statusReason', '').strip()
    
    # Get fasting status from form data
    fasting_status = form_data.get('fastingStatus', 'Non-fasting')  # Default to 'Non-fasting'
    
    # Get request priority from form data
    request_priority = form_data.get('requestPriority', 'routine')  # Default to 'routine'
    
    # Create Coverage resource if billing category is provided
    coverage_id = None
    coverage_reference = None
    bill_type = form_data.get('billingCategory', '')
    if bill_type:
        # Map billing category codes to their display text
        billing_category_mapping = {
            'PUBLICPOL': 'Medicare',
            'VET': 'Department of Veterans\' Affairs',
            'pay': 'Private Pay',
            'payconc': 'Private Pay with Concession',
            'AUPUBHOSP': 'Public Hospital',
            'WCBPOL': 'Work Cover'
        }
        v3ActCode = 'http://terminology.hl7.org/CodeSystem/v3-ActCode'
        bill_type_system_mapping = {
            'AUPUBHOSP': 'http://terminology.hl7.org.au/CodeSystem/v3-ActCode',
            'pay': 'http://terminology.hl7.org/CodeSystem/coverage-selfpay',
            'payconc': 'http://terminology.hl7.org/CodeSystem/coverage-selfpay'
        }
        
        coverage_id = str(uuid.uuid4())
        coverage_reference = {
            "reference": f"Coverage/urn:uuid:{coverage_id}" if USE_BROKEN_SMILECDR_MODE else f"urn:uuid:{coverage_id}"
        }
        
        coverage = {
            "resourceType": "Coverage",
            "meta": {
                "profile": [
                    "http://hl7.org.au/fhir/ereq/StructureDefinition/au-erequesting-coverage"
                ]
            },
            "id": coverage_id,
            "status": "active",
            "type": {
                "coding": [{
                    "code": bill_type,
                    "system": bill_type_system_mapping.get(bill_type,v3ActCode)
                }],
                "text": billing_category_mapping.get(bill_type, bill_type)
            },
            "beneficiary": patient_reference,
            "payor": [{
                "display": billing_category_mapping.get(bill_type, bill_type)
            }]
        }
        
        # Add Coverage to bundle
        transaction_bundle["entry"].append({
            "fullUrl": f"urn:uuid:{coverage_id}",
            "resource": coverage,
            "request": {
                "method": "POST",
                "url": "Coverage"
            }
        })
    
    # Create a ServiceRequest for each test
    service_requests = []
    specimen_references = []  # Store specimen references for ServiceRequests
    
    # Create Specimen if this is a Pathology request and specimen collection is checked
    specimen_id = None
    specimen_collected = form_data.get('specimenCollected') == 'true'
    
    if request_category == "Pathology" and specimen_collected:
        specimen_type = form_data.get('specimenType', '').strip()
        collection_method = form_data.get('collectionMethod', '').strip()
        body_site = form_data.get('bodySite', '').strip()
        collection_datetime = form_data.get('collectionDateTime', '').strip()
        
        # Try to get codes from hidden fields first, then lookup if needed
        specimen_type_code = form_data.get('specimenTypeCode', '').strip()
        collection_method_code = form_data.get('collectionMethodCode', '').strip()
        body_site_code = form_data.get('bodySiteCode', '').strip()
        
        # Lookup codes if not provided and we have display text
        if specimen_type and not specimen_type_code:
            specimen_type_code = lookup_snomed_code(
                specimen_type, 
                'https://healthterminologies.gov.au/fhir/ValueSet/specimen-type-1'
            )
            
        if collection_method and not collection_method_code:
            collection_method_code = lookup_snomed_code(
                collection_method, 
                'https://healthterminologies.gov.au/fhir/ValueSet/specimen-collection-procedure-1'
            )
            
        if body_site and not body_site_code:
            body_site_code = lookup_snomed_code(
                body_site, 
                'https://healthterminologies.gov.au/fhir/ValueSet/body-site-1'
            )
        
        # Create specimen if at least specimen type is provided
        if specimen_type:
            specimen_id = str(uuid.uuid4())
            
            # Use provided collection datetime or current time
            if not collection_datetime:
                collection_datetime = get_localtime_bne()
            else:
                # Convert from datetime-local format to FHIR format
                try:
                    # Parse the datetime-local input (YYYY-MM-DDTHH:MM)
                    dt = datetime.datetime.fromisoformat(collection_datetime)
                    # Add timezone for Brisbane (UTC+10)
                    collection_datetime = dt.strftime("%Y-%m-%dT%H:%M:%S.%f+10:00")
                except ValueError:
                    # Fallback to current time if parsing fails
                    collection_datetime = get_localtime_bne()
            
            # Build specimen resource
            specimen_resource = {
                "resourceType": "Specimen",
                "meta": {
                    "profile": [
                        "http://hl7.org.au/fhir/StructureDefinition/au-specimen"
                    ]
                },
                "id": specimen_id,
                "identifier": [{
                    "use": "usual",
                    "system": "http://myclinic.example.org.au/specimen-identifier",
                    "value": f"SPEC-{requisition_number}"
                }],
                "status": "available",
                "subject": patient_reference
            }
            
            # Add specimen type if provided
            if specimen_type:
                type_coding = {
                    "coding": [{
                        "system": "http://snomed.info/sct",
                        "display": specimen_type
                    }],
                    "text": specimen_type
                }
                # Add code if available
                if specimen_type_code:
                    type_coding["coding"][0]["code"] = specimen_type_code
                
                specimen_resource["type"] = type_coding
            
            # Add collection details if provided
            collection = {}
            if collection_datetime:
                collection["collectedDateTime"] = collection_datetime
                
            if collection_method:
                method_coding = {
                    "coding": [{
                        "system": "http://snomed.info/sct",
                        "display": collection_method
                    }],
                    "text": collection_method
                }
                # Add code if available
                if collection_method_code:
                    method_coding["coding"][0]["code"] = collection_method_code
                
                collection["method"] = method_coding
                
            if body_site:
                site_coding = {
                    "coding": [{
                        "system": "http://snomed.info/sct", 
                        "display": body_site
                    }],
                    "text": body_site
                }
                # Add code if available
                if body_site_code:
                    site_coding["coding"][0]["code"] = body_site_code
                
                collection["bodySite"] = site_coding
            
            if collection:
                specimen_resource["collection"] = collection
            
            # Add narrative if requested
            if form_data.get('addNarrative') == 'true':
                specimen_resource["text"] = generate_narrative_text(specimen_resource)
            
            # Add specimen to bundle
            transaction_bundle["entry"].append({
                "fullUrl": f"urn:uuid:{specimen_id}",
                "resource": specimen_resource,
                "request": {
                    "method": "POST",
                    "url": "Specimen"
                }
            })
            
            # Create specimen reference for ServiceRequests
            specimen_ref = f"Specimen/urn:uuid:{specimen_id}" if USE_BROKEN_SMILECDR_MODE else f"urn:uuid:{specimen_id}"
            specimen_references.append({
                "reference": specimen_ref,
                "display": f"Specimen: {specimen_type}"
            })
    
    for i, test in enumerate(tests):
        sr_id = str(uuid.uuid4())
        encounter_id = str(uuid.uuid4())  # Generate unique encounter ID for each ServiceRequest
        encounter_ref = f"Encounter/urn:uuid:{encounter_id}" if USE_BROKEN_SMILECDR_MODE else f"urn:uuid:{encounter_id}"
        # Set appropriate profile based on request category
        service_request_profile = "http://hl7.org.au/fhir/ereq/StructureDefinition/au-erequesting-servicerequest-path"
        if request_category == "Radiology":
            service_request_profile = "http://hl7.org.au/fhir/ereq/StructureDefinition/au-erequesting-servicerequest-imag"

        encounter_resource = {
            "resourceType": "Encounter",
            "meta": {
                "profile": [
                    "http://hl7.org.au/fhir/ereq/StructureDefinition/au-erequesting-encounter"
                ]
            },
            "id": encounter_id,
            "status": "planned",
            "class": {
                "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                "code": "AMB",
                "display": "ambulatory"
            },
            "subject": patient_reference
        }
        transaction_bundle["entry"].append({
            "fullUrl": f"urn:uuid:{encounter_id}",
            "resource": encounter_resource,
            "request": {
                "method": "POST",
                "url": "Encounter"
            }
        })
        
        # Create ServiceRequest
        service_request = {
            "resourceType": "ServiceRequest",
             "meta": {
                "profile": [
                    service_request_profile
                ]
            },
            "extension": [
                {
                    "url": "http://hl7.org.au/fhir/ereq/StructureDefinition/au-erequesting-displaysequence",
                    "valueInteger": test.get("display_sequence",1)
                },
                {
                    "url": "http://hl7.org.au/fhir/ereq/StructureDefinition/au-erequesting-fastingprecondition",
                    "valueCodeableConcept": {
                        "coding": [{
                            "system": "http://snomed.info/sct",
                            "code": "16985007" if fasting_status == "Fasting" else "440565004",
                            "display": "Fasting" if fasting_status == "Fasting" else "Nonfasting"
                        }]
                    }
                }
            ] + ([{
                "url": "http://hl7.org/fhir/StructureDefinition/request-statusReason",
                "valueCodeableConcept": {
                    "text": status_reason
                }
            }] if request_status == "on-hold" and status_reason else []),
            "id": sr_id,
            "identifier": [{
                "use": "usual",
                "type": {
                    "coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                        "code": "PLAC",
                        "display": "Placer Identifier"
                    }]
                },
                "system": "http://myclinic.example.org.au/identifier",
                "value": f"{requisition_number}-{test.get('display_sequence', 1)}"
            }],
            "status": request_status,
            "intent": "order",
            "requisition": {
                "use": "usual",
                "type": {
                    "coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                        "code": "PGN",
                        "display": "Placer Group Number"
                    }]
                },
                "system": "http://myclinic.example.org.au/identifier",
                "value": requisition_number,
                "assigner": organization_reference if organization_reference else {"display": "Requesting Organisation"}
            },
            "category": [{
                "coding": [{
                    "system": "http://snomed.info/sct",
                    "code": "108252007" if request_category == "Pathology" else "363679005",
                    "display": "Laboratory procedure" if request_category == "Pathology" else "Imaging"
                }]
            }],
            "code": _build_servicerequest_code(test),
            "subject": patient_reference,
            "encounter": {
                "reference": encounter_ref,
                "type": "Encounter"
            },
            "authoredOn": get_localtime_bne(),
            "priority": request_priority
        }
        
        # Add insurance reference if Coverage is available
        if coverage_reference:
            service_request["insurance"] = [coverage_reference]
        
        # Add requester if available
        if practitioner_reference:
            service_request["requester"] = practitioner_reference
            
        # Add performer (organization) if available
        if organization_reference:
            service_request["performer"] = [organization_reference]
            
        # Add reasons if available
        if reasons:
            reason_list = []
            for reason in reasons:
                # Handle None values or invalid types from JSON - use empty string as fallback
                # reason_code must be a simple string (not dict, list, or other types)
                reason_code = reason.get("code")
                if reason_code is None or not isinstance(reason_code, str):
                    # If code is not a string (e.g., a dict like {"isTrusted": true}), treat as no code
                    reason_code = ""
                else:
                    reason_code = reason_code.strip()
                
                reason_display = reason.get("display", "")
                if reason_display is None or not isinstance(reason_display, str):
                    reason_display = ""
                else:
                    reason_display = reason_display.strip()
                
                # If code is empty or not provided, treat as free-text (only use text field)
                if not reason_code:
                    reason_list.append({
                        "text": reason_display
                    })
                else:
                    # If code is provided, include both coding and text
                    reason_list.append({
                        "coding": [{
                            "system": "http://snomed.info/sct",
                            "code": reason_code,
                            "display": reason_display
                        }],
                        "text": reason_display
                    })
            
            if reason_list:
                service_request["reasonCode"] = reason_list
        
        # Prepare supportingInfo array
        supporting_info = []
        
        # Check if pregnancy status should be added
        if pregnancy_obs_id:
            obs_ref = f"Observation/urn:uuid:{pregnancy_obs_id}" if USE_BROKEN_SMILECDR_MODE else f"urn:uuid:{pregnancy_obs_id}"
            supporting_info.append({
                "reference": obs_ref,
                "display": "Pregnancy status"
            })
        
        # Check if clinical context DocumentReference should be added
        if doc_ref_id:
            doc_ref = f"DocumentReference/urn:uuid:{doc_ref_id}" if USE_BROKEN_SMILECDR_MODE else f"urn:uuid:{doc_ref_id}"
            supporting_info.append({
                "reference": doc_ref,
                "display": "Clinical Context"
            })
        
        # Add supportingInfo to ServiceRequest if we have any
        if supporting_info:
            service_request["supportingInfo"] = supporting_info
        
        # Add specimen references for pathology requests
        if specimen_references and request_category == "Pathology":
            service_request["specimen"] = specimen_references
                
        # Add ServiceRequest to bundle
        transaction_bundle["entry"].append({
            "fullUrl": f"urn:uuid:{sr_id}",
            "resource": service_request,
            "request": {
                "method": "POST",
                "url": "ServiceRequest"
            }
        })
        
        service_requests.append(service_request)
        
        # Create Task for this ServiceRequest
        task_id = str(uuid.uuid4())
        task = {
            "resourceType": "Task",
            "meta": {
                "profile": [
                    "http://hl7.org.au/fhir/ereq/StructureDefinition/au-erequesting-task-diagnosticrequest"
                ],
                "tag": [
                    {
                        "system": "http://terminology.hl7.org.au/CodeSystem/resource-tag",
                        "code": "fulfilment-task"
                    }
                ]
            },
            "id": task_id,
            "groupIdentifier": {
                "use": "usual",
                "type": {
                    "coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                        "code": "PGN",
                        "display": "Placer Group Number"
                    }]
                },
                "system": "http://myclinic.example.org.au/identifier",
                "value": requisition_number,
                "assigner": organization_reference if organization_reference else {"display": "Requesting Organisation"}
            },
            "status": "requested",
            "intent": "order",
            "focus": {
                "reference": f"ServiceRequest/urn:uuid:{sr_id}" if USE_BROKEN_SMILECDR_MODE else f"urn:uuid:{sr_id}"
            },
            "priority" : request_priority,
            "code" : {
                "coding" : [{
                "system" : "http://hl7.org/fhir/CodeSystem/task-code",
                "code" : "fulfill"
                }]
            },
            "for": patient_reference,
            # supportingInfo goes here
            "requester": practitioner_reference if practitioner_reference else {"reference": "PractitionerRole/unknown"},
            "owner": organization_reference if organization_reference else {"reference": "Organization/unknown"},
            "partOf": [{
                "reference": f"Task/urn:uuid:{group_task_id}" if USE_BROKEN_SMILECDR_MODE else f"urn:uuid:{group_task_id}"
            }],
            "authoredOn": get_localtime_bne()
        }
        
        # Add Task to bundle
        transaction_bundle["entry"].append({
            "fullUrl": f"urn:uuid:{task_id}",
            "resource": task,
            "request": {
                "method": "POST",
                "url": "Task"
            }
        })
    
    # Add CommunicationRequest for copy-to recipients (if provided)
    copy_to_recipients = form_data.get('copyTo', [])
    if copy_to_recipients:
        # Handle case where copyTo might be a JSON string (from new typeahead) or list (multiple values)
        if isinstance(copy_to_recipients, str):
            try:
                # Try to parse as JSON first (from typeahead implementation)
                import json
                copy_to_recipients = json.loads(copy_to_recipients)
            except json.JSONDecodeError:
                # If it's not valid JSON, treat as single value
                copy_to_recipients = [copy_to_recipients] if copy_to_recipients else []
        
        # Create a CommunicationRequest for each recipient
        for recipient_id in copy_to_recipients:
            if recipient_id:  # Skip empty values
                comm_req_id = str(uuid.uuid4())
                comm_req = {
                    "resourceType": "CommunicationRequest",
                    "meta": {
                        "profile": [
                            "http://hl7.org.au/fhir/ereq/StructureDefinition/au-erequesting-communicationrequest-copyto"
                        ]
                    },
                    "id": comm_req_id,
                    "groupIdentifier": {
                        "use": "usual",
                        "type": {
                            "coding": [{
                                "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                                "code": "PGN",
                                "display": "Placer Group Number"
                            }]
                        },
                        "system": "http://myclinic.example.org.au/identifier",
                        "value": requisition_number,
                        "assigner": organization_reference if organization_reference else {"display": "Requesting Organisation"}
                    },
                    "status": "active",
                    "category": [{
                        "coding": [{
                            "system" : "http://terminology.hl7.org.au/CodeSystem/communication-request-category",
                            "code" : "copyto-reports",
                            "display" : "Copy To Reports"
                        }]
                    }],
                    "subject": patient_reference,
                    "about": [{"reference": f"ServiceRequest/urn:uuid:{sr['id']}" if USE_BROKEN_SMILECDR_MODE else f"urn:uuid:{sr['id']}"} for sr in service_requests],
                    "requester": practitioner_reference if practitioner_reference else {"reference": "PractitionerRole/unknown"},
                    "recipient": [{
                        "reference": f"PractitionerRole/{recipient_id}"
                    }],
                    "authoredOn": get_localtime_bne()
                }
                
                # Add CommunicationRequest to bundle
                transaction_bundle["entry"].append({
                    "fullUrl": f"urn:uuid:{comm_req_id}",
                    "resource": comm_req,
                    "request": {
                        "method": "POST",
                        "url": "CommunicationRequest"
                    }
                })
                
                # Add PractitionerRole as a GET request in the bundle for each recipient
                transaction_bundle["entry"].append({
                    "fullUrl": f"urn:uuid:{str(uuid.uuid4())}",
                    "request": {
                        "method": "GET",
                        "url": f"PractitionerRole/{recipient_id}"
                    }
                })
    
    # Add Consent (MHR Consent Withdrawal) if user opted out
    consent_opt_out = form_data.get('mhrConsentWithdrawn', False)
    if consent_opt_out and service_requests:  # Only create if there are ServiceRequests to reference
        consent_id = str(uuid.uuid4())
        
        # Build provision.data array with references to all ServiceRequests
        provision_data = []
        for sr in service_requests:
            sr_ref = f"ServiceRequest/urn:uuid:{sr['id']}" if USE_BROKEN_SMILECDR_MODE else f"urn:uuid:{sr['id']}"
            provision_data.append({
                "meaning": "dependents",
                "reference": {
                    "reference": sr_ref
                }
            })
        
        consent = {
            "resourceType": "Consent",
            "meta": {
                "profile": [
                    "http://hl7.org.au/fhir/ereq/StructureDefinition/au-erequesting-mhrconsentwithdrawal"
                ]
            },
            "id": consent_id,
            "status": "active",
            "scope": {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/consentscope",
                    "code": "patient-privacy",
                    "display": "Privacy Consent"
                }],
                "text": "Patient Privacy"
            },
            "category": [{
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                    "code": "IDSCL",
                    "display": "information disclosure"
                }],
                "text": "information disclosure"
            }],
            "patient": patient_reference,
            "dateTime": get_localtime_bne(),
            "performer": [patient_reference],  # Patient is agreeing to the consent
            "organization": [organization_reference] if organization_reference else [{"display": "Requesting Organisation"}],
            "policy": [{
                "authority": "https://www.health.gov.au",
                "uri": "https://www.legislation.gov.au/C2012A00063"
            }],
            "policyRule": {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                    "code": "OPTIN"
                }],
                "text": "Opt in"
            },
            "provision": {
                "type": "deny",
                "action": [{
                    "coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/consentaction",
                        "code": "disclose",
                        "display": "Disclose"
                    }]
                }],
                "class": [{
                    "system": "http://hl7.org/fhir/resource-types",
                    "code": "DiagnosticReport"
                }],
                "data": provision_data
            }
        }
        
        # Add Consent to bundle
        transaction_bundle["entry"].append({
            "fullUrl": f"urn:uuid:{consent_id}",
            "resource": consent,
            "request": {
                "method": "POST",
                "url": "Consent"
            }
        })
    
    # Add CommunicationRequest for "Don't contact patient" preference if selected
    do_not_contact = form_data.get('doNotContactPatient', False)
    if do_not_contact and service_requests:  # Only create if there are ServiceRequests to reference
        comm_req_dnc_id = str(uuid.uuid4())
        
        # Build about array with references to all ServiceRequests
        about_refs = []
        for sr in service_requests:
            sr_ref = f"ServiceRequest/urn:uuid:{sr['id']}" if USE_BROKEN_SMILECDR_MODE else f"urn:uuid:{sr['id']}"
            about_refs.append({
                "reference": sr_ref
            })
        
        comm_request_dnc = {
            "resourceType": "CommunicationRequest",
            "meta": {
                "profile": [
                    "http://hl7.org.au/fhir/ereq/StructureDefinition/au-erequesting-communicationrequest-patient"
                ]
            },
            "id": comm_req_dnc_id,
            "groupIdentifier": {
                "type": {
                    "coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                        "code": "PGN",
                        "display": "Placer Group Number"
                    }],
                    "text": "Placer Group Number"
                },
                "system": "http://myclinic.example.org.au/identifier",
                "value": requisition_number,
                "assigner": organization_reference if organization_reference else {"display": "Requesting Organisation"}
            },
            "status": "active",
            "category": [{
                "coding": [{
                    "system": "http://terminology.hl7.org.au/CodeSystem/communication-request-category",
                    "code": "patient-preference",
                    "display": "Patient Preference"
                }]
            }],
            "doNotPerform": True,
            "medium": [{
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/v3-ParticipationMode",
                    "code": "SMSWRIT"
                }],
                "text": "SMS"
            }],
            "subject": patient_reference,
            "about": about_refs,
            "authoredOn": get_localtime_bne(),
            "requester": patient_reference,
            "recipient": [patient_reference],
            "sender": organization_reference if organization_reference else {"display": "Requesting Organisation"}
        }
        
        # Add CommunicationRequest to bundle
        transaction_bundle["entry"].append({
            "fullUrl": f"urn:uuid:{comm_req_dnc_id}",
            "resource": comm_request_dnc,
            "request": {
                "method": "POST",
                "url": "CommunicationRequest"
            }
        })
        
    # Create a Task group that references all ServiceRequests - MUST BE LAST for filler processing trigger
    if service_requests:
        task_group = {
            "resourceType": "Task",
            "meta": {
                "profile": [
                    "http://hl7.org.au/fhir/ereq/StructureDefinition/au-erequesting-task-group"
                ],
                "tag": [
                    {
                        "system": "http://terminology.hl7.org.au/CodeSystem/resource-tag",
                        "code": "fulfilment-task-group"
                    }
                ]
            },
            "id": group_task_id,
            "groupIdentifier": {
                "use": "usual",
                "type": {
                    "coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                        "code": "PGN",
                        "display": "Placer Group Number"
                    }]
                },
                "system": "http://myclinic.example.org.au/identifier",
                "value": requisition_number,
                "assigner": organization_reference if organization_reference else {"display": "Requesting Organisation"}
            },
            "status": "requested",
            "intent": "order",
            "priority" : request_priority,
            "code" : {
                "coding" : [{
                "system" : "http://hl7.org/fhir/CodeSystem/task-code",
                "code" : "fulfill"
                }]
            },
            "for": patient_reference,
            "authoredOn": get_localtime_bne(),
            "requester": practitioner_reference if practitioner_reference else {"reference": "PractitionerRole/unknown"},
            "owner": organization_reference if organization_reference else {"reference": "Organization/unknown"}
        }
            
        # Add Task group to bundle - LAST entry for filler processing trigger
        transaction_bundle["entry"].append({
            "fullUrl": f"urn:uuid:{group_task_id}",
            "resource": task_group,
            "request": {
                "method": "POST",
                "url": "Task"
            }
        })
        
    # Add narratives to all resources if requested
    add_narrative = form_data.get('addNarrative', False)
    if add_narrative:
        logging.info("Adding narrative text to all resources")
        for entry in transaction_bundle["entry"]:
            if "resource" in entry:
                resource = entry["resource"]
                narrative = generate_narrative_text(resource)
                resource["text"] = narrative
    
    return transaction_bundle
