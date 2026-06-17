"""
FHIR Bundle Parser Module

Handles parsing of FHIR Bundle dictionaries and extraction of resources and their codes.
Adapted from fhir-bundle-viz for use in Patient Referrals.
"""

import json
from typing import Dict, Any, List, Optional


def extract_resources(bundle: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Extract all resources from a FHIR Bundle and index them by ID.
    
    Args:
        bundle: Parsed FHIR Bundle dictionary
        
    Returns:
        Dictionary mapping resource IDs to resource objects with metadata
        Format: {resource_id: {'resource': {...}, 'fullUrl': '...', 'id': '...'}}
    """
    resources = {}
    entries = bundle.get('entry', [])
    
    for entry in entries:
        resource = entry.get('resource')
        full_url = entry.get('fullUrl', '')
        
        if not resource:
            continue
            
        resource_id = get_resource_id(resource, full_url)
        resources[resource_id] = {
            'resource': resource,
            'fullUrl': full_url,
            'id': resource_id
        }
    
    return resources


def get_resource_id(resource: Dict[str, Any], full_url: str) -> str:
    """
    Extract a unique identifier for a resource.
    
    Args:
        resource: FHIR resource dictionary
        full_url: The fullUrl from the Bundle entry
        
    Returns:
        Resource identifier (UUID or resource.id)
    """
    # Try to extract UUID from fullUrl (e.g., "urn:uuid:12345" -> "12345")
    if full_url.startswith('urn:uuid:'):
        return full_url.replace('urn:uuid:', '')
    
    # Fall back to resource.id if present
    if 'id' in resource:
        return resource['id']
    
    # Last resort: use the full URL
    return full_url


def extract_code_display(resource: Dict[str, Any]) -> Optional[str]:
    """
    Extract category and code information from a FHIR resource.
    
    Format as: "Category - Code: Display"
    
    Args:
        resource: FHIR resource dictionary
        
    Returns:
        Formatted code display string or None if no code found
    """
    parts = []
    
    # Extract category (if present)
    category_text = _extract_category(resource)
    if category_text:
        parts.append(category_text)
    
    # Extract code
    code_text = _extract_code(resource)
    if code_text:
        parts.append(code_text)
    
    if not parts:
        return None
    
    if len(parts) == 2:
        return f"{parts[0]} - {parts[1]}"
    else:
        return parts[0]


def _extract_category(resource: Dict[str, Any]) -> Optional[str]:
    """Extract category from a resource (if present)."""
    categories = resource.get('category', [])
    
    if not categories:
        return None
    
    # Take the first category
    if isinstance(categories, list) and len(categories) > 0:
        category = categories[0]
    else:
        category = categories
    
    if not isinstance(category, dict):
        return None
    
    return _extract_codeable_concept(category)


def _extract_code(resource: Dict[str, Any]) -> Optional[str]:
    """Extract code from a resource."""
    code = resource.get('code')
    
    if not code:
        code = resource.get('type')
    
    if not code:
        return None
    
    return _extract_codeable_concept(code)


def _extract_codeable_concept(codeable_concept: Dict[str, Any]) -> Optional[str]:
    """
    Extract display text from a CodeableConcept.
    
    Priority:
    1. coding[].code + coding[].display (formatted as "code: display")
    2. text field (fallback)
    """
    if not isinstance(codeable_concept, dict):
        return None
    
    # Try to get from coding array
    codings = codeable_concept.get('coding', [])
    if codings and isinstance(codings, list) and len(codings) > 0:
        coding = codings[0]
        code = coding.get('code', '')
        display = coding.get('display', '')
        
        if code and display:
            return f"{code}: {display}"
        elif display:
            return display
        elif code:
            return code
    
    # Fallback to text field
    text = codeable_concept.get('text')
    if text:
        return text
    
    return None


def is_task_group(resource: Dict[str, Any]) -> bool:
    """
    Check whether a Task resource is a group fulfillment task.
    """
    if resource.get('resourceType') != 'Task':
        return False

    meta = resource.get('meta', {})
    tags = meta.get('tag', [])
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, dict) and tag.get('code') == 'fulfilment-task-group':
                return True

    return False


def get_task_group_label(resource: Dict[str, Any]) -> str:
    """
    Build a display label for a group Task including Placer Group number.
    Format: "Task: PGN: {value}"
    """
    group_identifier = resource.get('groupIdentifier', {})
    if isinstance(group_identifier, dict):
        value = group_identifier.get('value', '')
        if value:
            return f"Task Group: PGN: {value}"

    return "Task Group"


def get_resource_type_display(resource: Dict[str, Any]) -> str:
    """
    Get a display name for the resource including its type and code.
    
    Args:
        resource: FHIR resource dictionary
        
    Returns:
        Display string in format "ResourceType: Code Display" or just "ResourceType"
    """
    resource_type = resource.get('resourceType', 'Unknown')
    if resource_type == 'Consent':
        consent_label = _get_mhr_consent_label(resource)
        if consent_label:
            return consent_label

    # Special-case Coverage for type code + text display
    if resource_type == 'Coverage':
        coverage_label = _get_coverage_label(resource)
        if coverage_label:
            return coverage_label

    # Special-case Task for PGN display (non-group tasks)
    if resource_type == 'Task':
        task_label = _get_task_label(resource)
        if task_label:
            return task_label

    # Special-case Observation for code + valueCodeableConcept display
    if resource_type == 'Observation':
        obs_label = _get_observation_label(resource)
        if obs_label:
            return obs_label

    # Special-case ServiceRequest for PON + category + code display
    if resource_type == 'ServiceRequest':
        sr_label = _get_servicerequest_label(resource)
        if sr_label:
            return sr_label

    # Special-case CommunicationRequest for richer graph labels
    if resource_type == 'CommunicationRequest':
        copyto_label = _get_copyto_reports_label(resource)
        if copyto_label:
            return copyto_label
        
        patient_pref_label = _get_patient_preference_label(resource)
        if patient_pref_label:
            return patient_pref_label

    code_display = extract_code_display(resource)
    
    if code_display:
        return f"{resource_type}: {code_display}"
    else:
        # For resources without code/category, try to get a meaningful identifier
        if resource_type == 'Patient':
            name = _get_human_name(resource)
            if name:
                return f"Patient: {name}"

        if resource_type == 'PractitionerRole':
            name = _get_human_name(resource)
            if name:
                return f"PractitionerRole: {name}"

            practitioner_ref = resource.get('practitioner', {})
            if isinstance(practitioner_ref, dict):
                practitioner_display = practitioner_ref.get('display', '')
                if practitioner_display:
                    return f"PractitionerRole: {practitioner_display}"
        
        if resource_type == 'Organization':
            org_name = resource.get('name', '')
            if org_name:
                return f"Organization: {org_name}"
        
        if resource_type == 'Encounter':
            enc_class = resource.get('class', {})
            if isinstance(enc_class, dict):
                display = enc_class.get('display', enc_class.get('code', ''))
                if display:
                    return f"Encounter: {display}"
        
        return resource_type


def _get_coverage_label(resource: Dict[str, Any]) -> Optional[str]:
    """
    Build label for Coverage with type code and text.

    Format: "Coverage: {code} {text}"
    Example: "Coverage: PUBLICPOL Medicare"
    """
    coverage_type = resource.get('type')
    if not coverage_type or not isinstance(coverage_type, dict):
        return None

    # Extract code from coding
    code = None
    codings = coverage_type.get('coding', [])
    if isinstance(codings, list) and codings:
        first_coding = codings[0]
        if isinstance(first_coding, dict):
            code = first_coding.get('code')

    # Extract text
    text = coverage_type.get('text')

    # Build label
    parts = []
    if code:
        parts.append(code)
    if text:
        parts.append(text)

    if parts:
        return f"Coverage: {' '.join(parts)}"

    return None


def _get_task_label(resource: Dict[str, Any]) -> Optional[str]:
    """
    Build label for Task (non-group) with PGN from groupIdentifier.

    Format: "Task: PGN: {value}"
    Example: "Task: PGN: 26-870358"
    """
    group_identifier = resource.get('groupIdentifier', {})
    if isinstance(group_identifier, dict):
        value = group_identifier.get('value', '')
        if value:
            return f"Task: PGN: {value}"

    return None


def _get_observation_label(resource: Dict[str, Any]) -> Optional[str]:
    """
    Build label for Observation with code display and valueCodeableConcept display.

    Format: "Observation: Code: Value"
    Example: "Observation: Pregnancy status: Pregnant"
    """
    # Extract code display
    code_display = None
    code = resource.get('code')
    if code and isinstance(code, dict):
        code_display = _extract_codeable_concept(code)

    # Extract valueCodeableConcept display
    value_display = None
    value_concept = resource.get('valueCodeableConcept')
    if value_concept and isinstance(value_concept, dict):
        value_display = _extract_codeable_concept(value_concept)

    # Build label
    if code_display and value_display:
        return f"Observation: {code_display}: {value_display}"
    elif code_display:
        return f"Observation: {code_display}"
    elif value_display:
        return f"Observation: {value_display}"

    return None


def _get_human_name(resource: Dict[str, Any]) -> Optional[str]:
    """Extract a display name from the FHIR HumanName element list."""
    names = resource.get('name', [])
    if names and isinstance(names, list) and len(names) > 0:
        name = names[0]
        given = name.get('given', [])
        family = name.get('family', '')
        
        parts = []
        if given:
            parts.append(given[0])
        if family:
            parts.append(family)
        
        if parts:
            return ' '.join(parts)
    
    return None


def _get_servicerequest_label(resource: Dict[str, Any]) -> Optional[str]:
    """
    Build label for ServiceRequest with PON (Placer Order Number) + code.

    Format: "ServiceRequest: PON - Code"
    Example: "ServiceRequest: 26-560275-1 - MRI Head"
    """
    # Extract PON (Placer Identifier)
    pon = None
    identifiers = resource.get('identifier', [])
    if isinstance(identifiers, list):
        for identifier in identifiers:
            if not isinstance(identifier, dict):
                continue
            identifier_type = identifier.get('type', {})
            if isinstance(identifier_type, dict):
                codings = identifier_type.get('coding', [])
                if isinstance(codings, list):
                    for coding in codings:
                        if isinstance(coding, dict) and coding.get('code') == 'PLAC':
                            pon = identifier.get('value')
                            break
            if pon:
                break

    # Extract code display (just the display, no code prefix)
    code_display = None
    code = resource.get('code')
    if code and isinstance(code, dict):
        codings = code.get('coding', [])
        if isinstance(codings, list) and codings:
            first_coding = codings[0]
            if isinstance(first_coding, dict):
                code_display = first_coding.get('display')
        if not code_display:
            code_display = code.get('text')

    # Build label
    parts = []
    if pon:
        parts.append(pon)
    if code_display:
        parts.append(code_display)

    if not parts:
        return None

    return f"ServiceRequest: {' - '.join(parts)}"


def _get_copyto_reports_label(resource: Dict[str, Any]) -> Optional[str]:
    """
    Build label for CommunicationRequest with category code 'copyto-reports'.

    Instead of showing 'copyto-reports:', extract the recipient reference ID
    and display that as the node label.
    """
    categories = resource.get('category', [])
    if not isinstance(categories, list):
        return None

    has_copyto_reports = False
    for category in categories:
        if not isinstance(category, dict):
            continue
        for coding in category.get('coding', []) or []:
            if isinstance(coding, dict) and coding.get('code') == 'copyto-reports':
                has_copyto_reports = True
                break
        if has_copyto_reports:
            break

    if not has_copyto_reports:
        return None

    # Extract recipient reference ID
    recipients = resource.get('recipient', [])
    if not isinstance(recipients, list) or not recipients:
        return 'CommunicationRequest: copyto-report'

    first_recipient = recipients[0]
    if not isinstance(first_recipient, dict):
        return 'CommunicationRequest: copyto-report'

    reference = first_recipient.get('reference', '')
    if not reference:
        return 'CommunicationRequest: copyto-report'

    # Extract the ID part after the "/" (e.g., "PractitionerRole/generalpractitioner-guthridge-jarred" -> "generalpractitioner-guthridge-jarred")
    recipient_id = reference.split('/')[-1] if '/' in reference else reference

    return f"CommunicationRequest: copyto-report {recipient_id}"


def _get_patient_preference_label(resource: Dict[str, Any]) -> Optional[str]:
    """
    Build label for CommunicationRequest with category code 'patient-preference'.

    Includes medium code(s) and a status indicator:
    - ❌ when doNotPerform is true
    - ✅ when doNotPerform is false or missing
    """
    categories = resource.get('category', [])
    if not isinstance(categories, list):
        return None

    has_patient_preference = False
    for category in categories:
        if not isinstance(category, dict):
            continue
        for coding in category.get('coding', []) or []:
            if isinstance(coding, dict) and coding.get('code') == 'patient-preference':
                has_patient_preference = True
                break
        if has_patient_preference:
            break

    if not has_patient_preference:
        return None

    mediums = []
    medium_elements = resource.get('medium', [])
    if isinstance(medium_elements, list):
        for medium in medium_elements:
            if not isinstance(medium, dict):
                continue

            code = ''
            codings = medium.get('coding', [])
            if isinstance(codings, list) and codings:
                first_coding = codings[0]
                if isinstance(first_coding, dict):
                    code = first_coding.get('code', '') or first_coding.get('display', '')

            if not code:
                code = medium.get('text', '')

            if code:
                mediums.append(code)

    medium_text = ', '.join(mediums) if mediums else 'UNKNOWN'

    do_not_perform = resource.get('doNotPerform', False) is True
    status_icon = '❌' if do_not_perform else '✅'

    return f"CommunicationRequest: patient-preference | medium: {medium_text} {status_icon}"


def _get_mhr_consent_label(resource: Dict[str, Any]) -> Optional[str]:
    """
    Build label for Consent resources where provision.type is 'deny'.

    Replaces the default IDSCL/information disclosure text with 'MYH'
    and appends a red-cross indicator.
    """
    provision = resource.get('provision', {})
    if not isinstance(provision, dict):
        return None

    provision_type = str(provision.get('type', '')).strip().lower()
    if provision_type == 'deny':
        return 'Consent: MHR ❌'

    return None
